# Parameter reference

[简体中文](../zh-CN/parameters.md) · [Installation](installation.md) · [Usage](usage.md)

All 75 PipelineConfig fields are listed below. Defaults are generated from the current code for four purpose/preset combinations. Both presets follow the same pipeline.

## Configuration in Python

Priority: **preset defaults < optional JSON file < config object/mapping < explicit run keywords**. A PipelineConfig is immutable and fully resolved: all its fields become explicit when passed as a base. Construct a new config to obtain a new purpose's defaults rather than changing only purpose on an existing config.

```python
from dataclasses import asdict
from eegproc import PipelineConfig, run

config = PipelineConfig(purpose="erp", task_name="oddball", epoch_mode="events")
print(asdict(config))
print(config.adjustments)
# result = run(raw, "outputs/sub01", "sub01", config=config, line_frequency=60.)
# Optional JSON is lower priority than these explicit Python keywords:
# result = run(raw, "outputs/sub02", "sub02", config_file="config.json",
#              purpose="rest", task_name="eyes_closed")
```

```json
{"purpose": "erp", "task_name": "oddball", "epoch_mode": "events"}
```

## All pipeline fields

| Parameter | Type | Values / units | Meaning | standard/rest | standard/erp | eeglab/rest | eeglab/erp |
|---|---|---|---|---|---|---|---|
| `preset` | str | standard / eeglab | Default parameter set within the same pipeline. eeglab approximates the original script; it does not reproduce MATLAB numerically. | `'standard'` | `'standard'` | `'eeglab'` | `'eeglab'` |
| `filter_method` | str | mne_fir / eeglab_fir / off | Analysis/training FIR implementation; off skips explicit band filtering. | `'mne_fir'` | `'mne_fir'` | `'eeglab_fir'` | `'eeglab_fir'` |
| `filter_order` | int | even int ≥ 2; samples | Used by eeglab_fir only; MNE FIR chooses its own length. | `15000` | `15000` | `15000` | `15000` |
| `filter_position` | str | after_reference | Currently the only supported filter position. | `'after_reference'` | `'after_reference'` | `'after_reference'` | `'after_reference'` |
| `line_method` | str | spectrum_fit / notch / off | Line-noise method; spectrum_fit uses MNE multitaper sinusoidal fitting. | `'spectrum_fit'` | `'spectrum_fit'` | `'spectrum_fit'` | `'spectrum_fit'` |
| `line_window_seconds` | float | seconds > 0 | spectrum_fit window. Unsupported DPSS settings reset to 4 s / 2 Hz; unusably short spans are reported. | `4.0` | `4.0` | `4.0` | `4.0` |
| `line_bandwidth` | float | Hz > 0 | Multitaper bandwidth; inactive for notch/off. | `2.0` | `2.0` | `2.0` | `2.0` |
| `line_p_value` | float | 0 < p < 1 | spectrum_fit significance threshold; inactive for notch/off. | `0.05` | `0.05` | `0.05` | `0.05` |
| `channel_method` | str | pyprep / eegprep / off | Bad-channel detector; eegprep needs an optional extra. Input bad channels remain relevant when off. | `'pyprep'` | `'pyprep'` | `'eegprep'` | `'eegprep'` |
| `flatline_seconds` | float | seconds > 0 | Flatline duration for the EEGPrep-compatible detector. | `5.0` | `5.0` | `5.0` | `5.0` |
| `channel_correlation` | float | 0 < fraction < 1 | EEGPrep-compatible correlation threshold; does not replace PyPREP internal settings. | `0.8` | `0.8` | `0.8` | `0.8` |
| `channel_broken_fraction` | float | 0 < fraction < 1 | EEGPrep-compatible fraction of failed channel windows. | `0.4` | `0.4` | `0.4` | `0.4` |
| `reference` | str | average / unchanged | Reference method for initial and enabled final reference; unchanged skips both. | `'average'` | `'average'` | `'average'` | `'average'` |
| `interpolate_bads` | bool | bool | Global interpolation gate; False also disables pre-ASR interpolation. | `True` | `True` | `True` | `True` |
| `final_interpolation` | bool | bool | Final interpolation, also gated by interpolate_bads. | `True` | `True` | `True` | `True` |
| `final_reference` | bool | bool | Apply the chosen reference after artifact handling; reference=unchanged still skips rereferencing. | `True` | `True` | `True` | `True` |
| `exclude_gross_from_training` | bool | bool | Exclude gross artifacts from ICA training without deleting delivered continuous samples. | `True` | `True` | `True` | `True` |
| `residual_qc` | bool | bool | Generate continuous BAD_residual annotations and residual diagnostics. | `True` | `True` | `True` | `True` |
| `ica_enabled` | bool | bool | Enable ICA/ICLabel/application. False deactivates review/manual selection. | `True` | `True` | `True` | `True` |
| `ica_mode` | str | auto / review / manual | auto applies a proposal; review pauses before subtraction; manual applies a complete explicit list. | `'auto'` | `'auto'` | `'auto'` | `'auto'` |
| `ica_exclude` | tuple / None | tuple[int] / None; zero-based | Complete list; [] keeps all. Supplying a list in auto selects manual. Invalid/out-of-range indices are audited, never replaced with automatic choices. | `None` | `None` | `None` | `None` |
| `ica_rule` | str | threshold / class_max | Automatic selection rule defined below; does not change ICA fitting. | `'threshold'` | `'threshold'` | `'class_max'` | `'class_max'` |
| `rank_method` | str | relative / covariance | relative: singular values > max(machine-precision tolerance, largest singular value × 1e-6). covariance: min(matrix_rank, covariance eigenvalues > 1e-7 µV²). | `'relative'` | `'relative'` | `'covariance'` | `'covariance'` |
| `review_author` | str | str | Reviewer label for an initial manual decision. | `''` | `''` | `''` | `''` |
| `review_reason` | str | str | Reason for an initial manual decision. | `''` | `''` | `''` | `''` |
| `purpose` | str | rest / erp | Analysis defaults; does not itself enable epoch export. | `'rest'` | `'erp'` | `'rest'` | `'erp'` |
| `task_name` | str / None | str / None; 1–100 characters | Task metadata, independent of purpose, filenames and event selection. No surrounding whitespace/control characters. | `'rest'` | `None` | `'rest'` | `None` |
| `ica_backend` | str | mne | Supported ICA interface; solver is selected by ica_method. | `'mne'` | `'mne'` | `'mne'` | `'mne'` |
| `highpass` | float | Hz > 0; < lowpass | Analysis high-pass edge; limited by existing acquisition filtering. | `0.5` | `0.1` | `0.5` | `0.5` |
| `lowpass` | float | Hz > highpass; < Nyquist | Analysis low-pass edge; may be clipped to input limits. | `80.0` | `30.0` | `100.0` | `100.0` |
| `training_highpass` | float | Hz > 0; < training_lowpass | ICA training high-pass edge. Identical analysis/training bands reuse the filtered signal. | `1.0` | `1.0` | `0.5` | `0.5` |
| `training_lowpass` | float | Hz > training_highpass; < Nyquist | ICA training low-pass edge; nominal ICLabel training is 1–100 Hz. | `100.0` | `100.0` | `100.0` | `100.0` |
| `line_frequency` | float / None | Hz > 0 / None | Known mains frequency, normally 50 or 60; harmonics up to min(100, sfreq/2−1) Hz. None disables removal. Not an automatic estimator. | `50.0` | `50.0` | `50.0` | `50.0` |
| `artifact_threshold` | float | 0.5 ≤ probability ≤ 1 | threshold only: minimum maximum Muscle/Eye/Heart/Line/Channel probability. | `0.9` | `0.9` | `0.9` | `0.9` |
| `brain_probability_max` | float | 0 ≤ probability ≤ 0.5 | threshold only: largest Brain probability allowed for removal. | `0.2` | `0.2` | `0.2` | `0.2` |
| `asr_cutoff` | float / None | positive / None | Burst cutoff; None disables ASR. Default 20 for both rest and ERP. | `20.0` | `20.0` | `20.0` | `20.0` |
| `asr_backend` | str | mne_native | Independent MNE-compatible ASR; no runtime ASRpy dependency. | `'mne_native'` | `'mne_native'` | `'mne_native'` | `'mne_native'` |
| `asr_options` | dict / None | dict / None | Advanced overrides below; cutoff/min_segment_seconds use top-level settings. | `None` | `None` | `None` | `None` |
| `seed` | int | int; 0 ≤ seed < 2**32 | Random seed for ICA and applicable detection/repair stages. | `20261018` | `20261018` | `20261018` | `20261018` |
| `n_threads` | int | int ≥ 1 | Numerical thread limit, not recording-level batch scheduling. | `1` | `1` | `1` | `1` |
| `ica_max_iter` | int | int ≥ 1 | Iteration limit; limit/convergence diagnostics are reported. | `1000` | `1000` | `4096` | `4096` |
| `ica_tolerance` | float | positive | Picard tol or Infomax w_change; identical values need not mean identical stopping behavior. | `1e-07` | `1e-07` | `1e-07` | `1e-07` |
| `bad_channel_fraction_limit` | float | 0 < fraction < 1 | Global bad-channel quality threshold; policy determines reporting/stopping. | `0.3` | `0.3` | `0.3` | `0.3` |
| `bad_channel_policy` | str | auto / report / stop | report continues viable processing; stop rejects excess bad channels; auto resolves to report with the supported mne_native backend. At least 8 usable EEG channels remain required. | `'report'` | `'report'` | `'report'` | `'report'` |
| `min_training_seconds` | float | seconds > 0 | Minimum usable training and ASR segment duration; not proof of adequate calibration. | `20.0` | `20.0` | `20.0` | `20.0` |
| `gross_peak_uv` | float | µV > 0 | Absolute peak threshold for gross training artifacts. | `500.0` | `500.0` | `500.0` | `500.0` |
| `residual_peak_uv` | float | µV > 0 | Residual absolute peak threshold, also the default epoch screen. | `150.0` | `150.0` | `150.0` | `150.0` |
| `residual_ptp_uv` | float | µV > 0 | Residual peak-to-peak threshold, also the default epoch screen. | `200.0` | `200.0` | `200.0` | `200.0` |
| `residual_robust_z` | float | positive robust z | Relative log-SD threshold, gated by residual_relative_min_ptp_uv. | `6.0` | `6.0` | `6.0` | `6.0` |
| `residual_relative_min_ptp_uv` | float | µV > 0 | Minimum peak-to-peak for a relative-noise rejection. | `50.0` | `50.0` | `50.0` | `50.0` |
| `window_seconds` | float | seconds > 0 | Continuous gross/residual screening window. | `1.0` | `1.0` | `1.0` | `1.0` |
| `guard_seconds` | float | seconds ≥ 0 | Padding around detected continuous artifact windows. | `0.25` | `0.25` | `0.25` | `0.25` |
| `detect_ransac` | bool | bool | PyPREP RANSAC switch; needs suitable electrode geometry/channel count. | `True` | `True` | `True` | `True` |
| `interpolate_before_asr` | bool | bool | Interpolate before ASR only if interpolate_bads=True; changes the spatial ASR input. | `False` | `False` | `False` | `False` |
| `ica_method` | str | picard / infomax | Extended-Infomax objective with Picard or MNE Infomax solver. | `'picard'` | `'picard'` | `'infomax'` | `'infomax'` |
| `heart_min_ecg_correlation` | float | 0 ≤ absolute r ≤ 1 | threshold only: extra AND gate for Heart-only candidates with a usable real ECG. Without ECG, use ICLabel alone. | `0.3` | `0.3` | `0.3` | `0.3` |
| `epoch_mode` | str | none / events / fixed | Epoch export. Passing explicit events to run activates events if mode is none. | `'none'` | `'none'` | `'none'` | `'none'` |
| `epoch_qc` | str | auto / event-window / annotations | auto uses event-window for event epochs (either purpose) and annotations for fixed windows. Original BAD always preserved. | `'auto'` | `'auto'` | `'auto'` | `'auto'` |
| `repair_epochs` | bool | bool | Opt-in AutoReject repair, ERP events with event-window QC only; requires extra. Continuous samples unchanged. | `False` | `False` | `False` | `False` |
| `epoch_tmin` | float | seconds ≤ 0 | Event epoch start relative to onset. | `-0.2` | `-0.2` | `-0.2` | `-0.2` |
| `epoch_tmax` | float | seconds > 0 | Event epoch end; sample rounding follows MNE. | `1.0` | `1.0` | `1.0` | `1.0` |
| `epoch_baseline` | tuple / None | (start, end) / None; seconds | Within event window; None endpoints mean boundaries; whole None disables baseline. Fixed epochs have no baseline. | `(None, 0.0)` | `(None, 0.0)` | `(None, 0.0)` | `(None, 0.0)` |
| `fixed_epoch_duration` | float | seconds > 0 | Fixed window duration; last sample at duration − 1/sfreq. | `2.0` | `2.0` | `2.0` | `2.0` |
| `fixed_epoch_overlap` | float | seconds; 0 ≤ overlap < duration | Fixed-window overlap; starts must differ by at least one sample. | `0.0` | `0.0` | `0.0` | `0.0` |
| `event_source` | str | auto / annotations / stim | Without explicit events. For STIM-only recordings explicitly use stim or pass events. | `'auto'` | `'auto'` | `'auto'` | `'auto'` |
| `event_names` | tuple / None | tuple[str] / None | Select names from event_id; None retains mapping. Unknown names skip epochs with an audit. | `None` | `None` | `None` | `None` |
| `stim_channel` | str / None | str / None | Actual STIM channel name; ignored for explicit events or annotation extraction. | `None` | `None` | `None` | `None` |
| `report_full_record_heatmap` | bool | bool | Optional full-record heatmap; off keeps reports compact. | `False` | `False` | `False` | `False` |
| `report_waveform_windows` | int | int ≥ 1 | Number of representative before/after waveform windows. | `3` | `3` | `3` | `3` |
| `report_window_seconds` | float | seconds > 0 | Duration of each representative waveform window. | `4.0` | `4.0` | `4.0` | `4.0` |
| `report_max_channels` | int | int ≥ 2 | Maximum displayed channels in representative waveforms. | `6` | `6` | `6` | `6` |
| `report_dpi` | int | int ≥ 60; dpi | Raster resolution; larger values increase HTML size. | `100` | `100` | `100` | `100` |
| `report_max_width` | int | int ≥ 600; pixels | Maximum stored report figure width. | `1200` | `1200` | `1200` | `1200` |
| `report_psd_windows` | int | int ≥ 1 | Maximum representative windows for report PSD. | `30` | `30` | `30` | `30` |
| `report_psd_window_seconds` | float / None | seconds > 0 / None | None uses bounded automatic sampling. Report PSD is diagnostic, not a final analysis estimate. | `None` | `None` | `None` | `None` |

