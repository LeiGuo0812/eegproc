# Processing workflow

[Home](../../README.md) · [中文](../zh-CN/workflow.md) · [Usage](usage.md) · [Parameters](parameters.md) · [Results](results.md)

These diagrams follow `engine.py`, `stages.py`, `signal_ops.py`, `review.py` and `delivery.py`. `purpose` selects parameter defaults; all purposes use the same stage order. `task_name` is descriptive metadata.

| Standard defaults | Rest | ERP |
|---|---|---|
| Analysis band | 0.5–80 Hz | 0.1–30 Hz |
| ICA training band | 1–100 Hz | 1–100 Hz |
| ASR | Enabled, cutoff 20 | Enabled, cutoff 20 |
| ICA / automatic rule | Picard / `threshold` | Picard / `threshold` |
| Epoch export | Requested separately | Requested separately |

## Main processing sequence

### 1. Input preparation and validation

```mermaid
flowchart TB
    accTitle: Input preparation and validation
    accDescr: Prepare continuous MNE input, resolve settings and verify the working EEG before cleaning.
    device_files["Device files"]
    prepare_input["Prepare MNE input"]
    raw_input["Continuous MNE Raw"]
    validate_input["Check Raw input"]
    resolve_parameters["Resolve parameters"]
    resolve_epochs["Resolve epoch request"]
    check_output["Check output paths"]
    copy_input["Create working copy"]
    check_coordinates["Check EEG coordinates"]
    select_eeg["Select working EEG"]
    device_files --> prepare_input
    prepare_input --> raw_input
    raw_input --> validate_input
    validate_input --> resolve_parameters
    resolve_parameters --> resolve_epochs
    resolve_epochs --> check_output
    check_output --> copy_input
    copy_input --> check_coordinates
    check_coordinates --> select_eeg
```

Preparation is a separate script. The input carries calibrated SI units, channel types, montage, timing, annotations and events; auxiliary samples remain in the original MNE container.

### 2. Line noise and channel cleaning

```mermaid
flowchart TB
    accTitle: Line noise and channel cleaning
    accDescr: Capture line-noise spectra, handle detected bad channels and filter the common processing band.
    line_before["Capture input line spectrum"]
    clean_line["Remove line noise"]
    line_after["Capture output line spectrum"]
    detect_bads["Detect bad channels"]
    early_interpolation{"Interpolate before ASR?"}
    interpolate_early["Interpolate bad channels"]
    exclude_bads["Exclude bad channels"]
    initial_reference["Apply reference"]
    common_filter["Filter common band"]
    gross_mask["Mark gross artifact windows"]
    line_before --> clean_line
    clean_line --> line_after
    line_after --> detect_bads
    detect_bads --> early_interpolation
    early_interpolation -->|Yes| interpolate_early
    early_interpolation -->|No, default| exclude_bads
    interpolate_early --> initial_reference
    exclude_bads --> initial_reference
    initial_reference --> common_filter
    common_filter --> gross_mask
```

Bad-channel detection uses a temporary training-band signal. The gross-artifact mask is measured before ASR and is used for ICA training exclusion.

### 3. ASR and band preparation

```mermaid
flowchart TB
    accTitle: ASR and band preparation
    accDescr: Apply ASR independently to valid segments, then prepare the analysis signal and optional ICA training data.
    asr_enabled{"ASR enabled?"}
    split_segments["Split valid ASR segments"]
    calibrate_asr["Calibrate each segment"]
    reconstruct_asr["Reconstruct each segment"]
    ica_enabled{"ICA enabled?"}
    training_reference["Apply reference again"]
    training_band["Complete training filter"]
    analysis_band["Complete analysis filter"]
    select_training["Select valid training samples"]
    analysis_only["Complete analysis filter"]
    asr_enabled -->|Yes| split_segments
    split_segments --> calibrate_asr
    calibrate_asr --> reconstruct_asr
    reconstruct_asr --> ica_enabled
    asr_enabled -->|No| ica_enabled
    ica_enabled -->|Yes| training_reference
    training_reference --> training_band
    training_band --> analysis_band
    analysis_band --> select_training
    ica_enabled -->|No| analysis_only
```

With ICA enabled, continue to stage 4. With ICA disabled, continue directly to stage 6. Band preparation only applies additional required filter edges; identical analysis and training bands share the full-record buffer.

### 4. ICA decomposition and automatic proposal

