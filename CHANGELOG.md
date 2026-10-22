# Changelog

## 0.4.0a1

- Publish as **eegproc**, with `eegproc` and `eegproc-prepare` commands.
- Retain `eeg_pipeline`, `eeg-preprocess`, `eeg-prepare` and existing bridge/ASR
  imports as compatibility aliases to the same implementation.
- Add English and Simplified Chinese installation, complete parameter,
  usage, report interpretation and downstream analysis guides.
- Add runnable synthetic and real-input examples. No data download is required
  for the synthetic demonstration.
- License project-owned code under BSD-3-Clause; retain original third-party
  notices. Use the MNE 1.12.1 montage resource with identical bridge fiducials
  and head transform.
- Preserve scientific algorithms and preset defaults. Verify five full-pipeline
  comparisons and twelve historical ICA continuations after renaming.

Known boundary: for annotations containing only BAD labels with events stored
in a STIM channel, request `event_source="stim"` or supply explicit events.
The automatic annotation-to-STIM fallback needs a separate correction.

## 0.3.1 (local development)

- Resolve parameter dependencies and record adjustments in the HTML report.
- Preserve channel-specific annotations when extracting ECG/channel subsets.
- Prepare dependency requirements, compact release staging and install checks.
