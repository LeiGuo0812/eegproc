"""Process a CSV batch in fresh processes and recover completed recordings.

Manifest CSV:
subject,input_fif,purpose,task_name,events_json
sub01,prepared/sub01_rest_raw.fif,rest,eyes_closed,
sub01,prepared/sub01_task_raw.fif,erp,oddball,prepared/sub01_task_raw.events.json

Paths are relative to the manifest. Each row gets its own output directory.
Run: python examples/batch_process.py manifest.csv --output outputs/cohort --workers 2
Resume the same manifest: add --resume. Completed data are never reprocessed.
Read batch_summary.json; a missing or partial report is not an EEG rejection.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
from threading import Event
import time
import traceback

PROCESSED = {"completed", "review_required", "awaiting_ica_review"}


def atomic_json(path, value):
    """Commit a small recovery record without exposing a truncated JSON file."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                         prefix=".batch-", suffix=".tmp", delete=False) as stream:
            name = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        for attempt in range(7):
            try:
                os.replace(name, path)
                break
            except OSError as error:
                if getattr(error, "winerror", None) not in (5, 32, 33) or attempt == 6:
                    raise
                time.sleep(min(.05 * 2 ** attempt, 1.))
    finally:
        if name is not None:
            name.unlink(missing_ok=True)