## Corrections, dependencies and failure boundaries

- Unknown fields are ignored; unsupported types, values and choices generally revert to the selected purpose/preset defaults. Every correction enters config.adjustments and the HTML parameter audit. An unreadable optional config file does not prevent using code parameters.
- Bands are constrained by acquisition filtering and Nyquist. Removed frequencies are not restored; no implicit resampling occurs. At sfreq ≤80 Hz the current ASR backend is disabled; below 100 Hz the current ICA/ICLabel stage is disabled, with an audit.
- Disabled ICA cancels review/manual selection. Review pauses without applying a final list. Malformed manual lists keep all components and require review; unavailable indices are omitted, including during resume. The complete effective exclusion list and changes are recorded. Checkpoint/input hashes and an imported selection JSON's model identity and reviewed=true remain strict requirements.
- Disabling interpolation disables pre-ASR interpolation; disabling both locations disables the global switch. Inapplicable local epoch repair is disabled with an audit.
- Missing/invalid events, unknown conditions, duplicate/out-of-range samples or impossible windows may skip epoch export while continuous processing completes. Inspect epoch_resolution and actual outputs. Continuous completion does not imply epoch export.
- report quality policy is not a promise that every input succeeds. Missing inputs, output collisions, missing dependencies, invalid sampling/filter metadata, missing required coordinates, unusable samples/rank, and damaged/mismatched checkpoints can still stop processing. No guessed data replace such failures.

