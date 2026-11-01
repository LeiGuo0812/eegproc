"""Report faults are contained independently of EEG processing results."""
from copy import deepcopy
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys

import pytest

from eegproc import PipelineResult, render_report, resolve_config
from eegproc.reporting import emit_report, read_report_source


def record():
    return dict(status='completed',config=asdict(resolve_config()),outputs={},
        provenance={},quality_flags=[],
        epochs=dict(condition_retention={'1':dict(input=5,eligible=4,retained=4)}))


def abrupt(*args):
    # Controlled process termination exercises supervision without provoking an
    # access violation or relying on the failing computer's native libraries.
    return [sys.executable,'-B','-c','import os; os._exit(23)']


def test_real_report_runs_in_new_process_and_success_keeps_only_html(tmp_path):
    value=record();target=tmp_path/'subject_report.html'
    assert emit_report(value,target)
    assert value['status']=='completed' and value['report_status']=='completed'
    assert value['report_execution']['worker_pid']!=os.getpid()
    saved=read_report_source(target)
    assert saved['outputs']['quality_report']==str(target)
    assert saved['report_execution']['attempts'][0]['returncode']==0
    assert saved['report_execution']['n_threads']==value['config']['n_threads']
    assert [path.name for path in tmp_path.iterdir()]==[target.name]


def test_worker_imports_calling_package_when_cwd_contains_another_copy(tmp_path,monkeypatch):
    shadow=tmp_path/'shadow'/'eegproc';shadow.mkdir(parents=True)
    (shadow/'__init__.py').write_text("raise RuntimeError('wrong eegproc copy imported')",encoding='utf8')
    monkeypatch.chdir(shadow.parent)
    value=record();target=tmp_path/'output'/'subject_report.html'
    assert emit_report(value,target)
    assert value['report_status']=='completed'


def test_abrupt_worker_exit_preserves_processing_result_and_retry_material(tmp_path,monkeypatch):
    import eegproc.report_process as process
    monkeypatch.setattr(process,'_worker_command',abrupt)
    value=record();target=tmp_path/'subject_report.html'
    assert emit_report(value,target) is False
    assert value['status']=='completed' and value['processing_status']=='completed'
    assert value['report_status']=='failed' and 'quality_report' not in value['outputs']
    assert not target.exists()
    assert [r['returncode'] for r in value['report_execution']['attempts']]==[23,23]
    assert Path(value['outputs']['report_data']).is_file()
    assert Path(value['outputs']['report_log']).is_file()
    saved=read_report_source(value['outputs']['report_data'])
    assert saved['epochs']==value['epochs'] and saved['report_status']=='failed'


def test_second_fresh_worker_recovers_without_leaving_sidecars(tmp_path,monkeypatch):
    import eegproc.report_process as process
    original=process._worker_command
    calls=[]
    def flaky(*args):
        calls.append(args)
        return abrupt() if len(calls)==1 else original(*args)
    monkeypatch.setattr(process,'_worker_command',flaky)
    value=record();target=tmp_path/'subject_report.html'
    assert emit_report(value,target)
    assert [r['returncode'] for r in value['report_execution']['attempts']]==[23,0]
    assert [r['returncode'] for r in read_report_source(target)['report_execution']['attempts']]==[23,0]
    assert [p.name for p in tmp_path.iterdir()]==[target.name]


def test_report_timeout_is_bounded_and_preserves_recovery_material(tmp_path,monkeypatch):
    import eegproc.report_process as process
    monkeypatch.setattr(process,'REPORT_TIMEOUT_SECONDS',.1)
    monkeypatch.setattr(process,'_worker_command',lambda *a:[sys.executable,'-B','-c','import time; time.sleep(5)'])
    value=record()
    assert not emit_report(value,tmp_path/'subject_report.html')
    assert len(value['report_execution']['attempts'])==2
    assert all(r['timed_out'] for r in value['report_execution']['attempts'])
    assert value['report_status']=='failed' and value['status']=='completed'


