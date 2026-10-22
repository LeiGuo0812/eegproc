"""Code-first configuration and adapter contracts, without signal processing."""
from dataclasses import asdict, replace
import hashlib
import json

import pytest

from eeg_pipeline import PipelineConfig, resolve_config, run
from eeg_pipeline.configuration import resolve_epoch_config
from eeg_pipeline.settings import config_for


# Canonical hashes captured from the untouched 0.2.0 config_for implementation.
@pytest.mark.parametrize('purpose,preset,expected', [
    ('rest','standard','e67cd56b0e6921e5eed29540c865d062953f566828c0136ea7cbd5299e2d55b2'),
    ('rest','eeglab','00d8da258f58594ad78aed7f88451daca0b84f3b667574d0acda27bdf86b2bb1'),
    ('erp','standard','5ab59a1d8e8fc3940430d5027939a03ebcbaf21ab3c8914e07625147cae3e8a1'),
    ('erp','eeglab','0eabe010e01c2c59ee7aec4af806c38c866df4d34507de29cebe0e59ab17f94a'),
])
def test_all_original_preset_defaults_are_unchanged(purpose,preset,expected):
    direct=PipelineConfig(purpose=purpose,preset=preset)
    factory=resolve_config(purpose=purpose,preset=preset)
    assert direct==factory==config_for(purpose,preset=preset)
    digest=hashlib.sha256(json.dumps(asdict(factory),sort_keys=True).encode()).hexdigest()
    assert digest==expected


def test_constructor_preserves_explicit_values_and_replace_semantics():
    config=PipelineConfig(purpose='erp',highpass=.5,lowpass=80.,task_name=None,
        asr_cutoff=None,line_frequency=None,ica_mode='manual',ica_exclude=[],detect_ransac=False)
    assert config.highpass==.5 and config.lowpass==80.
    assert config.task_name is None and config.ica_exclude==()
    assert config.asr_cutoff is None and config.line_frequency is None and config.detect_ransac is False
    assert replace(config,task_name='oddball').highpass==.5
    assert resolve_config(asdict(config))==config
    # A complete base retains its explicit resolved values when a label changes.
    assert resolve_config(config,purpose='rest').lowpass==80.


def test_mapping_file_and_keyword_precedence(tmp_path):
    path=tmp_path/'config.json'
    data={'purpose':'erp','task_name':'oddball','highpass':.2,'asr_cutoff':30.}
    path.write_text(json.dumps(data),encoding='utf8')
    assert resolve_config(path)==resolve_config(data)
    selected=resolve_config(data,asr_cutoff=None,task_name=None,detect_ransac=False)
    assert selected.lowpass==30. and selected.highpass==.2
    assert selected.asr_cutoff is None and selected.task_name is None
    assert selected.detect_ransac is False


@pytest.mark.parametrize('parameter,value', [
    ('highpass',True),('n_threads',1.5),('ica_max_iter',True),('seed',False),
    ('residual_qc',1),('lowpass',float('nan')),('residual_robust_z',float('inf')),
    ('detect_ransac','false'),('report_max_width',1200.5),('event_names','target'),
    ('epoch_baseline',[True,0.]),('asr_options',{'step_size':True}),
    ('asr_options',{'max_memory_mb':False}),('asr_options',{'not_an_option':2}),
])
def test_bad_types_are_resolved_and_audited_before_processing(parameter,value):
    from eeg_pipeline.configuration import validate_options
    resolved=resolve_config(**{parameter:value})
    validate_options(resolved)
    assert any(row['field'].startswith(parameter) for row in resolved.adjustments)


def test_nested_options_are_detached_immutable_and_serializable():
    options={'reference_tolerances':[-float('inf'),5.5],'step_size':32}
    config=PipelineConfig(asr_options=options)
    options['step_size']=64
    options['reference_tolerances'][1]=10.
    assert config.asr_options['step_size']==32
    assert config.asr_options['reference_tolerances']==(-float('inf'),5.5)
    with pytest.raises(TypeError):config.asr_options['step_size']=64
    with pytest.raises(TypeError):config.asr_options.update(step_size=64)
    assert resolve_config(json.loads(json.dumps(asdict(config))))==config
    assert replace(config,task_name='test').asr_options==config.asr_options


def test_public_run_accepts_keywords_mapping_and_optional_file(monkeypatch,tmp_path):
    import eeg_pipeline.engine as engine
    captured=[]
    sentinel=object()
    def fake(raw,save_path,subject,**kwargs):
        assert raw is sentinel
        captured.append(kwargs)
        return raw,{'status':'completed','outputs':{}},{}
    monkeypatch.setattr(engine,'preprocess_raw',fake)
    result=run(sentinel,tmp_path,'subject',purpose='erp',task_name='oddball',asr_cutoff=None)
    assert result.raw is sentinel
    assert captured[-1]['config']==PipelineConfig(purpose='erp',task_name='oddball',asr_cutoff=None)
    assert captured[-1]['invocation']['explicit_overrides']['asr_cutoff'] is None
    path=tmp_path/'config.json'
    path.write_text(json.dumps({'purpose':'erp','highpass':.2,'asr_cutoff':30.}),encoding='utf8')
    run(sentinel,tmp_path,'subject',config_file=path,config={'highpass':.3},asr_cutoff=None)
    config=captured[-1]['config']
    assert config.purpose=='erp' and config.lowpass==30. and config.highpass==.3
    assert config.asr_cutoff is None
    assert captured[-1]['invocation']['config_path']==str(path.resolve())
    run(sentinel,tmp_path,'subject',high_pas=1.)
    assert captured[-1]['config'].highpass==.5
    assert captured[-1]['config'].adjustments[0]['field']=='high_pas'
    assert len(captured)==3