## Exact ICA rules

threshold: at least one of Muscle, Eye, Heart, Line noise and Channel noise reaches artifact_threshold AND Brain ≤ brain_probability_max. Other is not removed automatically. With a usable real ECG, Heart-only candidates also require maximum absolute Pearson correlation with an ECG channel ≥ heart_min_ecg_correlation. This is an additional AND gate, not independent ECG-only deletion. Without ECG, ICLabel alone is used; no ECG surrogate is constructed.

class_max: remove if Eye equals the maximum class probability; OR Brain ≤0.5 and any of Muscle, Line noise or Channel noise equals that maximum. Ties count. Heart/Other are not independently selected. artifact_threshold, brain_probability_max and ECG support are inactive.

## Epochs and BAD annotations

purpose, task_name and epoch_mode are independent. Both rest and ERP default to continuous output. Explicit events passed to run activate event export when epoch_mode is none. auto QC uses trial-local screening for event epochs under either purpose, and continuous annotations for fixed epochs. Only local repair, not trial-local rejection, requires purpose=erp.

Event-window QC temporarily ignores only newly generated BAD_residual while checking actual event windows for peaks, peak-to-peak and relative noise. Original manual BAD, including pre-existing BAD_residual, still excludes overlapping trials. Continuous samples and annotations remain intact. Ordinary mne.Epochs(clean_raw, reject_by_annotation=True, ...) uses continuous BAD and may not match trial-local exports.

