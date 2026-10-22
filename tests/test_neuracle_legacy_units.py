"""An unusual vendor header must never silently relax voltage-unit validation."""
import numpy as np
import pytest
from neuracle_io import _microvolt_scale, read_neuracle_bdf


def test_legacy_unit_is_explicit_and_narrow():
    with pytest.raises(ValueError): _microvolt_scale('uV/mm', False)
    assert _microvolt_scale('uV/mm', False, True) == 1.
    with pytest.raises(ValueError): _microvolt_scale('mV/mm', True, True)
    assert _microvolt_scale('mV', True, True) == 1000.
    with pytest.raises(ValueError, match='calibration'):
        read_neuracle_bdf('unused', calibration='physical', allow_legacy_uv_per_mm=True)


def test_legacy_bdf_keeps_gain_values_and_records_assumption(tmp_path):
    import pyedflib
    header=dict(label='Cz', dimension='uV/mm', sample_frequency=256,
                physical_min=-375000,physical_max=375000,
                digital_min=-8388608,digital_max=8388607,
                transducer='EEG',prefilter='')
    digital=np.arange(-128,128,dtype=np.int32)[None,:]
    with pyedflib.EdfWriter(str(tmp_path/'data.bdf'),1,file_type=pyedflib.FILETYPE_BDFPLUS) as w:
        w.setSignalHeaders([header]);w.writeSamples(digital,digital=True)
    with pyedflib.EdfWriter(str(tmp_path/'evt.bdf'),1,file_type=pyedflib.FILETYPE_BDFPLUS) as w:
        w.setSignalHeaders([{**header,'dimension':'uV'}]);w.writeSamples(digital,digital=True)
        w.writeAnnotation(.5,0,'1')
    with pytest.raises(ValueError,match='dimension'):read_neuracle_bdf(tmp_path)
    result=read_neuracle_bdf(tmp_path,allow_legacy_uv_per_mm=True)
    np.testing.assert_array_equal(result['data'],digital.astype(float)*(750000/16777215))
    assert result['metadata']['calibration_info'][0]['source_unit']=='uV/mm'
    assert result['metadata']['legacy_uv_per_mm_interpreted_as_uV']
    assert result['events']==[dict(type='1',latency=128.)]
    from neuracle_io import import_neuracle
    from mne_bridge import eeg_to_raw
    import mne
    raw = eeg_to_raw(import_neuracle(tmp_path, allow_legacy_uv_per_mm=True))
    np.testing.assert_array_equal(raw.get_data(), result['data'] * 1e-6)
    events, event_id = mne.events_from_annotations(raw, verbose=False)
    assert events[0, 0] == 127  # preserve the audited vendor latency convention
    assert list(event_id) == ['1']
