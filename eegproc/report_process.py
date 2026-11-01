"""Bounded report subprocesses; no plotting is imported in the parent."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

REPORT_TIMEOUT_SECONDS = 300
REPORT_MAX_ATTEMPTS = 2
_LOG_TAIL_BYTES = 1024 * 1024


def _worker_command(source, output, result, logical_target, context):
    return [sys.executable, '-B', '-P', '-X', 'faulthandler', '-m', 'eegproc.report_worker',
            '--source', str(source), '--output', str(output), '--result', str(result),
            '--target', str(logical_target), '--context', str(context)]


def _worker_environment(n_threads):
    env = os.environ.copy()
    env.update(MPLBACKEND='Agg', PYTHONFAULTHANDLER='1', PYTHONDONTWRITEBYTECODE='1',
               PYTHONUTF8='1')
    for name in ('OMP_NUM_THREADS', 'OPENBLAS_NUM_THREADS', 'MKL_NUM_THREADS',
                 'NUMEXPR_NUM_THREADS'):
        env[name] = str(n_threads)
    # Source-checkout and installed calls must render with the calling package.
    package_root = str(Path(__file__).resolve().parent.parent)
    env['PYTHONPATH'] = package_root + (os.pathsep + env['PYTHONPATH']
                                      if env.get('PYTHONPATH') else '')
    return env


def _tail(path):
    try:
        with Path(path).open('rb') as stream:
            stream.seek(0, 2)
            size = stream.tell()
            stream.seek(max(0, size - _LOG_TAIL_BYTES))
            text = stream.read().decode('utf-8', errors='replace')
        return ('[earlier worker output omitted]\n' if size > _LOG_TAIL_BYTES else '') + text
    except OSError:
        return ''


def _preserve_failure(record, target, logs, source_path=None):
    """Retain retry material without overwriting a user's existing archive."""
    from .report_data import save_report_data
    from .storage import atomic_write_text

    outputs = record.setdefault('outputs', {})
    log = target.with_name(target.stem + '_errors.log')
    outputs['report_log'] = str(log)
    outputs['expected_report'] = str(target)
    bundle = target.with_name(target.stem + '_data.npz')
    source = Path(source_path).resolve() if source_path else None
    if source is not None and source.suffix.lower() == '.npz' and source.is_file():
        outputs['report_data'] = str(source)
    elif not bundle.exists():
        outputs['report_data'] = str(bundle)
        try:
            saved=dict(record)
            if 'report_materials' in saved:
                # Failed/partial PNGs can be regenerated from numeric material.
                # Keep collected errors but avoid copying embedded image bytes
                # into the recovery package as well as the partial HTML.
                saved['visualizations']={k:v for k,v in record.get('visualizations',{}).items()
                                         if k!='figures'}
                saved.pop('ica_diagnostics',None)
            save_report_data(saved, bundle)
        except Exception as exc:
            outputs.pop('report_data', None)
            record.setdefault('warnings', []).append(f'Report retry material could not be saved: {exc}')
    else:
        # The no-overwrite contract also applies to recovery material.
        record.setdefault('warnings', []).append('Existing report-data archive was preserved: ' + str(bundle))
    try:
        atomic_write_text(log, logs or json.dumps(record.get('report_error', {}), indent=2), overwrite=False)
    except Exception as exc:
        outputs.pop('report_log', None)
        record.setdefault('warnings', []).append(f'Report log could not be saved: {exc}')


