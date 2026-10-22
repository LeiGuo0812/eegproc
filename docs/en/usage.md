# Complete usage

[Home](../../README.md) · [中文](../zh-CN/usage.md) · [Parameters](parameters.md) · [Results](results.md)

[Workflow diagrams](workflow.md) show the processing order, analysis/ICA branches, manual review, and delivered files.

Examples use paths relative to the directory where Python is started. Replace recording paths, channel names and condition codes with those from your study. Each run needs a fresh output directory or subject label.

## Executable examples

After installation, run these scripts from a repository checkout:

```bash
python examples/synthetic_demo.py --output outputs/demo
python examples/analyze_outputs.py --raw outputs/demo/rest/synthetic_cont_raw.fif --output analysis/demo_rest
python examples/analyze_outputs.py --epochs outputs/demo/erp/synthetic_clean-epo.fif --output analysis/demo_erp
```

The first command creates a 60-second, 32-EEG-channel simulation with EOG/ECG/STIM, events and a manual BAD label. It exercises rest, ERP, review and continuation without dataset downloads. Its continuation reuses the automatic proposal to demonstrate the API; it is not a completed human review. The analysis commands generate exploratory PSD, ERP and time-frequency files in separate directories; these are example analysis products, not extra preprocessing attachments.

For real recordings, [code_first.py](../../examples/code_first.py) provides `rest`, `erp`, `review`, `manual`, `resume`, `config`, `prepare` and `render` subcommands. [batch_process.py](../../examples/batch_process.py) accepts a CSV manifest:

```csv
subject,input_fif,purpose,task_name,events_json
sub01,prepared/sub01_rest_raw.fif,rest,eyes_closed,
sub01,prepared/sub01_task_raw.fif,erp,oddball,prepared/sub01_task_raw.events.json
```

```bash
python examples/batch_process.py manifest.csv --output outputs/cohort
```

Manifest paths are relative to the manifest, and each row receives its own output directory. Inspect `batch_summary.json`: individual failures are recorded while remaining rows continue. The [synthetic demo](../../examples/synthetic_demo.py) and [downstream analysis script](../../examples/analyze_outputs.py) can also be imported/read as complete API examples.

## Input contract and data preparation

`run()` accepts a continuous `mne.io.BaseRaw`, including file-backed Raw objects with `preload=False`. It does not modify the supplied object. EEG, EOG and ECG samples must be in **volts**, electrode coordinates in **metres**, and channel types, sampling frequency, `first_samp`, measurement date, annotations and montage must represent the actual acquisition. Auxiliary channels are carried through without EEG cleaning. Prefer the vendor/MNE reader's calibration over rescaling according to apparent amplitude.

If data are already prepared:

```python
import mne
raw = mne.io.read_raw_fif("prepared/sub01_raw.fif", preload=False)
print(raw.info["sfreq"], raw.get_channel_types(), raw.first_samp)
print(raw.annotations)
```

Device conversion is separate from signal processing:

```python
from eegproc.preparation import prepare_data

prepared = prepare_data(
    "device_data/sub01.vhdr",  # Also FIF, EDF, BDF, SET or a Neuracle folder
    output_fif="prepared/sub01_raw.fif",  # Omit to return in memory only
    channel_types={"VEOG": "eog", "ECG": "ecg"},
    montage="standard_1020",  # Use only if it matches the actual cap/channel names
    return_result=True,
)
raw = prepared.raw
print(prepared.event_id)
```

Only specify channel names present in your recording. Existing digitized positions can be retained by omitting `montage`; a template must not replace measured coordinates without a deliberate decision. The preparation function can also rename/drop channels. It applies no filter, rereference or artifact correction. With `output_fif`, it writes the prepared FIF, a `.preparation.json` provenance record and an `.events.json` event input. Without `return_result=True`, the return value is Raw rather than `PreparationResult`.

A Neuracle folder must contain the supported `data.bdf` and `evt.bdf` pair. Install the `device` extra for this adapter. The optional legacy calibration switch is for recordings with the documented vendor calibration convention, not a general amplitude adjustment.

For an array whose values are genuinely stored in µV:

