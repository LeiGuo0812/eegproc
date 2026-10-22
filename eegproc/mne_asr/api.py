"""Native MNE interface; all algorithm state belongs to the estimator instance."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
import hashlib
import warnings
import mne
import numpy as np
from mne.utils import object_diff
from ._reference import select_reference
from ._calibrate import asr_calibrate
from ._process import asr_process
from ._math import round_mat


@dataclass(frozen=True)
class ASRConfig:
    """Compatibility defaults; memory budget also determines update boundaries.

    Signal arrays use volts externally; internally the validated single-precision
    microvolt input convention is followed, then computations use float64.
    min_segment_seconds is a processing policy, not a claim that 20 s of reference
    data is scientifically sufficient. Selected references under 30 s are flagged.
    """
    cutoff: float = 20.
    reference_window: float = 1.
    reference_max_bad_channels: float = .075
    # clean_rawdata -> clean_artifacts overrides clean_asr's lower threshold.
    reference_tolerances: tuple[float, float] = (-np.inf, 5.5)
    calibration_window: float = .5
    overlap: float = .66
    processing_window: float | None = None
    step_size: int | None = None
    max_dimensions: float = .66
    max_memory_mb: float = 64.
    min_segment_seconds: float = 20.
    amplification_limit: float = 100.

    def validate(self):
        for name in ['cutoff','reference_window','calibration_window','max_memory_mb',
                     'min_segment_seconds','amplification_limit']:
            value = getattr(self, name)
            if not np.isfinite(value) or value <= 0:
                raise ValueError(f'{name} must be finite and positive')
        if not 0 <= self.overlap < 1 or not 0 <= self.reference_max_bad_channels < 1:
            raise ValueError('Invalid overlap or reference bad-channel fraction')
        if not 0 < self.max_dimensions < 1:
            raise ValueError('max_dimensions must be a fraction strictly between 0 and 1')
        lo, hi = self.reference_tolerances
        if np.isnan(lo) or not np.isfinite(hi) or not lo < 0 < hi:
            raise ValueError('Reference tolerances must straddle zero; lower may be -inf')
        if self.processing_window is not None and (not np.isfinite(self.processing_window) or self.processing_window <= 0):
            raise ValueError('processing_window must be finite and positive')
        if self.step_size is not None and (not isinstance(self.step_size, (int, np.integer)) or self.step_size < 1):
            raise ValueError('step_size must be a positive integer')


def _check_raw(raw):
    if not isinstance(raw, mne.io.BaseRaw):
        raise TypeError('ASR expects continuous mne.io.BaseRaw with EEG in volts')
    if not np.isfinite(raw.info['sfreq']) or raw.info['sfreq'] <= 80:
        raise ValueError('This spectral-shaping implementation requires sfreq > 80 Hz')


def _picks(raw, picks):
    if picks is None:
        result = mne.pick_types(raw.info, eeg=True, exclude='bads')
    else:
        names = [picks] if isinstance(picks, str) else list(picks)
        result = np.array([raw.ch_names.index(n) for n in names], dtype=int)
        types = raw.get_channel_types(picks=result)
        if any(t != 'eeg' for t in types) or set(names) & set(raw.info['bads']):
            raise ValueError('Explicit picks must be usable EEG channel names, excluding info.bads')
    if len(result) < 2 or len(set(result)) != len(result):
        raise ValueError('ASR needs at least two distinct usable EEG channels')
    return result


def _spans(raw):
    """Block BAD/EDGE/boundary samples, including zero-duration discontinuities.

    Channel-scoped BAD blocks the whole multichannel ASR window, conservatively.
    MNE attached onsets include first_time for either clock convention.
    """
    blocked = np.zeros(raw.n_times, dtype=bool)
    sf = raw.info['sfreq']
    for a in raw.annotations:
        if str(a['description']).lower().startswith(('bad','edge','boundary')):
            start = int(np.floor((a['onset']-raw.first_time)*sf + 1e-7))
            stop = int(np.ceil((a['onset']-raw.first_time+a['duration'])*sf - 1e-7))
            left, right = max(0,start), min(raw.n_times,max(start+1,stop))
            if right > left:
                blocked[left:right] = True
    change = np.diff(np.r_[False, ~blocked, False].astype(int))
    return list(zip(np.flatnonzero(change == 1), np.flatnonzero(change == -1))), blocked


def _backend_values(x):
    if not np.isfinite(x).all():
        raise ValueError('Usable EEG samples must be finite; mark unusable spans BAD first')
    with np.errstate(over='raise', invalid='raise'):
        quantized = (x*1e6).astype(np.float32).astype(float)
    return quantized, float(np.max(np.abs(quantized-x*1e6)))


class ASR:
    """Reusable offline calibration with fit/transform on MNE Raw.

    fit excludes BAD/EDGE/boundaries from reference selection. transform resets
    processing state at every boundary and preserves blocked/short spans. A
    separate reference can be fitted once and transformed onto compatible data.
    fit_transform uses one reference model for the supplied Raw. For per-span
    recalibration matching P13/P15, use clean_asr_raw instead.
    """
    def __init__(self, cutoff=20., *, config=None):
        self.config = config if config is not None else ASRConfig(cutoff=cutoff)
        self.config.validate()
        self._state = None

    def fit(self, raw, picks=None):
        _check_raw(raw)
        self._state = None
        indices = _picks(raw, picks)
        sf = float(raw.info['sfreq'])
        spans, blocked = _spans(raw)
        mask = np.zeros(raw.n_times, dtype=bool)
        chunks = []
        quantization = 0.
        x = raw.get_data(picks=indices)
        for start, stop in spans:
            if stop-start < self.config.min_segment_seconds*sf:
                continue
            part, q = _backend_values(x[:,start:stop])
            quantization = max(quantization, q)
            selected = select_reference(part, sf, window=self.config.reference_window,
                overlap=self.config.overlap, max_bad=self.config.reference_max_bad_channels,
                tolerances=self.config.reference_tolerances)
            mask[start:stop] = selected
            chunks.append(part[:,selected])
        if not chunks or sum(p.shape[1] for p in chunks) < max(64, sf):
            raise ValueError('Insufficient selected reference data; no all-data fallback is used')
        reference = np.concatenate(chunks, axis=1)
        # The reference owns its concatenated data. None of the input/selection
        # work arrays are needed by calibration, whose temporary arrays can be
        # substantially larger than the signal itself.
        del x, part, selected, chunks
        if np.any(np.std(reference, axis=1) == 0):
            raise ValueError('Flat reference channel; remove or mark it bad before ASR')
        state = asr_calibrate(reference, sf, cutoff=self.config.cutoff,
            window_len=self.config.calibration_window, window_overlap=self.config.overlap,
            maxmem=self.config.max_memory_mb)
        if not all(np.isfinite(state[k]).all() for k in ['M','T','B','A']):
            raise FloatingPointError('Nonfinite ASR calibration state')
        flags = []
        if reference.shape[1]/sf < 30:
            flags.append('Selected calibration is under 30 s; inspect reference quality')
        if raw.info['highpass'] < .5:
            flags.append('Input highpass metadata is below 0.5 Hz; ASR assumes high-passed EEG and does not filter it for you')
        for flag in flags:
            warnings.warn(flag, RuntimeWarning, stacklevel=2)
        self.ch_names_ = [raw.ch_names[i] for i in indices]
        self.sfreq_ = sf
        self.calibration_mask_ = mask
        self._signature = dict(locs=np.array([raw.info['chs'][i]['loc'] for i in indices]),
            reference=raw.info['custom_ref_applied'], projs=deepcopy(raw.info['projs']),
            filters=(raw.info['highpass'],raw.info['lowpass']))
        config_record = asdict(self.config)
        config_record['reference_tolerances'] = [float(v) if np.isfinite(v) else '-inf'
                                                 for v in self.config.reference_tolerances]
        self.fit_report_ = dict(backend='mne_asr', implementation_version='0.1.0',
            config=config_record, channels=self.ch_names_, method='euclid',
            calibration_retained_samples=int(mask.sum()), calibration_retained_seconds=float(mask.sum()/sf),
            calibration_total_samples=int(raw.n_times), excluded_bad_samples=int(blocked.sum()),
            calibration_mask_sha256=hashlib.sha256(mask.tobytes()).hexdigest(),
            input_quantization_max_uv=quantization, quality_flags=flags,
            input_units='V', backend_units='uV', backend_input_dtype='float32 then float64 computation',
            numerical_identity_claimed=False)
        self._state = state
        return self

    def transform(self, raw):
        """Return a cleaned copy; the caller's data are never modified."""
        return self._transform(raw, owned=False)

    def _transform(self, raw, *, owned):
        """Shared numerical path; ``owned`` is only for private EEG work buffers."""
        _check_raw(raw)
        if self._state is None:
            raise RuntimeError('Call fit before transform')
        if float(raw.info['sfreq']) != self.sfreq_:
            raise ValueError('Sampling rate differs from calibration')
        indices = _picks(raw, self.ch_names_)
        if not np.array_equal([raw.info['chs'][i]['loc'] for i in indices],self._signature['locs'],equal_nan=True):
            raise ValueError('Electrode geometry differs from calibration')
        if (raw.info['custom_ref_applied'] != self._signature['reference'] or
                object_diff(raw.info['projs'],self._signature['projs'])):
            raise ValueError('Reference or projection state differs from calibration')
        if (raw.info['highpass'],raw.info['lowpass']) != self._signature['filters']:
            raise ValueError('Filter metadata differs from calibration')
        window = max(self.config.processing_window or .5, 1.5*len(indices)/self.sfreq_)
        step = self.config.step_size or int(np.floor(self.sfreq_*window/2))
        if step > round_mat(window*self.sfreq_):
            raise ValueError('step_size exceeds the processing window')
        padding = int(round_mat(window/2*self.sfreq_))
        spans, blocked = _spans(raw)
        if owned:
            if not raw.preload or not np.array_equal(indices,np.arange(len(raw.ch_names))):
                raise ValueError('Owned ASR transform needs a preloaded, usable EEG-only Raw')
            # No external object aliases this private pipeline buffer. Public
            # transform still creates its output only after every span succeeds.
            values = raw._data
        else:
            values = raw.get_data(picks=indices)
        records = []
        for start, stop in spans:
            if stop-start < self.config.min_segment_seconds*self.sfreq_:
                records.append(dict(samples=[int(start),int(stop)],status='skipped_short'))
                continue
            original, q = _backend_values(values[:,start:stop])
            if original.shape[1] <= padding:
                raise ValueError('Segment too short for reflection padding')
            extension = 2*original[:,[-1]]-original[:,-2:-padding-2:-1]
            extended = np.concatenate([original,extension],axis=1)
            processed, state = asr_process(extended,self.sfreq_,deepcopy(self._state),
                window_len=window,lookahead=window/2,step_size=step,
                max_dims=self.config.max_dimensions,max_mem=self.config.max_memory_mb)
            cleaned = processed[:,:original.shape[1]]
            amplification = float(np.sqrt(np.mean(cleaned**2))/max(np.sqrt(np.mean(original**2)),np.finfo(float).tiny))
            if not np.isfinite(cleaned).all() or amplification > self.config.amplification_limit:
                raise FloatingPointError('ASR numerical instability; no fallback/output delivered')
            values[:,start:stop] = cleaned*1e-6
            records.append(dict(samples=[int(start),int(stop)],status='processed',
                input_quantization_max_uv=q,output_rms_amplification=amplification,**state['diagnostics']))
            del original, extension, extended, processed, cleaned, state
        result = raw if owned else raw.copy().load_data()
        if not owned:
            result.apply_function(lambda _:values,picks=indices,channel_wise=False)
        self.transform_report_ = dict(backend='mne_asr', segments=records,
            blocked_samples_preserved=int(blocked.sum()), processing_window=window,
            step_size=step, terminal_padding='reflection', data_deleted=False,
            metadata_strategy='copy Raw; replace selected EEG only')
        return result

    def fit_transform(self, raw, picks=None):
        return self.fit(raw,picks=picks).transform(raw)


