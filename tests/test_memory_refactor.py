"""Regression checks for bounded-memory paths, independent of output packaging."""
import mne
import numpy as np
import pytest
from mne.utils import object_diff
from scipy.ndimage import binary_dilation
from threadpoolctl import threadpool_limits

from eeg_pipeline.raw_helpers import channel_is_finite_nonconstant, concatenate_samples
from eeg_pipeline.signal_ops import window_mask, relative_window_mask, _training_segments
from mne_asr import ASRConfig, clean_asr_raw
from mne_asr.api import _clean_asr_owned
from test_pipeline import fixture


@pytest.fixture(autouse=True)
def limit_threads():
    with threadpool_limits(limits=1):
        yield


@pytest.mark.parametrize('window_seconds',[.137,1.,2.3])
def test_bounded_qc_matches_full_array_definition(window_seconds):
    raw=fixture().crop(0,38.123)
    raw.info['bads']=['F3']
    # Different DC offsets, local bursts, a partial last window, and one bad
    # channel ensure that channel selection and the full-record median matter.
    raw._data[:12]+=np.linspace(-100,100,12)[:,None]*1e-6
    raw._data[0,500:700]+=200e-6
    raw._data[2,-15:]+=160e-6
    before=raw.get_data()
    data=raw.get_data(picks=mne.pick_types(raw.info,eeg=True,exclude='bads'))*1e6
    centered=data-np.median(data,axis=1,keepdims=True)
    width=max(1,round(window_seconds*raw.info['sfreq']))
    expected=np.zeros(raw.n_times,bool)
    for start in range(0,raw.n_times,width):
        part=centered[:,start:start+width]
        if np.max(np.abs(part))>150 or np.max(np.ptp(part,axis=1))>200:
            expected[start:start+width]=True
    expected=binary_dilation(expected,iterations=int(np.ceil(.25*raw.info['sfreq']))) if expected.any() else expected
    np.testing.assert_array_equal(window_mask(raw,150,200,window_seconds=window_seconds),expected)

    width=max(2,round(window_seconds*raw.info['sfreq']))
    starts=list(range(0,raw.n_times,width))
    scale=np.array([np.log(np.maximum(np.std(data[:,a:a+width],axis=1),1e-9)) for a in starts]).T
    center=np.median(scale,axis=1,keepdims=True)
    deviation=1.4826*np.median(np.abs(scale-center),axis=1,keepdims=True)
    z=(scale-center)/np.maximum(deviation,.1)
    expected=np.zeros(raw.n_times,bool)
    for i,a in enumerate(starts):
        if np.any((z[:,i]>6)&(np.ptp(data[:,a:a+width],axis=1)>50)):
            expected[a:a+width]=True
    expected=binary_dilation(expected,iterations=int(np.ceil(.25*raw.info['sfreq']))) if expected.any() else expected
    np.testing.assert_array_equal(relative_window_mask(raw,window_seconds=window_seconds),expected)
    np.testing.assert_array_equal(raw.get_data(),before)


@pytest.mark.parametrize('clock',[True,False])
def test_owned_asr_matches_public_nonmutating_route(clock,monkeypatch):
    raw=fixture(clock).pick('eeg')
    raw.set_annotations(mne.Annotations([3.],[0.],'event'))
    info=raw.info.copy();annotations=raw.annotations.copy();before=raw.get_data()
    expected,expected_report=clean_asr_raw(raw)
    np.testing.assert_array_equal(raw.get_data(),before)
    # The eligible private path should not copy any full Raw object.
    monkeypatch.setattr(mne.io.BaseRaw,'copy',lambda self:pytest.fail('Unexpected full Raw copy'))
    actual,actual_report=_clean_asr_owned(raw)
    assert actual is raw
    np.testing.assert_array_equal(actual.get_data(),expected.get_data())
    assert actual_report==expected_report
    assert object_diff(actual.info,info)=='' and actual.annotations==annotations


def test_owned_asr_falls_back_for_auxiliary_channels_and_boundaries():
    raw=fixture();before=raw.get_data()
    expected,report=clean_asr_raw(raw)
    actual,actual_report=_clean_asr_owned(raw)
    assert actual is not raw
    np.testing.assert_array_equal(actual.get_data(),expected.get_data())
    np.testing.assert_array_equal(raw.get_data(),before)
    assert actual_report==report


def test_auxiliary_channel_validation_scans_all_blocks():
    raw=fixture()
    raw._data[0]=1.
    assert not channel_is_finite_nonconstant(raw,0,129)
    raw._data[0,250]=2.
    assert channel_is_finite_nonconstant(raw,0,129)
    raw._data[0,-1]=np.nan
    assert not channel_is_finite_nonconstant(raw,0,129)


def test_auxiliary_concatenation_preserves_order_exactly():
    raw=fixture();spans=[(19,133),(255,563),(701,999)]
    expected=np.concatenate([raw.get_data(picks=[12,13],start=a,stop=b) for a,b in spans],axis=1)
    actual=concatenate_samples(raw,spans,picks=[12,13])
    np.testing.assert_array_equal(actual,expected)


@pytest.mark.parametrize('clock',[True,False])
def test_training_retains_mne_concatenation_annotations(clock):
    raw=fixture(clock)
    raw.annotations.append(raw.first_time+20,.5,'BAD_scoped',ch_names=[('F3',)],extras=[{'source':'manual'}])
    result,spans=_training_segments(raw,min_seconds=10)
    expected=np.concatenate([raw.get_data(start=a,stop=b) for a,b in spans],axis=1)
    np.testing.assert_array_equal(result.get_data(),expected)
    assert result.first_samp==raw.first_samp+spans[0][0]
    assert sum(result.annotations.description=='BAD boundary')==len(spans)-1
    assert sum(result.annotations.description=='EDGE boundary')==len(spans)-1