## Advanced ASR options

Pass asr_options as a dictionary. Below are standalone ASRConfig defaults; the pipeline supplies cutoff and min_segment_seconds from asr_cutoff and min_training_seconds. Those two nested keys are ignored with an audit. Invalid nested keys/values use backend defaults. max_memory_mb also affects update boundaries, so it is not a purely cosmetic performance option.

| Parameter | Type | Values / units | Meaning | Class default |
|---|---|---|---|---|
| `cutoff` | float | positive; use asr_cutoff | Burst cutoff, controlled at pipeline level. | `20.0` |
| `reference_window` | float | seconds > 0 | Reference-selection window. | `1.0` |
| `reference_max_bad_channels` | float | 0 ≤ fraction < 1 | Maximum bad-channel fraction in reference windows. | `0.075` |
| `reference_tolerances` | tuple[float, float] | (lo, hi); lo < 0 < hi; lo can be -inf | Robust reference acceptance interval; supply -inf through Python rather than nonstandard JSON. | `(-inf, 5.5)` |
| `calibration_window` | float | seconds > 0 | Calibration window. | `0.5` |
| `overlap` | float | 0 ≤ fraction < 1 | Reference/calibration window overlap. | `0.66` |
| `processing_window` | float / None | seconds > 0 / None | Effective window=max(requested or 0.5, 1.5 × usable EEG channels / sfreq). | `None` |
| `step_size` | int / None | int ≥ 1 / None; samples | None uses floor(sfreq × effective processing window / 2); explicit step may not exceed the window samples. | `None` |
| `max_dimensions` | float | 0 < fraction < 1 | Maximum reconstructed subspace fraction. | `0.66` |
| `max_memory_mb` | float | MB > 0 | ASR block budget also affects update boundaries and numerical results. | `64.0` |
| `min_segment_seconds` | float | seconds > 0; use min_training_seconds | Minimum eligible segment, controlled at pipeline level. | `20.0` |
| `amplification_limit` | float | positive ratio | Maximum output/input RMS ratio; a violation stops ASR with a numerical-instability error. | `100.0` |