def read_manifest(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        required = {"subject", "input_fif", "purpose", "task_name"}
        if not required <= set(reader.fieldnames or []):
            raise ValueError(f"Manifest requires columns: {sorted(required)}")
        rows = list(reader)
    if not rows:
        raise ValueError("Manifest is empty")
    return rows


def receipt_path(output, number):
    return Path(output) / f"recording_{number:04d}" / "batch_result.json"


def load_receipt(output, number):
    path = receipt_path(output, number)
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or "status" not in value:
        raise ValueError(f"Unreadable recovery record: {path}")
    return value


def base_entry(number, row):
    return {"row": number, "subject": row["subject"], "purpose": row["purpose"],
            "task_name": row["task_name"], "status": "pending", "report_status": "pending"}


def next_html(directory, subject):
    target = directory / f"{subject}_report.html"
    attempt = 0
    while target.exists():
        attempt += 1
        target = directory / f"{subject}_report_retry{attempt}.html"
    return target


def render_saved(entry, directory):
    """Retry presentation from its package; never load or clean EEG here."""
    from eegproc import render_report
    from eegproc.reporting import read_report_source

    outputs = entry.setdefault("outputs", {})
    source = Path(outputs.get("report_data", ""))
    if not source.is_file():
        raise FileNotFoundError("No report-data package remains; EEG processing was not repeated")
    target = next_html(directory, entry["subject"])
    render_report(source, target)
    record = read_report_source(target)
    entry["report_status"] = record["report_status"]
    entry["report_execution"] = record.get("report_execution", {})
    report_log = record.get("outputs", {}).get("report_log")
    if report_log and Path(report_log).is_file():
        outputs["report_log"] = report_log
    outputs["quality_report"] = str(target)
    outputs.pop("expected_report", None)
    entry.pop("report_error", None)
    # Only remove a package made by this worker after a complete report commits.
    # Incomplete packages remain for --resume without repeating science.
    owned = directory / f"{entry['subject']}_report_data.npz"
    if entry["report_status"] == "completed" and source.resolve() == owned.resolve():
        try:
            source.unlink()
            outputs.pop("report_data", None)
        except OSError as error:
            entry["cleanup_warning"] = f"The completed report was saved; could not remove its package: {error}"


def worker(manifest, output, number, action):
    row = read_manifest(manifest)[number - 1]
    directory = Path(output) / f"recording_{number:04d}"
    directory.mkdir(parents=True, exist_ok=True)
    receipt = receipt_path(output, number)
    entry = base_entry(number, row)
    try:
        if action == "report":
            saved = load_receipt(output, number)
            if saved is None:
                raise FileNotFoundError("The completed-data recovery record is missing")
            entry = saved
        if action == "process":
            if row["purpose"] not in ("rest", "erp"):
                raise ValueError("Batch purpose must explicitly be rest or erp")
            import mne
            from eegproc import PipelineConfig, run

            payload = {}
            if row.get("events_json", "").strip():
                events_file = (Path(manifest).parent / row["events_json"]).resolve()
                payload = json.loads(events_file.read_text(encoding="utf-8-sig"))
                if not isinstance(payload, dict) or not payload.get("events"):
                    raise ValueError("Explicit events JSON must contain a nonempty events array")
            config = PipelineConfig(
                purpose=row["purpose"], task_name=row["task_name"] or None,
                epoch_mode="events" if row["purpose"] == "erp" else "none", n_threads=1)
            source = (Path(manifest).parent / row["input_fif"]).resolve()
            with mne.io.read_raw_fif(source, preload=False, verbose=False) as raw:
                result = run(raw, directory, row["subject"], config=config,
                             events=payload.get("events"), event_id=payload.get("event_id"),
                             report=False)
                entry.update(status=result.status, outputs=dict(result.outputs),
                             report_status=result.report.get("report_status", "failed"),
                             quality_flags=result.report.get("quality_flags", []),
                             parameter_adjustments=result.report.get("parameter_adjustments", []),
                             epoch_resolution=result.report.get("epoch_resolution"),
                             trial_retention=result.report.get("epochs", {}).get("condition_retention"))
                del result
            atomic_json(receipt, entry)  # science is durable before rendering
        if entry["status"] in PROCESSED:
            try:
                render_saved(entry, directory)
            except Exception as error:
                entry.update(report_status="failed", report_error=f"{type(error).__name__}: {error}")
                traceback.print_exc()
        atomic_json(receipt, entry)
        return 0
    except Exception as error:
        entry.update(status="failed", error=f"{type(error).__name__}: {error}")
        atomic_json(receipt, entry)
        traceback.print_exc()
        return 1


def terminate_worker_tree(process):
    """Stop this owned worker and its report children before closing its handle."""
    if os.name == "nt":
        # Execute the Windows utility directly; no shell or unrelated PIDs.
        executable = Path(os.environ.get("SystemRoot", "C:/Windows")) / "System32" / "taskkill.exe"
        result = subprocess.run([str(executable), "/PID", str(process.pid), "/T", "/F"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                                check=False, timeout=15.)
        if result.returncode != 0 and process.poll() is None:
            process.kill()
            process.wait(timeout=15.)
            raise RuntimeError("Could not confirm termination of the worker's child-process tree")
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    process.wait(timeout=15.)


def supervise(manifest, output, number, row, action, timeout, cancelled=None):
    """Only stdlib supervision runs in the parent, including parallel batches."""
    if cancelled is not None and cancelled.is_set():
        entry = base_entry(number, row)
        entry["batch_note"] = "Interrupted before this worker started"
        return entry
    directory = Path(output) / f"recording_{number:04d}"
    directory.mkdir(parents=True, exist_ok=True)
    log = directory / "batch_worker.log"
    env = dict(os.environ, PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1", MPLBACKEND="Agg")
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[name] = "1"
    command = [sys.executable, "-B", "-X", "faulthandler", str(Path(__file__).resolve()),
               str(manifest), "--output", str(output), "--_worker", str(number), "--_action", action]
    returncode = None
    error = None
    cleanup_error = None
    try:
        with log.open("ab") as stream:
            stream.write(f"\nBatch worker: row={number}, action={action}\n".encode("utf-8"))
            stream.flush()
            options = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
            process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stream,
                                       stderr=subprocess.STDOUT, env=env, **options)
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if cancelled is not None and cancelled.is_set():
                    error = "Worker interrupted by the batch controller"
                elif remaining <= 0:
                    error = f"Worker exceeded {timeout:g} seconds"
                if error:
                    try:
                        terminate_worker_tree(process)
                    except Exception as exc:
                        cleanup_error = f"Worker tree cleanup failed: {type(exc).__name__}: {exc}"
                    returncode = process.returncode
                    break
                try:
                    returncode = process.wait(timeout=min(.2, remaining))
                    break
                except subprocess.TimeoutExpired:
                    pass
    except OSError as exc:
        error = f"Could not start worker: {exc}"
    try:
        entry = load_receipt(output, number) or base_entry(number, row)
    except (OSError, ValueError) as exc:
        entry = base_entry(number, row)
        error = f"Could not read worker recovery record: {exc}"
    if error or returncode != 0:
        message = error or f"Worker exited abnormally with code {returncode}"
        if entry["status"] in PROCESSED:
            entry.update(report_status="failed", report_error=message)
        else:
            entry.update(status="failed", error=entry.get("error", message))
        entry["worker_exit_code"] = returncode
        if cleanup_error:
            entry["worker_cleanup_error"] = cleanup_error
    elif entry["status"] == "pending":
        entry.update(status="failed", error="Worker exited without a recovery record")
    complete = entry["status"] in PROCESSED and entry.get("report_status") == "completed"
    if complete:
        try:
            log.unlink(missing_ok=True)
            entry.pop("worker_log", None)
        except OSError as error:
            entry.update(worker_log=str(log), cleanup_warning=f"Could not remove successful worker log: {error}")
    else:
        entry["worker_log"] = str(log)
    atomic_json(receipt_path(output, number), entry)
    return entry


def recovery_action(output, number, row):
    """Reuse completed science; do not silently restart an incomplete recording."""
    entry = load_receipt(output, number)
    if entry is None:
        directory = Path(output) / f"recording_{number:04d}"
        if directory.exists() and any(directory.iterdir()):
            entry = base_entry(number, row)
            entry.update(status="failed", error="Incomplete output has no recovery record; use a new output for reprocessing")
            return None, entry
        return "process", base_entry(number, row)
    if entry["status"] not in PROCESSED:
        return None, entry
    html = entry.get("outputs", {}).get("quality_report")
    if entry.get("report_status") == "completed" and html and Path(html).is_file():
        return None, entry
    return "report", entry


def parser():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("manifest", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--workers", type=int, default=1, help="Concurrent recordings (default: 1)")
    p.add_argument("--resume", action="store_true", help="Continue the same batch; reuse completed data")
    p.add_argument("--timeout", type=float, default=86400., help="Maximum seconds per recording worker (default: 86400)")
    p.add_argument("--_worker", type=int, help=argparse.SUPPRESS)
    p.add_argument("--_action", choices=("process", "report"), default="process", help=argparse.SUPPRESS)
    return p


def main(argv=None):
    p = parser()
    args = p.parse_args(argv)
    manifest, output = args.manifest.resolve(), args.output.resolve()
    if args._worker is not None:
        return worker(manifest, output, args._worker, args._action)
    if args.workers < 1 or args.timeout <= 0:
        p.error("--workers and --timeout must be positive")
    rows = read_manifest(manifest)
    if output.exists() and not args.resume:
        raise FileExistsError("Output exists; use --resume with the unchanged manifest, or choose a new directory")
    output.mkdir(parents=True, exist_ok=True)
    summary, jobs = {}, []
    for number, row in enumerate(rows, 1):
        try:
            action, entry = recovery_action(output, number, row) if args.resume else ("process", base_entry(number, row))
        except (OSError, ValueError) as error:
            action, entry = None, base_entry(number, row)
            entry.update(status="failed", error=f"Could not read recovery record: {error}")
        summary[number] = entry
        if action:
            jobs.append((number, row, action))
    def save_summary():
        atomic_json(output / "batch_summary.json", [summary[n] for n in sorted(summary)])
    save_summary()
    cancelled = Event()
    pool = ThreadPoolExecutor(max_workers=args.workers)
    pending = {}
    interrupted = False
    try:
        pending = {pool.submit(supervise, manifest, output, n, row, action, args.timeout, cancelled): n
                   for n, row, action in jobs}
        for future in as_completed(pending):
            number = pending[future]
            try:
                summary[number] = future.result()
            except Exception as error:
                summary[number].update(status="failed", error=f"Supervisor error: {type(error).__name__}: {error}")
            save_summary()
            entry = summary[number]
            print(f"row {number}: {entry['status']}; report={entry.get('report_status')}", flush=True)
    except KeyboardInterrupt:
        interrupted = True
        cancelled.set()
        for future in pending:
            future.cancel()
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
    if interrupted:
        for future, number in pending.items():
            if future.cancelled():
                summary[number]["batch_note"] = "Interrupted before this worker started"
            else:
                try:
                    summary[number] = future.result()
                except Exception as error:
                    summary[number].update(status="failed", error=f"Supervisor error: {error}")
        save_summary()
        print("Batch interrupted; recovery summary saved", file=sys.stderr)
        return 130
    if any(e["status"] not in PROCESSED or e.get("report_status") != "completed" for e in summary.values()):
        print("Some processing or reports need attention; inspect batch_summary.json", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
