import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import mne
import numpy as np
import pytest
from mne.utils import object_diff
from threadpoolctl import threadpool_limits
from eegproc.mne_asr import ASR, ASRConfig, clean_asr_raw
from test_pipeline import fixture


@pytest.fixture(autouse=True)
def limit_threads():
    with threadpool_limits(limits=1):
        yield


@pytest.mark.parametrize('clock',[True,False])
def test_native_raw_roundtrip_and_manual_bad(clock,tmp_path):
    raw=fixture(clock).crop(1,38);raw.info['bads']=['F3']
    raw.info['subject_info']=dict(id=42,his_id='native-ASR')
    raw.info['description']='native test';raw.info['experimenter']='manual operator'
    raw.annotations.append(raw.first_time+15,.25,'BAD_scoped',ch_names=[('F4',)],extras=[{'source':'manual'}])
    # Extra scoped BAD splits the input; long spans run, short spans stay intact.
    original=raw.copy();out,diag=clean_asr_raw(raw)
    assert object_diff(out.info,original.info)==''
    assert out.annotations==original.annotations
    assert out.first_samp==raw.first_samp and out.n_times==raw.n_times
    np.testing.assert_array_equal(raw.get_data(),original.get_data())
    np.testing.assert_array_equal(out.get_data(picks=['F3','EOG','STI']),raw.get_data(picks=['F3','EOG','STI']))
    json.dumps(diag,allow_nan=False)
    out.save(tmp_path/'native_raw.fif',fmt='double',overwrite=True,verbose=False)
    reread=mne.io.read_raw_fif(tmp_path/'native_raw.fif',preload=True,verbose=False)
    np.testing.assert_array_equal(reread.get_data(),out.get_data())
    assert reread.annotations.extras==out.annotations.extras
    assert list(reread.annotations.ch_names)==list(out.annotations.ch_names)
    assert reread.info['subject_info']==out.info['subject_info']
    assert reread.first_samp==out.first_samp and reread.info['meas_date']==out.info['meas_date']


def test_processed_segment_metadata_and_input_are_preserved():
    raw=fixture();raw.info['bads']=['F3'];before=raw.copy()
    out,diag=clean_asr_raw(raw)
    assert any(r['status']=='processed' for r in diag['segments'])
    assert object_diff(out.info,before.info)=='' and out.annotations==before.annotations
    np.testing.assert_array_equal(out.get_data(picks=['F3','EOG','STI']),raw.get_data(picks=['F3','EOG','STI']))
    np.testing.assert_array_equal(out.get_data()[:,:11*256],raw.get_data()[:,:11*256])
    np.testing.assert_array_equal(raw.get_data(),before.get_data())
    json.dumps(diag,allow_nan=False)


def test_reusable_estimator_does_not_carry_state_and_maps_channel_order():
    raw=fixture();raw.set_annotations(mne.Annotations([],[],[]))
    model=ASR().fit(raw);before=raw.get_data().copy()
    first=model.transform(raw);second=model.transform(raw)
    np.testing.assert_array_equal(first.get_data(),second.get_data())
    np.testing.assert_array_equal(raw.get_data(),before)
    shuffled=raw.copy().reorder_channels(raw.ch_names[::-1])
    converted=model.transform(shuffled).reorder_channels(raw.ch_names)
    np.testing.assert_array_equal(converted.get_data(),first.get_data())
    # Simultaneous transforms use private copies of calibration/filter state.
    with ThreadPoolExecutor(max_workers=2) as pool:
        concurrent=list(pool.map(model.transform,[raw,raw]))
    for item in concurrent:np.testing.assert_array_equal(item.get_data(),first.get_data())


def test_reference_excludes_bad_and_checks_transfer_contract():
    raw=fixture();model=ASR().fit(raw)
    assert not model.calibration_mask_[10*256:11*256].any()
    with pytest.raises(ValueError,match='Sampling rate'):
        model.transform(raw.copy().resample(128,verbose=False))
    modified=raw.copy();modified.info['chs'][0]['loc'][0]+=.01
    with pytest.raises(ValueError,match='geometry'):model.transform(modified)
    modified=raw.copy();modified.info['bads']=['Fp1']
    with pytest.raises(ValueError,match='usable EEG'):model.transform(modified)
    modified=raw.copy().set_eeg_reference('average',projection=False,verbose=False)
    with pytest.raises(ValueError,match='Reference'):model.transform(modified)
    broken=raw.copy();broken._data[0,20*256]=np.nan
    with pytest.raises(ValueError,match='finite'):model.fit(broken)
    with pytest.raises(RuntimeError,match='fit'):model.transform(raw)


