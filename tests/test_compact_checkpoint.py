"""Compact checkpoints preserve selection, source identity and task metadata."""
from pathlib import Path
import json
import shutil
import mne
import numpy as np
import pytest
from eeg_pipeline import resolve_config,run,resume
from eeg_pipeline.cli import parser,main
from test_pipeline import fixture
from report_helpers import read_report


def test_task_name_is_independent_metadata_and_accepts_json_cli_overrides(tmp_path):
    config=tmp_path/'config.json'
    config.write_text(json.dumps(dict(purpose='erp',task_name='oddball')),encoding='utf8')
    assert resolve_config().task_name=='rest'
    assert resolve_config(purpose='erp').task_name is None
    assert resolve_config(config).task_name=='oddball'
    changed=resolve_config(config,task_name='stroop')
    assert changed.task_name=='stroop' and changed.highpass==.1 and changed.lowpass==30
    assert resolve_config(purpose='rest',task_name='eyes-closed').highpass==.5
    args=parser().parse_args(['--input-fif','input_raw.fif','--save-path','out',
                             '--subject','s','--purpose','erp','--task-name','oddball'])
    assert args.task_name=='oddball'
    for task in ['', ' ', ' oddball', 'x\nx', 42, 'a'*101]:
        repaired=resolve_config(task_name=task)
        assert repaired.task_name=='rest'
        assert any(r['field']=='task_name' and r['requested']==task and r['effective']=='rest'
                   for r in repaired.adjustments)
    ignored=resolve_config(task='oddball')
    assert ignored.task_name=='rest' and not hasattr(ignored,'task')
    assert any(r['field']=='task' and r['effective'] is None for r in ignored.adjustments)


@pytest.mark.parametrize('interpolate_before_asr',[False,True])
def test_file_backed_compact_resume_and_relocated_input(tmp_path,monkeypatch,interpolate_before_asr):
    source=tmp_path/'input_raw.fif'
    raw=fixture()
    raw.info['bads']=['Fp1']
    raw.save(source,fmt='double',overwrite=True,verbose=False)
    raw=mne.io.read_raw_fif(source,preload=False,verbose=False)
    cfg=resolve_config(purpose='erp',task_name='oddball',asr_cutoff=None,
                       channel_method='off',line_frequency=None,epoch_mode='events',
                       interpolate_before_asr=interpolate_before_asr)
    result=run(raw,tmp_path/'automatic','s',config=cfg)
    checkpoint=Path(result.outputs['checkpoint'])
    state=json.loads(checkpoint.read_text(encoding='utf8'))
    assert state['schema']=='eeg-ica-review-v2'
    assert set(state['artifacts'])=={'pre_ica','ica'}
    assert {p.name for p in checkpoint.parent.iterdir()}=={
        'checkpoint.json','pre_ica_raw.fif','decomposition-ica.fif'}
    assert state['original_input']['fif_path']==str(source)
    assert state['config']['task_name']==state['report']['task_name']=='oddball'
    pre=mne.io.read_raw_fif(result.outputs['pre_ica'],preload=True,verbose=False)
    assert pre.ch_names==raw.ch_names and pre.annotations==raw.annotations
    np.testing.assert_array_equal(pre.get_data(picks=['EOG','STI']),raw.get_data(picks=['EOG','STI']))
    def never(*args,**kwargs):raise AssertionError('Resume must use the saved decomposition and diagnostics')
    import eeg_pipeline.engine as engine
    monkeypatch.setattr(engine,'fit_ica',never)
    monkeypatch.setattr(mne.preprocessing.ICA,'get_sources',never)
    resumed=resume(checkpoint,tmp_path/'resumed','s',
                   exclude=result.report['ica']['removed_components_0based'])
    np.testing.assert_allclose(resumed.raw.get_data(),result.raw.get_data(),rtol=1e-10,atol=1e-15)
    assert resumed.report['ica_diagnostics']==result.report['ica_diagnostics']
    assert resumed.report['epochs']['records']==result.report['epochs']['records']
    assert all(v is not False for v in resumed.report['metadata_audit']['checks'].values())
    assert not resumed.report['visualizations']['errors']
    page=Path(resumed.outputs['quality_report']).read_text(encoding='utf8')
    assert '<td>Task name</td><td>oddball</td>' in page
    assert read_report(page)['task_name']=='oddball'
    # An explicitly relocated input remains usable without a new snapshot.
    relocated=tmp_path/'relocated_raw.fif'
    shutil.copyfile(source,relocated)
    main(['--resume',str(checkpoint),'--original-fif',str(relocated),
          '--save-path',str(tmp_path/'cli'),'--subject','s','--ica-exclude'])
    cli_page=(tmp_path/'cli/s_report.html').read_text(encoding='utf8')
    assert read_report(cli_page)['config']['task_name']=='oddball'


def test_in_memory_resume_requires_same_input_and_rejects_changed_annotations(tmp_path):
    raw=fixture(False)
    result=run(raw,tmp_path/'review','s',config=resolve_config(
        ica_mode='review',channel_method='off',asr_cutoff=None,line_frequency=None))
    checkpoint=result.outputs['checkpoint']
    with pytest.raises(ValueError,match='Original input is required'):
        resume(checkpoint,tmp_path/'missing','s',exclude=[])
    wrong=raw.copy()
    wrong.annotations.append(wrong.first_time+2,1,'BAD_added_after_run')
    with pytest.raises(ValueError,match='does not match'):
        resume(checkpoint,tmp_path/'wrong','s',exclude=[],original_raw=wrong)
    wrong=raw.copy()
    wrong._data[-2,0]+=1e-6
    with pytest.raises(ValueError,match='does not match'):
        resume(checkpoint,tmp_path/'wrong_data','s',exclude=[],original_raw=wrong)
    assert not (tmp_path/'missing').exists() and not (tmp_path/'wrong').exists()
