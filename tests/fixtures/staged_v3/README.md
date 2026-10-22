# Synthetic numerical regression fixtures

These fixed 40-second recordings contain 12 EEG channels, EOG/STIM, 256 Hz,
two events and a synthetic BAD annotation. They contain no participant data.

* `input_raw.fif`: synthetic input.
* `p16_rest_cont_raw.fif`: historical resting-state reference.
* `p16_erp_cont_raw.fif`: historical ERP reference (ASR disabled in that reference).
* JSON manifests: historical parameter/provenance records. Machine-specific
  path prefixes were removed for this source snapshot; numerical values and
  recorded data hashes were preserved. These are historical software checks,
  not physiological ground truth or current-default outputs.

The three FIF files are copied byte-for-byte. `RELEASE_MANIFEST.json` records
both source and staged hashes, including every sanitized metadata file.
Run `python scripts/validate_pipeline.py --output outputs/validation` with the
documented optional dependencies to regenerate a current comparison.
