"""Preparation returns usable metadata and commits a collision-safe file family."""
import json
from pathlib import Path

import mne
import numpy as np
import pytest

from eeg_pipeline.preparation import PreparationResult,prepare_data
from eeg_pipeline.checkpoint_input import input_identity,identity_matches
from test_pipeline import fixture


def source_file(tmp_path):
    raw=fixture();raw.annotations.extras[1]['reviewer']='human'
    source=tmp_path/'source_raw.fif'
    raw.save(source,fmt='double',overwrite=False,verbose=False)
    return source


def test_preparation_raw_default_and_result_without_files(tmp_path):
    source=source_file(tmp_path)
    raw=prepare_data(source,event_id={'target':7})
    assert isinstance(raw,mne.io.BaseRaw)
    result=prepare_data(source,event_id={'target':7},return_result=True)
    assert isinstance(result,PreparationResult) and result.outputs=={}
    assert result.event_id=={'target':7}
    np.testing.assert_array_equal(result.events[:,2],[7,7])
    np.testing.assert_array_equal(result.events[:,0],[5120,9216])
    assert not result.provenance['filtering_applied']
    assert list(tmp_path.iterdir())==[source]


def test_preparation_roundtrip_metadata_and_sidecar_contract(tmp_path):
    source=source_file(tmp_path);output=tmp_path/'prepared/recording_raw.fif'
    result=prepare_data(source,output_fif=output,event_id={'target':7},return_result=True)
    reopened=mne.io.read_raw_fif(output,preload=False,verbose=False)
    assert identity_matches(input_identity(result.raw),input_identity(reopened))
    assert result.outputs['raw']==str(output)
    assert result.outputs['raw_files']==[str(output)]
    assert result.provenance['saved_raw_files']==[str(output)]
    sidecar=json.loads(output.with_suffix('.events.json').read_text())
    assert sidecar==dict(events=result.events.tolist(),event_id=result.event_id)
    assert sorted(p.name for p in output.parent.iterdir())==[
        'recording_raw.events.json','recording_raw.fif','recording_raw.preparation.json']


@pytest.mark.parametrize('collision',['raw','preparation','events','split'])
def test_preparation_preflights_every_output_and_split_family(tmp_path,collision):
    source=source_file(tmp_path);output=tmp_path/'prepared_raw.fif'
    target={'raw':output,'preparation':output.with_suffix('.preparation.json'),
            'events':output.with_suffix('.events.json'),'split':tmp_path/'prepared_raw-1.fif'}[collision]
    target.write_bytes(b'original bytes')
    with pytest.raises(FileExistsError,match='already exists'):
        prepare_data(source,output_fif=output)
    assert target.read_bytes()==b'original bytes'
    assert set(tmp_path.iterdir())=={source,target}
    with pytest.raises(ValueError,match='original input'):
        prepare_data(source,output_fif=source)


def test_preparation_sidecar_failure_removes_only_new_outputs(tmp_path,monkeypatch):
    import eeg_pipeline.preparation as preparation
    source=source_file(tmp_path);output=tmp_path/'prepared_raw.fif'
    unrelated=tmp_path/'keep.txt';unrelated.write_text('keep')
    write=preparation.atomic_write_json
    def fail_events(path,payload):
        if path.name.endswith('.events.json'):raise OSError('controlled sidecar failure')
        return write(path,payload)
    monkeypatch.setattr(preparation,'atomic_write_json',fail_events)
    with pytest.raises(OSError,match='controlled sidecar failure'):
        prepare_data(source,output_fif=output)
    assert set(tmp_path.iterdir())=={source,unrelated}
    assert unrelated.read_text()=='keep'
    assert mne.io.read_raw_fif(source,preload=False,verbose=False).n_times==10240


def test_brainvision_provenance_uses_named_companion_files(tmp_path):
    header=tmp_path/'header.vhdr';data=tmp_path/'actual-data.eeg';marker=tmp_path/'actual-events.vmrk'
    values=np.arange(2048,dtype='<f4').reshape(1024,2)
    data.write_bytes(values.tobytes())
    header.write_text('Brain Vision Data Exchange Header File Version 1.0\n'
        '[Common Infos]\nCodepage=UTF-8\nDataFile=actual-data.eeg\nMarkerFile=actual-events.vmrk\n'
        'DataFormat=BINARY\nDataOrientation=MULTIPLEXED\nNumberOfChannels=2\nSamplingInterval=3906.25\n'
        '[Binary Infos]\nBinaryFormat=IEEE_FLOAT_32\n'
        '[Channel Infos]\nCh1=Fp1,,1,µV\nCh2=Fp2,,1,µV\n',encoding='utf8')
    marker.write_text('Brain Vision Data Exchange Marker File, Version 1.0\n'
        '[Common Infos]\nCodepage=UTF-8\nDataFile=actual-data.eeg\n'
        '[Marker Infos]\nMk1=Stimulus,S  1,257,1,0\n',encoding='utf8')
    # Unrelated same-stem files must not enter the source audit.
    (tmp_path/'header.eeg').write_bytes(b'unrelated')
    (tmp_path/'header.vmrk').write_bytes(b'unrelated')
    result=prepare_data(header,return_result=True)
    assert {Path(p['path']).name for p in result.provenance['sources']}=={
        'header.vhdr','actual-data.eeg','actual-events.vmrk'}
    np.testing.assert_array_equal(result.raw.get_data(),values.astype(float).T*1e-6)
    assert result.events[0,0]==256
