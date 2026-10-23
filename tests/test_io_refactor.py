"""I/O safety: collision rejection, staged rollback, split FIFs and report errors."""
import json
from pathlib import Path

import mne
import numpy as np
import pytest

from eegproc.storage import OutputPlan, OutputStore, _commit, atomic_save_raw, atomic_write_json


def small_raw(n_times=1024, n_channels=8):
    names=['Fp1','Fp2','F3','F4','C3','C4','P3','P4'][:n_channels]
    values=np.random.default_rng(17).standard_normal((n_channels,n_times))*1e-6
    raw=mne.io.RawArray(values,mne.create_info(names,256.,'eeg'),first_samp=4096,verbose=False)
    raw.set_montage('standard_1020',verbose=False)
    raw.set_annotations(mne.Annotations([.25],[.125],['BAD_manual']))
    return raw


@pytest.mark.parametrize('name',[
    'subject_cont_raw.fif','subject_cont_raw-1.fif','subject_clean-epo.fif',
    'subject_clean-epo-1.fif','subject-ica.fif','subject_report.html','subject_ica_review',
])
def test_output_family_collision_preserves_existing_artifact(tmp_path,name):
    target=tmp_path/name
    if name.endswith('_review'):
        target.mkdir();existing=target/'checkpoint.json';existing.write_bytes(b'old checkpoint')
    else:
        existing=target;existing.write_bytes(b'old artifact')
    before=existing.read_bytes()
    with pytest.raises(FileExistsError,match='Output already exists'):
        OutputPlan(tmp_path,'subject').preflight()
    assert existing.read_bytes()==before
    assert not list(tmp_path.glob('.eeg-write-*'))


def test_preflight_protects_input_path_and_does_not_process(tmp_path,monkeypatch):
    import eegproc.engine as engine
    raw=small_raw()
    source=tmp_path/'subject_cont_raw.fif'
    raw.save(source,fmt='double',verbose=False)
    original=source.read_bytes()
    loaded=mne.io.read_raw_fif(source,preload=False,verbose=False)
    def forbidden(*args,**kwargs):
        raise AssertionError('Input collision must be detected before signal processing')
    monkeypatch.setattr(engine,'prepare_signals',forbidden)
    with pytest.raises(ValueError,match='overlaps an input'):
        engine.preprocess_raw(loaded,tmp_path,'subject')
    assert source.read_bytes()==original
    assert not (tmp_path/'subject_report.html').exists()


def test_existing_output_stops_run_without_new_report(tmp_path,monkeypatch):
    import eegproc.engine as engine
    existing=tmp_path/'subject_cont_raw.fif';existing.write_bytes(b'previous result')
    def forbidden(*args,**kwargs):
        raise AssertionError('Output collision must precede signal processing')
    monkeypatch.setattr(engine,'prepare_signals',forbidden)
    with pytest.raises(FileExistsError,match='Output already exists'):
        engine.preprocess_raw(small_raw(),tmp_path,'subject')
    assert existing.read_bytes()==b'previous result'
    assert sorted(p.name for p in tmp_path.iterdir())==['subject_cont_raw.fif']


def test_staged_save_failure_preserves_input_and_removes_only_temporary_files(tmp_path,monkeypatch):
    source=tmp_path/'input_raw.fif';raw=small_raw()
    raw.save(source,fmt='double',verbose=False)
    original=source.read_bytes()
    existing=tmp_path/'other_report.html';existing.write_bytes(b'existing report')
    def incomplete(self,path,**kwargs):
        Path(path).write_bytes(b'incomplete new data')
        raise OSError('controlled disk failure')
    monkeypatch.setattr(mne.io.BaseRaw,'save',incomplete)
    with pytest.raises(OSError,match='disk failure'):
        atomic_save_raw(raw,tmp_path/'new_cont_raw.fif')
    assert source.read_bytes()==original
    assert existing.read_bytes()==b'existing report'
    assert not (tmp_path/'new_cont_raw.fif').exists()
    assert not list(tmp_path.glob('.eeg-write-*'))


def test_commit_failure_rolls_back_new_family_without_touching_existing(tmp_path,monkeypatch):
    import eegproc.storage as storage
    staging=tmp_path/'staging';staging.mkdir()
    files=[staging/'new_raw.fif',staging/'new_raw-1.fif']
    for file in files:file.write_bytes(b'new file')
    output=tmp_path/'out';output.mkdir()
    old=output/'old_raw.fif';old.write_bytes(b'old result')
    replace=storage.os.replace
    def fail_second(src,dst):
        if Path(src).name.endswith('-1.fif'):raise OSError('controlled second commit failure')
        return replace(src,dst)
    monkeypatch.setattr(storage.os,'replace',fail_second)
    with pytest.raises(OSError,match='second commit'):
        _commit(files,output)
    assert sorted(p.name for p in output.iterdir())==['old_raw.fif']
    assert old.read_bytes()==b'old result'


