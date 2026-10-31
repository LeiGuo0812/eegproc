"""FIF-persistent annotation sources, without recording identity registries."""
from datetime import datetime, timezone

import mne
import numpy as np
import pytest
from mne.utils import object_diff

from eegproc import PipelineConfig
from eegproc.epoch_export import make_strict_epochs
from eegproc.epoch_metadata import (
    AUTOMATIC_RESIDUAL, ORIGIN_KEY, add_residual_annotations,
    prepare_annotations, read_metadata, save_epoch_metadata,
)
from eegproc.epoching import build_epochs
from eegproc.epochs import _restore_input_annotations


def recording(clock=False):
    sfreq=256.
    names=['Fp1','Fp2','F3','F4','C3','C4','P3','P4','Pz','ECG','STI']
    signal=np.tile(5e-6*np.sin(2*np.pi*10*np.arange(20*256)/sfreq),(len(names),1))
    signal[-1]=0
    raw=mne.io.RawArray(signal,mne.create_info(names,sfreq,['eeg']*9+['ecg','stim']),
                        first_samp=4096,verbose=False)
    raw.set_montage('standard_1020',verbose=False)
    if clock:raw.set_meas_date(datetime(2020,1,1,tzinfo=timezone.utc))
    raw.info['description']='Keep this original description unchanged.'
    raw.set_annotations(mne.Annotations([4.,7.],[.3,.3],['BAD_manual','BAD_residual'],
        ch_names=[('F3',),()],extras=[{'source':'human'}, {'source':'input'}]))
    events=np.column_stack([raw.first_samp+np.array([2,4,7,10,13,16])*256,
                            np.zeros(6,int),np.ones(6,int)])
    return raw,events


@pytest.mark.parametrize('clock',[False,True])
def test_self_contained_epochs_equal_original_aware_path_after_fif_roundtrip(clock,tmp_path):
    original,events=recording(clock)
    clean=original.copy()
    mask=np.zeros(clean.n_times,bool);mask[round(1.7*256):round(2.9*256)]=True
    add_residual_annotations(clean,mask)
    clean.annotations.append(clean.first_time+13.,.3,'BAD_manual_after_cleaning')
    clean._data[:9,16*256:16*256+40]+=500e-6*np.sin(np.arange(40))
    config=PipelineConfig(purpose='erp',epoch_mode='events')
    save_epoch_metadata(clean,config,['Pz'],tmp_path/'subject_report.html','subject')
    expected,qc=make_strict_epochs(clean,original,events,{'target':1},global_bads=['Pz'])
    before=clean.get_data().copy();info=clean.info.copy();annotations=clean.annotations.copy()
    fname=tmp_path/'subject_cont_raw.fif'
    clean.save(fname,fmt='double',overwrite=False,verbose=False)
    restored=mne.io.read_raw_fif(fname,preload=False,verbose=False)
    actual,standalone=build_epochs(restored,config,events,{'target':1})
    np.testing.assert_array_equal(actual.selection,expected.selection)
    np.testing.assert_array_equal(actual.get_data(),expected.get_data())
    assert actual.drop_log==expected.drop_log
    assert standalone['condition_retention']==qc['condition_retention']
    assert standalone['newly_generated_residual_annotations_ignored']==1
    assert 'Pz' not in standalone['qc_channels']
    assert restored.first_samp==clean.first_samp
    assert restored.info['meas_date']==clean.info['meas_date']
    assert restored.annotations.orig_time==clean.annotations.orig_time
    assert restored.get_channel_types()==clean.get_channel_types()
    assert [a['description'] for a in restored.annotations]==[a['description'] for a in clean.annotations]
    assert [a['ch_names'] for a in restored.annotations]==[a['ch_names'] for a in clean.annotations]
    assert [dict(a['extras']) for a in restored.annotations]==[dict(a['extras']) for a in clean.annotations]
    np.testing.assert_array_equal(clean.get_data(),before)
    assert object_diff(clean.info,info)=='' and clean.annotations==annotations
    restored.close()


def test_metadata_preserves_description_and_replaces_only_its_own_block(tmp_path):
    raw,_=recording()
    config=PipelineConfig(purpose='erp',task_name='oddball')
    save_epoch_metadata(raw,config,['Pz'],tmp_path/'one_report.html','one')
    save_epoch_metadata(raw,config,['F3'],tmp_path/'two_report.html','two')
    assert raw.info['description'].startswith('Keep this original description unchanged.')
    assert raw.info['description'].count('[eegproc-epoch]')==1
    metadata=read_metadata(raw)
    assert metadata['global_bads']==['F3'] and metadata['subject']=='two'
    assert metadata['parameters']['task_name']=='oddball'
    assert not {'uuid','hash','identity','run_id'} & set(metadata)


def test_old_and_new_manual_bad_are_hard_exclusions_without_original_raw():
    raw,events=recording()
    raw.annotations.append(raw.first_time+2.,.1,'BAD_residual')
    raw.annotations.append(raw.first_time+13.,.1,'BAD_manual_after_cleaning')
    actual,qc=make_strict_epochs(raw,None,events,{'target':1})
    assert actual.selection.tolist()==[3,5]
    assert qc['newly_generated_residual_annotations_ignored']==0
    assert actual.drop_log[0]==('BAD_residual',)
    assert actual.drop_log[2]==('BAD_residual',)
    assert actual.drop_log[4]==('BAD_manual_after_cleaning',)


def test_deliberately_reprocessed_automatic_bad_becomes_protected_input():
    raw,events=recording()
    raw.annotations.append(raw.first_time+2.,.1,'BAD_residual',extras=[{ORIGIN_KEY:AUTOMATIC_RESIDUAL,'user':'unchanged'}])
    before=raw.copy()
    current=raw.copy();prepare_annotations(current)
    actual,qc=make_strict_epochs(current,None,events,{'target':1})
    assert 0 not in actual.selection and qc['newly_generated_residual_annotations_ignored']==0
    source=next(a for a in current.annotations if a.get('extras',{}).get('user')=='unchanged')
    assert source['extras'][ORIGIN_KEY]=='input'
    assert source['extras']['user']=='unchanged'
    assert raw.annotations==before.annotations


def test_repair_annotation_base_keeps_postprocessing_manual_bad():
    original,_=recording()
    clean=original.copy()
    clean.annotations.append(clean.first_time+13.,.3,'BAD_manual_after_cleaning')
    clean.annotations.append(clean.first_time+2.,.3,'BAD_residual',extras=[{ORIGIN_KEY:AUTOMATIC_RESIDUAL}])
    base=_restore_input_annotations(clean,original)
    assert 'BAD_manual_after_cleaning' in base.annotations.description
    assert len(base.annotations)==len(original.annotations)+1
    assert len(_restore_input_annotations(clean,None).annotations)==len(base.annotations)