def clean_asr_raw(raw, cutoff=20., *, config=None):
    """Per-good-span fit/reconstruct, preserving MNE metadata and all BAD spans.

    Returns (Raw copy, JSON-compatible diagnostic). Does not filter, rereference,
    delete time, interpolate channels, or mark reconstructed samples BAD.
    """
    _check_raw(raw)
    cfg = config if config is not None else ASRConfig(cutoff=cutoff)
    cfg.validate()
    picks = _picks(raw,None)
    values = raw.get_data(picks=picks)
    spans, blocked = _spans(raw)
    records = [];flags = [];retained = 0;quantization = 0.
    for start, stop in spans:
        if stop-start < cfg.min_segment_seconds*raw.info['sfreq']:
            records.append(dict(samples=[int(start),int(stop)],status='skipped_short'))
            flags.append('ASR skipped a short uninterrupted good segment')
            continue
        part = raw.copy().crop(start/raw.info['sfreq'],(stop-1)/raw.info['sfreq'])
        estimator = ASR(config=cfg)
        clean = estimator.fit_transform(part)
        values[:,start:stop] = clean.get_data(picks=picks)
        retained += estimator.fit_report_['calibration_retained_samples']
        quantization = max(quantization,estimator.fit_report_['input_quantization_max_uv'])
        flags.extend(estimator.fit_report_['quality_flags'])
        records.append(dict(samples=[int(start),int(stop)],status='processed',
            calibration=estimator.fit_report_,processing=estimator.transform_report_))
        del part, clean, estimator
    result = raw.copy().load_data()
    result.apply_function(lambda _:values,picks=picks,channel_wise=False)
    report = dict(backend='mne_asr',implementation_version='0.1.0',cutoff=cfg.cutoff,
        segments=records,calibration_retained_samples=retained,input_quantization_max_uv=quantization,
        existing_bad_and_boundary_samples_excluded=int(blocked.sum()),quality_flags=sorted(set(flags)),
        data_deleted=False,metadata_strategy='copy Raw; replace selected EEG only',
        runtime_dependencies=['numpy','scipy','mne'],numerical_identity_claimed=False)
    return result,report


