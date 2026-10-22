"""Acquisition-aware normalization preserves supported requests and raw data."""
from dataclasses import asdict

import mne
import numpy as np
import pytest
from mne.utils import object_diff

from eeg_pipeline import PipelineConfig
from eeg_pipeline.runtime_parameters import resolve_for_raw,resolve_manual_exclude,update_parameter_report
from eeg_pipeline.settings import validate_config
from eeg_pipeline.signal_ops import band_filter


def raw_at(sfreq,*,highpass=0.,lowpass=None):
    raw=mne.io.RawArray(np.random.default_rng(51).normal(size=(8,round(sfreq*8)))*1e-6,
        mne.create_info(['Fp1','Fp2','F3','F4','C3','C4','P3','P4'],sfreq,'eeg'),
        first_samp=2048,verbose=False)
    raw.set_montage('standard_1020',verbose=False)
    with raw.info._unlock():
        raw.info['highpass']=highpass
        raw.info['lowpass']=sfreq/2 if lowpass is None else lowpass
    raw.set_annotations(mne.Annotations([2.],[.25],['BAD_manual']))
    return raw


@pytest.mark.parametrize('purpose',['rest','erp'])
def test_valid_defaults_unchanged(purpose):
    raw=raw_at(256);config=PipelineConfig(purpose=purpose)
    before=raw.copy()
    effective,audit=resolve_for_raw(config,raw)
    assert effective is config and asdict(effective)==asdict(config)
    assert audit['adjustments']==[] and audit['review_notes']==[]
    np.testing.assert_array_equal(raw.get_data(),before.get_data())
    assert object_diff(raw.info,before.info)=='' and raw.annotations==before.annotations


def test_128hz_clips_bands_and_actual_mne_filter_succeeds():
    raw=raw_at(128);config=PipelineConfig()
    effective,audit=resolve_for_raw(config,raw)
    assert effective.lowpass==62 and effective.training_lowpass==62
    assert effective.highpass==.5 and effective.training_highpass==1
    assert effective.asr_cutoff==20
    assert effective.ica_enabled is True and audit['ica_enabled'] is True
    assert not audit['iclabel_nominal_training_band'] and audit['manual_review_required']
    assert {item['field'] for item in audit['adjustments']}=={'lowpass','training_lowpass'}
    validate_config(effective,128)
    band_filter(raw.copy(),effective.highpass,effective.lowpass)
    band_filter(raw.copy(),effective.training_highpass,effective.training_lowpass)


def test_already_filtered_input_never_claims_low_frequency_recovery():
    raw=raw_at(256,highpass=2.,lowpass=45.)
    effective,audit=resolve_for_raw(PipelineConfig(purpose='erp'),raw)
    assert (effective.highpass,effective.lowpass)==(2.,30.)
    assert (effective.training_highpass,effective.training_lowpass)==(2.,45.)
    assert audit['removed_frequencies_restored'] is False
    assert all('cannot be restored' in row['reason'] for row in audit['adjustments'])
    assert len(effective.adjustments)==3


def test_intentionally_valid_edge_near_nyquist_is_preserved():
    config=PipelineConfig(highpass=1.,lowpass=63.5,training_highpass=1.,training_lowpass=63.5)
    effective,audit=resolve_for_raw(config,raw_at(128))
    assert effective is config and audit['adjustments']==[]
    assert (effective.lowpass,effective.training_lowpass)==(63.5,63.5)
    assert audit['review_notes']==[] and not audit['manual_review_required']
    assert not audit['iclabel_nominal_training_band']


def test_valid_eeglab_training_band_does_not_add_review_requirement():
    config=PipelineConfig(preset='eeglab')
    effective,audit=resolve_for_raw(config,raw_at(256))
    assert effective is config and audit['adjustments']==[]
    assert not audit['iclabel_nominal_training_band']
    assert audit['review_notes']==[] and not audit['manual_review_required']


