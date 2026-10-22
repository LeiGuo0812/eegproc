"""Post-ICA reconstruction, continuous QC and optional epochs (also used on resume)."""
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
import mne
import numpy as np
from .signal_ops import window_mask, relative_window_mask, add_mask_annotations, annotation_mask, physical_rank
from .backends import reference
from .report_provenance import utc_now

@dataclass
class ProcessingContext:
    """Named state shared by initial processing and ICA continuation."""
    config: Any
    report: dict
    execution: Any
    store: Any
    paths: dict
    directory: Path
    subject: str
    events: Any = None
    event_id: Any = None
    epoch_config: Any = None
    collect_stages: bool = False
    stages: dict | None = None


def finish_processing(current,raw,clean,model,*,context: ProcessingContext):
    config,report,execution,store=context.config,context.report,context.execution,context.store
    paths,directory,subject=context.paths,context.directory,context.subject
    events,event_id,epoch_config=context.events,context.event_id,context.epoch_config
    collect_stages,stages=context.collect_stages,context.stages
    picks=mne.pick_types(current.info,eeg=True,exclude=[])
    eeg_info=mne.pick_info(current.info,picks,copy=True)
    bads=report["bad_channels"]
    # Rebuild the original EEG container and restore final interpolation/CAR.
    execution.start('final_interpolation_reference')
    # Recreate only missing channel slots; never filter already-clean EEG again.
    values=np.zeros((len(picks),current.n_times),dtype=float)
    for i, name in enumerate(clean.ch_names):
        values[eeg_info['ch_names'].index(name)] = clean._data[i]
    final_eeg=mne.io.RawArray(values,eeg_info,first_samp=current.first_samp,copy='auto',verbose=False)
    final_eeg.info["bads"] = bads
    if not config.interpolate_bads:
        for name in bads:
            final_eeg._data[final_eeg.ch_names.index(name)] = current.get_data(picks=[name])[0]
    if bads and config.interpolate_bads and config.final_interpolation:
        final_eeg.interpolate_bads(reset_bads=True, method={"eeg": "spline"}, verbose="warning")
    if config.interpolate_before_asr:final_eeg.info['bads']=[]
    with final_eeg.info._unlock():final_eeg.info['custom_ref_applied']=clean.info['custom_ref_applied']
    if config.final_reference:reference(final_eeg,config)
    # Preserve auxiliary channels and all original metadata in current.
    current._data[picks,:] = final_eeg._data
    current.info["bads"] = [x for x in current.info["bads"] if x not in final_eeg.ch_names]
    if not config.interpolate_bads:current.info['bads']+=bads
    with current.info._unlock():
        current.info["highpass"] = clean.info["highpass"]
        current.info["lowpass"] = clean.info["lowpass"]
        current.info["custom_ref_applied"] = final_eeg.info["custom_ref_applied"]
    execution.start('continuous_qc')
    residual = window_mask(current, config.residual_peak_uv, config.residual_ptp_uv,
                           config.guard_seconds, config.window_seconds)
    residual |= relative_window_mask(current, config.residual_robust_z,
        config.residual_relative_min_ptp_uv,config.guard_seconds,config.window_seconds)
    if config.residual_qc:
        add_mask_annotations(current, residual, "BAD_residual")
    else:
        residual[:] = False
    report['residual_qc_enabled'] = config.residual_qc
    rejected = annotation_mask(current)
    report["quality"] = {"bad_sample_fraction": float(rejected.mean()),
        "retained_seconds": float((~rejected).sum()/current.info["sfreq"]),
        "residual_sample_fraction": float(residual.mean()), "interpolated_channels": bads if config.interpolate_bads else [],
        "data_deleted": False, "auxiliary_channels_unchanged": True,
        "final_rank": physical_rank(final_eeg._data)[0]}
    del final_eeg, values
    if rejected.mean() > .5:
        report["quality_flags"].append("More than half of the recording is BAD annotated")
    if any(not np.isfinite(current.get_data(picks=picks,start=a,stop=min(a+65536,current.n_times))).all()
           for a in range(0,current.n_times,65536)):
        raise FloatingPointError("Nonfinite output")
    execution.start('save_continuous')
    store.save_final(current, paths["raw"])
    if model is not None:store.save_ica(model,paths['ica'])
    report['provenance']['continuous_finished_utc']=utc_now()
    if events is not None:
        execution.start('epochs')
        from .epochs import repair_epochs, EpochConfig
        from .epoch_export import make_strict_epochs
        selected_qc=('annotations' if config.epoch_mode=='fixed' else 'event-window') if config.epoch_qc=='auto' else config.epoch_qc
        ec=epoch_config or EpochConfig(tmin=config.epoch_tmin,tmax=config.epoch_tmax,baseline=config.epoch_baseline,
            peak_uv=config.residual_peak_uv,ptp_uv=config.residual_ptp_uv,robust_z=config.residual_robust_z,
            relative_min_ptp_uv=config.residual_relative_min_ptp_uv,seed=config.seed)
        if config.epoch_mode=='fixed':
            ec=replace(ec,tmin=0.,tmax=config.fixed_epoch_duration-1/current.info['sfreq'],baseline=None)
        if config.repair_epochs:
            epochs,epoch_report=repair_epochs(current,raw,events,event_id,global_bads=bads,
                config=ec,save_path=None,subject=subject)
        else:
            epochs,epoch_report=make_strict_epochs(current,raw,events,event_id,global_bads=bads,
                config=ec,save_path=None,subject=subject,annotation_policy=selected_qc)
        epoch_report['epoch_mode']=config.epoch_mode
        epoch_path=directory/f'{subject}_clean-epo.fif'
        if len(epochs):store.save_epochs(epochs,epoch_path)
        report['epochs']=epoch_report
        if len(epochs):paths['epochs']=directory/f'{subject}_clean-epo.fif'
        if epoch_report['status']=='review_required':
            report['quality_flags'].append('Epoch retention is below 50 percent; inspect epoch QC')
    else:
        execution.skip('epochs',report.get('epoch_resolution',{}).get('reason','Not requested'))
    report['delivery_policy']=dict(asr_cutoff=config.asr_cutoff,asr_backend=config.asr_backend,
        asr_enabled=config.asr_cutoff is not None,local_epoch_repair=config.repair_epochs,
        continuous_purpose=config.purpose,epoch_mode=config.epoch_mode,epochs_requested=events is not None,
        epoch_qc=selected_qc if events is not None else None,original_BAD_annotations_preserved=True,
        heart_policy=report.get('ica',{}).get('component_selection',{}).get('heart_policy'),
        entrypoint=report.get('provenance',{}).get('invocation',{}).get('entrypoint','run'))
    execution.finish()

    report["status"] = "review_required" if report["quality_flags"] else "completed"
    if collect_stages:
        stages["final"] = current.copy()
    return current
