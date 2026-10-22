"""Bounded, paired spectra of the line-cleaning stage; no Raw copies or changes."""
import mne
import numpy as np
from scipy.signal import welch

from .backends import line_frequencies
from .signal_ops import annotation_mask, contiguous_spans, BOUNDARIES


def _spectrum(raw, state):
    width=state['window_samples']
    total=None
    for start in state['starts_samples']:
        data=raw.get_data(picks=state['channels'],start=start,stop=start+width)*1e6
        if not np.isfinite(data).all():
            raise ValueError('Nonfinite samples in line-noise diagnostic windows')
        _,power=welch(data,fs=raw.info['sfreq'],window='hann',nperseg=width,
            noverlap=0,detrend='constant',scaling='density',axis=-1)
        power=power[:,state['_frequency_indices']]
        total=power if total is None else total+power
    return total/len(state['starts_samples'])


def capture_line_input(raw, config):
    """Capture only sampled PSD bins before in-place line cleaning."""
    targets=line_frequencies(raw,config).tolist()
    if config.line_method=='off' or config.line_frequency is None:
        return dict(status='disabled',reason='Line-noise removal was disabled.',targets_hz=[])
    if not targets:
        return dict(status='not_applied',reason='No target frequencies within the processing range.',targets_hz=[])
    channels=[raw.ch_names[i] for i in mne.pick_types(raw.info,eeg=True,exclude='bads')]
    spans=contiguous_spans(~annotation_mask(raw,BOUNDARIES))
    sf=float(raw.info['sfreq'])
    width=int(min(round(4.*sf),max((b-a for a,b in spans),default=0)))
    if not channels or width<max(8,round(2.*sf)):
        return dict(status='unavailable',reason='No usable EEG channels or non-BAD segment of at least 2 s.',
            targets_hz=targets)
    eligible=[start for a,b in spans for start in range(a,b-width+1,width)]
    starts=[int(eligible[i]) for i in np.unique(np.linspace(0,len(eligible)-1,
        min(config.report_psd_windows,len(eligible)),dtype=int))]
    frequency=np.fft.rfftfreq(width,1/sf)
    select=np.any(np.abs(frequency[:,None]-np.array(targets)[None,:])<=5.,axis=1)
    state=dict(status='captured',targets_hz=targets,channels=channels,
        starts_samples=starts,starts_seconds=[s/sf for s in starts],window_samples=width,
        window_seconds=width/sf,window_count=len(starts),sfreq=sf,first_samp=int(raw.first_samp),
        n_times=int(raw.n_times),frequency_resolution_hz=sf/width,frequency_hz=frequency[select].tolist(),
        reference='recorded reference; no display rereferencing',units='uV^2/Hz',
        input_bad_channels_excluded=True,input_bad_intervals_excluded=True,
        stage='immediately before/after line-noise removal; before band filtering, ASR and ICA',
        _frequency_indices=np.flatnonzero(select))
    state['_before_psd']=_spectrum(raw,state)
    return state


def finish_line_diagnostics(raw, state):
    """Use exactly the same windows/channels; persist compact summaries only."""
    if state['status']!='captured':return state
    if (raw.n_times!=state['n_times'] or raw.first_samp!=state['first_samp']
            or raw.info['sfreq']!=state['sfreq']):
        raise ValueError('Line-noise diagnostic sample grid changed')
    before=state['_before_psd'];after=_spectrum(raw,state)
    frequency=np.asarray(state['frequency_hz'])
    result={key:value for key,value in state.items() if not key.startswith('_')}
    result.update(status='available',before_psd_quartiles=np.percentile(before,[25,50,75],axis=0).tolist(),
        after_psd_quartiles=np.percentile(after,[25,50,75],axis=0).tolist(),metrics=[])
    for target in state['targets_hz']:
        mask=np.abs(frequency-target)<=1.
        a=before[:,mask].sum(axis=1)*state['frequency_resolution_hz']
        b=after[:,mask].sum(axis=1)*state['frequency_resolution_hz']
        valid=(a>0)&(b>0)
        reduction=10*(np.log10(a[valid])-np.log10(b[valid]))
        result['metrics'].append(dict(frequency_hz=target,band_low_hz=float(frequency[mask].min()),
            band_high_hz=float(frequency[mask].max()),before_median_power_uv2=float(np.median(a)),
            after_median_power_uv2=float(np.median(b)),
            median_reduction_db=float(np.median(reduction)) if len(reduction) else None,
            reduction_iqr_db=np.percentile(reduction,[25,75]).tolist() if len(reduction) else None,
            valid_channel_count=int(valid.sum())))
    return result
