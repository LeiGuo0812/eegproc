"""Regression tests for opt-in P13 epochs and annotation provenance."""
from datetime import datetime, timezone
import json
import sys
import mne
import numpy as np
import pytest
from eegproc.epochs import EpochConfig
from eegproc.epoch_export import make_strict_epochs


def example(clock):
    sf=256.;t=np.arange(20*256)/sf
    raw=mne.io.RawArray(np.tile(5e-6*np.sin(2*np.pi*10*t),(8,1)),
        mne.create_info([f'E{i}' for i in range(8)],sf,'eeg'),first_samp=4096,verbose=False)
    if clock:raw.set_meas_date(datetime(2020,1,1,tzinfo=timezone.utc))
    raw.set_annotations(mne.Annotations([4.,7.],[.3,.3],['BAD_manual','BAD_residual']))
    clean=raw.copy()
    clean.annotations.append(clean.first_time+1.7,1.2,'BAD_residual')
    clean.annotations.append(clean.first_time+13.,.3,'BAD_manual_after_cleaning')
    clean._data[:,16*256:16*256+40]+=500e-6*np.sin(np.arange(40))
    events=np.column_stack([raw.first_samp+np.array([2,4,7,10,13,16])*256,np.zeros(6,int),np.ones(6,int)])
    return raw,clean,events


@pytest.mark.parametrize('clock',[False,True])
def test_input_bad_and_added_manual_survive_with_complete_audit(clock,tmp_path):
    raw,clean,events=example(clock);before=clean.get_data().copy();ann=clean.annotations.copy()
    ep,q=make_strict_epochs(clean,raw,events,{'target':1},save_path=tmp_path,subject='p13')
    assert ep.selection.tolist()==[0,3]
    assert len(q['records'])==6
    assert q['records'][1]['drop_reasons']==['BAD_manual']
    assert q['records'][2]['drop_reasons']==['BAD_residual']
    assert q['records'][4]['drop_reasons']==['BAD_manual_after_cleaning']
    assert q['records'][5]['drop_reasons']==['BALANCED_RESIDUAL']
    assert q['newly_generated_residual_annotations_ignored']==1
    assert q['input_BAD_annotation_count']==2 and q['repaired_epochs']==0
    assert q['condition_retention']['1']==dict(input=6,eligible=3,retained=2)
    np.testing.assert_array_equal(clean.get_data(),before)
    assert clean.annotations==ann
    reread=mne.read_epochs(tmp_path/'p13_clean-epo.fif',preload=True,verbose=False)
    np.testing.assert_array_equal(reread.selection,ep.selection)
    np.testing.assert_array_equal(reread.get_data(),ep.get_data())
    assert reread.drop_log==ep.drop_log


def test_annotations_option_matches_ordinary_mne():
    raw,clean,events=example(False)
    ep,q=make_strict_epochs(clean,raw,events,None,annotation_policy='annotations')
    ordinary=mne.Epochs(clean,events,tmin=-.2,tmax=1.,baseline=(None,0),preload=True,verbose=False)
    np.testing.assert_array_equal(ep.selection,ordinary.selection)
    np.testing.assert_array_equal(ep.get_data(),ordinary.get_data())
    assert q['newly_generated_residual_annotations_ignored']==0
    assert not q['event_window_qc_enabled']


def test_all_bad_saves_complete_qc_and_no_epochs(tmp_path):
    raw,clean,events=example(False)
    make_strict_epochs(clean,raw,events,None,save_path=tmp_path)
    assert (tmp_path/'subject_clean-epo.fif').is_file()
    raw.annotations.append(raw.first_time,20,'BAD_whole_record')
    ep,q=make_strict_epochs(clean,raw,events,None,save_path=tmp_path)
    assert len(ep)==0 and q['status']=='review_required'
    assert len(q['records'])==6 and all(not r['retained'] for r in q['records'])
    assert (tmp_path/'subject_epoch_qc.json').is_file()
    assert not (tmp_path/'subject_clean-epo.fif').exists()


def test_grid_mismatch_rejected():
    raw,clean,events=example(False)
    with pytest.raises(ValueError,match='sample grid'):
        make_strict_epochs(clean.copy().crop(tmin=1),raw,events,None)


def test_rest_cli_enables_epochs_without_changing_continuous_config(monkeypatch,tmp_path):
    import eegproc.cli
    import eegproc.engine as pipeline
    raw,clean,events=example(False)
    raw.annotations.append(raw.first_time+2.,0.,'target')
    clean.annotations.append(clean.first_time+2.,0.,'target')
    inp=tmp_path/'input_raw.fif';raw.save(inp,fmt='double',overwrite=True,verbose=False)
    calls=[]
    def fake(raw,out,subject,**kw):
        calls.append(kw)
        return clean,dict(bad_channels=[],quality_flags=[],status='completed',
            outputs={'manifest':str(tmp_path/'p13_report.html')}),None
    monkeypatch.setattr(pipeline,'preprocess_raw',fake)
    monkeypatch.setattr(sys,'argv',['balanced','--input-fif',str(inp),'--save-path',str(tmp_path),
        '--subject','p13','--config','configs/rest.json','--epochs','--event-names','target'])
    eegproc.cli.main()
    cfg=calls[0]['config']
    assert cfg.purpose=='rest' and cfg.asr_cutoff==20 and cfg.highpass==.5
    assert cfg.epoch_mode=='events' and cfg.event_names==('target',)
    assert calls[0]['events'] is None


@pytest.mark.parametrize('source',['stim','annotations'])
def test_explicit_event_source_does_not_read_automatic_sidecar(source,monkeypatch,tmp_path):
    import eegproc.cli
    import eegproc.engine as pipeline
    raw,clean,events=example(False)
    inp=tmp_path/'input_raw.fif';raw.save(inp,fmt='double',overwrite=True,verbose=False)
    inp.with_suffix('.events.json').write_text(json.dumps({'events':events.tolist(),'event_id':{'sidecar':1}}))
    calls=[]
    def fake(raw,out,subject,**kw):
        calls.append(kw)
        return clean,dict(quality_flags=[],status='completed',outputs={}),None
    monkeypatch.setattr(pipeline,'preprocess_raw',fake)
    eegproc.cli.main(['--input-fif',str(inp),'--save-path',str(tmp_path),'--subject','events',
                      '--epochs','--event-source',source])
    assert calls[0]['events'] is None
    assert calls[0]['config'].event_source==source