def test_explicit_render_failure_preserves_original_npz(tmp_path,monkeypatch):
    import eegproc.report_process as process
    value=record()
    assert emit_report(value,tmp_path/'subject_report.html',generate=False)
    source=Path(value['outputs']['report_data']);before=source.read_bytes()
    monkeypatch.setattr(process,'_worker_command',abrupt)
    with pytest.raises(RuntimeError,match='Report rendering failed'):
        render_report(source,tmp_path/'subject_report.html')
    assert source.read_bytes()==before
    assert not (tmp_path/'subject_report.html').exists()


def test_completed_render_keeps_source_archive_but_has_no_recovery_outputs(tmp_path):
    value=record()
    assert emit_report(value,tmp_path/'planned_report.html',generate=False)
    source=Path(value['outputs']['report_data']);before=source.read_bytes()
    target=render_report(source,tmp_path/'finished_report.html')
    saved=read_report_source(target)
    assert source.read_bytes()==before
    assert saved['report_generation']['source_report']==str(source)
    assert not {'report_data','report_log','expected_report'} & saved['outputs'].keys()
    assert 'recovery' not in saved['report_execution']


def test_result_falls_back_to_html_when_old_archive_path_no_longer_exists(tmp_path):
    value=record();target=tmp_path/'subject_report.html'
    assert emit_report(value,target)
    saved=read_report_source(target)
    saved['outputs']['report_data']=str(tmp_path/'deleted_report_data.npz')
    for figure in saved['visualizations']['figures']:
        figure.pop('data_uri',None)
    result=PipelineResult(None,saved,{})
    restored=read_report_source(result)
    assert restored['visualizations']['figures'][0]['data_uri'].startswith('data:image/')
    rebuilt=render_report(result,tmp_path/'rebuilt_report.html')
    assert read_report_source(rebuilt)['report_generation']['source_report']==str(target)


def test_missing_applicable_figures_are_partial_even_without_plot_exception(tmp_path,monkeypatch):
    import eegproc.quality_figures as figures
    from eegproc.quality_report import safe_report
    monkeypatch.setattr(figures,'build_material_figures',lambda *a,**k:dict(figures=[],notes=[],errors=[]))
    value=record()
    value['report_materials']={'waveforms':{'windows':[{}]},'psd':{}}
    assert safe_report(value,tmp_path/'partial.html')
    assert value['report_status']=='partial'
    assert value['report_completeness']['missing_figures']==['psd','waveform_1']
    assert 'Partial' in (tmp_path/'partial.html').read_text(encoding='utf8')


def test_real_partial_worker_saves_retry_material_and_does_not_delete_source(tmp_path):
    value=record();value['report_materials']={'psd':{}}
    target=tmp_path/'subject_report.html'
    assert emit_report(value,target)
    assert value['report_status']=='partial' and value['status']=='completed'
    saved=read_report_source(target)
    assert saved['report_status']=='partial'
    assert saved['outputs']['report_data']==value['outputs']['report_data']
    assert Path(value['outputs']['report_data']).is_file()
    assert Path(value['outputs']['report_log']).is_file()


def test_low_level_html_commit_never_overwrites_existing_report(tmp_path):
    from eegproc.quality_report import safe_report
    target=tmp_path/'existing.html';target.write_bytes(b'previous successful report')
    value=record()
    assert not safe_report(value,target)
    assert target.read_bytes()==b'previous successful report'
    assert value['report_status']=='failed'


def test_worker_environment_controls_threads_and_uses_current_package(monkeypatch):
    from eegproc.report_process import _worker_environment
    monkeypatch.setenv('OPENBLAS_NUM_THREADS','99')
    env=_worker_environment(1)
    assert all(env[n]=='1' for n in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS','NUMEXPR_NUM_THREADS'))
    assert env['MPLBACKEND']=='Agg' and env['PYTHONFAULTHANDLER']=='1'
    assert Path(env['PYTHONPATH'].split(os.pathsep)[0])==Path(__file__).resolve().parents[1]
