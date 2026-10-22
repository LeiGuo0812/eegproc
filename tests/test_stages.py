"""Regression contracts for stages, original-rule alignment, and human ICA decisions."""
from dataclasses import replace
import json
from pathlib import Path
import mne
import numpy as np
import pytest
from eeg_pipeline.settings import config_for
from eeg_pipeline.configuration import resolve_config
from eeg_pipeline.ica import choose_components,validate_exclude
from eeg_pipeline.api import run,resume
from eeg_pipeline.review import resume_ica
from test_pipeline import fixture


def test_presets_and_override_precedence():
    p=config_for();old=json.loads(Path('configs/rest.json').read_text())
    for key,value in old.items():
        actual=getattr(p,key)
        assert (list(actual) if isinstance(actual,tuple) else actual) == value
    c=resolve_config(preset='eeglab',purpose='erp',lowpass=40.)
    assert c.highpass==.5 and c.lowpass==40 and c.training_highpass==.5
    assert c.ica_rule=='class_max' and c.filter_order==15000
    assert not c.interpolate_before_asr and c.final_interpolation and c.final_reference
    assert c.filter_position=="after_reference" and c.preset=="eeglab"
    assert c.asr_cutoff==20 and c.ica_max_iter==4096
    missing=resolve_config(ica_mode='manual')
    assert missing.ica_mode=='manual' and missing.ica_exclude==()
    assert any(r['field']=='ica_exclude' and 'keep all' in r['reason']
               for r in missing.adjustments)
    assert resolve_config(ica_mode='manual',ica_exclude=[]).ica_exclude==()


def test_legacy_selection_handles_ties_heart_and_other():
    p=np.array([[.1,.1,.3,.1,.1,.1,.2], [.1,.1,.1,.4,.1,.1,.1],
        [.5,.5,0,0,0,0,0], [.4,0,0,0,.3,.3,0], [0,0,0,0,0,0,1]])
    assert choose_components(p,config_for(preset='eeglab'))==[0,2]
    assert choose_components(p,config_for())==[]


@pytest.mark.parametrize('selection',[[-1],[0,0],[1.2],[True],[99],None])
def test_invalid_manual_selection_never_applies(selection):
    with pytest.raises(ValueError):validate_exclude(selection,3)


@pytest.fixture
def review_run(tmp_path,monkeypatch):
    import mne_icalabel.iclabel as labels
    # Real ICA decomposition; deterministic class assignment isolates the resume contract.
    def eye_first(training,model,inplace=True):
        p=np.zeros((model.n_components_,7));p[:,0]=1.;p[0]=[.01,.01,.94,.01,.01,.01,.01];return p
    monkeypatch.setattr(labels,'iclabel_label_components',eye_first)
    raw=fixture(False)
    cfg=config_for(asr_cutoff=None,line_frequency=None,channel_method='off',
        ica_mode='review',epoch_mode='events')
    result=run(raw,tmp_path/'review','review',config=cfg)
    return raw,cfg,result


def test_review_resume_uses_same_model_preserves_metadata_and_manual_override(review_run,tmp_path,monkeypatch):
    raw,cfg,result=review_run
    assert result.raw is None and result.status=='awaiting_ica_review'
    assert result.report['ica']['automatic_proposal_0based']==[0]
    assert result.report['ica']['removed_components_0based']==[]
    assert not list((tmp_path/'review').glob('*_cont_raw.fif'))
    assert not (tmp_path/'review/review_stages').exists()
    checkpoint=Path(result.outputs['checkpoint'])
    original_hash=checkpoint.read_bytes()
    import eeg_pipeline.engine as engine
    def no_refit(*a,**kw):raise AssertionError('Resume must never refit ICA')
    monkeypatch.setattr(engine,'fit_ica',no_refit)
    resumed=resume(checkpoint,tmp_path/'resumed','resumed',exclude=[],reviewer='test',reason='keep all',original_raw=raw)
    assert resumed.report['ica']['decision_status']=='manual'
    assert resumed.report['ica']['removed_components_0based']==[]
    assert not resumed.report['parent_run']['fit_repeated']
    assert checkpoint.read_bytes()==original_hash
    assert resumed.raw.first_samp==raw.first_samp and resumed.raw.annotations==raw.annotations
    np.testing.assert_array_equal(resumed.raw.get_data(picks=['EOG','STI']),raw.get_data(picks=['EOG','STI']))
    assert resumed.report['epochs']['retained_epochs']==2
    assert not resumed.report['visualizations']['errors']
    html=Path(resumed.outputs['quality_report']).read_text(encoding='utf8')
    assert 'Automatic' in html and 'Final' in html and 'keep all' in html
    assert 'automatic_proposal' in html and 'decision_status' in html
    assert resumed.report['report_audit']['tables']=={}


def test_wrong_unconfirmed_and_changed_checkpoint_are_rejected(review_run,tmp_path):
    _,_,result=review_run
    checkpoint=Path(result.outputs['checkpoint']);template=dict(result.report['ica_checkpoint']['selection_template'])
    selection=tmp_path/'decision.json';selection.write_text(json.dumps(template))
    with pytest.raises(ValueError,match='reviewed=true'):resume_ica(checkpoint,tmp_path/'out',selection_json=selection)
    template.update(reviewed=True,checkpoint_id='wrong');selection.write_text(json.dumps(template))
    with pytest.raises(ValueError,match='different'):resume_ica(checkpoint,tmp_path/'out',selection_json=selection)
    payload=json.loads(checkpoint.read_text());path=checkpoint.parent.parent/payload['artifacts']['pre_ica']
    path.write_bytes(path.read_bytes()+b'changed')
    with pytest.raises(ValueError,match='hash mismatch'):resume_ica(checkpoint,tmp_path/'out',exclude=[])


def test_all_disabled_honors_input_bads_and_stage_defaults(tmp_path):
    raw=fixture();raw.info['bads']=['Fp1'];before=raw.get_data().copy()
    cfg=config_for(filter_method='off',line_method='off',channel_method='off',asr_cutoff=None,
        reference='unchanged',interpolate_bads=False,ica_enabled=False,residual_qc=False)
    result=run(raw,tmp_path,'none',config=cfg)
    np.testing.assert_array_equal(result.raw.get_data(),before)
    assert result.raw.info['bads']==['Fp1'] and result.raw.annotations==raw.annotations
    assert result.report['stage_files']==[]
    assert 'ica' not in result.outputs
    for record in result.report['stage_files']:assert Path(record['path']).is_file()


def test_eeglab_fir_port_and_bad_boundary_protection():
    pytest.importorskip('eegprep')
    from eeg_pipeline.backends import apply_filter
    from eegprep import pop_eegfiltnew
    from eeg_pipeline.backends import eegprep_input
    raw=fixture().pick('eeg');before=raw.get_data().copy()
    c=config_for(preset='eeglab',filter_order=2000)
    apply_filter(raw,.5,100,c)
    np.testing.assert_array_equal(raw.get_data()[:,2560:2816],before[:,2560:2816])
    # A continuous segment matches the port's direct convolution, validating FFT acceleration.
    direct=eegprep_input(raw,before[:,:2560])
    direct=pop_eegfiltnew(direct,locutoff=.5,filtorder=2000,gui=False)
    direct=pop_eegfiltnew(direct,hicutoff=100,filtorder=2000,gui=False)
    np.testing.assert_allclose(raw.get_data()[:,:2560],direct['data']/1e6,atol=1e-18,rtol=1e-10)