def test_cli_routes_through_public_api(monkeypatch,tmp_path):
    from eeg_pipeline import api, cli
    captured={}
    sentinel=object()
    monkeypatch.setattr(cli.mne.io,'read_raw_fif',lambda *a,**k:sentinel)
    def fake(raw,save_path,subject,**kwargs):
        captured.update(kwargs)
        return api.PipelineResult(raw,{'status':'completed','quality_flags':[],'outputs':{}},{})
    monkeypatch.setattr(api,'run',fake)
    cli.main(['--input-fif',str(tmp_path/'source_raw.fif'),'--save-path',str(tmp_path/'out'),
        '--subject','test','--purpose','erp','--task-name','oddball','--asr-cutoff','off'])
    assert captured['config']==PipelineConfig(purpose='erp',task_name='oddball',asr_cutoff=None)
    assert captured['invocation']['entrypoint']=='preprocess.py'
    assert captured['invocation']['explicit_overrides']['asr_cutoff'] is None


def test_epoch_stage_resolves_legacy_override_without_changing_continuous_qc():
    from eeg_pipeline.epochs import EpochConfig
    config=resolve_config(purpose='erp',epoch_mode='events')
    default=resolve_epoch_config(config)
    assert default==EpochConfig()
    override=EpochConfig(tmax=.8,ptp_uv=180.,max_interpolate=2)
    selected=resolve_epoch_config(config,override)
    assert selected==override and config.residual_ptp_uv==200.
    fixed=resolve_epoch_config(resolve_config(epoch_mode='fixed'),sfreq=256.)
    assert fixed.tmin==0. and fixed.tmax==2.-1/256. and fixed.baseline is None
    corrected=resolve_epoch_config(config,EpochConfig(cv=2.5))
    assert corrected.cv==5
    assert corrected.adjustments[0]['field']=='epoch_config.cv'


@pytest.mark.parametrize('selection',[None,'0,1',[0,-1],[0,True],[0,1.5]])
def test_malformed_manual_intent_never_becomes_automatic_deletion(selection):
    resolved=resolve_config(ica_mode='manual',ica_exclude=selection)
    assert resolved.ica_mode=='manual' and resolved.ica_exclude==()
    assert any('human review' in row['reason'] for row in resolved.adjustments)


def test_parameter_dependencies_preserve_explicit_disable_and_manual_selection():
    disabled=resolve_config(ica_enabled=False,ica_mode='review',ica_exclude=[2],
        interpolate_bads=False,interpolate_before_asr=True,purpose='rest',repair_epochs=True)
    assert disabled.ica_enabled is False and disabled.ica_mode=='auto' and disabled.ica_exclude is None
    assert disabled.interpolate_bads is False and disabled.interpolate_before_asr is False
    assert disabled.purpose=='rest' and disabled.repair_epochs is False
    selected=resolve_config(ica_exclude=[2,2,3])
    assert selected.ica_mode=='manual' and selected.ica_exclude==(2,3)
    pending=resolve_config(purpose='erp',repair_epochs=True)
    assert pending.epoch_mode=='none' and pending.repair_epochs is True
    fixed=resolve_config(purpose='erp',repair_epochs=True,epoch_mode='fixed')
    assert fixed.epoch_mode=='fixed' and fixed.repair_epochs is False


def test_incompatible_bands_fall_back_to_selected_preset_without_clamping():
    erp=resolve_config(purpose='erp',highpass=40.,lowpass=30.,artifact_threshold=.1)
    assert erp.highpass==.1 and erp.lowpass==30. and erp.artifact_threshold==.9
    eeglab=resolve_config(preset='eeglab',training_highpass=100.,training_lowpass=1.)
    assert eeglab.training_highpass==.5 and eeglab.training_lowpass==100.


def test_audit_survives_config_merges_without_changing_dataclass_fields(tmp_path):
    original=resolve_config(n_threads=1.5,unknown_option=3)
    current=resolve_config(resolve_config(original),task_name='test')
    assert current.adjustments==original.adjustments
    assert len(asdict(current))==75 and 'adjustments' not in asdict(current)
    with pytest.raises(TypeError):current.adjustments[0]['effective']=8
    json.dumps(current.adjustments,allow_nan=False)
    weird=resolve_config(highpass=float('nan'))
    json.dumps(weird.adjustments,allow_nan=False)


@pytest.mark.parametrize('contents',['{bad json','[1,2,3]'])
def test_invalid_optional_config_file_uses_code_overrides_and_records_failure(tmp_path,contents):
    path=tmp_path/'settings.json';path.write_text(contents,encoding='utf8')
    config=resolve_config(path,purpose='erp',task_name='oddball')
    assert config.highpass==.1 and config.task_name=='oddball'
    assert config.adjustments and config.adjustments[0]['field'] in ('config','config_file')
    missing=resolve_config(tmp_path/'missing.json',purpose='erp')
    assert missing.highpass==.1 and missing.adjustments[0]['field']=='config_file'


def test_partial_epoch_mapping_uses_resolved_pipeline_defaults_and_audits_invalid_values():
    config=resolve_config(purpose='erp',epoch_mode='events',residual_peak_uv=180.)
    result=resolve_epoch_config(config,{'cv':2.5,'ptp_uv':190.,'baseline':[True,0.],'unknown':2})
    assert result.peak_uv==180. and result.ptp_uv==190. and result.cv==5
    assert result.baseline==(None,0.)
    assert {row['field'] for row in result.adjustments}=={'epoch_config.cv','epoch_config.baseline','epoch_config.unknown'}