```mermaid
flowchart TB
    accTitle: ICA decomposition and automatic proposal
    accDescr: Estimate rank, fit ICA, classify components and save a checkpoint before any component subtraction.
    estimate_rank["Estimate training rank"]
    fit_ica["Fit ICA"]
    classify_ics["Run ICLabel"]
    propose_exclusions["Propose component exclusions"]
    ecg_support{"ECG support applicable?"}
    check_heart["Check Heart ECG correlation"]
    save_checkpoint["Save ICA checkpoint"]
    estimate_rank --> fit_ica
    fit_ica --> classify_ics
    classify_ics --> propose_exclusions
    propose_exclusions --> ecg_support
    ecg_support -->|Yes| check_heart
    ecg_support -->|No| save_checkpoint
    check_heart --> save_checkpoint
```

ECG support applies to Heart-only candidates under the `threshold` rule when usable ECG exists. Its reference is prepared from the matching valid training samples before ICA fitting. Without usable ECG, ICLabel alone determines the automatic proposal. The checkpoint contains untouched analysis-band data and a frozen decomposition.

### 5. Component selection

```mermaid
flowchart TB
    accTitle: ICA component selection modes
    accDescr: Select automatic or manual exclusions, or return a review report without subtracting components.
    ica_mode{"ICA mode"}
    automatic_list["Use automatic list"]
    manual_list["Use complete manual list"]
    apply_ica["Subtract selected components"]
    review_html["Write review HTML"]
    await_review(["Await ICA review"])
    ica_mode -->|auto| automatic_list
    ica_mode -->|manual| manual_list
    ica_mode -->|review| review_html
    automatic_list --> apply_ica
    manual_list --> apply_ica
    review_html --> await_review
```

Automatic and manual modes continue to stage 6. Review mode returns `awaiting_ica_review` with `result.raw is None`; use the continuation workflow below.

### 6. Continuous data delivery

```mermaid
flowchart TB
    accTitle: Continuous data finalization and delivery
    accDescr: Rebuild EEG, apply configured final operations, annotate residual artifacts and save continuous results.
    rebuild_eeg["Reconstruct EEG channels"]
    final_interpolation["Interpolate bad channels"]
    final_reference["Apply final reference"]
    restore_container["Restore MNE container"]
    continuous_qc["Check continuous residuals"]
    annotate_residual["Add BAD_residual annotations"]
    save_continuous["Save continuous FIF"]
    model_available{"ICA model available?"}
    save_model["Save final ICA model"]
    epoch_stage(["Continue to stage 7"])
    rebuild_eeg --> final_interpolation
    final_interpolation --> final_reference
    final_reference --> restore_container
    restore_container --> continuous_qc
    continuous_qc --> annotate_residual
    annotate_residual --> save_continuous
    save_continuous --> model_available
    model_available -->|Yes| save_model
    model_available -->|No| epoch_stage
    save_model --> epoch_stage
```

Interpolation, reference and residual annotation follow their respective switches. Reconstruction preserves original auxiliary channels and MNE metadata; continuous QC retains all samples.

### 7. Optional epochs and report

```mermaid
flowchart TB
    accTitle: Optional epoch export and report
    accDescr: Run requested epoch QC, save trials only when retained, then write the standalone HTML report.
    epochs_available{"Epochs requested and available?"}
    repair_enabled{"Epoch repair enabled?"}
    repair_epochs["Run bounded epoch repair"]
    strict_epochs["Run strict epoch QC"]
    retained_trials{"Any trials retained?"}
    save_epochs["Save epoch FIF"]
    summarize_retention["Summarize trial retention"]
    write_html["Write standalone HTML"]
    epochs_available -->|Yes| repair_enabled
    epochs_available -->|No| write_html
    repair_enabled -->|Yes| repair_epochs
    repair_enabled -->|No, default| strict_epochs
    repair_epochs --> retained_trials
    strict_epochs --> retained_trials
    retained_trials -->|Yes| save_epochs
    retained_trials -->|No| summarize_retention
    save_epochs --> summarize_retention
    summarize_retention --> write_html
```

With `epoch_qc="auto"`, event epochs use actual event-window QC and fixed epochs use continuous annotation rejection. Bounded repair is an alternative epoch path. Both preserve input BAD; the report includes per-condition retention and rejection reasons.