def test_commit_detects_late_collision_without_deleting_new_external_file(tmp_path,monkeypatch):
    import eegproc.storage as storage
    staging=tmp_path/'staging';staging.mkdir()
    files=[staging/'new_raw.fif',staging/'new_raw-1.fif']
    for file in files:file.write_bytes(b'new file')
    output=tmp_path/'out';output.mkdir()
    replace=storage.os.replace
    def external_writer(src,dst):
        result=replace(src,dst)
        (output/'new_raw-1.fif').write_bytes(b'external writer data')
        return result
    monkeypatch.setattr(storage.os,'replace',external_writer)
    with pytest.raises(FileExistsError):_commit(files,output)
    assert not (output/'new_raw.fif').exists()
    assert (output/'new_raw-1.fif').read_bytes()==b'external writer data'


def windows_lock_error(code):
    error=PermissionError('controlled transient Windows file lock')
    error.winerror=code
    return error


@pytest.mark.parametrize('code',[5,32,33])
def test_commit_retries_transient_windows_locks_only_with_owned_target(tmp_path,monkeypatch,code):
    import eegproc.storage as storage
    staging=tmp_path/'staging';staging.mkdir()
    source=staging/'new_raw.fif';source.write_bytes(b'complete new recording')
    output=tmp_path/'output';output.mkdir()
    replace=storage.os.replace;attempts=[];delays=[]
    def transient(src,dst):
        attempts.append((src,dst))
        if len(attempts)<3:raise windows_lock_error(code)
        return replace(src,dst)
    monkeypatch.setattr(storage.os,'replace',transient)
    monkeypatch.setattr(storage.time,'sleep',delays.append)
    assert _commit([source],output)==[output/source.name]
    assert (output/source.name).read_bytes()==b'complete new recording'
    assert len(attempts)==3 and delays==[.05,.1]


def test_commit_permanent_windows_lock_is_bounded_and_rolls_back_own_family(tmp_path,monkeypatch):
    import eegproc.storage as storage
    staging=tmp_path/'staging';staging.mkdir()
    files=[staging/'new_raw.fif',staging/'new_raw-1.fif']
    for path in files:path.write_bytes(b'new recording')
    output=tmp_path/'output';output.mkdir()
    old=output/'old.txt';old.write_bytes(b'existing data')
    replace=storage.os.replace;attempts=[];delays=[]
    def permanent(src,dst):
        if Path(src).name.endswith('-1.fif'):
            attempts.append(src);raise windows_lock_error(5)
        return replace(src,dst)
    monkeypatch.setattr(storage.os,'replace',permanent)
    monkeypatch.setattr(storage.time,'sleep',delays.append)
    with pytest.raises(PermissionError,match='transient Windows'):_commit(files,output)
    assert len(attempts)==7 and sum(delays)==pytest.approx(2.55)
    assert list(output.iterdir())==[old] and old.read_bytes()==b'existing data'


def test_commit_retry_does_not_replace_or_delete_external_change_to_reservation(tmp_path,monkeypatch):
    import eegproc.storage as storage
    staging=tmp_path/'staging';staging.mkdir()
    source=staging/'new_raw.fif';source.write_bytes(b'new recording')
    output=tmp_path/'output';output.mkdir();attempts=[]
    def external_writer(src,dst):
        attempts.append(src)
        Path(dst).write_bytes(b'other writer data')
        raise windows_lock_error(32)
    monkeypatch.setattr(storage.os,'replace',external_writer)
    monkeypatch.setattr(storage.time,'sleep',lambda delay:None)
    with pytest.raises(FileExistsError,match='Reserved output changed'):_commit([source],output)
    assert len(attempts)==1
    assert (output/source.name).read_bytes()==b'other writer data'
    assert source.read_bytes()==b'new recording'


def test_existing_checkpoint_cannot_be_overwritten(tmp_path):
    checkpoint=tmp_path/'checkpoint.json';checkpoint.write_bytes(b'old checkpoint')
    with pytest.raises(FileExistsError):atomic_write_json(checkpoint,{'new':'data'})
    assert checkpoint.read_bytes()==b'old checkpoint'
    assert not list(tmp_path.glob('.eeg-write-*'))


