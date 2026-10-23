"""Public Python arguments normalize optional settings before signal execution."""
from copy import deepcopy
from dataclasses import asdict
import json

import pytest

from eegproc import PipelineConfig, run
from eegproc.configuration import resolve_epoch_config


@pytest.fixture
def captured_engine(monkeypatch):
    import eegproc.engine as engine
    captured = []
    raw = object()

    def process(value, save_path, subject, **kwargs):
        assert value is raw
        captured.append(kwargs)
        return raw, {'status': 'completed', 'outputs': {}}, {}

    monkeypatch.setattr(engine, 'preprocess_raw', process)
    return raw, captured


@pytest.mark.parametrize('requested', ['false', 1, None, []])
def test_invalid_collect_stages_is_disabled_with_audit(captured_engine, tmp_path, requested):
    raw, captured = captured_engine
    result = run(raw, tmp_path, 'subject', collect_stages=requested)
    call = captured[-1]
    assert result.raw is raw and call['collect_stages'] is False
    assert any(r['field']=='collect_stages' and json.loads(json.dumps(r['requested']))==requested and r['effective'] is False
               for r in call['config'].adjustments)


def test_valid_stage_collection_and_invocation_are_preserved(captured_engine, tmp_path):
    raw, captured = captured_engine
    evidence = {'entrypoint': 'custom Python workflow', 'argv': ['analysis.py']}
    run(raw, tmp_path, 'subject', collect_stages=True, invocation=evidence)
    call = captured[-1]
    assert call['collect_stages'] is True and not call['config'].adjustments
    assert call['invocation']['entrypoint']==evidence['entrypoint']
    assert call['invocation']['argv']==evidence['argv']
    assert evidence=={'entrypoint': 'custom Python workflow', 'argv': ['analysis.py']}


@pytest.mark.parametrize('requested', [42, ['not', 'a', 'mapping']])
def test_optional_file_remains_effective_with_invalid_base_config(captured_engine, tmp_path, requested):
    raw, captured = captured_engine
    path = tmp_path/'config.json'
    path.write_text(json.dumps({'purpose': 'erp', 'highpass': .2, 'task_name': 'oddball'}), encoding='utf8')
    run(raw, tmp_path/'out', 'subject', config_file=path, config=requested, lowpass=40.)
    call = captured[-1]
    config = call['config']
    assert config.purpose=='erp' and config.highpass==.2 and config.lowpass==40.
    assert config.task_name=='oddball'
    assert any(r['field']=='config' and json.loads(json.dumps(r['requested']))==requested for r in config.adjustments)
    assert call['invocation']['config_path']==str(path.resolve())


@pytest.mark.parametrize('requested', ['not-a-mapping', 12, ['entrypoint', 'script']])
def test_invalid_invocation_uses_default_provenance_and_audits(captured_engine, tmp_path, requested):
    raw, captured = captured_engine
    run(raw, tmp_path, 'subject', invocation=requested, purpose='erp')
    call = captured[-1]
    assert call['invocation']['entrypoint']=='Python API'
    assert call['invocation']['effective_config']==asdict(call['config'])
    assert any(r['field']=='invocation' and json.loads(json.dumps(r['requested']))==requested and r['effective'] is None
               for r in call['config'].adjustments)
    json.dumps(call['invocation'], allow_nan=False)


def test_mapping_epoch_override_reaches_real_epoch_resolver_without_mutating_input(captured_engine, tmp_path):
    raw, captured = captured_engine
    requested = {'tmax': .8, 'ptp_uv': 180., 'max_interpolate': 2}
    original = deepcopy(requested)
    run(raw, tmp_path, 'subject', purpose='erp', epoch_mode='events', epoch_tmin=-.3,
        residual_peak_uv=140., seed=7, epoch_config=requested)
    call = captured[-1]
    config = call['config']
    epoch = resolve_epoch_config(config, call['epoch_config'], sfreq=256.)
    assert epoch.tmin==-.3 and epoch.tmax==.8
    assert epoch.peak_uv==140. and epoch.ptp_uv==180. and epoch.max_interpolate==2
    assert epoch.seed==7 and epoch.baseline==(None,0.)
    assert config.residual_ptp_uv==200. and requested==original
    assert not epoch.adjustments


def test_configuration_audit_survives_optional_file_and_api_resolution(captured_engine, tmp_path):
    raw, captured = captured_engine
    path = tmp_path/'config.json'
    path.write_text(json.dumps({'task_name': 'file_task'}), encoding='utf8')
    config = PipelineConfig(purpose='erp', highpass=-1.)
    run(raw, tmp_path/'out', 'subject', config_file=path, config=config, n_threads=0)
    resolved = captured[-1]['config']
    assert resolved.highpass==.1 and resolved.n_threads==1 and resolved.task_name is None
    changed = {r['field'] for r in resolved.adjustments}
    assert {'highpass','n_threads'} <= changed
    assert sum(r['field']=='highpass' for r in resolved.adjustments)==1


def test_missing_optional_configuration_file_keeps_explicit_code_settings(captured_engine, tmp_path):
    raw, captured = captured_engine
    missing = tmp_path/'missing.json'
    run(raw, tmp_path/'out', 'subject', config_file=missing, purpose='erp', task_name='oddball')
    config = captured[-1]['config']
    assert config.purpose=='erp' and config.highpass==.1 and config.task_name=='oddball'
    assert any(r['field']=='config_file' and r['requested']==str(missing) for r in config.adjustments)
    assert not missing.exists()
