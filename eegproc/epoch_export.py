"""Fixed trial-local ERP QC, with no automatic local interpolation.

Uses the identical screen scored for the scientific comparator. The frozen
AutoReject path is available as an explicit opt-in in the public CLI.
"""
from pathlib import Path
from dataclasses import asdict
from collections import Counter
import hashlib,json
import mne
import numpy as np
from .epochs import EpochConfig,screen


def _annotation_key(annotation):
    return (float(annotation['onset']),float(annotation['duration']),annotation['description'],
            tuple(annotation.get('ch_names',())),json.dumps(dict(annotation.get('extras',{})),sort_keys=True))


def _epoch_base(clean,original,policy):
    """Ignore only newly generated BAD_residual, preserving all input labels.

    This also retains manual labels added to the cleaned Raw. Matching against
    the input is necessary: a pre-existing label named BAD_residual must survive.
    Neither supplied Raw is mutated; first_samp and absolute clock are checked.
    """
    if (clean.first_samp!=original.first_samp or clean.n_times!=original.n_times
            or clean.info['sfreq']!=original.info['sfreq']
            or clean.info['meas_date']!=original.info['meas_date']
            or clean.annotations.orig_time!=original.annotations.orig_time):
        raise ValueError('ERP export needs original input on the identical sample grid and clock')
    if policy not in ('event-window','annotations'):
        raise ValueError('Unknown epoch annotation policy')
    remaining=Counter(_annotation_key(a) for a in original.annotations)
    added=[];ignored=0
    for i,a in enumerate(clean.annotations):
        key=_annotation_key(a)
        if remaining[key]:remaining[key]-=1
        elif policy=='event-window' and a['description']=='BAD_residual':ignored+=1
        else:added.append(i)
    # Union with original labels even if a caller accidentally lost them.
    ann=original.annotations.copy()
    if added:ann+=clean.annotations[added]
    if ann.orig_time is None:ann.onset-=original.first_time
    base=clean.copy().set_annotations(ann)
    return base,ignored


def make_strict_epochs(clean,original,events,event_id,*,global_bads=(),config=None,save_path=None,subject='subject',
                       annotation_policy='event-window'):
    cfg=config or EpochConfig()
    if (not cfg.tmin<=0<cfg.tmax or not np.isfinite([cfg.tmin,cfg.tmax,cfg.peak_uv,cfg.ptp_uv,
            cfg.robust_z,cfg.relative_min_ptp_uv]).all()
            or min(cfg.peak_uv,cfg.ptp_uv,cfg.robust_z,cfg.relative_min_ptp_uv)<=0):
        raise ValueError('Invalid ERP epoch window or artifact limits')
    base,ignored=_epoch_base(clean,original,annotation_policy)
    epochs=mne.Epochs(base,events,event_id,tmin=cfg.tmin,tmax=cfg.tmax,baseline=cfg.baseline,
        preload=True,reject_by_annotation=True,event_repeated='error',verbose=False)
    good=[i for i in mne.pick_types(epochs.info,eeg=True,exclude=[]) if epochs.ch_names[i] not in global_bads]
    if len(good)<8:raise ValueError('Insufficient usable EEG channels for epoch QC')
    selection=epochs.selection.copy()
    failed=(screen(epochs.get_data(picks=good),cfg).any(axis=1)
            if len(epochs) and annotation_policy=='event-window' else np.zeros(len(epochs),bool))
    epochs.drop(np.flatnonzero(failed),reason='BALANCED_RESIDUAL',verbose=False)
    retained=set(epochs.selection.tolist());screened={int(i):bool(b) for i,b in zip(selection,failed)}
    records=[dict(input_event_index=i,event_sample=int(e[0]),condition=int(e[2]),
        retained=i in retained,failed_trial_screen=screened.get(i),
        drop_reasons=list(epochs.drop_log[i]),interpolated_channels=[]) for i,e in enumerate(events)]
    report=dict(method=('Fixed trial-local QC, no local interpolation' if annotation_policy=='event-window'
                        else 'Continuous annotation rejection, no trial-local screen'),config=asdict(cfg),
        annotation_policy=annotation_policy,event_window_qc_enabled=annotation_policy=='event-window',
        newly_generated_residual_annotations_ignored=ignored,
        input_BAD_annotation_count=sum(a['description'].lower().startswith('bad') for a in original.annotations),
        annotation_or_boundary_rejected_epochs=len(events)-len(selection),
        qc_channels=[epochs.ch_names[i] for i in good],
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),input_events=len(events),
        eligible_epochs=len(selection),retained_epochs=len(epochs),repaired_epochs=0,
        local_interpolation_enabled=False,
        condition_retention={str(int(code)):dict(input=int(np.sum(events[:,2]==code)),
            eligible=int(np.sum(events[selection,2]==code)),
            retained=int(np.sum(epochs.events[:,2]==code))) for code in np.unique(events[:,2])},
        failed_screen_before_repair=int(failed.sum()),failed_screen_after_repair=int(failed.sum()),
        enabled=False,records=records,original_BAD_annotations_preserved=True,continuous_data_modified=False,
        global_interpolated=list(global_bads),original_drop_log=[list(x) for x in epochs.drop_log],
        status='review_required' if len(epochs)<.5*len(events) else 'completed')
    if save_path:
        out=Path(save_path);out.mkdir(parents=True,exist_ok=True)
        epoch_path=out/f'{subject}_clean-epo.fif'
        if len(epochs):epochs.save(epoch_path,fmt='double',overwrite=True,verbose=False)
        elif epoch_path.exists():epoch_path.unlink()  # No stale successful export after an all-rejected rerun.
        (out/f'{subject}_epoch_qc.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    return epochs,report
