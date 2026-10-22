"""Sequential rest/ERP processing with per-recording QC and failure logging.

Manifest CSV:
subject,input_fif,purpose,task_name,events_json
sub01,prepared/sub01_rest_raw.fif,rest,eyes_closed,
sub01,prepared/sub01_task_raw.fif,erp,oddball,prepared/sub01_task_raw.events.json

Paths are relative to the manifest. Each row gets a separate output directory.
Run: python examples/batch_process.py manifest.csv --output outputs/cohort
The output directory must be new. An error in one recording is recorded while
other recordings continue; read batch_summary.json before accepting a cohort.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    manifest = args.manifest.resolve()
    with manifest.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"subject", "input_fif", "purpose", "task_name"}
        if not required <= set(reader.fieldnames or []):
            raise ValueError(f"Manifest requires columns: {sorted(required)}")
        rows = list(reader)
    if not rows:
        raise ValueError("Manifest is empty")
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError(f"Choose a new output directory: {output}")
    output.mkdir(parents=True)
    import mne
    from eegproc import PipelineConfig, run

    summary = []
    for number, row in enumerate(rows, 1):
        raw = None
        entry = {"row": number, "subject": row["subject"], "purpose": row["purpose"]}
        try:
            if row["purpose"] not in ("rest", "erp"):
                raise ValueError("Batch purpose must explicitly be rest or erp")
            source = (manifest.parent / row["input_fif"]).resolve()
            raw = mne.io.read_raw_fif(source, preload=False, verbose=False)
            payload = {}
            if row.get("events_json", "").strip():
                events_file = (manifest.parent / row["events_json"]).resolve()
                payload = json.loads(events_file.read_text(encoding="utf-8-sig"))
                if not isinstance(payload, dict) or not payload.get("events"):
                    raise ValueError("Explicit events JSON must contain a nonempty events array")
            config = PipelineConfig(
                purpose=row["purpose"], task_name=row["task_name"] or None,
                epoch_mode="events" if row["purpose"] == "erp" else "none", n_threads=1)
            result = run(raw, output / f"recording_{number:04d}", row["subject"],
                         config=config, events=payload.get("events"),
                         event_id=payload.get("event_id"))
            entry.update(status=result.status, outputs=result.outputs,
                         quality_flags=result.report.get("quality_flags", []),
                         parameter_adjustments=result.report.get("parameter_adjustments", []),
                         epoch_resolution=result.report.get("epoch_resolution"),
                         trial_retention=result.report.get("epochs", {}).get("condition_retention"))
            del result  # do not retain a cohort of cleaned Raw arrays in memory
        except Exception as error:
            entry.update(status="failed", error=f"{type(error).__name__}: {error}")
        finally:
            if raw is not None:
                raw.close()
        summary.append(entry)
        (output / "batch_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf8")
        print(f"row {number}: {entry['status']}")
    if any(row["status"] == "failed" for row in summary):
        raise SystemExit("Some recordings failed; inspect batch_summary.json")


if __name__ == "__main__":
    main()
