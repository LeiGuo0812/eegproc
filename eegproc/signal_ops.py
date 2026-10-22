"""Annotation-aware continuous signal operations; no file output."""
import mne
import numpy as np
from scipy.ndimage import binary_dilation
BOUNDARIES = ("edge", "bad", "boundary")

def assess_bad_channel_burden(report, config, bads, total):
    """Separate a review threshold from the minimum viable channel count."""
    policy = config.bad_channel_policy
    if policy == 'auto':
        policy = 'report' if config.asr_backend == 'mne_native' else 'stop'
    count = len(bads)
    exceeded = count > config.bad_channel_fraction_limit * total
    report['bad_channel_qc'] = dict(policy=policy, fraction_limit=config.bad_channel_fraction_limit,
        bad_count=count, total_eeg_channels=total, bad_fraction=count/total,
        good_count=total-count, threshold_exceeded=exceeded,
        continued_despite_threshold=exceeded and policy=='report' and total-count>=8,
        minimum_good_channels=8)
    if total-count < 8:
        raise ValueError(f'Insufficient usable EEG channels: {total-count}/{total}; at least 8 required')
    if exceeded:
        message = f'Bad-channel fraction {count}/{total} ({count/total:.2%}) exceeds {config.bad_channel_fraction_limit:.0%}'
        if policy == 'stop':
            raise ValueError(message+'; manual review required (bad_channel_policy=stop)')
        report['quality_flags'].append(message+'; processing continued; manual review required before analysis')


def annotation_mask(raw, prefixes=("bad",)):
    """Map annotations to the actual sample grid, including cropped first_samp."""
    mask = np.zeros(raw.n_times, bool)
    sf = raw.info["sfreq"]
    for a in raw.annotations:
        if str(a["description"]).lower().startswith(prefixes):
            start = int(np.floor((a["onset"] - raw.first_time) * sf + 1e-7))
            end = int(np.ceil((a["onset"] - raw.first_time + a["duration"]) * sf - 1e-7))
            mask[max(0, start):min(raw.n_times, max(start + 1, end))] = True
    return mask


def contiguous_spans(mask):
    changes = np.diff(np.r_[False, mask, False].astype(int))
    return list(zip(np.flatnonzero(changes == 1), np.flatnonzero(changes == -1)))


def add_mask_annotations(raw, mask, name):
    # Annotations already attached to Raw use onset relative to meas_date,
    # with first_time included even when orig_time is None. Append directly.
    for start, end in contiguous_spans(mask):
        raw.annotations.append(raw.first_time + start / raw.info["sfreq"],
                               (end - start) / raw.info["sfreq"], name)


def physical_rank(data):
    x = np.asarray(data, float)
    x = x - x.mean(axis=1, keepdims=True)
    s = np.linalg.svd(x, compute_uv=False)
    tol = max(x.shape) * np.finfo(float).eps * s[0]
    # A relative covariance threshold avoids the uV/V dependent legacy cutoff.
    keep = s > max(tol, s[0] * 1e-6)
    return int(keep.sum()), {"singular_values_volts": s.tolist(), "relative_singular_tolerance": 1e-6}


def band_filter(raw, low, high):
    if low is None and high is None:
        return raw
    raw.filter(low, high, picks="eeg", method="fir", phase="zero", fir_design="firwin",
               fir_window="hamming", l_trans_bandwidth=min(low, max(low / 2, 0.1)) if low is not None else "auto",
               h_trans_bandwidth=min(max(high / 4, 2), raw.info["sfreq"] / 2 - high) if high is not None else "auto",
               pad="reflect_limited", skip_by_annotation=BOUNDARIES, verbose="warning")
    return raw


def window_mask(raw, peak_uv, ptp_uv=None, guard_seconds=0.25, window_seconds=1):
    picks = mne.pick_types(raw.info, eeg=True, exclude="bads")
    # Preserve the full-record channel medians, but hold only one channel at
    # a time. Computing a median independently per row gives the same values
    # as the former median(data, axis=1), without an EEG-sized partition copy.
    centers = np.empty((len(picks), 1))
    for row, pick in enumerate(picks):
        values = raw.get_data(picks=[pick])[0]
        values *= 1e6
        centers[row, 0] = np.median(values)
    if len(picks):
        del values
    sf = raw.info["sfreq"]
    width = max(1, int(round(window_seconds * sf)))
    mask = np.zeros(raw.n_times, bool)
    for start in range(0, raw.n_times, width):
        part = raw.get_data(picks=picks, start=start, stop=min(start + width, raw.n_times))
        part *= 1e6
        part -= centers
        if np.max(np.abs(part)) > peak_uv or (ptp_uv is not None and np.max(np.ptp(part, axis=1)) > ptp_uv):
            mask[start:start + width] = True
    if mask.any() and guard_seconds:
        mask = binary_dilation(mask, iterations=int(np.ceil(guard_seconds * sf)))
    return mask