def test_narrow_band_at_nyquist_uses_positive_transition_without_inverting_band():
    raw=raw_at(128,highpass=63.,lowpass=64.)
    effective,audit=resolve_for_raw(PipelineConfig(),raw)
    assert (effective.highpass,effective.lowpass)==(63.,63.75)
    assert (effective.training_highpass,effective.training_lowpass)==(63.,63.75)
    assert audit['manual_review_required']
    validate_config(effective,128)


def test_requested_band_outside_input_uses_recorded_fallback():
    raw=raw_at(128)
    effective,audit=resolve_for_raw(PipelineConfig(highpass=90.,lowpass=110.),raw)
    assert (effective.highpass,effective.lowpass)==(.5,62.)
    assert audit['bands']['analysis']['requested_band_unavailable']
    assert all('no usable overlap' in row['reason'] for row in audit['adjustments'] if row['field'] in ('highpass','lowpass'))


@pytest.mark.parametrize('sfreq',[64.,80.])
def test_asr_unsupported_sampling_is_disabled_with_evidence(sfreq):
    raw=raw_at(sfreq)
    effective,audit=resolve_for_raw(PipelineConfig(),raw)
    assert effective.asr_cutoff is None
    assert not audit['asr_enabled'] and audit['resampling_applied'] is False
    assert any(row['field']=='asr_cutoff' and 'sfreq > 80' in row['reason'] for row in audit['adjustments'])
    validate_config(effective,sfreq)


@pytest.mark.parametrize('mode,exclude',[('auto',None),('manual',(0,2)),('review',None)])
def test_low_sampling_disables_current_iclabel_dependency_in_every_ica_mode(mode,exclude):
    raw=raw_at(64);before=raw.copy()
    config=PipelineConfig(highpass=1.,lowpass=30.,training_highpass=1.,training_lowpass=30.,
                          ica_mode=mode,ica_exclude=exclude)
    effective,audit=resolve_for_raw(config,raw)
    assert effective.ica_enabled is False and audit['ica_enabled'] is False
    assert effective.asr_cutoff is None and audit['asr_enabled'] is False
    assert effective.ica_mode=='auto' and effective.ica_exclude is None
    assert (effective.highpass,effective.lowpass,effective.training_highpass,effective.training_lowpass)==(1.,30.,1.,30.)
    assert {row['field'] for row in audit['adjustments']}=={'ica_enabled','asr_cutoff'}
    record=next(row for row in audit['adjustments'] if row['field']=='ica_enabled')
    assert 'ICLabel backend autocorrelation' in record['reason']
    assert 'below 100 Hz' in record['reason'] and 'not a general limit of ICA' in record['reason']
    assert record['requested'] is True and record['effective'] is False
    assert audit['manual_review_required'] and audit['review_notes']
    report=update_parameter_report({'quality_flags':[]},effective)
    assert report['quality_flags'] and report['config']['ica_enabled'] is False
    if mode!='auto':
        assert any(row['field']=='ica_mode' for row in effective.adjustments)
    if exclude is not None:
        assert any(row['field']=='ica_exclude' for row in effective.adjustments)
    np.testing.assert_array_equal(raw.get_data(),before.get_data())
    assert object_diff(raw.info,before.info)=='' and raw.annotations==before.annotations
    assert config.ica_enabled is True
    validate_config(effective,64.)


@pytest.mark.parametrize('sfreq,expected_enabled',[(99.5,False),(100.,True),(128.,True)])
def test_iclabel_dependency_sampling_boundary_preserves_supported_requests(sfreq,expected_enabled):
    config=PipelineConfig(highpass=1.,lowpass=30.,training_highpass=1.,training_lowpass=30.)
    effective,audit=resolve_for_raw(config,raw_at(sfreq))
    assert effective.ica_enabled is expected_enabled
    assert effective.asr_cutoff==config.asr_cutoff
    assert (effective.highpass,effective.lowpass,effective.training_highpass,effective.training_lowpass)==(1.,30.,1.,30.)
    if expected_enabled:
        assert effective is config and audit['adjustments']==[]
    else:
        assert {row['field'] for row in audit['adjustments']}=={'ica_enabled'}


