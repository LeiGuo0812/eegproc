"""Optional epoch requests fail closed while preserving continuous processing."""
from dataclasses import asdict

import mne
import numpy as np
import pytest

from eeg_pipeline import PipelineConfig
from eeg_pipeline.configuration import resolve_epoch_config
from eeg_pipeline.engine import _resolve_epoch_request
from eeg_pipeline.runtime_parameters import resolve_for_raw


def recording(seconds=8.):
    return mne.io.RawArray(np.zeros((8,round(256*seconds))),
        mne.create_info(['Fp1','Fp2','F3','F4','C3','C4','P3','P4'],256,'eeg'),
        first_samp=2048,verbose=False)


def valid_events(raw):
    return np.array([[raw.first_samp+512,0,1],[raw.first_samp+1024,0,2]])


def assert_skipped(result):
    config,events,event_id,epoch_config,resolution=result
    assert config.epoch_mode=='none' and config.repair_epochs is False
    assert events is None and event_id is None and epoch_config is None
    assert resolution['status']=='skipped'
    assert 'Continuous processing continues; no epochs exported' in resolution['reason']
    assert any(row['field']=='epoch_mode' and row['effective']=='none' for row in config.adjustments)
    return config,resolution


def test_missing_annotations_and_stim_skip_requested_epochs():
    raw=recording();before=raw.get_data()
    config,resolution=assert_skipped(_resolve_epoch_request(raw,PipelineConfig(epoch_mode='events'),None,None,None))
    assert 'No stimulus annotations or STIM channel' in resolution['reason']
    np.testing.assert_array_equal(raw.get_data(),before)


@pytest.mark.parametrize('events',[
    [],[[2048,1]],[[2048,0,1],[2050,0]],
    [[2048.,0.,1.1]],[[float('nan'),0.,1.]],
    [['bad',0,1]],np.zeros((2,3,1)),
])
def test_malformed_event_arrays_do_not_stop_continuous_request(events):
    assert_skipped(_resolve_epoch_request(recording(),PipelineConfig(epoch_mode='events'),events,{'target':1},None))


@pytest.mark.parametrize('event_id',[
    {42:1},{'target':True},{'target':1.0},{'target':'1'},
    {'target':1,'missing':99},{},object(),
])
def test_invalid_condition_mapping_is_not_guessed_or_partially_silenced(event_id):
    raw=recording()
    assert_skipped(_resolve_epoch_request(raw,PipelineConfig(epoch_mode='events'),valid_events(raw),event_id,None))


@pytest.mark.parametrize('positions',[
    [2560,2560],[3072,2560],[2047,2560],[2560,4096],
])
def test_duplicate_unsorted_and_outside_samples_are_not_retimed(positions):
    raw=recording();events=np.array([[positions[0],0,1],[positions[1],0,2]])
    before=events.copy()
    assert_skipped(_resolve_epoch_request(raw,PipelineConfig(epoch_mode='events'),events,{'one':1,'two':2},None))
    np.testing.assert_array_equal(events,before)


def test_fixed_epochs_ignore_explicit_event_locked_input_with_audit():
    raw=recording();config=PipelineConfig(epoch_mode='fixed')
    effective,events,mapping,epoch_config,resolution=_resolve_epoch_request(raw,config,object(),object(),None)
    expected=mne.make_fixed_length_events(raw,id=1,duration=2.,overlap=0.,first_samp=True)
    np.testing.assert_array_equal(events,expected)
    assert mapping=={'fixed_window':1} and resolution['status']=='ready'
    assert epoch_config.tmin==0 and epoch_config.tmax==2.-1/256 and epoch_config.baseline is None
    assert effective.epoch_mode=='fixed'
    assert any(row['field']=='events/event_id' and row['effective'] is None for row in effective.adjustments)


