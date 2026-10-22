"""Explicit backend adapters; EEGPrep is optional and never runs MATLAB."""
import mne
import numpy as np
from .signal_ops import BOUNDARIES, annotation_mask, contiguous_spans, band_filter


def reference(raw, config):
    if config.reference == 'average':
        raw.set_eeg_reference('average', projection=False, verbose='warning')
    return raw


def eegprep_input(raw, data=None):
    from eegprep import eeg_emptyset
    eeg=eeg_emptyset()
    values=raw.get_data() if data is None else data
    eeg.update(data=values*1e6,srate=float(raw.info['sfreq']),nbchan=len(raw.ch_names),
        pnts=values.shape[1],trials=1,xmin=0.,xmax=(values.shape[1]-1)/raw.info['sfreq'],
        times=np.arange(values.shape[1])*1000/raw.info['sfreq'],event=[],urevent=[])
    eeg['chanlocs']=[dict(labels=name,X=float(ch['loc'][1]),Y=float(-ch['loc'][0]),Z=float(ch['loc'][2]))
        for name,ch in zip(raw.ch_names,raw.info['chs'])]
    return eeg


def apply_filter(raw, low, high, config):
    if config.filter_method=='off' or (low is None and high is None):return raw
    if config.filter_method=='mne_fir':return band_filter(raw,low,high)
    from eegprep import pop_eegfiltnew
    # The original script runs two successive EEGLAB FIR filters. Preserve each
    # original BAD/boundary span without allowing filter padding across it.
    mask=annotation_mask(raw,BOUNDARIES)
    for a,b in contiguous_spans(~mask):
        eeg=eegprep_input(raw,raw.get_data(start=a,stop=b))
        if low is not None:eeg=pop_eegfiltnew(eeg,locutoff=low,filtorder=config.filter_order,usefftfilt=True,gui=False)
        if high is not None:eeg=pop_eegfiltnew(eeg,hicutoff=high,filtorder=config.filter_order,usefftfilt=True,gui=False)
        raw._data[:,a:b]=eeg['data']/1e6
    with raw.info._unlock():
        if low is not None:raw.info['highpass']=max(raw.info['highpass'],low)
        if high is not None:raw.info['lowpass']=min(raw.info['lowpass'],high)
    return raw


def line_frequencies(raw,config):
    """Frequencies actually eligible for line-noise removal."""
    if config.line_method=='off' or config.line_frequency is None:
        return np.array([],dtype=float)
    return np.arange(config.line_frequency,min(100.,raw.info['sfreq']/2-1)+.01,config.line_frequency)


def clean_line(raw,config):
    if config.line_method=='off' or config.line_frequency is None:
        return dict(backend='disabled',frequencies_hz=[])
    freqs=line_frequencies(raw,config)
    options=dict(method='spectrum_fit',mt_bandwidth=config.line_bandwidth,p_value=config.line_p_value,
        filter_length=f'{config.line_window_seconds}s') if config.line_method=='spectrum_fit' else dict(method='fir',phase='zero')
    skipped=[];processed=[]
    if len(freqs):
        if config.line_method=='spectrum_fit':
            from .runtime_parameters import spectrum_fit_support
            # These are the same boundaries used inside the pinned MNE Raw
            # implementation, including its zero-duration discontinuity rules.
            from mne.annotations import _annotations_starts_stops
            starts,stops=_annotations_starts_stops(raw,BOUNDARIES,invert=True)
            spans=[(int(start),int(stop)) for start,stop in zip(starts,stops)]
            checks=[spectrum_fit_support(config.line_window_seconds,config.line_bandwidth,
                raw.info['sfreq'],stop-start) for start,stop in spans]
            skipped=[dict(samples=[start,stop],duration_seconds=(stop-start)/raw.info['sfreq'],**check)
                     for (start,stop),check in zip(spans,checks) if not check['supported']]
        if not skipped:
            # Preserve the original numerical call for every supported input.
            raw.notch_filter(freqs,picks='eeg',skip_by_annotation=BOUNDARIES,verbose='warning',**options)
        else:
            if not raw.preload:
                raise RuntimeError('Line cleaning requires preloaded Raw data')
            picks=mne.pick_types(raw.info,eeg=True,exclude=[])
            for (start,stop),check in zip(spans,checks):
                if not check['supported']:
                    continue
                mne.filter.notch_filter(raw._data[:,start:stop],raw.info['sfreq'],freqs,
                    picks=picks,copy=False,verbose='warning',**options)
                processed.append([start,stop])
    report=dict(backend='MNE '+config.line_method+' (not CleanLine)',frequencies_hz=freqs.tolist(),
        window_seconds=config.line_window_seconds if config.line_method=='spectrum_fit' else None,
        bandwidth_hz=config.line_bandwidth if config.line_method=='spectrum_fit' else None,p_value=config.line_p_value)
    if skipped:
        report.update(skipped_segments=skipped,processed_segments=processed,
            quality_flags=[f'Line-noise fitting skipped {len(skipped)} unsupported continuous segment(s); samples were retained.'],
            reason='Some BAD-separated spans cannot support the selected DPSS/COLA window and bandwidth.')
    return report


def detect_channels(eeg,config):
    existing=set(eeg.info['bads'])
    if config.channel_method=='off':return sorted(existing),dict(backend='disabled; input bads retained')
    detection=eeg.copy()
    if config.channel_method=='pyprep':band_filter(detection,config.training_highpass,config.training_lowpass)
    else:apply_filter(detection,config.training_highpass,config.training_lowpass,config)
    blocked=annotation_mask(detection,BOUNDARIES)
    data=detection.get_data()[:,~blocked]
    if data.shape[1]<config.min_training_seconds*detection.info['sfreq']:
        raise ValueError('Insufficient unannotated data for channel detection')
    if blocked.any():detection=mne.io.RawArray(data,detection.info.copy(),verbose=False)
    if config.channel_method=='pyprep':
        from pyprep import NoisyChannels
        detector=NoisyChannels(detection,do_detrend=False,random_state=config.seed,ransac=config.detect_ransac)
        detector.find_all_bads()
        bads=set(detector.get_bads());criteria=detector.get_bads(as_dict=True)
    else:
        from eegprep import clean_flatlines,clean_channels
        native=eegprep_input(detection)
        native=clean_flatlines(native,max_flatline_duration=config.flatline_seconds)
        flat=set(eeg.ch_names)-{c['labels'] for c in native['chanlocs']}
        native=clean_channels(native,corr_threshold=config.channel_correlation,noise_threshold=np.inf,
            max_broken_time=config.channel_broken_fraction)
        bads=set(eeg.ch_names)-{c['labels'] for c in native['chanlocs']}
        criteria=dict(flatline=sorted(flat),correlation=sorted(bads-flat),flatline_seconds=config.flatline_seconds,
            correlation_threshold=config.channel_correlation,noise_threshold='disabled',
            max_broken_fraction=config.channel_broken_fraction)
    return sorted(existing|bads),dict(backend=config.channel_method,criteria=criteria,
        existing_bad_samples_excluded=int(blocked.sum()),on_1_100_hz_copy=config.channel_method=='pyprep',
        omission_note='Input BAD/boundaries excluded; remaining samples concatenated only for channel detection')


def alignment_notes(config):
    return ['EEGLAB-derived filter, channel, rank and component-selection parameters; processing stages are shared with the standard preset.'] if config.preset=='eeglab' else []