def test_discontinuities_prevent_cross_segment_calibration_and_processing():
    a=fixture();a.set_annotations(mne.Annotations([],[],[]))
    raw=mne.concatenate_raws([a.copy(),a.copy()],verbose=False)
    raw.set_annotations(mne.Annotations([30,40],[.5,0],['BAD_manual','EDGE boundary']))
    changed=raw.copy();changed._data[:12,41*256:]*=2
    one,report=clean_asr_raw(raw);two,_=clean_asr_raw(changed)
    np.testing.assert_array_equal(one.get_data()[:,:30*256],two.get_data()[:,:30*256])
    np.testing.assert_array_equal(one.get_data()[:,30*256:40*256+1],raw.get_data()[:,30*256:40*256+1])
    assert report['existing_bad_and_boundary_samples_excluded']==129


@pytest.mark.parametrize('config',[ASRConfig(cutoff=0),ASRConfig(overlap=1),ASRConfig(max_dimensions=1),
    ASRConfig(step_size=2.5),ASRConfig(reference_tolerances=(0,5.5))])
def test_invalid_parameters_fail_before_processing(config):
    with pytest.raises(ValueError):ASR(config=config)


def test_numerical_failure_never_returns_changed_data(monkeypatch):
    import eegproc.mne_asr.api as api
    raw=fixture();raw.set_annotations(mne.Annotations([],[],[]));before=raw.get_data().copy()
    model=ASR().fit(raw)
    def explode(x,*args,**kwargs):return x*1000,{'diagnostics':{}}
    monkeypatch.setattr(api,'asr_process',explode)
    with pytest.raises(FloatingPointError,match='numerical instability'):model.transform(raw)
    np.testing.assert_array_equal(raw.get_data(),before)


def test_no_calibration_fallback_for_unusable_input():
    raw=fixture();raw._data[0]=0
    with pytest.raises(ValueError,match='Flat reference'):ASR().fit(raw)
    short=fixture().crop(0,5)
    with pytest.raises(ValueError,match='Insufficient'):ASR().fit(short)
    output,report=clean_asr_raw(short)
    assert report['quality_flags'] and report['calibration_retained_samples']==0
    np.testing.assert_array_equal(output.get_data(),short.get_data())


def test_import_and_real_execution_without_eegprep_or_asrpy():
    common=Path(__file__).resolve().parents[1]
    code='''
import sys,importlib.abc
sys.path.insert(0,sys.argv[1])
class Block(importlib.abc.MetaPathFinder):
 def find_spec(self,name,path=None,target=None):
  if name.split('.')[0] in ('eegprep','asrpy'):raise ImportError('Forbidden dependency: '+name)
sys.meta_path.insert(0,Block())
import numpy as np,mne
from eegproc.mne_asr import clean_asr_raw
x=np.random.default_rng(21).normal(size=(4,8192))*1e-6
raw=mne.io.RawArray(x,mne.create_info(['A','B','C','D'],256,'eeg'),verbose=False)
out,report=clean_asr_raw(raw)
assert out.n_times==raw.n_times and report['calibration_retained_samples']>0
assert not any(n.split('.')[0] in ('eegprep','asrpy') for n in sys.modules)
print('independent ASR passed')
'''
    result=subprocess.run([sys.executable,'-X','utf8','-I','-c',code,str(common)],capture_output=True,text=True,encoding='utf8',errors='replace',timeout=60)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'independent ASR passed' in result.stdout


def test_native_backend_pipeline_epochs_and_optional_package_metadata(tmp_path,monkeypatch):
    import eegproc.engine as pipeline
    from eegproc.settings import config_for
    from importlib.metadata import PackageNotFoundError
    from eegproc.epoch_export import make_strict_epochs
    original_version=pipeline.version
    def version(name):
        if name=='eegprep':raise PackageNotFoundError(name)
        return original_version(name)
    import eegproc.engine as engine
    monkeypatch.setattr(engine,'version',version)
    raw=fixture();events=np.array([[raw.first_samp+4*256,0,1],[raw.first_samp+10*256,0,1],[raw.first_samp+20*256,0,1]])
    out,report,_=pipeline.preprocess_raw(raw,tmp_path,'standard',config=config_for(asr_backend='mne_native',detect_ransac=False))
    ep,qc=make_strict_epochs(out,raw,events,{'target':1},global_bads=report['bad_channels'])
    assert events[1,0] not in ep.events[:,0]
    assert any('BAD_manual' in r['drop_reasons'] for r in qc['records'])
    assert report['packages']['eegprep'] is None
    reread=mne.io.read_raw_fif(tmp_path/'standard_cont_raw.fif',preload=True,verbose=False)
    np.testing.assert_array_equal(reread.get_data(picks=['EOG','STI']),raw.get_data(picks=['EOG','STI']))
    assert reread.first_samp==raw.first_samp and reread.info['meas_date']==raw.info['meas_date']
    assert 'BAD_manual' in reread.annotations.description