def test_pending_repair_without_an_epoch_request_is_disabled():
    config=PipelineConfig(purpose='erp',epoch_mode='none',repair_epochs=True)
    assert config.repair_epochs is True  # Kept pending until explicit events are known.
    effective,events,mapping,epoch_config,resolution=_resolve_epoch_request(recording(),config,None,None,None)
    assert effective.epoch_mode=='none' and effective.repair_epochs is False
    assert events is mapping is epoch_config is None and resolution['status']=='not_requested'
    assert any(row['field']=='repair_epochs' and row['effective'] is False for row in effective.adjustments)


def test_explicit_events_promote_none_and_keep_applicable_pending_repair():
    raw=recording();events=valid_events(raw)
    config=PipelineConfig(purpose='erp',epoch_mode='none',repair_epochs=True)
    effective,actual,mapping,epoch_config,resolution=_resolve_epoch_request(raw,config,events,{'one':1,'two':2},None)
    assert effective.epoch_mode=='events' and effective.repair_epochs is True
    assert resolution=={'status':'ready','n_events':2,'mode':'events'}
    np.testing.assert_array_equal(actual,events)
    assert mapping=={'one':1,'two':2} and epoch_config.tmin<0
    assert config.epoch_mode=='none' and config.adjustments==()


def test_valid_explicit_request_preserves_effective_config_and_event_values():
    raw=recording();events=valid_events(raw);mapping={'one':1,'two':2}
    config=PipelineConfig(epoch_mode='events',purpose='erp')
    epoch_config=resolve_epoch_config(config)
    effective,actual,actual_mapping,actual_epoch,resolution=_resolve_epoch_request(raw,config,events,mapping,epoch_config)
    assert asdict(effective)==asdict(config) and effective.adjustments==()
    np.testing.assert_array_equal(actual,events)
    assert actual_mapping==mapping and asdict(actual_epoch)==asdict(epoch_config)
    assert resolution['status']=='ready'


@pytest.mark.parametrize('missing_events',[False,True])
def test_epoch_config_adjustments_survive_request_resolution(missing_events):
    raw=recording();config=PipelineConfig(epoch_mode='events',n_threads=0)
    epoch_config=resolve_epoch_config(config,{'peak_uv':0.,'cv':1,'unknown_epoch_parameter':'ignored'})
    effective,events,mapping,actual_epoch,resolution=_resolve_epoch_request(raw,config,
        None if missing_events else valid_events(raw),None if missing_events else {'one':1,'two':2},epoch_config)
    fields={row['field'] for row in effective.adjustments}
    assert {'n_threads','epoch_config.peak_uv','epoch_config.cv','epoch_config.unknown_epoch_parameter'}<=fields
    if missing_events:
        assert actual_epoch is None and resolution['status']=='skipped'
    else:
        assert actual_epoch.adjustments==epoch_config.adjustments
        assert resolution['status']=='ready'


@pytest.mark.parametrize('seconds,duration,overlap',[(8.,.001,0.),(.5,2.,0.),(8.,2.,1.999)])
def test_runtime_then_request_resolution_handles_short_fixed_windows(seconds,duration,overlap):
    raw=recording(seconds)
    config=PipelineConfig(epoch_mode='fixed',fixed_epoch_duration=duration,fixed_epoch_overlap=overlap)
    bounded,audit=resolve_for_raw(config,raw)
    effective,events,mapping,epoch_config,resolution=_resolve_epoch_request(raw,bounded,None,None,None)
    assert audit['adjustments'] and resolution['status']=='ready'
    assert len(events)>0 and np.all(np.diff(events[:,0])>0)
    assert events[0,0]>=raw.first_samp
    assert events[-1,0]+round(epoch_config.tmax*raw.info['sfreq'])<raw.first_samp+raw.n_times
    assert effective.epoch_mode=='fixed' and mapping=={'fixed_window':1}
    assert set(row['field'] for row in bounded.adjustments)<=set(row['field'] for row in effective.adjustments)


