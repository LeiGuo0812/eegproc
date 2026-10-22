from report_helpers import read_report
"""Input/clock, conditional ECG, single-band reuse, and compact delivery regressions."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import mne
import numpy as np
import pytest
from eeg_pipeline.configuration import resolve_config, resolve_events
from eeg_pipeline.pipeline import config_for, _select_heart, _fit_ica, preprocess_raw
from eeg_pipeline.raw_helpers import raw_slice, signal_hash
from eeg_pipeline.preparation import prepare_data
from eeg_pipeline.report_provenance import methods_text
from test_pipeline import fixture


@pytest.mark.parametrize('clock',[False,True])
def test_bounded_slice_equals_mne_crop_with_absolute_clock(clock):
    raw=fixture(clock);picks=[0,2,12,13]
    expected=raw.copy().pick(picks).crop(3.,21.-1/256.)
    actual=raw_slice(raw,3*256,21*256,picks=picks)
    np.testing.assert_array_equal(actual.get_data(),expected.get_data())
    assert actual.first_samp==expected.first_samp
    assert actual.annotations==expected.annotations
    assert actual.info['meas_date']==expected.info['meas_date']
    assert actual.get_channel_types()==expected.get_channel_types()
    assert signal_hash(raw,333)==hashlib.sha256(raw.get_data().astype('<f8').tobytes()).hexdigest()


def test_config_precedence_and_explicit_off(tmp_path):
    path=tmp_path/'settings.json'
    path.write_text(json.dumps(dict(purpose='erp',highpass=.2,line_frequency=60,asr_cutoff=30)))
    cfg=resolve_config(path,highpass=1.,lowpass=100.,asr_cutoff=None,line_frequency=None)
    assert cfg.purpose=='erp' and cfg.highpass==1. and cfg.lowpass==100.
    assert cfg.asr_cutoff is None and cfg.line_frequency is None
    ignored=resolve_config(path,unknown_option=1)
    assert any(row['field']=='unknown_option' for row in ignored.adjustments)
    fixed=resolve_config(repair_epochs=True,epoch_mode='fixed')
    assert fixed.repair_epochs is False and fixed.adjustments[0]['field']=='repair_epochs'


@pytest.mark.parametrize('clock',[False,True])
def test_preparation_roundtrip_has_no_signal_processing(clock,tmp_path):
    raw=fixture(clock);source=tmp_path/'original_raw.fif';out=tmp_path/'prepared_raw.fif'
    raw.save(source,fmt='double',overwrite=True,verbose=False)
    prepared=prepare_data(source,output_fif=out,event_id={'target':7})
    reread=mne.io.read_raw_fif(out,preload=True,verbose=False)
    np.testing.assert_array_equal(reread.get_data(),raw.get_data())
    assert reread.annotations==raw.annotations and reread.first_samp==raw.first_samp
    assert reread.info['meas_date']==raw.info['meas_date']
    payload=json.loads(out.with_suffix('.events.json').read_text())
    assert payload['event_id']=={'target':7} and payload['events'][0][0]==raw.first_samp+4*256
    info=json.loads(out.with_suffix('.preparation.json').read_text())
    assert not info['filtering_applied'] and not info['artifact_cleaning_applied']


def test_event_source_stim_and_named_selection_are_explicit():
    raw=fixture(False)
    e,names=resolve_events(raw,config_for(epoch_mode='events',event_names=('target',)))
    assert e[:,0].tolist()==[raw.first_samp+4*256,raw.first_samp+20*256]
    s,mapping=resolve_events(raw,config_for(epoch_mode='events',event_source='stim'))
    assert s[0].tolist()==[raw.first_samp+1024,0,7] and mapping=={'7':7}


@pytest.mark.parametrize('reference,expected',[(None,[0]),('matched',[0]),('unrelated',[])])
def test_heart_fallback_and_ecg_veto(reference,expected):
    n=131072;t=np.arange(n);x=np.sin(2*np.pi*t/128)
    class Sources:
        def __init__(self,values):self.values=values
        def get_data(self,picks):return self.values[picks]
    class Model:
        def get_sources(self,training,start,stop):
            assert reference is not None, 'No ECG must not compute source correlations'
            return Sources(x[None,start:stop])
    class Training:n_times=n
    ecg=None if reference is None else (x if reference=='matched' else np.cos(2*np.pi*t/128))[None]
    probabilities=np.array([[.01,.01,.01,.94,.01,.01,.01]])
    removed,decisions=_select_heart(Model(),Training(),probabilities,[0],ecg,config_for())
    assert removed==expected
    if reference is None:assert decisions[0]['absolute_ecg_correlation'] is None
    else:assert decisions[0]['absolute_ecg_correlation']==pytest.approx(1. if reference=='matched' else 0.,abs=1e-12)


def test_heart_candidate_is_really_subtracted_without_ecg(monkeypatch):
    import mne_icalabel.iclabel as label
    raw=fixture(False).pick('eeg').filter(1,100,verbose=False)
    raw.set_eeg_reference('average',projection=False,verbose=False)
    original=raw.get_data().copy()
    def known_labels(training,model,inplace=True):
        p=np.zeros((model.n_components_,7));p[:,0]=1.
        p[0]=[.01,.01,.01,.94,.01,.01,.01]
        return p
    monkeypatch.setattr(label,'iclabel_label_components',known_labels)
    cleaned,model,report=_fit_ica(raw.copy(),raw.copy(),config_for())
    assert report['removed_components_0based']==[0]
    assert report['heart_support_decisions'][0]['rule']=='iclabel_only_no_ecg'
    assert np.linalg.norm(cleaned.get_data()-original)>1e-6
    np.testing.assert_array_equal(raw.get_data(),original)


@pytest.mark.parametrize('has_ecg',[False,True])
def test_single_band_pipeline_fixed_epochs_metadata_and_small_report(has_ecg,tmp_path,monkeypatch):
    import pyprep
    import eeg_pipeline.pipeline as pipeline
    import eeg_pipeline.quality_figures as figures
    import mne_icalabel.iclabel as label
    raw=fixture(False)
    if has_ecg:
        raw.set_channel_types({'EOG':'ecg'})
    original=raw.get_data().copy()
    class NoBads:
        def __init__(self,*a,**k):pass
        def find_all_bads(self):pass
        def get_bads(self,as_dict=False):return {} if as_dict else []
    monkeypatch.setattr(pyprep,'NoisyChannels',NoBads)
    def brain_only(training,model,inplace=True):
        p=np.zeros((model.n_components_,7));p[:,0]=1.;return p
    monkeypatch.setattr(label,'iclabel_label_components',brain_only)
    def forbidden_heatmap(*a,**k):raise AssertionError('Compact report must not generate a full heatmap')
    monkeypatch.setattr(figures,'full_record_qc',forbidden_heatmap)
    cfg=config_for('rest',highpass=1.,lowpass=100.,asr_cutoff=None,line_frequency=None,
                   detect_ransac=False,epoch_mode='fixed')
    expected=raw.copy().pick('eeg').set_eeg_reference('average',projection=False,verbose=False)
    pipeline.band_filter(expected,1.,100.)
    clean,report,_=preprocess_raw(raw,tmp_path,'shared',config=cfg)
    assert report['filter_plan']['shared_full_record_buffer']
    assert report['filter_plan']['analysis_additional_edges_hz']==[None,None]
    assert report['filter_plan']['training_additional_edges_hz']==[None,None]
    np.testing.assert_allclose(clean.get_data(picks='eeg'),expected.get_data(),atol=1e-12,rtol=1e-9)
    np.testing.assert_array_equal(raw.get_data(),original)
    np.testing.assert_array_equal(clean.get_data(picks=['EOG','STI']),original[-2:])
    assert report['epochs']['retained_epochs']==19
    assert report['delivery_policy']['epoch_qc']=='annotations'
    assert not (tmp_path/'shared_ica_training_raw.fif').exists()
    assert report['ica']['component_selection']['ecg_available']==has_ecg
    page=(tmp_path/'shared_report.html').read_text(encoding='utf-8')
    assert 'data:image/png;base64' in page
    assert not (tmp_path/'shared_quality_assets/whole_record_qc.png').exists()
    # All ICs now have diagnostic plots, including retained components.
    assert report['report_storage']['total_bytes']<4*1024**2
    assert sum(f['key'].startswith('ica_topomap_') for f in report['visualizations']['figures'])==report['ica']['rank']
    assert len(report['visualizations']['waveform_windows'])<=3
    for f in report['visualizations']['figures']:assert f['width_px']<=1200
    assert not report['visualizations']['errors']
    saved=read_report((tmp_path/'shared_report.html').read_text(encoding='utf-8'))
    assert 'records' in saved['epochs'] and 'epoch_qc' not in saved['outputs']
    assert len(saved['stage_files'])==0
    assert not list(tmp_path.glob('*_qc'))
    methods=methods_text(report)
    assert ('With available ECG' in methods)==has_ecg
    assert ('Without available ECG' in methods)==(not has_ecg)