```python
import numpy as np
import mne

data_uv = np.load("eeg_microvolts.npy")  # shape: channels × samples
channel_names = ["Fp1", "Fp2", "F3", "F4", "C3", "C4", "P3", "P4", "O1", "O2"]
info = mne.create_info(channel_names, sfreq=500.0, ch_types="eeg")
raw = mne.io.RawArray(data_uv * 1e-6, info)
raw.set_montage("standard_1020")
raw.save("prepared/sub01_array_raw.fif", fmt="double", overwrite=False)
```

This conversion is appropriate only when the array's units and channel order are known. A small channel array demonstrates input construction; the available channel count also constrains RANSAC, interpolation, ICA and event QC. Read runtime adjustments and quality observations.

## Resting-state recording

```python
import mne
from eegproc import run

raw = mne.io.read_raw_fif("prepared/sub01_raw.fif", preload=False)
result = run(
    raw,
    save_path="outputs/sub01_rest",
    subject="sub01",
    purpose="rest",
    task_name="eyes_closed",
    line_frequency=50.0,
)
print(result.status)
print(result.outputs)
clean = result.raw
```

The standard rest settings use an analysis band of 0.5–80 Hz, ICA training at 1–100 Hz, ASR cutoff 20, Picard, and threshold-based IC selection. Line frequency is explicitly supplied or defaults to 50 Hz; it is not automatically detected. Use 60 Hz for a known 60 Hz environment.

`purpose="rest"` alone exports continuous data. To also create non-overlapping 2-second segments:

```python
result = run(
    raw, "outputs/sub01_rest_epochs", "sub01",
    purpose="rest", task_name="eyes_closed",
    epoch_mode="fixed", fixed_epoch_duration=2.0,
    fixed_epoch_overlap=0.0,
)
```

With `epoch_qc="auto"`, fixed epochs reject overlap with continuous BAD annotations; no baseline correction is used. Adjacent fixed windows are sample-contiguous, with the end at duration minus one sample.

## ERP with explicit events

This example uses annotation descriptions `"1"` and `"2"` for two conditions. Trial-end codes such as `"11"`–`"80"` are excluded by the explicit mapping. Change the description mapping if your recorder uses labels such as `"Stimulus/S  1"`.

```python
import mne
from eegproc import run

raw = mne.io.read_raw_fif("prepared/sub01_task_raw.fif", preload=False)
events, _ = mne.events_from_annotations(
    raw, event_id={"1": 1, "2": 2},
)
event_id = {"standard": 1, "target": 2}

result = run(
    raw,
    save_path="outputs/sub01_oddball",
    subject="sub01",
    purpose="erp",
    task_name="oddball",
    events=events,
    event_id=event_id,
    epoch_mode="events",
    epoch_qc="event-window",
    epoch_tmin=-0.2,
    epoch_tmax=1.0,
    epoch_baseline=(-0.2, 0.0),
)

if "epochs" in result.outputs:
    epochs = mne.read_epochs(result.outputs["epochs"], preload=True)
    print({name: len(epochs[name]) for name in epochs.event_id})
else:
    print(result.report.get("epoch_resolution"), result.report.get("epochs"))
```

The standard ERP band is 0.1–30 Hz; ASR remains enabled at 20 and ICA is trained at 1–100 Hz. `purpose="erp"` does not by itself request epochs. Supplying `events` automatically requests event epochs when `epoch_mode` was `"none"`.

Events are an integer array of shape `(n_events, 3)`, with increasing, unique **absolute MNE sample indices including `raw.first_samp`** in column 0 and integer condition codes in column 2. `event_id` maps condition names to codes, not descriptions to timestamps. Missing/invalid optional events are reported and epoch export is skipped while viable continuous processing continues. Inspect the report instead of assuming a file must exist.

For a STIM channel, extract explicitly:

```python
events = mne.find_events(raw, stim_channel="STI 014", shortest_event=1)
events = mne.pick_events(events, include=[1, 2])
result = run(
    raw, "outputs/sub01_stim", "sub01",
    purpose="erp", task_name="oddball",
    events=events, event_id={"standard": 1, "target": 2},
)
```

Alternatively use `epoch_mode="events", event_source="stim", stim_channel="STI 014"`. In this release, `event_source="auto"` first tries annotations; a recording with only BAD annotations may produce an extraction error before STIM fallback. Explicit events or `event_source="stim"` avoids that ambiguity. For annotation-based epoching, use `event_source="annotations"` and `event_names` when selecting known names.

