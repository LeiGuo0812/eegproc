"""EEG preprocessing parameters; presets share the same processing stages."""
from dataclasses import dataclass, fields
import numpy as np

class FrozenOptions(dict):
    """JSON-compatible, immutable copy of algorithm-specific options."""

    def _readonly(self, *args, **kwargs):
        raise TypeError("Configuration options are immutable; create a new configuration")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = __ior__ = _readonly

    def __deepcopy__(self, memo):
        return self


def _freeze_options(value):
    if isinstance(value, dict):
        return FrozenOptions((key, _freeze_options(item)) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_options(item) for item in value)
    return value


@dataclass(frozen=True, init=False)
class PipelineConfig:
    """Resolved, immutable parameters, constructed directly from Python.

    Omitted fields receive the selected purpose/preset defaults. Valid supplied
    fields win, including ``None``, ``False`` and empty sequences. Invalid values
    and incompatible dependencies are resolved with an immutable audit. ``replace``
    retains all existing values; use ``PipelineConfig(purpose=...)`` for a fresh
    set of purpose defaults.
    """
    preset: str = "standard"
    filter_method: str = "mne_fir"
    filter_order: int = 15000
    filter_position: str = "after_reference"
    line_method: str = "spectrum_fit"
    line_window_seconds: float = 4.
    line_bandwidth: float = 2.
    line_p_value: float = .05
    channel_method: str = "pyprep"
    flatline_seconds: float = 5.
    channel_correlation: float = .8
    channel_broken_fraction: float = .4
    reference: str = "average"
    interpolate_bads: bool = True
    final_interpolation: bool = True
    final_reference: bool = True
    exclude_gross_from_training: bool = True
    residual_qc: bool = True
    ica_enabled: bool = True
    ica_mode: str = "auto"
    ica_exclude: tuple | None = None
    ica_rule: str = "threshold"
    rank_method: str = "relative"
    review_author: str = ""
    review_reason: str = ""
    purpose: str = "rest"
    task_name: str | None = None
    ica_backend: str = "mne"
    highpass: float = 0.5
    lowpass: float = 80.0
    training_highpass: float = 1.0
    training_lowpass: float = 100.0
    line_frequency: float | None = 50.0
    artifact_threshold: float = 0.9
    brain_probability_max: float = 0.2
    asr_cutoff: float | None = 20.0
    asr_backend: str = "mne_native"
    asr_options: dict | None = None
    seed: int = 20261018
    n_threads: int = 1
    ica_max_iter: int = 1000
    ica_tolerance: float = 1e-7
    bad_channel_fraction_limit: float = 0.3
    # Finish viable processing and report quality concerns for human review.
    bad_channel_policy: str = "report"
    min_training_seconds: float = 20.0
    gross_peak_uv: float = 500.0
    residual_peak_uv: float = 150.0
    residual_ptp_uv: float = 200.0
    residual_robust_z: float = 6.0
    residual_relative_min_ptp_uv: float = 50.0
    window_seconds: float = 1.0
    guard_seconds: float = 0.25
    detect_ransac: bool = True
    interpolate_before_asr: bool = False
    ica_method: str = "picard"
    heart_min_ecg_correlation: float = .3
    # Analysis purpose, epoch export, and report/storage are independent.
    epoch_mode: str = "none"
    epoch_qc: str = "auto"
    repair_epochs: bool = False
    epoch_tmin: float = -.2
    epoch_tmax: float = 1.
    epoch_baseline: tuple | None = (None, 0.)
    fixed_epoch_duration: float = 2.
    fixed_epoch_overlap: float = 0.
    event_source: str = "auto"
    event_names: tuple | None = None
    stim_channel: str | None = None
    report_full_record_heatmap: bool = False
    report_waveform_windows: int = 3
    report_window_seconds: float = 4.
    report_max_channels: int = 6
    report_dpi: int = 100
    report_max_width: int = 1200
    report_psd_windows: int = 30
    report_psd_window_seconds: float | None = None

    def __init__(self, *args, **overrides):
        definitions = fields(type(self))
        if len(args) > len(definitions):
            raise TypeError(f"PipelineConfig takes at most {len(definitions)} positional arguments")
        for definition, value in zip(definitions, args):
            if definition.name in overrides:
                raise TypeError(f"Multiple values for {definition.name}")
            overrides[definition.name] = value
        from .parameter_resolution import normalize_parameters,append_adjustments
        values,adjustments=normalize_parameters(overrides,definitions,_preset_defaults)
        values['asr_options'] = _freeze_options(values['asr_options'])
        for key, value in values.items():
            object.__setattr__(self, key, value)
        from .configuration import validate_options
        validate_options(self)
        append_adjustments(self,adjustments)

    @property
    def adjustments(self):
        """Immutable normalization audit; excluded from scientific dataclass fields."""
        return getattr(self,'_adjustments',())


