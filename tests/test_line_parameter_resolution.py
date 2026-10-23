"""Numerical spectrum-fit guards preserve every previously supported segment."""
from dataclasses import asdict

import mne
import numpy as np
import pytest
from mne.annotations import _annotations_starts_stops

from eegproc import PipelineConfig
from eegproc.backends import clean_line
from eegproc.runtime_parameters import resolve_for_raw,spectrum_fit_support
from eegproc.signal_ops import BOUNDARIES


def recording(seconds=8.):
    sfreq=256.;samples=round(seconds*sfreq)
    data=np.random.default_rng(61).normal(size=(9,samples))*1e-6
    data[:8]+=10e-6*np.sin(2*np.pi*50*np.arange(samples)/sfreq)
    return mne.io.RawArray(data,mne.create_info([f'E{i}' for i in range(8)]+['ECG'],sfreq,['eeg']*8+['ecg']),
                           first_samp=2048,verbose=False)


@pytest.mark.parametrize('window,bandwidth',[(4.,2.),(2.,1.),(10.,2.)])
def test_supported_pairs_are_not_changed_even_if_window_exceeds_record(window,bandwidth):
    config=PipelineConfig(line_window_seconds=window,line_bandwidth=bandwidth)
    effective,audit=resolve_for_raw(config,recording())
    assert effective is config and asdict(effective)==asdict(config)
    assert audit['adjustments']==[] and audit['line_spectrum_fit']['supported']


@pytest.mark.parametrize('window,bandwidth',[(4.,.1),(.001,2.),(4.,256.),(1/256,256.)])
def test_unsupported_pairs_fall_back_and_real_spectrum_fit_runs(window,bandwidth):
    raw=recording();config=PipelineConfig(line_window_seconds=window,line_bandwidth=bandwidth)
    effective,audit=resolve_for_raw(config,raw)
    assert (effective.line_window_seconds,effective.line_bandwidth)==(4.,2.)
    assert audit['adjustments'] and audit['line_spectrum_fit']['supported']
    report=clean_line(raw,effective)
    assert 'skipped_segments' not in report and np.isfinite(raw.get_data()).all()


def test_finite_window_overflow_is_capped_before_sample_conversion():
    raw=recording();effective,audit=resolve_for_raw(PipelineConfig(line_window_seconds=1e308),raw)
    assert effective.line_window_seconds==8.
    assert any(row['field']=='line_window_seconds' and 'overflows' in row['reason'] for row in audit['adjustments'])
    assert spectrum_fit_support(1e308,2.,256.,raw.n_times)['supported']
    clean_line(raw,effective)


def test_short_record_does_not_expand_default_bandwidth_to_force_fitting():
    raw=recording(.1);before=raw.get_data()
    config=PipelineConfig();effective,audit=resolve_for_raw(config,raw)
    assert effective is config and (effective.line_window_seconds,effective.line_bandwidth)==(4.,2.)
    assert not audit['line_spectrum_fit']['supported']
    report=clean_line(raw,effective)
    assert report['processed_segments']==[] and report['skipped_segments'] and report['quality_flags']
    np.testing.assert_array_equal(raw.get_data(),before)


def test_fully_supported_annotation_spans_use_original_raw_call_and_exact_values(monkeypatch):
    raw=recording();raw.set_annotations(mne.Annotations([3.],[1.],['BAD_manual']))
    config=PipelineConfig();expected=raw.copy()
    expected.notch_filter([50,100],picks='eeg',method='spectrum_fit',mt_bandwidth=2.,p_value=.05,
                          filter_length='4.0s',skip_by_annotation=BOUNDARIES,verbose='warning')
    original=mne.io.BaseRaw.notch_filter;calls=[]
    def tracked(self,*args,**kwargs):
        calls.append(kwargs)
        return original(self,*args,**kwargs)
    monkeypatch.setattr(mne.io.BaseRaw,'notch_filter',tracked)
    report=clean_line(raw,config)
    assert len(calls)==1 and calls[0]['skip_by_annotation']==BOUNDARIES
    assert 'skipped_segments' not in report
    np.testing.assert_array_equal(raw.get_data(),expected.get_data())


def test_only_unsupported_bad_separated_span_is_skipped(monkeypatch):
    raw=recording();raw.set_annotations(mne.Annotations([.1],[1.],['BAD_scoped'],ch_names=[('E0',)],extras=[{'source':'manual'}]))
    original=raw.copy();expected=raw.get_data();config=PipelineConfig()
    starts,stops=_annotations_starts_stops(raw,BOUNDARIES,invert=True)
    expected_processed=[];expected_skipped=[]
    for start,stop in zip(starts,stops):
        if spectrum_fit_support(4.,2.,256.,stop-start)['supported']:
            mne.filter.notch_filter(expected[:,start:stop],256.,[50,100],picks=np.arange(8),copy=False,
                method='spectrum_fit',mt_bandwidth=2.,p_value=.05,filter_length='4.0s',verbose='warning')
            expected_processed.append([int(start),int(stop)])
        else:expected_skipped.append([int(start),int(stop)])
    monkeypatch.setattr(mne.io.BaseRaw,'notch_filter',lambda *args,**kwargs:pytest.fail('Partial path must not call Raw over unsupported spans'))
    report=clean_line(raw,config)
    assert report['processed_segments']==expected_processed
    assert [row['samples'] for row in report['skipped_segments']]==expected_skipped
    np.testing.assert_array_equal(raw.get_data(),expected)
    np.testing.assert_array_equal(raw.get_data(picks=['ECG']),original.get_data(picks=['ECG']))
    assert raw.annotations==original.annotations and raw.first_samp==original.first_samp


def test_single_sample_segment_is_reported_without_cola_zero_stride():
    raw=recording(1/256);before=raw.get_data()
    report=clean_line(raw,PipelineConfig())
    assert report['skipped_segments'][0]['window_samples']==1
    np.testing.assert_array_equal(raw.get_data(),before)