### Event-window QC versus continuous BAD rejection

Event-window QC keeps all original manual BAD annotations. Only `BAD_residual` annotations newly added by this run are set aside for the epoch decision; the exact event window is screened instead. Existing input annotations named `BAD_residual` remain protected. The continuous output retains its full BAD annotations and all samples.

Use `epoch_qc="annotations"` to apply ordinary continuous BAD rejection. `epoch_qc="auto"` means event-window QC for event epochs and annotation rejection for fixed epochs. `repair_epochs=False` is the default: failing trials are rejected without local interpolation. Optional `repair_epochs=True` requires the AutoReject extra and ERP event-window QC; bounded local repair changes exported epochs only. See the [parameter reference](parameters.md) for repair limits.

## Configuration in code

```python
from eegproc import PipelineConfig, resolve_config, run

config = PipelineConfig(
    purpose="erp", task_name="oddball",
    epoch_mode="events", artifact_threshold=0.90,
)
result = run(raw, "outputs/sub01_config", "sub01", config=config,
             events=events, event_id={"standard": 1, "target": 2})

# A mapping is equally valid; explicit keywords have highest priority.
parameters = {"purpose": "rest", "task_name": "eyes_open", "line_frequency": 50.0}
resolved = resolve_config(parameters, highpass=1.0, lowpass=100.0)
print(resolved.adjustments)
```

When analysis and ICA training are both 1–100 Hz, the workflow shares the full-record band buffer. Temporary algorithm buffers and the compact training data may still be needed. Changing only the analysis band does not change the requested ICA training band.

An optional JSON file can supply a reusable base:

```python
result = run(
    raw, "outputs/sub01_json", "sub01",
    config_file="configs/rest.json",
    config={"task_name": "eyes_closed"},
    report_window_seconds=4.0,
)
```

Priority is **preset defaults < explicit JSON file < configuration/mapping < keyword parameters**. Files are never discovered automatically. `None`, `False` and empty lists are explicit choices. Parameters are immutable; construct a new `PipelineConfig(purpose="erp")` when switching to ERP defaults. `dataclasses.replace()` retains other already-resolved values.

Invalid values, unknown keys and dependency conflicts use audited fallback rules. Inspect `result.report["parameter_adjustments"]` and **Summary → Parameter adjustments** for the actual values. A fallback is not a reason to ignore a misspelled study setting. Invalid acquisition data, missing required dependencies, output collisions and numerical failures remain genuine errors.

## IC selection rules

| Rule | Automatic exclusion |
|---|---|
| `threshold` (default) | At least one of Muscle/Eye/Heart/Line noise/Channel noise reaches `artifact_threshold=0.90`, and Brain is at most `brain_probability_max=0.20`. Other is not targeted. |
| `class_max` | Eye equals the largest class probability; **or** Muscle/Line noise/Channel noise equals the maximum and Brain ≤0.50. Ties count. Heart and Other are not targeted by the original-script rule. |

Under `threshold`, a Heart-only candidate with usable ECG also needs maximum absolute IC–ECG Pearson correlation ≥0.30 over valid training samples. Without usable ECG, ICLabel alone decides. The correlation is an additional requirement for those Heart candidates, not an independent mechanism that adds new candidates. There is no automatically constructed ECG proxy. ICs that independently pass another artifact category are not rescued by low ECG correlation.

`class_max` uses the original script's category logic and does not use ECG assistance. Changing `artifact_threshold` under this rule does not change its category-maximum test. Review maps, spectra and activations rather than interpreting a class probability as proof of signal purity.

## ICA review and continuation

### Pause before subtracting ICs

```python
import mne
from eegproc import run, resume

raw = mne.io.read_raw_fif("prepared/sub01_raw.fif", preload=False)
pending = run(
    raw, "outputs/sub01_review", "sub01",
    purpose="rest", task_name="eyes_closed", ica_mode="review",
)
assert pending.status == "awaiting_ica_review"
assert pending.raw is None
print(pending.outputs["quality_report"])
```

Open the report. Every IC has a topography and inline PSD. Click a map for activation and class probabilities. **Exclude** is editable both on the tile and in the detail dialog. Enter reviewer/reason and select **Download confirmed selection**.

```python
revised = resume(
    pending.outputs["checkpoint"],
    save_path="outputs/sub01_reviewed",
    selection_json="selection.json",
    original_raw=raw,
)
```