def _preset_defaults(purpose, preset):
    if purpose not in ('rest', 'erp'):
        raise ValueError('purpose must be rest or erp')
    values = dict(task_name='rest' if purpose == 'rest' else None)
    if purpose == 'erp':
        values.update(highpass=.1, lowpass=30.)
    if preset == 'eeglab':
        values.update(highpass=.5, lowpass=100., training_highpass=.5, training_lowpass=100.,
            filter_method='eeglab_fir', channel_method='eegprep', asr_cutoff=20.,
            ica_method='infomax', ica_max_iter=4096, rank_method='covariance', ica_rule='class_max')
    elif preset != 'standard':
        raise ValueError('preset must be standard or eeglab')
    return values


def config_for(purpose="rest", backend="mne", preset="standard", **overrides):
    """Backward-compatible alias for the single configuration constructor."""
    return PipelineConfig(**{**dict(purpose=purpose, ica_backend=backend, preset=preset), **overrides})


def validate_config(config, sfreq):
    from .configuration import validate_options
    validate_options(config)
    if config.bad_channel_policy not in ('auto', 'report', 'stop'):
        raise ValueError('bad_channel_policy must be auto, report or stop')
    if config.asr_backend != "mne_native":
        raise ValueError("asr_backend must be 'mne_native'")
    if config.purpose not in ("rest", "erp") or config.ica_backend != "mne":
        raise ValueError("purpose must be rest/erp and ica_backend must be 'mne'")
    if not (0 < config.highpass < config.lowpass < sfreq / 2 and
            0 < config.training_highpass < config.training_lowpass < sfreq / 2):
        raise ValueError("Invalid analysis/training bands; ICLabel requires sufficient sampling rate for 100 Hz")
    if not (0.5 <= config.artifact_threshold <= 1 and 0 <= config.brain_probability_max <= 0.5):
        raise ValueError("Invalid IC probabilities")
    if config.asr_cutoff is not None and (not np.isfinite(config.asr_cutoff) or config.asr_cutoff <= 0):
        raise ValueError("ASR cutoff must be positive or None")
    for key in ("min_training_seconds", "gross_peak_uv", "residual_peak_uv",
                "residual_ptp_uv", "window_seconds", "ica_tolerance"):
        if not np.isfinite(getattr(config, key)) or getattr(config, key) <= 0:
            raise ValueError(f"{key} must be positive and finite")
    if not 0 < config.bad_channel_fraction_limit < 1 or config.guard_seconds < 0:
        raise ValueError("Invalid QC settings")
    if not isinstance(config.seed, int) or not 0 <= config.seed < 2**32:
        raise ValueError("seed must be an unsigned 32 bit integer")
    if min(config.n_threads, config.ica_max_iter) < 1:
        raise ValueError("Thread and iteration counts must be positive")
    if config.ica_method not in ('picard','infomax'):
        raise ValueError('Invalid ICA method')
    if not np.isfinite(config.heart_min_ecg_correlation) or not 0<=config.heart_min_ecg_correlation<=1:
        raise ValueError('Invalid ECG support threshold')
    if config.line_frequency is not None and (not np.isfinite(config.line_frequency) or config.line_frequency <= 0):
        raise ValueError('line_frequency must be positive or None')