- The standard common band is **0.5–100 Hz for rest** and **0.1–100 Hz for ERP**. Line cleaning occurs before this filter and before ASR, not only on the final low-pass output.
- If analysis and ICA training bands are identical, for example **1–100 Hz**, they share the full-record band buffer. Selecting valid training samples and numerical algorithm work can still require other arrays.
- ASR never calibrates or carries state across input BAD/boundary spans. Segments shorter than the configured minimum are skipped and reported. `asr_cutoff=None` bypasses ASR.
- Each eligible ASR segment independently selects reference data, calibrates and reconstructs. The default segment minimum is 20 seconds. The gross-artifact mask is for later ICA training exclusion, not an additional ASR exclusion mask.
- Bad-channel detection uses a temporary training-band copy without input BAD/boundary samples. ICA training retains valid subsegments of at least 1 second and requires at least 20 seconds in total by default. Its bounded diagnostic preview remains in memory, not another Raw file.
- Optional `interpolate_before_asr=True` changes the bad-channel handling at that point. Reference/interpolation switches remain effective; `reference="unchanged"` also prevents reference changes at the final stage.
- With the default `threshold` rule, Heart-only ICLabel candidates require ECG correlation when usable ECG exists; otherwise ICLabel alone is used. `class_max` uses the original category rule without ECG assistance.
- Event-window QC preserves all input BAD annotations, including manual labels and any pre-existing `BAD_residual`. It reevaluates only `BAD_residual` added by this run on the actual requested trial. The continuous output keeps those annotations. Optional bounded epoch repair changes epochs only.

The default QC policy reports quality concerns and finishes viable processing for manual acceptance. `purpose="erp"` alone does not request epochs. Missing optional events can skip epoch export while continuous processing completes.

## ICA review and continuation

### Review the selection

```mermaid
flowchart TB
    accTitle: Review ICA component selection
    accDescr: Inspect component maps and spectra, confirm exclusions and provide the complete selection for continuation.
    open_report["Open ICA report"]
    inspect_maps["Inspect component maps"]
    inspect_psd["Inspect component spectra"]
    inspect_details["Inspect component details"]
    toggle_exclude["Adjust Exclude checkboxes"]
    confirm_selection["Confirm complete selection"]
    download_selection["Download selection.json"]
    direct_list["Supply exclude list"]
    call_resume["Call resume"]
    open_report --> inspect_maps
    inspect_maps --> inspect_psd
    inspect_psd --> inspect_details
    inspect_details --> toggle_exclude
    toggle_exclude --> confirm_selection
    confirm_selection --> download_selection
    download_selection --> call_resume
    direct_list --> call_resume
```

Use the review HTML either before initial subtraction or after an automatic/manual run. Exclude checkboxes are available on each component tile and inside its detail view. The downloaded JSON and `exclude=[...]` are alternative inputs; indices start at zero, and `exclude=[]` keeps every component.

### Resume from the checkpoint

```mermaid
flowchart TB
    accTitle: Resume verified ICA checkpoint
    accDescr: Verify the selection and unchanged checkpoint, restore original data and apply the revised complete exclusion list.
    verify_selection["Verify selection identity"]
    verify_hashes["Verify checkpoint hashes"]
    check_compatibility["Check code compatibility"]
    load_model["Load frozen ICA model"]
    validate_exclusions["Validate exclusion indices"]
    verify_original["Verify original input identity"]
    load_pre_ica["Load pre-subtraction data"]
    restore_metadata["Restore original MNE container"]
    apply_selection["Subtract selected components"]
    continue_delivery(["Continue at stage 6"])
    verify_selection --> verify_hashes
    verify_hashes --> check_compatibility
    check_compatibility --> load_model
    load_model --> validate_exclusions
    validate_exclusions --> verify_original
    verify_original --> load_pre_ica
    load_pre_ica --> restore_metadata
    restore_metadata --> apply_selection
    apply_selection --> continue_delivery
```

Provide the original prepared FIF or the unchanged original Raw. Compatibility checks include the computation source and dependencies. Resume requires a separate output directory. The new list replaces the previous decision, so previously removed components omitted from the list are restored.

Continuation reuses filtering, ASR, the ICA fit and ICLabel results. It reuses the parent checkpoint rather than writing another full copy. Checkbox edits alone do not modify saved FIFs; the original report's labels and plots describe its saved result until a new run is created.

## Standalone epoching

```mermaid
flowchart TB
    accTitle: Standalone epoch construction and QC
    accDescr: Read cleaned Raw and embedded BAD origins, build requested epochs and save retained trials without repeating continuous preprocessing.
    cleaned_raw["Cleaned MNE Raw"] --> bad_origins["Read BAD origins"]
    bad_origins --> resolve_events["Resolve epoch request"]
    resolve_events --> construct_epochs["Construct epochs"]
    construct_epochs --> epoch_qc["Run epoch QC"]
    epoch_qc --> save_epochs["Save retained epochs"]
    save_epochs --> report_output["Deliver epoch report"]
    source_report["Previous report or package"] -.-> report_output
```