def render_in_subprocess(record, target, *, reuse_figures=False, source_path=None):
    """Mutate only the report record; return False on failed report delivery.

    Two fresh workers at most are allowed. A worker has five minutes. These
    execution bounds do not change any signal-processing parameter.
    """
    from .report_data import save_report_data, read_report_data
    from .storage import _commit

    target = Path(target).resolve()
    outputs = record.setdefault('outputs', {})
    outputs.pop('quality_report', None)
    outputs.pop('expected_report', None)
    outputs.pop('report_log', None)
    record.pop('report_error', None)
    record.pop('report_supervision', None)
    record['report_status'] = 'running'
    attempts = []
    logs = []
    n_threads = max(1, int(record.get('config', {}).get('n_threads', 1)))
    context = dict(mode='subprocess', parent_pid=os.getpid(), n_threads=n_threads,
                   timeout_seconds=REPORT_TIMEOUT_SECONDS, max_attempts=REPORT_MAX_ATTEMPTS,
                   attempts=attempts, reuse_figures=bool(reuse_figures))
    source_file=Path(source_path).resolve() if source_path else None
    context['recovery']=dict(report_data=str(source_file if source_file is not None
        and source_file.suffix.lower()=='.npz' and source_file.is_file()
        else target.with_name(target.stem+'_data.npz')),
        report_log=str(target.with_name(target.stem+'_errors.log')))
    record['report_execution'] = context
    try:
        if target.exists():
            raise FileExistsError('Report target already exists; choose a new HTML path')
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.eeg-render-', dir=target.parent) as staging:
            root = Path(staging)
            source = root / 'material.npz'
            save_report_data(record, source)
            for number in range(1, REPORT_MAX_ATTEMPTS + 1):
                attempt_dir = root / str(number)
                attempt_dir.mkdir()
                html = attempt_dir / target.name
                result = attempt_dir / 'result.npz'
                config_path = attempt_dir / 'context.json'
                context['attempt'] = number
                config_path.write_text(json.dumps(context), encoding='utf8')
                log_path = attempt_dir / 'worker.log'
                started = time.monotonic()
                item = dict(attempt=number, returncode=None, timed_out=False)
                try:
                    with log_path.open('wb') as stream:
                        completed = subprocess.run(
                            _worker_command(source, html, result, target, config_path),
                            stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                            env=_worker_environment(n_threads), timeout=REPORT_TIMEOUT_SECONDS,
                            check=False, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    item['returncode'] = completed.returncode
                except subprocess.TimeoutExpired:
                    item['timed_out'] = True
                except OSError as exc:
                    item['error'] = f'{type(exc).__name__}: {exc}'
                item['elapsed_seconds'] = time.monotonic() - started
                attempts.append(item)
                logs.append(f'=== report attempt {number} ===\n' + json.dumps(item) + '\n' + _tail(log_path))
                candidate = None
                if result.is_file():
                    try:
                        candidate = read_report_data(result)
                    except Exception as exc:
                        item['result_error'] = f'{type(exc).__name__}: {exc}'
                if (item['returncode'] == 0 and candidate is not None and html.is_file()
                        and candidate.get('report_status') in ('completed', 'partial')):
                    # The worker never touches the final output. A racing writer
                    # cannot be replaced, even after the initial exists check.
                    # Worker observations embedded in HTML are distinct from
                    # timings observed after that process actually exits.
                    candidate['report_supervision'] = dict(attempts=deepcopy(attempts))
                    if candidate['report_status'] == 'partial':
                        _preserve_failure(candidate, target, '\n'.join(logs), source_path)
                    _commit([html], target.parent)
                    record.clear()
                    record.update(candidate)
                    if record['report_status'] == 'completed':
                        record.setdefault('outputs', {}).pop('expected_report', None)
                    record.pop('report_materials', None)
                    record.pop('ica_materials', None)
                    return True
                if candidate is not None and candidate.get('report_error'):
                    record['report_error'] = candidate['report_error']
                # Ordinary, handled rendering errors have a complete error
                # record. Repeating them without a changed input is unhelpful.
                if candidate is not None and candidate.get('report_status') == 'failed':
                    break
            record['report_status'] = 'failed'
            record.setdefault('report_error', dict(type='ReportWorkerError', message=(
                'Report worker timed out' if attempts and attempts[-1]['timed_out']
                else 'Report worker exited without a complete report')))
    except Exception as exc:
        record['report_status'] = 'failed'
        record['report_error'] = dict(type=type(exc).__name__, message=str(exc))
    outputs = record.setdefault('outputs', {})
    outputs.pop('quality_report', None)
    record['report_execution']['attempts'] = deepcopy(attempts)
    _preserve_failure(record, target, '\n'.join(logs), source_path)
    return False
