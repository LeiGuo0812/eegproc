"""Named scientific stages. All inputs and outputs are native MNE containers."""
import mne
import numpy as np
from .raw_helpers import raw_slice, channel_is_finite_nonconstant, concatenate_samples
from .signal_ops import BOUNDARIES, assess_bad_channel_burden, window_mask, _asr_segments, _training_segments
from .backends import apply_filter, clean_line, detect_channels, reference

def prepare_signals(current,picks,config,report,execution,store):
    eeg = raw_slice(current,picks=picks)
    eeg_info=eeg.info.copy()
    execution.start('line_cleaning')
    from .line_diagnostics import capture_line_input, finish_line_diagnostics
    try:
        line_input=capture_line_input(eeg,config)
    except Exception as exc:
        line_input=dict(status='unavailable',reason=str(exc),error=type(exc).__name__)
    report["line_cleaning"] = clean_line(eeg, config)
    report['quality_flags'].extend(report['line_cleaning'].get('quality_flags', []))
    try:
        report['line_diagnostics']=finish_line_diagnostics(eeg,line_input)
    except Exception as exc:
        report['line_diagnostics']=dict(status='unavailable',reason=str(exc),error=type(exc).__name__)
    del line_input
    execution.start('channel_detection')
    bads, report["channel_detection"] = detect_channels(eeg,config)
    report["bad_channels"] = bads
    if len(bads)>.2*len(picks):
        report['quality_flags'].append('More than 20 percent of EEG channels require global interpolation')
    assess_bad_channel_burden(report, config, bads, len(picks))
    execution.start('reference_and_broad_filter')
    if config.interpolate_before_asr and bads:
        good = eeg
        good.info["bads"] = bads
        good.interpolate_bads(reset_bads=True, method={"eeg":"spline"}, verbose="warning")
    else:
        good = raw_slice(eeg,picks=[i for i,n in enumerate(eeg.ch_names) if n not in bads]) if bads else eeg
    del eeg
    report["interpolation_before_asr"] = config.interpolate_before_asr
    good.info["bads"] = []
    reference(good,config)
    common_low=min(config.highpass,config.training_highpass)
    common_high=max(config.lowpass,config.training_lowpass)
    broad = apply_filter(good, common_low, common_high,config)
    gross = window_mask(broad, config.gross_peak_uv, guard_seconds=config.guard_seconds,
                        window_seconds=config.window_seconds)
    report["gross_training_fraction"] = float(gross.mean())
    if config.asr_cutoff is not None:
        execution.start('asr')
        broad, report['asr'], asr_flags = _asr_segments(broad, config)
        report['quality_flags'].extend(asr_flags)
    else:
        execution.skip('asr', 'Disabled by configuration: asr_cutoff=None')
        report["asr"] = {"enabled": False, "reason": "Disabled by configuration; gross segments excluded from ICA, residuals flagged"}
    return broad, eeg_info, bads, gross

def prepare_training(broad,gross,config,report,execution,store,collect_stages,stages):
    execution.start('analysis_and_ica_training')
    reference(broad,config)
    common_low=min(config.highpass,config.training_highpass)
    common_high=max(config.lowpass,config.training_lowpass)
    same_band=(config.highpass,config.lowpass)==(config.training_highpass,config.training_lowpass)
    training_source = broad if same_band else broad.copy()
    training_edges=(config.training_highpass if config.training_highpass>common_low else None,
                    config.training_lowpass if config.training_lowpass<common_high else None)
    analysis_edges=(config.highpass if config.highpass>common_low else None,
                    config.lowpass if config.lowpass<common_high else None)
    apply_filter(training_source,*training_edges,config)
    analysis=apply_filter(broad,*analysis_edges,config)
    report['filter_plan']=dict(common_band_hz=[common_low,common_high],
        analysis_additional_edges_hz=list(analysis_edges),training_additional_edges_hz=list(training_edges),
        shared_full_record_buffer=same_band,duplicate_edge_filtering=False,
        note='BAD/gross exclusion can still require a compact training array; algorithm work buffers remain necessary')
    training, spans = _training_segments(training_source, config.min_training_seconds,excluded=gross if config.exclude_gross_from_training else None)
    report["training_original_relative_spans_samples"] = [[int(a),int(b)] for a,b in spans]
    # Small diagnostic excerpt is captured BEFORE in-place ICA application.
    lengths=[b-a for a,b in spans];which=int(np.argmax(lengths));preview_start=sum(lengths[:which])
    preview_stop=preview_start+min(lengths[which],round(60*training.info['sfreq']))
    diagnostic_training=raw_slice(training,preview_start,preview_stop)
    report['ica_preview']=dict(original_start_seconds=spans[which][0]/broad.info['sfreq'],
        training_start_sample=preview_start,training_stop_sample=preview_stop,
        duration_seconds=(preview_stop-preview_start)/broad.info['sfreq'],captured_before_ica_application=True)
    if collect_stages:
        stages.update(analysis_input=analysis.copy(), training=training.copy())
    return analysis, training, diagnostic_training, spans

def prepare_ecg(current,spans,config,report):
    typed_ecg=mne.pick_types(current.info,ecg=True,exclude=[])
    ecg_indices=[];ecg_rejected=[]
    for i in typed_ecg:
        if current.ch_names[i] in current.info['bads'] or not channel_is_finite_nonconstant(current,i):
            ecg_rejected.append(current.ch_names[i])
        else:ecg_indices.append(i)
    ecg_data=None
    if ecg_indices:
        ecg=raw_slice(current,picks=ecg_indices)
        nyquist=current.info['sfreq']/2
        upper=40. if nyquist>40. else nyquist-min(2.,nyquist*.05)
        if upper<=1.:
            # An ECG support band cannot be represented; retain ICLabel decisions.
            report['ecg_assistance']=dict(typed_channels=[current.ch_names[i] for i in typed_ecg],
                usable_channels=[],unusable_channels=[current.ch_names[i] for i in typed_ecg],
                fallback_to_iclabel_only=True,automatic_proxy_created=False,
                reason='Sampling frequency cannot support the ECG assistance band')
            report['quality_flags'].append('ECG assistance unavailable at this sampling frequency; ICLabel only')
            return None
        if upper!=40.:
            from .parameter_resolution import adjustment
            from .runtime_parameters import update_parameter_report
            update_parameter_report(report,config,[adjustment('ecg_support_band_hz',[1.,40.],[1.,upper],
                'ECG assistance upper frequency limited to below input Nyquist')])
        ecg.filter(1.,upper,picks=np.arange(len(ecg.ch_names)),skip_by_annotation=BOUNDARIES,verbose='warning')
        ecg_data=concatenate_samples(ecg,spans)
        usable=np.isfinite(ecg_data).all(axis=1)&(np.ptp(ecg_data,axis=1)>0)
        ecg_rejected.extend(ecg.ch_names[i] for i in np.flatnonzero(~usable))
        ecg_indices=[i for i,keep in zip(ecg_indices,usable) if keep]
        ecg_data=ecg_data[usable] if usable.any() else None
        del ecg
    report['ecg_assistance']=dict(typed_channels=[current.ch_names[i] for i in typed_ecg],
        usable_channels=[current.ch_names[i] for i in ecg_indices],unusable_channels=ecg_rejected,
        fallback_to_iclabel_only=ecg_data is None,automatic_proxy_created=False)
    if ecg_rejected:
        report['quality_flags'].append('Unusable ECG channels excluded from ICA support: '+', '.join(ecg_rejected))
    return ecg_data
