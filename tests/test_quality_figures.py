from report_helpers import read_report
"""Scientific comparison semantics and resilient final-report delivery."""
import copy
from pathlib import Path
import json
import mne
import numpy as np
import pytest
from eegproc.quality_figures import paired_psd,bad_spans,build_signal_figures,retention_rows
from eegproc.quality_report import save_quality_report
from test_pipeline import fixture


@pytest.mark.parametrize('clock',[True,False])
def test_psd_is_paired_and_input_bad_clock_is_respected(clock):
    raw=fixture(clock);before=raw.get_data().copy();good=raw.ch_names[:12]
    clean=raw.copy();clean._data[:12]*=.5
    clean.annotations.append(raw.first_time+24,4,'BAD_residual')
    annotations=raw.annotations.copy()
    f,a,b,meta=paired_psd(raw,clean,good)
    np.testing.assert_allclose(b,a*.25,rtol=1e-12)
    assert meta['starts_samples']==[s*256 for s in [0,4,12,16,20,24,28,32,36]]
    assert bad_spans(raw)==[(2560,2816,'BAD_manual')]
    assert not meta['output_bad_excluded'] and meta['original_bad_excluded']
    np.testing.assert_array_equal(raw.get_data(),before)
    assert raw.annotations==annotations and f[1]==.25


def test_visuals_cannot_compare_mismatched_sample_grid(tmp_path):
    raw=fixture();clean=raw.copy().crop(tmin=1)
    with pytest.raises(ValueError,match='sample grids'):
        build_signal_figures({},raw,clean,tmp_path)


def test_condition_counts_and_missing_denominators():
    report={'event_id':{'标准':1,'目标':2,'缺失':3},'epochs':{'condition_retention':{
        '1':{'input':12,'eligible':10,'retained':8},'2':{'input':4,'retained':0},'3':{'input':0,'eligible':0,'retained':0}}}}
    rows=retention_rows(report)
    assert rows[0]['name']=='标准' and rows[0]['annotation_rejected']==2 and rows[0]['qc_rejected']==2
    assert rows[1]['annotation_rejected'] is None and rows[1]['retention_fraction']==0
    assert rows[2]['retention_fraction'] is None
    report['epochs']['condition_retention']['1']['eligible']=7
    with pytest.raises(ValueError,match='eligible'):retention_rows(report)


@pytest.mark.parametrize('all_bad',[False,True])
def test_optional_repair_reports_each_condition_and_manual_bad(all_bad,tmp_path):
    from eegproc.epochs import repair_epochs
    raw=fixture()
    if all_bad:raw.set_annotations(mne.Annotations([0],[40],['BAD_manual']))
    events=np.array([[raw.first_samp+4*256,0,1],[raw.first_samp+10*256,0,2],[raw.first_samp+20*256,0,2]])
    epochs,r=repair_epochs(raw.copy(),raw,events,{'标准':1,'目标':2},save_path=tmp_path)
    assert r['condition_retention']['1']=={'input':1,'eligible':0 if all_bad else 1,'retained':0 if all_bad else 1}
    assert r['condition_retention']['2']=={'input':2,'eligible':0 if all_bad else 1,'retained':0 if all_bad else 1}
    assert len(r['records'])==3 and 'BAD_manual' in r['records'][1]['drop_reasons']
    assert len(epochs)==(0 if all_bad else 2)


def test_trial_update_escapes_names_and_image_storage(tmp_path):
    report={'status':'completed','config':{},'event_id':{'<script>alert(1)</script>':1,'目标':2},
            'epochs':{'input_events':16,'retained_epochs':10,'condition_retention':{
                '1':{'input':12,'eligible':10,'retained':8},'2':{'input':4,'eligible':4,'retained':2}}}}
    dest=tmp_path/'test_report.html'
    save_quality_report(report,dest)
    page=Path(report['outputs']['quality_report']).read_text(encoding='utf8')
    assert '<script>alert(1)</script>' not in page and '&lt;script&gt;' in page
    assert '10 / 16' in page
    assert 'src="data:image/png;base64,' in page
    assert report['human_review']['decision']=='pending' and not report['human_review']['automatic_acceptance']
    report['epochs']['retained_epochs']=8
    report['epochs']['condition_retention']['2']['retained']=0
    save_quality_report(report,dest)
    assert sum(f['key']=='epoch_retention' for f in report['visualizations']['figures'])==1
    assert '8 / 16' in Path(report['outputs']['quality_report']).read_text(encoding='utf8')


def test_failure_or_missing_plots_never_claim_success(tmp_path):
    report={'status':'failed','error':{'type':'ValueError','message':'Insufficient data'}}
    save_quality_report(report,tmp_path/'failed_report.html')
    assert not report['human_review']['processing_completed']
    assert report['human_review']['quality_warning_requires_review']
    assert not report['human_review']['automatic_acceptance']


def test_missing_sensor_geometry_still_writes_other_plots_without_mutation(tmp_path):
    raw=fixture();clean=raw.copy();raw.set_montage(None);clean.set_montage(None)
    before=raw.get_data().copy();after=clean.get_data().copy();ann=copy.deepcopy(raw.annotations)
    report={'status':'completed','config':{'highpass':.5,'lowpass':80,'line_frequency':50},'bad_channels':[],
            'ica':{'probabilities':[[.97,.005,.005,.005,.005,.005,.005]],'removed_components_0based':[]}}
    save_quality_report(report,tmp_path/'missing_report.html',original=raw,clean=clean)
    assert any(e['section']=='bad_channels' for e in report['visualizations']['errors'])
    assert any(f['key']=='psd' for f in report['visualizations']['figures'])
    assert report['status']=='completed' and report['human_review']['quality_warning_requires_review']
    np.testing.assert_array_equal(raw.get_data(),before);np.testing.assert_array_equal(clean.get_data(),after)
    assert raw.annotations==ann
    assert read_report((tmp_path/'missing_report.html').read_text(encoding='utf8'))['human_review']['decision']=='pending'


