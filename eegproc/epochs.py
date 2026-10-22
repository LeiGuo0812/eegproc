"""Bounded, audited ERP repair using the published AutoReject implementation.

Only trials failing the prespecified amplitude/relative-noise screen may be
changed. Input BAD annotations remain hard exclusions. Continuous samples are
never overwritten with trial-specific interpolation.
"""
from dataclasses import dataclass, asdict
from pathlib import Path
import json
import mne
import numpy as np
from threadpoolctl import threadpool_limits


@dataclass(frozen=True)
class EpochConfig:
    tmin: float = -.2
    tmax: float = 1.
    baseline: tuple = (None, 0.)
    peak_uv: float = 150.
    ptp_uv: float = 200.
    robust_z: float = 6.
    relative_min_ptp_uv: float = 50.
    max_interpolate: int = 4
    max_local_fraction: float = .125
    min_fit_epochs: int = 10
    cv: int = 5
    seed: int = 20261018


def screen(data, cfg):
    """Trial x channel screen; same absolute limits before and after repair."""
    uv=np.asarray(data)*1e6
    ptp=np.ptp(uv,axis=-1)
    logsd=np.log(np.maximum(np.std(uv,axis=-1),1e-9))
    center=np.median(logsd,axis=0)
    mad=1.4826*np.median(np.abs(logsd-center),axis=0)
    z=(logsd-center)/np.maximum(mad,.1)
    return (np.max(np.abs(uv),axis=-1)>cfg.peak_uv)|(ptp>cfg.ptp_uv)|((z>cfg.robust_z)&(ptp>cfg.relative_min_ptp_uv))


def _restore_input_annotations(clean, original):
    """Copy attached annotations without double-applying first_time."""
    if clean.first_samp!=original.first_samp or clean.n_times!=original.n_times or clean.info['sfreq']!=original.info['sfreq']:
        raise ValueError('ERP repair needs original input on the identical sample grid')
    result=clean.copy()
    ann=original.annotations.copy()
    if ann.orig_time is None:
        ann.onset-=original.first_time
    result.set_annotations(ann)
    return result