def test_already_disabled_ica_does_not_add_low_rate_adjustment():
    config=PipelineConfig(highpass=1.,lowpass=30.,training_highpass=1.,training_lowpass=30.,
                          ica_enabled=False,asr_cutoff=None)
    effective,audit=resolve_for_raw(config,raw_at(64.))
    assert effective is config and audit['adjustments']==[] and audit['review_notes']==[]


@pytest.mark.parametrize('highpass,lowpass',[(10.,5.),(-1.,50.),(0.,130.),(float('nan'),50.)])
def test_invalid_input_filter_metadata_remains_an_error(highpass,lowpass):
    raw=raw_at(256,highpass=highpass,lowpass=lowpass)
    with pytest.raises(ValueError,match='metadata'):
        resolve_for_raw(PipelineConfig(),raw)


@pytest.mark.parametrize('duration,overlap',[(.001,0.),(100.,7.999),(2.,1.999)])
def test_fixed_epochs_resolve_to_distinct_supported_sample_windows(duration,overlap):
    raw=raw_at(256)
    config=PipelineConfig(epoch_mode='fixed',fixed_epoch_duration=duration,fixed_epoch_overlap=overlap)
    effective,audit=resolve_for_raw(config,raw)
    events=mne.make_fixed_length_events(raw,duration=effective.fixed_epoch_duration,
        overlap=effective.fixed_epoch_overlap,first_samp=True)
    assert effective.fixed_epoch_duration>1/raw.info['sfreq']
    assert effective.fixed_epoch_duration<=raw.n_times/raw.info['sfreq']
    assert len(events)>0 and np.all(np.diff(events[:,0])>0)
    assert audit['adjustments']


@pytest.mark.parametrize('indices,expected',[((),()),((0,2),(0,2)),((0,2,99),(0,2)),((3,99),())])
def test_manual_indices_use_fitted_rank_without_enabling_auto(indices,expected):
    config=PipelineConfig(ica_mode='manual',ica_exclude=indices)
    effective,records=resolve_manual_exclude(config,3)
    assert effective.ica_mode=='manual' and effective.ica_exclude==expected
    assert config.ica_exclude==indices
    if indices==expected:
        assert effective is config and records==[]
    else:
        assert len(records)==1 and records[0]['field']=='ica_exclude'
        assert records[0]['effective']==list(expected)
        assert 'automatic selection is not substituted' in records[0]['reason']
        assert len(effective.adjustments)==1


def test_auto_selection_is_unaffected_by_manual_resolution():
    config=PipelineConfig()
    effective,records=resolve_manual_exclude(config,3)
    assert effective is config and records==[]


@pytest.mark.parametrize('count',[0,-1,True,2.5])
def test_invalid_fitted_component_count_is_not_silently_repaired(count):
    with pytest.raises(ValueError,match='n_components'):
        resolve_manual_exclude(PipelineConfig(ica_mode='manual',ica_exclude=[]),count)


def test_report_merges_static_and_dynamic_adjustments_without_duplicates():
    config=PipelineConfig(ica_mode='manual',ica_exclude=[0,99],n_threads=0)
    effective,manual_records=resolve_manual_exclude(config,3)
    report={'quality_flags':['Existing QC flag'],
            'parameter_adjustments':[dict(config.adjustments[0])],
            'provenance':{'invocation':{'effective_config':{'stale':True},'entrypoint':'test'}}}
    assert update_parameter_report(report,effective,extra=manual_records) is report
    assert len(report['parameter_adjustments'])==2
    assert len(report['quality_flags'])==2
    assert report['config']==asdict(effective)
    assert report['provenance']['invocation']['effective_config']==asdict(effective)
    update_parameter_report(report,effective,extra=manual_records)
    assert len(report['parameter_adjustments'])==2 and len(report['quality_flags'])==2
    assert report['quality_flags'][0]=='Existing QC flag'


def test_unchanged_configuration_does_not_add_quality_flags_or_provenance():
    config=PipelineConfig()
    report={'quality_flags':[]}
    update_parameter_report(report,config)
    assert report['parameter_adjustments']==[] and report['quality_flags']==[]
    assert report['config']==asdict(config) and 'provenance' not in report