Changing a checkbox does not immediately modify a FIF or redraw the existing report. The downloaded JSON is a complete new exclusion list associated with that model. `resume()` applies it and produces a new result/report.

Choose a separate output directory that neither contains nor is contained by the original run directory. A new sibling directory works.

### Revise an automatic result or restore an IC

Automatic runs also save the untouched pre-subtraction checkpoint. After inspecting that model, pass the complete desired **zero-based** list:

```python
revised = resume(
    "outputs/sub01_rest/sub01_ica_review/checkpoint.json",
    "outputs/sub01_revised",
    exclude=[1, 4],  # Example only: choose indices from this decomposition
    reviewer="Researcher",
    reason="Reviewed maps, spectra and activation",
    original_fif="prepared/sub01_raw.fif",
)
```

If the previous list was `[1, 4, 7]`, the new list `[1, 4]` restores component 7. `exclude=[]` explicitly retains every component. Do not apply another ICA subtraction directly to the already-cleaned output if the intention is to restore an IC.

An initial manual run uses `ica_mode="manual", ica_exclude=[1, 4]`, provided those indices are intended for the new decomposition. Review mode is preferable when the decomposition has not yet been inspected.

Continuation repeats reconstruction, final interpolation/reference, continuous QC, optional epochs and reporting. It does not refit ICA or repeat ICLabel, ASR, or filtering. Its frozen scientific parameters are restored from the checkpoint; changing those processing parameters requires a fresh run.

Keep all three checkpoint files and the original prepared input. File-backed inputs can be reopened and identity-checked; relocated files use `original_fif=...`. In-memory inputs require the unchanged `original_raw=...`. Do not substitute a cleaned result or a different recording. Compatibility checks cover checkpoint schema, computation source and critical numerical dependencies; old checkpoints are accepted only through verified transitions.

## Batch processing and memory

Process subjects sequentially until actual memory use is known:

```python
from pathlib import Path
import mne
from eegproc import run

summaries = []
for path in sorted(Path("prepared").glob("*_raw.fif")):
    subject = path.name.removesuffix("_raw.fif")
    raw = mne.io.read_raw_fif(path, preload=False)
    result = run(raw, Path("outputs") / subject, subject,
                 purpose="rest", task_name="eyes_closed", n_threads=1)
    summaries.append({"subject": subject, "status": result.status,
                      "report": result.outputs["quality_report"]})
    del result
    raw.close()
```

File-backed input reduces initial loading but processing still requires arrays in memory. Keep `collect_stages=False` unless diagnostic stage copies are needed. It defaults to false and writes no stage files. If running separate subjects in parallel, give every worker its own output directory and limit numerical threads; peak memory roughly accumulates across workers.

## CLI and report rebuilding

```bash
eegproc --input-fif prepared/sub01_raw.fif --save-path outputs/rest --subject sub01 --purpose rest --task-name eyes_closed
eegproc --input-fif prepared/sub01_task_raw.fif --save-path outputs/erp --subject sub01 --purpose erp --task-name oddball --epochs --events-json prepared/sub01_task_raw.events.json
eegproc --resume outputs/rest/sub01_ica_review/checkpoint.json --ica-exclude 1 4 --save-path outputs/revised --subject sub01 --original-fif prepared/sub01_raw.fif
eegproc-prepare --input device_data/sub01.vhdr --output-fif prepared/sub01_raw.fif --montage standard_1020 --eog VEOG --ecg ECG
```

`python -m eegproc` uses the same preprocessing CLI. Rare settings can be supplied as `--set key=JSON`, for example `--set ica_max_iter=4096`. Preparation and preprocessing are separate commands. Prepared event JSON contains `{"events": [[sample, 0, code], ...], "event_id": {"condition": code}}`; this illustration is a schema, not literal valid JSON with ellipses. Select actual stimulus conditions rather than exporting trial-end markers as analysis events.

Rebuild only the presentation from an existing HTML:

```python
from eegproc import render_report
render_report("outputs/rest/sub01_report.html", "outputs/rest/sub01_rebuilt_report.html")
```

The target must be new. This reuses saved figures and diagnostics without signal reprocessing; it does not change scientific results, IC exclusions or the sampling windows already used for those figures.