@pytest.mark.parametrize('tmin,baseline',[(0.,(None,0.)),(-.0001,(None,0.)),(-.2,(.001,.002))])
def test_unusable_baseline_on_sample_grid_is_disabled_with_audit(tmin,baseline):
    raw=recording();config=PipelineConfig(epoch_mode='events',epoch_tmin=tmin,epoch_baseline=baseline)
    effective,events,mapping,epoch_config,resolution=_resolve_epoch_request(
        raw,config,valid_events(raw),{'one':1,'two':2},None)
    assert epoch_config.baseline is None and resolution['status']=='ready'
    assert any(row['field']=='epoch_config.baseline' and row['effective'] is None for row in effective.adjustments)
    epochs=mne.Epochs(raw,events,mapping,tmin=epoch_config.tmin,tmax=epoch_config.tmax,
                     baseline=epoch_config.baseline,preload=True,verbose=False)
    assert len(epochs)==2


def test_explicit_zero_single_sample_baseline_is_preserved():
    raw=recording();config=PipelineConfig(epoch_mode='events',epoch_tmin=0.,epoch_baseline=(0.,0.))
    effective,events,mapping,epoch_config,resolution=_resolve_epoch_request(
        raw,config,valid_events(raw),{'one':1,'two':2},None)
    assert epoch_config.baseline==(0.,0.) and resolution['status']=='ready'
    assert not effective.adjustments
    epochs=mne.Epochs(raw,events,mapping,tmin=epoch_config.tmin,tmax=epoch_config.tmax,
                     baseline=epoch_config.baseline,preload=True,verbose=False)
    assert len(epochs)==2


def test_repair_request_requires_real_prestimulus_samples():
    raw=recording();config=PipelineConfig(purpose='erp',epoch_mode='events',repair_epochs=True,epoch_tmin=-.0001)
    effective,events,mapping,epoch_config,resolution=_resolve_epoch_request(
        raw,config,valid_events(raw),{'one':1,'two':2},None)
    assert effective.repair_epochs is True and epoch_config.tmin==-.2
    assert round(epoch_config.tmin*raw.info['sfreq'])<0
    assert epoch_config.baseline==(None,0.) and resolution['status']=='ready'
    assert any(row['field']=='epoch_config.tmin' and row['effective']==-.2 for row in effective.adjustments)


@pytest.mark.parametrize('tmin,tmax',[(-.2,1e308),(-1e308,1.),(-1e308,1e308)])
def test_extreme_finite_event_windows_skip_before_sample_conversion(tmin,tmax):
    raw=recording(40.);before=raw.get_data()
    config=PipelineConfig(purpose='erp',epoch_mode='events',repair_epochs=True,
                          epoch_tmin=tmin,epoch_tmax=tmax)
    effective,resolution=assert_skipped(_resolve_epoch_request(
        raw,config,valid_events(raw),{'one':1,'two':2},None))
    assert 'exceeds the recording duration' in resolution['reason']
    assert any(row['field']=='repair_epochs' and row['effective'] is False for row in effective.adjustments)
    np.testing.assert_array_equal(raw.get_data(),before)


def test_standard_event_window_on_40_second_input_is_unchanged():
    raw=recording(40.);config=PipelineConfig(purpose='erp',epoch_mode='events')
    requested=resolve_epoch_config(config)
    effective,events,mapping,epoch_config,resolution=_resolve_epoch_request(
        raw,config,valid_events(raw),{'one':1,'two':2},None)
    assert resolution=={'status':'ready','n_events':2,'mode':'events'}
    assert asdict(effective)==asdict(config) and effective.adjustments==()
    assert asdict(epoch_config)==asdict(requested)
    epochs=mne.Epochs(raw,events,mapping,tmin=epoch_config.tmin,tmax=epoch_config.tmax,
                     baseline=epoch_config.baseline,preload=True,verbose=False)
    assert len(epochs)==2