def repair_epochs(clean, original, events, event_id, *, global_bads=(), config=None, save_path=None, subject='subject'):
    """Return MNE Epochs, per-input-event log and fitted AutoReject diagnostics.

    Events use MNE absolute sample indices. No condition labels, truth, ERP
    amplitudes, or held-out benchmark outcomes select thresholds.
    """
    from autoreject import AutoReject
    cfg=config or EpochConfig()
    if not cfg.tmin<0<cfg.tmax or min(cfg.peak_uv,cfg.ptp_uv,cfg.robust_z,cfg.relative_min_ptp_uv)<=0:
        raise ValueError('Invalid epoch window or artifact limits')
    if not 0<cfg.max_local_fraction<=.25 or cfg.max_interpolate<1 or cfg.cv<2 or cfg.min_fit_epochs<cfg.cv:
        raise ValueError('Invalid repair budget/CV')
    base=_restore_input_annotations(clean,original)
    epochs=mne.Epochs(base,events,event_id,tmin=cfg.tmin,tmax=cfg.tmax,baseline=cfg.baseline,
        preload=True,reject_by_annotation=True,event_repeated='error',verbose=False)
    eeg=mne.pick_types(epochs.info,eeg=True,exclude=[])
    good=[i for i in eeg if epochs.ch_names[i] not in global_bads]
    if len(good)<8:raise ValueError('Insufficient originally usable EEG channels for ERP repair')
    report=dict(config=asdict(cfg),method='AutoReject 0.4.3; gated repair and fixed post-screen',
        input_events=len(events),eligible_epochs=len(epochs),global_interpolated=list(global_bads),
        original_BAD_annotations_preserved=True,continuous_data_modified=False,
        condition_labels_used_for_thresholds=False,enabled=False,thresholds_uv={},records=[])
    # Reporting only: retain the pre-screen counts even if no trial survives.
    report['condition_retention']={str(int(code)):dict(input=int(np.sum(events[:,2]==code)),
        eligible=int(np.sum(epochs.events[:,2]==code)),retained=0) for code in np.unique(events[:,2])}
    report['annotation_policy']='input-annotations-plus-local-repair'
    if not len(epochs):
        report.update(retained_epochs=0,repaired_epochs=0,status='review_required',reason='No eligible epochs')
        report['original_drop_log']=[list(x) for x in epochs.drop_log]
        report['records']=[dict(input_event_index=i,event_sample=int(e[0]),condition=int(e[2]),
            retained=False,drop_reasons=list(epochs.drop_log[i]),interpolated_channels=[]) for i,e in enumerate(events)]
        if save_path:
            directory=Path(save_path);directory.mkdir(parents=True,exist_ok=True)
            (directory/f'{subject}_epoch_qc.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        return epochs,report
    original_data=epochs.get_data(copy=True)
    before=screen(original_data[:,good],cfg)
    targets=before.any(axis=1)
    values=original_data.copy()
    reject=targets.copy()
    repaired={}
    cap=min(cfg.max_interpolate,int(np.floor(len(eeg)*cfg.max_local_fraction)))
    report['failed_screen_before_repair']=int(targets.sum())
    report['repair_cap_channels']=cap
    if targets.any() and len(epochs)>=cfg.min_fit_epochs and cap>=1:
        # Consensus must exceed the interpolation budget. Whole trial failures
        # are still rejected; no zero-filling, clipping, or amplitude scaling.
        ar=AutoReject(n_interpolate=sorted(set([1,min(2,cap),cap])),
            consensus=[.15,.25,.35],cv=min(cfg.cv,len(epochs)),picks=good,
            random_state=cfg.seed,n_jobs=1,verbose=False)
        with threadpool_limits(limits=1):
            ar.fit(epochs)
            fixed,log=ar.transform(epochs[targets],return_log=True)
        report.update(enabled=True,thresholds_uv={k:float(v*1e6) for k,v in ar.threshes_.items()},
            learned_n_interpolate=ar.n_interpolate_,learned_consensus=ar.consensus_)
        lookup={int(e[0]):i for i,e in enumerate(epochs.events)}
        fixed_values=fixed.get_data(copy=True) if len(fixed) else []
        for arr,event in zip(fixed_values,fixed.events):
            idx=lookup[int(event[0])]
            values[idx]=arr
            reject[idx]=False
        for local,idx in enumerate(np.flatnonzero(targets)):
            interpolated=[epochs.ch_names[i] for i in np.flatnonzero(log.labels[local]==2)]
            if not reject[idx] and interpolated:repaired[int(idx)]=interpolated
        # Restore permanently bad channels after changing their neighbours,
        # then CAR. Auxiliary channels never enter interpolation/reference.
        candidate=epochs.copy()
        candidate.apply_function(lambda _:values,channel_wise=False,verbose=False)
        if global_bads:
            candidate.info['bads']=list(global_bads)
            candidate.interpolate_bads(reset_bads=True,verbose=False)
        candidate.set_eeg_reference('average',projection=False,verbose=False)
        # Only gated targets may change, including when global interpolation is
        # recomputed. The pre/post screen uses identical numerical limits.
        corrected=candidate.get_data(copy=True)
        values[targets]=corrected[targets]
        after=screen(values[:,good],cfg)
        reject|=after.any(axis=1)
        report['failed_screen_after_repair']=int(after.any(axis=1).sum())
    else:
        report['reason']='No screen failures' if not targets.any() else 'Too few epochs or insufficient repair budget; failed trials rejected'
        report['failed_screen_after_repair']=int(targets.sum())
    # Preserve the MNE selection/drop_log chain and the original event samples.
    epochs.apply_function(lambda _:values,channel_wise=False,verbose=False)
    selection=epochs.selection.copy()
    epochs.drop(np.flatnonzero(reject),reason='BALANCED_RESIDUAL',verbose=False)
    for idx,source_index in enumerate(selection):
        report['records'].append(dict(input_event_index=int(source_index),
            event_sample=int(events[source_index,0]),condition=int(events[source_index,2]),
            failed_initial_screen=bool(targets[idx]),retained=not bool(reject[idx]),
            drop_reasons=list(epochs.drop_log[source_index]),
            interpolated_channels=repaired.get(idx,[])))
    eligible_indices=set(selection.tolist())
    report['records'] += [dict(input_event_index=i,event_sample=int(e[0]),condition=int(e[2]),
        retained=False,drop_reasons=list(epochs.drop_log[i]),interpolated_channels=[]) for i,e in enumerate(events) if i not in eligible_indices]
    report['records'].sort(key=lambda r:r['input_event_index'])
    for code,row in report['condition_retention'].items():
        row['retained']=int(np.sum(epochs.events[:,2]==int(code)))
    report.update(retained_epochs=len(epochs),repaired_epochs=sum(not reject[i] for i in repaired),
        status='review_required' if len(epochs)<.5*len(events) else 'completed',
        original_drop_log=[list(x) for x in epochs.drop_log])
    if save_path:
        directory=Path(save_path);directory.mkdir(parents=True,exist_ok=True)
        if len(epochs):epochs.save(directory/f'{subject}_clean-epo.fif',fmt='double',overwrite=True,verbose=False)
        def conv(x):
            if isinstance(x,np.generic):return x.item()
            raise TypeError(type(x).__name__)
        (directory/f'{subject}_epoch_qc.json').write_text(json.dumps(report,ensure_ascii=False,indent=2,default=conv),encoding='utf8')
    return epochs,report