## Advanced epoch parameters

Pass a mapping or EpochConfig through run's epoch_config. A complete object overrides all stage defaults; a mapping overrides supplied fields only. Continuous QC is unchanged. Fixed windows force tmin=0, tmax=duration−1/sfreq, baseline=None. Repair budget/CV require repair_epochs=True; repair is off by default. The table shows standalone class defaults; inherited pipeline values are described separately.

| Parameter | Type | Values / units | Meaning | Class default |
|---|---|---|---|---|
| `tmin` | float | seconds ≤ 0 | Inherited from resolved epoch_tmin unless explicitly supplied. | `-0.2` |
| `tmax` | float | seconds > 0 | Inherited from resolved epoch_tmax. | `1.0` |
| `baseline` | tuple | tuple / None; seconds | Inherited from epoch_baseline. | `(None, 0.0)` |
| `peak_uv` | float | µV > 0 | Inherited from residual_peak_uv. | `150.0` |
| `ptp_uv` | float | µV > 0 | Inherited from residual_ptp_uv. | `200.0` |
| `robust_z` | float | positive | Inherited from residual_robust_z. | `6.0` |
| `relative_min_ptp_uv` | float | µV > 0 | Inherited from residual_relative_min_ptp_uv. | `50.0` |
| `max_interpolate` | int | int ≥ 1; channels | Local repair cap, also limited by floor(n_EEG × max_local_fraction). | `4` |
| `max_local_fraction` | float | 0 < fraction ≤ 0.25 | Maximum local interpolation fraction. | `0.125` |
| `min_fit_epochs` | int | int ≥ cv | Minimum eligible epochs to fit AutoReject. | `10` |
| `cv` | int | int ≥ 2 | AutoReject cross-validation folds. | `5` |
| `seed` | int | int; 0 ≤ seed < 2**32 | Inherited from pipeline seed. | `20261018` |

