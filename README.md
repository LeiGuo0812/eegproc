# eegproc

[中文](README.zh-CN.md) · [GitHub](https://github.com/LeiGuo0812/eegproc)

eegproc preprocesses resting-state and task EEG through MNE. It accepts continuous Raw data and combines line-noise removal, bad-channel detection, ASR, ICLabel-assisted ICA, and continuous or event-level quality control. Results include MNE FIF data and a self-contained HTML report with editable ICA selections.

Configure the workflow directly in Python, or use JSON and the command line. Every ICA run keeps a checkpoint for revising component exclusions without repeating the decomposition.

## Installation

Use **Python 3.12** and an activated virtual environment:

```bash
python -m pip install "eegproc @ git+https://github.com/LeiGuo0812/eegproc.git"
```

From a downloaded or cloned repository, run `python -m pip install -r requirements.txt` in its root directory. `requirements-all.txt` adds all optional runtime backends. See [installation](docs/en/installation.md) for Windows, Linux, macOS and dependency options.

## Quick start

```python
import mne
from eegproc import run

raw = mne.io.read_raw_fif("prepared/sub01_raw.fif", preload=False)
result = run(
    raw, save_path="outputs/sub01_rest", subject="sub01",
    purpose="rest", task_name="eyes_closed",
)
clean_raw = result.raw
print(result.status, result.outputs["quality_report"])
```

Prepare EEG/EOG/ECG in volts, electrode coordinates in metres, and correct channel types, montage and event timing. Device conversion is handled separately by `eegproc.preparation.prepare_data`. The input Raw is not modified; original BAD annotations and auxiliary samples are retained.

For a task recording with stimulus annotations `"1"` and `"2"`:

```python
task_raw = mne.io.read_raw_fif("prepared/sub01_task_raw.fif", preload=False)
events, _ = mne.events_from_annotations(task_raw, event_id={"1": 1, "2": 2})
erp = run(
    task_raw, "outputs/sub01_oddball", "sub01",
    purpose="erp", task_name="oddball",
    events=events, event_id={"standard": 1, "target": 2},
    epoch_tmin=-0.2, epoch_tmax=1.0,
)
```

`purpose` selects analysis defaults; `task_name` labels the recording. Supplying events requests event epochs. Inspect the HTML report and condition retention before accepting the data for analysis. Use a fresh output directory for each run.

| Standard default | Rest | ERP |
|---|---|---|
| Analysis band | 0.5–80 Hz | 0.1–30 Hz |
| ICA training band | 1–100 Hz | 1–100 Hz |
| ASR | Enabled; cutoff 20 | Enabled; cutoff 20 |
| ICA / automatic selection | Picard / ICLabel thresholds | Picard / ICLabel thresholds |
| Epoch export | When requested | When requested |
| Report waveform window | 4 s | 4 s |

## Workflow and outputs

```mermaid
flowchart TB
    accTitle: EEG preprocessing workflow
    accDescr: Top-down sequence of processing, review decisions, or delivered files.
    A[MNE Raw] --> B[Line noise and bad channels]
    B --> C[Reference, filters and ASR]
    C --> D[ICA fit and checkpoint]
    D --> E[Automatic or manual IC selection]
    E --> F[Reconstruction and continuous QC]
    F --> G[Optional epoch QC]
    G --> H[Clean FIF, ICA and HTML]
    D --> I[HTML review]
    I -->|Resume without refitting| E
```

```text
outputs/sub01_rest/
├── sub01_cont_raw.fif          Cleaned continuous data
├── sub01-ica.fif               ICA model and final exclusions
├── sub01_report.html           Figures, QC, settings and provenance
└── sub01_ica_review/
    ├── pre_ica_raw.fif         Data before component subtraction
    ├── decomposition-ica.fif   Frozen ICA decomposition
    └── checkpoint.json        Continuation state
```

Requested epochs add `sub01_clean-epo.fif` when trials remain. Report figures and tables are embedded in the HTML. Continuous BAD annotations mark problematic intervals without deleting samples.

To review before subtraction, set `ica_mode="review"`. To revise an automatic result, open its report and change **Exclude** on an IC tile or its detail view. Download the selection and call `resume()` with the checkpoint. A new complete list can restore previously removed components; filtering, ASR and ICA fitting are reused. Keep the original prepared input and all checkpoint files. See [ICA review and continuation](docs/en/usage.md#ica-review-and-continuation).

## Documentation

| Topic | English | 中文 |
|---|---|---|
| Installation and dependencies | [Installation](docs/en/installation.md) | [安装教程](docs/zh-CN/installation.md) |
| Processing stages and file delivery | [Workflow diagrams](docs/en/workflow.md) | [处理流程图](docs/zh-CN/workflow.md) |
| Preparation, rest, ERP, batch, ICA review and CLI | [Complete usage](docs/en/usage.md) | [完整使用示例](docs/zh-CN/usage.md) |
| Parameters, defaults and dependencies | [Parameters](docs/en/parameters.md) | [参数说明](docs/zh-CN/parameters.md) |
| Report, BAD labels and acceptance decisions | [Interpreting results](docs/en/results.md) | [结果解读](docs/zh-CN/results.md) |
| PSD, ERP, time-frequency, connectivity and statistics | [Further analysis](docs/en/analysis.md) | [后续分析建议](docs/zh-CN/analysis.md) |

Run the [synthetic example](examples/synthetic_demo.py) from a repository checkout to explore rest, ERP and ICA continuation:

```bash
python examples/synthetic_demo.py --output outputs/demo
```

More [executable examples](examples) cover real-data preparation, batch processing and downstream analysis.

Licensed under [BSD 3-Clause](LICENSE); see [third-party notices](docs/THIRD_PARTY_NOTICES.md) for included components.
