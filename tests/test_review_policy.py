from report_helpers import read_report
"""QC warnings must not silently become acceptance or numerical bypasses."""
import json
import numpy as np
import pytest
from eeg_pipeline.pipeline import config_for, assess_bad_channel_burden, preprocess_raw, validate_config
from eeg_pipeline.quality_report import save_quality_report
from test_pipeline import fixture


def test_workflow_continues_above_threshold_and_explicit_stop_remains_available():
    bads=[f'EEG{i}' for i in range(10)]
    report={'quality_flags':[]}
    assess_bad_channel_burden(report,config_for(asr_backend='mne_native'),bads,32)
    assert report['bad_channel_qc']['continued_despite_threshold']
    assert report['quality_flags']
    assess_bad_channel_burden({'quality_flags':[]},config_for(),bads,32)
    with pytest.raises(ValueError,match='bad_channel_policy=stop'):
        assess_bad_channel_burden({'quality_flags':[]},config_for(asr_backend='mne_native',bad_channel_policy='stop'),bads,32)


def test_report_policy_does_not_bypass_minimum_channels():
    report={'quality_flags':[]}
    with pytest.raises(ValueError,match='at least 8'):
        assess_bad_channel_burden(report,config_for(bad_channel_policy='report'),list(range(25)),32)
    assert not report['bad_channel_qc']['continued_despite_threshold']
    resolved=config_for(bad_channel_policy='ignore')
    validate_config(resolved,256.)
    assert resolved.bad_channel_policy=='report'
    assert any(r['field']=='bad_channel_policy' and r['requested']=='ignore' and
               r['effective']=='report' for r in resolved.adjustments)


def test_exact_limit_is_not_exceeded():
    report={'quality_flags':[]}
    assess_bad_channel_burden(report,config_for(asr_backend='mne_native'),list(range(6)),20)
    assert not report['bad_channel_qc']['threshold_exceeded'] and not report['quality_flags']


def test_above_threshold_finishes_preserves_metadata_and_writes_review(tmp_path,monkeypatch):
    import pyprep
    raw=fixture();before=raw.get_data().copy()
    names=raw.ch_names[:4]
    class KnownBads:
        def __init__(self,*args,**kwargs):pass
        def find_all_bads(self):pass
        def get_bads(self,as_dict=False):return {'controlled_test':names} if as_dict else names
    monkeypatch.setattr(pyprep,'NoisyChannels',KnownBads)
    cfg=config_for(asr_backend='mne_native',asr_cutoff=None,detect_ransac=False)
    clean,report,_=preprocess_raw(raw,tmp_path,'review',config=cfg)
    assert report['status']=='review_required' and report['bad_channel_qc']['bad_fraction']>0.3
    assert report['human_review']['processing_completed'] and report['human_review']['decision']=='pending'
    assert not report['human_review']['automatic_acceptance']
    assert np.isfinite(clean.get_data()).all()
    np.testing.assert_array_equal(raw.get_data(),before)
    np.testing.assert_array_equal(clean.get_data(picks=['EOG','STI']),before[-2:])
    assert clean.first_samp==raw.first_samp and clean.info['meas_date']==raw.info['meas_date']
    for a in raw.annotations:
        assert any(b['description']==a['description'] and b['onset']==a['onset'] for b in clean.annotations)
    page=tmp_path/'review_report.html'
    assert page.exists() and 'Completed with observations' in page.read_text(encoding='utf8')
    # Final CLI report update must include epoch counts, not the earlier continuous-only report.
    report['epochs']={'input_events':10,'retained_epochs':4,'condition_retention':{'1':{'input':10,'retained':4}}}
    save_quality_report(report,report['outputs']['quality_report'])
    assert '4 / 10' in page.read_text(encoding='utf8')
    saved=read_report((tmp_path/'review_report.html').read_text(encoding='utf8'))
    assert saved['human_review']['decision']=='pending' and saved['epochs']['retained_epochs']==4
