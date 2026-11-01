"""Batch supervision recovers records without replaying completed science."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest


@pytest.fixture
def batch():
    path = Path(__file__).parents[1] / "examples" / "batch_process.py"
    spec = importlib.util.spec_from_file_location("batch_example", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def row(subject="sub01"):
    return dict(subject=subject, input_fif="prepared.fif", purpose="rest", task_name="eyes_closed")


def test_completed_receipt_skips_science_but_missing_report_retries_only_report(batch, tmp_path):
    directory = tmp_path / "recording_0001"
    directory.mkdir()
    html = directory / "sub01_report.html"
    html.write_text("complete", encoding="utf-8")
    entry = dict(batch.base_entry(1, row()), status="completed", report_status="completed",
                 outputs={"quality_report": str(html)})
    batch.atomic_json(batch.receipt_path(tmp_path, 1), entry)
    assert batch.recovery_action(tmp_path, 1, row())[0] is None
    html.unlink()
    assert batch.recovery_action(tmp_path, 1, row())[0] == "report"


def test_failed_science_and_interrupted_outputs_are_not_automatically_reprocessed(batch, tmp_path):
    entry = dict(batch.base_entry(1, row()), status="failed", error="numerical stage failed")
    batch.atomic_json(batch.receipt_path(tmp_path, 1), entry)
    assert batch.recovery_action(tmp_path, 1, row())[0] is None
    directory = tmp_path / "recording_0002"
    directory.mkdir()
    (directory / "partial_cont_raw.fif").write_bytes(b"partial")
    action, recovered = batch.recovery_action(tmp_path, 2, row())
    assert action is None and recovered["status"] == "failed"
    assert batch.recovery_action(tmp_path, 3, row())[0] == "process"


def test_abrupt_worker_exit_does_not_stop_other_recordings(batch, tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("subject,input_fif,purpose,task_name\nsub01,a.fif,rest,eyes_closed\nsub02,b.fif,rest,eyes_closed\n", encoding="utf-8")
    output = tmp_path / "outputs"
    popen = subprocess.Popen

    def controlled_worker(command, **kwargs):
        if "--_worker" not in command:
            return popen(command, **kwargs)
        number = int(command[command.index("--_worker") + 1])
        if number == 1:
            # An unhandled process exit, not a deliberately induced memory fault.
            script = "import os; os._exit(3)"
        else:
            directory = output / "recording_0002"
            html = directory / "sub02_report.html"
            entry = dict(batch.base_entry(2, row("sub02")), status="completed", report_status="completed",
                         outputs={"quality_report": str(html)})
            script = ("from pathlib import Path; "
                      f"Path({str(html)!r}).write_text('complete',encoding='utf-8'); "
                      f"Path({str(batch.receipt_path(output, 2))!r}).write_text({json.dumps(entry)!r},encoding='utf-8')")
        assert kwargs["env"]["OPENBLAS_NUM_THREADS"] == "1"
        return popen([sys.executable, "-B", "-c", script], **kwargs)

    monkeypatch.setattr(batch.subprocess, "Popen", controlled_worker)
    assert batch.main([str(manifest), "--output", str(output), "--workers", "2"]) == 1
    results = json.loads((output / "batch_summary.json").read_text(encoding="utf-8"))
    assert results[0]["status"] == "failed" and results[0]["worker_exit_code"] == 3
    assert Path(results[0]["worker_log"]).is_file()
    assert results[1]["status"] == "completed"
    assert not (output / "recording_0002" / "batch_worker.log").exists()
    assert not list(output.rglob(".batch-*.tmp"))


def test_report_failure_preserves_completed_processing(batch, tmp_path, monkeypatch):
    entry = dict(batch.base_entry(1, row()), status="completed", report_status="deferred",
                 outputs={"report_data": str(tmp_path / "saved.npz")})

    class Interrupted:
        returncode = 7

        def wait(self, timeout=None):
            return self.returncode

    def interrupted(command, **kwargs):
        batch.atomic_json(batch.receipt_path(tmp_path, 1), entry)
        return Interrupted()

    monkeypatch.setattr(batch.subprocess, "Popen", interrupted)
    result = batch.supervise(tmp_path / "manifest.csv", tmp_path, 1, row(), "report", 30.)
    assert result["status"] == "completed"
    assert result["report_status"] == "failed"
    assert batch.recovery_action(tmp_path, 1, row())[0] == "report"


def test_resume_skips_completed_rows_and_schedules_report_recovery(batch, tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("subject,input_fif,purpose,task_name\nsub01,a.fif,rest,a\nsub02,b.fif,rest,b\n", encoding="utf-8")
    output = tmp_path / "outputs"
    html = output / "recording_0001" / "sub01_report.html"
    html.parent.mkdir(parents=True)
    html.write_text("complete", encoding="utf-8")
    batch.atomic_json(batch.receipt_path(output, 1), dict(batch.base_entry(1, row()), status="completed",
                                                       report_status="completed", outputs={"quality_report": str(html)}))
    batch.atomic_json(batch.receipt_path(output, 2), dict(batch.base_entry(2, row("sub02")), status="completed",
                                                       report_status="failed", outputs={"report_data": "saved.npz"}))
    calls = []

    def supervise(manifest, output, number, row, action, timeout, cancelled=None):
        calls.append((number, action))
        return dict(batch.base_entry(number, row), status="completed", report_status="completed")

    monkeypatch.setattr(batch, "supervise", supervise)
    assert batch.main([str(manifest), "--output", str(output), "--resume"]) == 0
    assert calls == [(2, "report")]


def test_atomic_summary_failure_keeps_previous_json(batch, tmp_path, monkeypatch):
    target = tmp_path / "summary.json"
    batch.atomic_json(target, {"status": "before"})

    def fail(*args):
        raise PermissionError("injected write failure")

    monkeypatch.setattr(batch.os, "replace", fail)
    with pytest.raises(PermissionError):
        batch.atomic_json(target, {"status": "after"})
    assert json.loads(target.read_text(encoding="utf-8")) == {"status": "before"}
    assert not list(tmp_path.glob(".batch-*.tmp"))


def test_timeout_terminates_worker_and_its_report_child(batch, tmp_path, monkeypatch):
    ready = tmp_path / "child_ready"
    late = tmp_path / "orphan_wrote_after_timeout"
    child = ("from pathlib import Path; import time; "
             f"Path({str(ready)!r}).write_text('ready'); time.sleep(1.8); "
             f"Path({str(late)!r}).write_text('orphan')")
    parent = ("import subprocess,sys,time; "
              f"subprocess.Popen([sys.executable,'-B','-c',{child!r}]); time.sleep(30)")
    popen = subprocess.Popen

    def controlled_worker(command, **kwargs):
        if "--_worker" in command:
            return popen([sys.executable, "-B", "-c", parent], **kwargs)
        return popen(command, **kwargs)

    monkeypatch.setattr(batch.subprocess, "Popen", controlled_worker)
    entry = batch.supervise(tmp_path / "manifest.csv", tmp_path / "output", 1, row(), "process", .8)
    assert ready.exists(), "The controlled child must start before timeout"
    time.sleep(1.3)
    assert entry["status"] == "failed" and "exceeded" in entry["error"]
    assert "worker_cleanup_error" not in entry
    assert not late.exists(), "The child must not survive its timed-out parent"


def test_report_only_worker_never_reprocesses_and_keeps_partial_material(batch, tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("subject,input_fif,purpose,task_name\nsub01,nonexistent.fif,rest,eyes_closed\n", encoding="utf-8")
    output = tmp_path / "outputs"
    directory = output / "recording_0001"
    directory.mkdir(parents=True)
    source = directory / "sub01_report_data.npz"
    source.write_bytes(b"saved material")
    entry = dict(batch.base_entry(1, row()), status="completed", report_status="failed",
                 outputs={"report_data": str(source)})
    batch.atomic_json(batch.receipt_path(output, 1), entry)
    calls = []

    def render(entry, directory):
        calls.append(entry["outputs"]["report_data"])
        entry["report_status"] = "partial"

    monkeypatch.setattr(batch, "render_saved", render)
    assert batch.worker(manifest, output, 1, "report") == 0
    receipt = batch.load_receipt(output, 1)
    assert receipt["status"] == "completed" and receipt["report_status"] == "partial"
    assert source.read_bytes() == b"saved material"
    assert calls == [str(source)]


def test_keyboard_interrupt_cancels_workers_and_saves_summary(batch, tmp_path, monkeypatch):
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("subject,input_fif,purpose,task_name\nsub01,a.fif,rest,a\n", encoding="utf-8")
    observed = []

    def waiting_worker(manifest, output, number, row, action, timeout, cancelled):
        assert cancelled.wait(2.)
        observed.append("cancelled")
        return dict(batch.base_entry(number, row), status="failed", error="Interrupted")

    def interrupt(futures):
        raise KeyboardInterrupt

    monkeypatch.setattr(batch, "supervise", waiting_worker)
    monkeypatch.setattr(batch, "as_completed", interrupt)
    output = tmp_path / "output"
    assert batch.main([str(manifest), "--output", str(output)]) == 130
    result = json.loads((output / "batch_summary.json").read_text(encoding="utf-8"))
    assert result[0]["status"] in {"pending", "failed"}
    assert observed == ["cancelled"] or result[0].get("batch_note")
