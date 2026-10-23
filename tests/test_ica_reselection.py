"""Reselection always applies a fresh list to the same untouched pre-ICA data."""
import json
from pathlib import Path
import re

import mne
import numpy as np
import pytest

from eegproc import resolve_config, run, resume
from eegproc.report_provenance import file_hash
from test_pipeline import fixture


def components(page):
    return json.loads(re.search(r'<script id="component-data" type="application/json">(.*?)</script>',
        Path(page).read_text(encoding='utf8'), re.S).group(1))


@pytest.mark.parametrize("purpose,mode", [("rest","auto"), ("erp","manual")])
def test_completed_run_can_restore_and_reselect_without_refitting(purpose,mode,tmp_path,monkeypatch):
    import mne_icalabel.iclabel as labels
    import eegproc.engine as engine
    def eye_first(training,model,inplace=True):
        p=np.zeros((model.n_components_,7));p[:,0]=1.
        p[0]=[.01,.01,.94,.01,.01,.01,.01]
        return p
    monkeypatch.setattr(labels,'iclabel_label_components',eye_first)
    raw=fixture(False);input_data=raw.get_data().copy()
    config=resolve_config(purpose=purpose,ica_mode=mode,**({'ica_exclude':[0]} if mode=='manual' else {}),
        channel_method='off',line_frequency=None,epoch_mode='events',residual_qc=False)
    result=run(raw,tmp_path/'automatic','sample',config=config)
    assert result.report['config']['asr_cutoff']==20
    assert result.report['ica']['removed_components_0based']==[0]
    checkpoint=Path(result.outputs['checkpoint'])
    checkpoint_bytes=checkpoint.read_bytes()
    state=json.loads(checkpoint_bytes)
    assert not state['applied'] and not state['report']['ica']['applied']
    assert state['report']['ica']['removed_components_0based']==[]
    for record in state['files']:
        assert file_hash(checkpoint.parent.parent/record['path'])==record['sha256']
    original_model=mne.preprocessing.read_ica(result.outputs['decomposition'],verbose=False)
    final_model=mne.preprocessing.read_ica(result.outputs['ica'],verbose=False)
    assert original_model.exclude==[] and final_model.exclude==[0]
    pre=mne.io.read_raw_fif(result.outputs['pre_ica'],preload=True,verbose=False)
    assert pre.first_samp==raw.first_samp and pre.annotations==raw.annotations
    assert pre.ch_names==raw.ch_names
    assert np.linalg.norm(result.raw.get_data(picks='eeg')-pre.get_data(picks='eeg'))>1e-8
    def never(*args,**kwargs):raise AssertionError('Earlier stages and ICA fitting must not be repeated')
    monkeypatch.setattr(engine,'fit_ica',never)
    monkeypatch.setattr(engine,'prepare_signals',never)
    selection=components(result.outputs['quality_report'])['selection']
    assert selection['exclude']==[0]
    selection.update(reviewed=True,exclude=[],reviewer='Human',reason='Restore IC 0')
    choice=tmp_path/'selection.json';choice.write_text(json.dumps(selection),encoding='utf8')
    restored=resume(checkpoint,tmp_path/'restored','sample',selection_json=choice,original_raw=raw)
    np.testing.assert_allclose(restored.raw.get_data(picks='eeg'),pre.get_data(picks='eeg'),rtol=1e-10,atol=1e-15)
    np.testing.assert_array_equal(restored.raw.get_data(picks=['EOG','STI']),input_data[-2:])
    assert restored.raw.annotations==raw.annotations and restored.raw.first_samp==raw.first_samp
    assert restored.report['epochs']['retained_epochs']==2
    assert not restored.report['parent_run']['fit_repeated']
    assert restored.outputs['checkpoint']==str(checkpoint)
    view=components(restored.outputs['quality_report'])
    assert view['selection']['exclude']==[] and view['automatic_proposal']==[0]
    assert all(row['exists'] for row in restored.report['report_audit']['data_files'])
    assert any(row.get('reused') and not row['produced_this_run'] for row in restored.report['report_audit']['data_files'])
    assert not (tmp_path/'restored/sample_ica_review').exists()
    changed=resume(restored.outputs['checkpoint'],tmp_path/'changed','sample',exclude=[1],original_raw=raw)
    expected=original_model.apply(pre.copy(),exclude=[1],verbose=False)
    expected.set_eeg_reference('average',projection=False,verbose=False)
    np.testing.assert_allclose(changed.raw.get_data(picks='eeg'),expected.get_data(picks='eeg'),rtol=1e-10,atol=1e-15)
    assert changed.report['ica']['removed_components_0based']==[1]
    assert changed.report['ica_diagnostics']==result.report['ica_diagnostics']
    assert all(v is not False for v in changed.report['metadata_audit']['checks'].values())
    assert checkpoint.read_bytes()==checkpoint_bytes
    for record in state['files']:
        assert file_hash(checkpoint.parent.parent/record['path'])==record['sha256']
    np.testing.assert_array_equal(raw.get_data(),input_data)
    with pytest.raises(ValueError,match='separate output'):
        resume(checkpoint,checkpoint.parent,'decomposition',exclude=[])