def test_atomic_raw_split_roundtrip_and_inventory(tmp_path,monkeypatch):
    raw=small_raw(n_times=60000)
    save=mne.io.BaseRaw.save
    def split(self,path,**kwargs):
        return save(self,path,split_size='2MB',buffer_size_sec=.5,**kwargs)
    monkeypatch.setattr(mne.io.BaseRaw,'save',split)
    report={};store=OutputStore(report)
    target=tmp_path/'subject_cont_raw.fif'
    store.save_final(raw,target)
    files=[Path(path) for path in report['final_raw_files']]
    assert len(files)>1
    assert set(files)==set(tmp_path.glob('*.fif'))
    assert {row['path'] for row in report['output_files']}=={str(path) for path in files}
    assert all(row['kind']=='raw' and row['status']=='committed' and row['bytes']>0 for row in report['output_files'])
    loaded=mne.io.read_raw_fif(target,preload=True,verbose=False)
    np.testing.assert_array_equal(loaded.get_data(),raw.get_data())
    assert loaded.first_samp==raw.first_samp and loaded.ch_names==raw.ch_names
    assert loaded.annotations==raw.annotations
    assert not list(tmp_path.glob('.eeg-write-*'))


def test_atomic_epoch_split_roundtrip_and_inventory(tmp_path,monkeypatch):
    data=np.random.default_rng(31).standard_normal((110,8,512))*1e-6
    info=small_raw().info
    events=np.column_stack([4096+np.arange(110)*512,np.zeros(110,dtype=int),1+np.arange(110)%2])
    epochs=mne.EpochsArray(data,info,events=events,event_id={'a':1,'b':2},tmin=-.2,baseline=None,verbose=False)
    save=mne.BaseEpochs.save
    def split(self,path,**kwargs):
        return save(self,path,split_size='2MB',**kwargs)
    monkeypatch.setattr(mne.BaseEpochs,'save',split)
    report={};store=OutputStore(report)
    target=tmp_path/'subject_clean-epo.fif'
    store.save_epochs(epochs,target)
    files=[Path(path) for path in report['epoch_files']]
    assert len(files)>1 and set(files)==set(tmp_path.glob('*.fif'))
    assert {row['path'] for row in report['output_files']}=={str(path) for path in files}
    loaded=mne.read_epochs(target,preload=True,verbose=False)
    np.testing.assert_array_equal(loaded.get_data(),epochs.get_data())
    np.testing.assert_array_equal(loaded.events,epochs.events)
    assert loaded.event_id==epochs.event_id and loaded.ch_names==epochs.ch_names
    assert not list(tmp_path.glob('.eeg-write-*'))


@pytest.mark.parametrize('status',['completed','review_required','awaiting_ica_review','failed'])
def test_report_failure_preserves_scientific_status_error_and_delivered_data(tmp_path,monkeypatch,status):
    import eegproc.quality_report as reporting
    raw=tmp_path/'subject_cont_raw.fif';raw.write_bytes(b'already committed recording')
    original_error={'type':'RuntimeError','message':'original processing error'} if status=='failed' else None
    report={'status':status,'outputs':{'raw':str(raw)},'config':{}}
    if original_error:report['error']=original_error.copy()
    def fail(*args,**kwargs):raise RuntimeError('controlled render failure')
    monkeypatch.setattr(reporting,'save_quality_report',fail)
    target=tmp_path/'subject_report.html'
    assert reporting.safe_report(report,target) is False
    assert report['status']==report['processing_status']==status
    assert report['report_status']=='failed'
    assert report.get('error')==original_error
    assert raw.read_bytes()==b'already committed recording'
    assert report['report_error']['message']=='controlled render failure'
    assert target.is_file() and 'Report unavailable' in target.read_text(encoding='utf8')


def test_pipeline_processing_exception_survives_render_and_fallback_write_failures(tmp_path,monkeypatch):
    import eegproc.engine as engine
    import eegproc.quality_report as reporting
    import eegproc.storage as storage
    def processing_error(*args,**kwargs):raise ValueError('original numerical failure')
    def report_error(*args,**kwargs):raise RuntimeError('plotting failure')
    def disk_error(*args,**kwargs):raise OSError('report disk failure')
    monkeypatch.setattr(engine,'prepare_signals',processing_error)
    monkeypatch.setattr(reporting,'save_quality_report',report_error)
    monkeypatch.setattr(storage,'atomic_write_text',disk_error)
    with pytest.raises(ValueError,match='original numerical failure'):
        engine.preprocess_raw(small_raw(),tmp_path,'subject')
    assert not list(tmp_path.glob('*.fif'))