```text
run(raw: 'mne.io.BaseRaw', save_path: 'str | PathLike[str]', subject: 'str', *, config: 'ConfigInput' = None, config_file: 'str | PathLike[str] | None' = None, montage: 'Any' = None, collect_stages: 'bool' = False, events: 'np.ndarray | Sequence[Sequence[int]] | None' = None, event_id: 'Mapping[str, int] | None' = None, epoch_config: 'EpochConfig | None' = None, invocation: 'Mapping[str, Any] | None' = None, **parameters: 'Any') -> 'PipelineResult'
```

```text
resume(checkpoint: 'str | PathLike[str]', save_path: 'str | PathLike[str]', subject: 'str | None' = None, *, selection_json: 'str | PathLike[str] | None' = None, exclude: 'Sequence[int] | None' = None, reviewer: 'str' = '', reason: 'str' = '', collect_stages: 'bool' = False, original_raw: 'mne.io.BaseRaw | None' = None, original_fif: 'str | PathLike[str] | None' = None) -> 'PipelineResult'
```

```text
render_report(source: 'PipelineResult | str | PathLike[str]', report_path: 'str | PathLike[str]') -> 'Path'
```

```text
resolve_config(path=None, **overrides) -> eegproc.settings.PipelineConfig
```

```text
prepare_data(source, *, output_fif=None, channel_types=None, rename=None, drop=(), montage=None, event_id=None, allow_legacy_uv_per_mm=False, return_result=False)
```


## Runtime API inputs

| Interface | Inputs and returned objects |
|---|---|
| run | raw: continuous MNE BaseRaw; EEG/EOG/ECG in volts; input unchanged. save_path: output directory; subject: safe filename prefix. config/config_file: sources above. montage: explicit geometry override on the working copy; omit it to preserve existing digitization. collect_stages=False avoids extra stage copies. events: integer n×3, first column absolute MNE samples including first_samp. event_id: condition name → integer. epoch_config: stage overrides. invocation: provenance mapping. Additional keywords: all PipelineConfig fields. |
| PipelineResult | raw: cleaned Raw, or None while awaiting ICA review; report: diagnostics dictionary; stages: requested in-memory snapshots; status: run status; outputs: actual product paths. review_required means assess flagged quality before downstream analysis. |
| resume | checkpoint: checkpoint.json; save_path: new output family; subject: optional prefix. Either selection_json or exclude: a complete zero-based list, [] keeps all. reviewer/reason record the decision. original_raw or original_fif supplies matching original data; required explicitly for an in-memory origin or moved source. collect_stages defaults False. Reuses ICA/ICLabel; no change of scientific parameters. |
| render_report | source: PipelineResult or saved HTML; report_path: fresh HTML path. Rebuilds layout using embedded diagnostics, without reprocessing EEG. |
| resolve_config | path: optional JSON path, mapping or PipelineConfig; keyword overrides have highest priority. Returns an immutable PipelineConfig; no configuration file is discovered implicitly. |
| prepare_data | source: supported file or Neuracle directory; output_fif=None returns data only, a path also writes FIF/.events.json/.preparation.json. channel_types and rename are mappings; drop is a channel-name sequence; montage is actual electrode geometry; event_id maps annotation descriptions to integer codes. allow_legacy_uv_per_mm=False applies only to confirmed legacy Neuracle calibration. return_result=False returns Raw; True returns PreparationResult(raw, events, event_id, provenance, outputs). No filtering, referencing or cleaning is performed. |

## Complete CLI flags

Generated from the actual parser. Command: eegproc. Every config field is accessible through repeated --set KEY=JSON, including fields without dedicated flags. JSON uses true/false/null. During --resume, only exclusion/reviewer/reason, original FIF and output arguments are accepted; science settings are frozen. Required input and CLI syntax errors can still stop execution.