def _clean_asr_owned(raw, cutoff=20., *, config=None):
    """Clean a private preloaded EEG-only uninterrupted work buffer in place.

    The pipeline has already copied the caller's EEG and split it around all
    BAD/EDGE/boundary samples. This avoids copying that same span several more
    times through the public per-span wrapper. Quantization, reference selection,
    calibration, processing grids and state resets use the public numerical path.
    An unexpected boundary or auxiliary channel falls back to the public wrapper.
    This function is private: the caller must own the data and may not reuse it
    after an exception. Public ``clean_asr_raw`` and ``ASR.transform`` stay atomic
    with respect to their input.
    """
    _check_raw(raw)
    cfg = config if config is not None else ASRConfig(cutoff=cutoff)
    cfg.validate()
    indices = _picks(raw,None)
    spans,blocked = _spans(raw)
    eligible = (raw.preload and np.array_equal(indices,np.arange(len(raw.ch_names)))
                and spans == [(0,raw.n_times)]
                and raw.n_times >= cfg.min_segment_seconds*raw.info['sfreq'])
    if not eligible:
        return clean_asr_raw(raw,config=cfg)
    estimator = ASR(config=cfg).fit(raw)
    result = estimator._transform(raw,owned=True)
    report = dict(backend='mne_asr',implementation_version='0.1.0',cutoff=cfg.cutoff,
        segments=[dict(samples=[0,int(raw.n_times)],status='processed',
            calibration=estimator.fit_report_,processing=estimator.transform_report_)],
        calibration_retained_samples=estimator.fit_report_['calibration_retained_samples'],
        input_quantization_max_uv=estimator.fit_report_['input_quantization_max_uv'],
        existing_bad_and_boundary_samples_excluded=int(blocked.sum()),
        quality_flags=sorted(set(estimator.fit_report_['quality_flags'])),
        data_deleted=False,metadata_strategy='copy Raw; replace selected EEG only',
        runtime_dependencies=['numpy','scipy','mne'],numerical_identity_claimed=False)
    return result,report