def relative_window_mask(raw, z_threshold=6., min_ptp_uv=50., guard_seconds=.25, window_seconds=1.):
    """Conservative QC for local bursts below an absolute rejection threshold.

    This is a documented engineering rule, not a calibrated diagnostic test.
    It only annotates; it never deletes or rescales samples.
    """
    picks=mne.pick_types(raw.info,eeg=True,exclude="bads")
    width=max(2,int(round(window_seconds*raw.info['sfreq'])))
    starts=list(range(0,raw.n_times,width))
    scales=[];ptps=[]
    for a in starts:
        part=raw.get_data(picks=picks,start=a,stop=min(a+width,raw.n_times))
        part*=1e6
        scales.append(np.log(np.maximum(np.std(part,axis=1),1e-9)))
        ptps.append(np.ptp(part,axis=1))
    scale=np.array(scales).T
    center=np.median(scale,axis=1,keepdims=True)
    deviation=1.4826*np.median(np.abs(scale-center),axis=1,keepdims=True)
    z=(scale-center)/np.maximum(deviation,.1)
    mask=np.zeros(raw.n_times,bool)
    for i,a in enumerate(starts):
        ptp=ptps[i]
        if np.any((z[:,i]>z_threshold)&(ptp>min_ptp_uv)):
            mask[a:a+width]=True
    if mask.any() and guard_seconds:
        mask=binary_dilation(mask,iterations=int(np.ceil(guard_seconds*raw.info['sfreq'])))
    return mask


def _line_clean(raw, frequency):
    """Native sinusoidal spectrum-fit, separately within continuous segments."""
    if frequency is None:
        return {"backend": "disabled", "frequencies_hz": [], "reason": "line_frequency=None"}
    freqs = np.arange(frequency, min(100.0, raw.info["sfreq"] / 2 - 1) + 0.01, frequency)
    if freqs.size:
        raw.notch_filter(freqs, picks="eeg", method="spectrum_fit", mt_bandwidth=2,
                         p_value=0.05, filter_length="4s", skip_by_annotation=BOUNDARIES,
                         verbose="warning")
    return {"backend": "MNE spectrum_fit (not CleanLine)", "frequencies_hz": freqs.tolist(),
            "window_seconds": 4, "bandwidth_hz": 2, "p_value": 0.05}


def _training_segments(raw, min_seconds, excluded=None):
    mask = annotation_mask(raw)
    # Separate segments at acquisition boundaries even for zero duration.
    mask |= annotation_mask(raw, BOUNDARIES)
    if excluded is not None:
        mask |= excluded
    spans = [(a, b) for a, b in contiguous_spans(~mask) if b - a >= raw.info["sfreq"]]
    if sum(b - a for a, b in spans) < min_seconds * raw.info["sfreq"]:
        raise ValueError("Insufficient clean continuous samples for ICA training")
    if spans == [(0, raw.n_times)]:
        return raw, spans
    from .raw_helpers import raw_slice
    parts = [raw_slice(raw, a, b) for a, b in spans]
    result = mne.concatenate_raws(parts, verbose="warning")
    return result, spans


def _asr_segments(raw, config):
    """Never calibrate or propagate ASR state through an existing BAD span."""
    from .mne_asr import ASRConfig
    from .mne_asr.api import _clean_asr_owned as native_clean
    def clean_asr_raw(part, cutoff):
        return native_clean(part, config=ASRConfig(cutoff=cutoff,
            min_segment_seconds=config.min_training_seconds,**(config.asr_options or {})))
    blocked = annotation_mask(raw, BOUNDARIES)
    # This private helper receives an owned, preloaded EEG working buffer.
    from .raw_helpers import raw_slice, signal_hash
    result = raw
    records = []
    flags = []
    for a, b in contiguous_spans(~blocked):
        if b-a < config.min_training_seconds * raw.info['sfreq']:
            flags.append('ASR skipped a short uninterrupted good segment')
            continue
        part = raw_slice(raw, a, b)
        input_hash = signal_hash(part)
        clean, diagnostic = clean_asr_raw(part, cutoff=config.asr_cutoff)
        diagnostic['input_eeg_float64_sha256'] = input_hash
        # The private ASR path owns and updates ``part``. The source working
        # record is still unchanged here, so it supplies the exact input for
        # diagnostics without retaining another segment-sized Raw copy.
        delta=clean._data-raw._data[:,a:b]
        diagnostic['changed_sample_fraction_above_0p1nV']=float((np.max(np.abs(delta),axis=0)>1e-10).mean())
        diagnostic['correction_rms_uv']=float(np.sqrt(np.mean(delta**2))*1e6)
        result._data[:, a:b] = clean._data
        records.append({'samples':[int(a),int(b)],'diagnostics':diagnostic})
        del part, clean, delta
    return result, {'cutoff':config.asr_cutoff,'backend':config.asr_backend,'segments':records,
                    'existing_bad_and_boundary_samples_excluded':int(blocked.sum()),
                    'shared_broadband_reconstruction':True}, flags