| Flags | Destination | Required |
|---|---|---|
| `-h` / `--help` | `help` | False |
| `--input-fif` | `input_fif` | False |
| `--resume` | `resume` | False |
| `--save-path` | `save_path` | True |
| `--subject` | `subject` | True |
| `--preset` | `preset` | False |
| `--ica-mode` | `ica_mode` | False |
| `--ica-exclude` | `ica_exclude` | False |
| `--selection-json` | `selection_json` | False |
| `--review-author` | `review_author` | False |
| `--review-reason` | `review_reason` | False |
| `--original-fif` | `original_fif` | False |
| `--ica-enabled` / `--no-ica-enabled` | `ica_enabled` | False |
| `--interpolate-bads` / `--no-interpolate-bads` | `interpolate_bads` | False |
| `--interpolate-before-asr` / `--no-interpolate-before-asr` | `interpolate_before_asr` | False |
| `--exclude-gross-from-training` / `--no-exclude-gross-from-training` | `exclude_gross_from_training` | False |
| `--residual-qc` / `--no-residual-qc` | `residual_qc` | False |
| `--filter-method` | `filter_method` | False |
| `--filter-position` | `filter_position` | False |
| `--line-method` | `line_method` | False |
| `--channel-method` | `channel_method` | False |
| `--reference` | `reference` | False |
| `--rank-method` | `rank_method` | False |
| `--ica-rule` | `ica_rule` | False |
| `--set` | `settings` | False |
| `--config` | `config` | False |
| `--purpose` | `purpose` | False |
| `--task-name` | `task_name` | False |
| `--highpass` | `highpass` | False |
| `--lowpass` | `lowpass` | False |
| `--artifact-threshold` | `artifact_threshold` | False |
| `--brain-probability-max` | `brain_probability_max` | False |
| `--heart-min-ecg-correlation` | `heart_min_ecg_correlation` | False |
| `--line-frequency` | `line_frequency` | False |
| `--asr-cutoff` | `asr_cutoff` | False |
| `--bad-channel-policy` | `bad_channel_policy` | False |
| `--ica-method` | `ica_method` | False |
| `--seed` | `seed` | False |
| `--n-threads` | `n_threads` | False |
| `--detect-ransac` / `--no-detect-ransac` | `detect_ransac` | False |
| `--epochs` | `epoch_mode` | False |
| `--epoch-mode` | `epoch_mode` | False |
| `--fixed-epochs` | `fixed_epoch_duration` | False |
| `--epoch-qc` | `epoch_qc` | False |
| `--repair-epochs` / `--no-repair-epochs` | `repair_epochs` | False |
| `--event-names` | `event_names` | False |
| `--event-source` | `event_source` | False |
| `--stim-channel` | `stim_channel` | False |
| `--events-json` | `events_json` | False |
| `--tmin` | `epoch_tmin` | False |
| `--tmax` | `epoch_tmax` | False |
| `--baseline` | `baseline` | False |
| `--fixed-overlap` | `fixed_epoch_overlap` | False |
| `--report-full-record-heatmap` / `--no-report-full-record-heatmap` | `report_full_record_heatmap` | False |
| `--report-waveform-windows` | `report_waveform_windows` | False |
| `--report-max-channels` | `report_max_channels` | False |
| `--report-dpi` | `report_dpi` | False |
| `--report-max-width` | `report_max_width` | False |
| `--report-psd-windows` | `report_psd_windows` | False |
| `--report-window-seconds` | `report_window_seconds` | False |
| `--report-psd-window-seconds` | `report_psd_window_seconds` | False |

```bash
eegproc --input-fif prepared/sub01_raw.fif --save-path outputs/sub01 --subject sub01 --purpose erp --task-name oddball --epochs --set report_window_seconds=4.0
eegproc --input-fif prepared/sub02_raw.fif --save-path outputs/sub02 --subject sub02 --purpose rest --asr-cutoff off --set ica_enabled=false
eegproc --resume outputs/review/sub01_ica_review/checkpoint.json --save-path outputs/revised --subject sub01 --ica-exclude 1 4 --original-fif prepared/sub01_raw.fif
```

### Preparation command

`eegproc-prepare`

| Flag | Meaning / 说明 |
|---|---|
| `--input` | Required: recording file or Neuracle folder |
| `--output-fif` | Required: new prepared FIF path |
| `--montage` | Actual supported montage name; no guessed cap geometry |
| `--eog` | Zero or more names to type as EOG |
| `--ecg` | Zero or more names to type as ECG |
| `--stim` | Zero or more names to type as STIM |
| `--drop` | Zero or more channels to omit from prepared input |
| `--rename-json` | JSON path with old-name to new-name mapping |
| `--event-id-json` | JSON path with annotation-name to code mapping |
| `--neuracle-uv-per-mm` | Opt-in confirmed legacy calibration only |
| `--help` | Show usage and exit |

Regenerate with python scripts/generate_parameter_reference.py; --check detects stale fields, defaults, API signatures and CLI definitions.