`epoch()` uses the same epoch kernel as stage 7. It does not repeat line cleaning, channel detection, filters, ASR or ICA. The cleaned Raw/FIF carries the global bad-channel list, relevant epoch defaults and minimal automatic-residual origins. Existing, manual and unknown BAD remain protected. The source Raw is unchanged; only the Epochs receive baseline correction or optional bounded repair.

The source report is optional and supplies presentation material, not BAD decisions or required original data. An explicit source takes priority over a same-directory HTML/package and the Raw's report-path hint. Missing or unreadable sources warn and produce an independent epoch report. Choose the correct source yourself; no recording-identity matching is added. New combined HTML keeps the original report by default.

## Immediate or delayed report delivery

```mermaid
flowchart TB
    accTitle: Isolated immediate and delayed reports
    accDescr: Collect numeric diagnostics, render them in a fresh subprocess now or later, and retain recovery material if delivery is incomplete.
    collect_data["Collect numeric diagnostics"] --> report_enabled{"report=True?"}
    report_enabled -->|Yes| spawn["Start report subprocess"]
    spawn --> draw["Render stored diagnostics"]
    draw --> html["Commit HTML"]
    report_enabled -->|No| package["Save report-data package"]
    package --> render_later["Call render_report"]
    render_later --> spawn
    draw -->|Incomplete| recovery["Retain package and log"]
```

`run()`, `epoch()` and `resume()` default to immediate HTML through a fresh report subprocess. The data-processing caller first collects bounded numeric material without actively importing Agg or font-rendering components; MNE itself may import Matplotlib. `report=False` saves one `*_report_data.npz`, with no drawing or HTML. Representative before/after windows, spectrum summaries, ICA diagnostics and QC records are retained; a full original Raw is not copied. Rendering does not rerun denoising or epoch QC. Existing HTML reuses embedded figures in the same isolated path. A complete immediate report removes temporary material; partial or failed rendering retains a compact package and log. Report status is independent of processing status. Scientific defaults and the four-second waveform display window are unchanged.

## Input and delivered files

### Result files

```mermaid
flowchart TB
    accTitle: Delivered result files
    accDescr: Each result file has its own node; requested retained epochs are derived from the continuous result.
    completed_run["run or resume"]
    continuous_file["*_cont_raw.fif"]
    ica_file["*-ica.fif"]
    report_file["*_report.html"]
    epoch_file["*_clean-epo.fif"]
    completed_run --> continuous_file
    completed_run -->|ICA enabled| ica_file
    completed_run --> report_file
    continuous_file -->|Requested and retained| epoch_file
```

The continuous FIF contains cleaned EEG and original auxiliaries. The final ICA model includes the applied exclusion list. The HTML embeds all report figures, tables, effective settings and provenance.

### ICA checkpoint files

```mermaid
flowchart TB
    accTitle: ICA checkpoint file layout
    accDescr: Show the three independently saved checkpoint artifacts; continuation reuses this directory.
    checkpoint_directory["*_ica_review/"]
    pre_ica_file["pre_ica_raw.fif"]
    decomposition_file["decomposition-ica.fif"]
    checkpoint_file["checkpoint.json"]
    checkpoint_directory --> pre_ica_file
    checkpoint_directory --> decomposition_file
    checkpoint_directory --> checkpoint_file
```

`pre_ica_raw.fif` contains the analysis-band signal before IC subtraction. `decomposition-ica.fif` is the frozen model; `checkpoint.json` records continuation settings, identity checks and report data.

The normal ICA run with a completed report contains **six files**: three result files and the three-file checkpoint. Partial or failed rendering additionally retains compact report material and an error log for retry. Retained epochs add one file. With `report=False`, the report-data package replaces the immediate HTML. Review-only mode creates the report or deferred package plus the checkpoint; ICA-disabled runs have neither model nor checkpoint. Standalone epoching writes retained epoch FIF and one HTML or package, without a continuous-data or ICA copy. Large FIFs may have numbered parts. No `original_raw.fif`, `preview_raw.fif`, stage-by-stage snapshots, or report image/table attachments are generated. The optional `selection.json` is downloaded by the reviewer.
