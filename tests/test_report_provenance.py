from report_helpers import read_report
"""Report integrity is separate from scientific acceptance of a recording."""
import csv
import json
from pathlib import Path
import numpy as np
import pytest
from eegproc.report_provenance import StageRecorder,capture_signal_audit,methods_text,capture_provenance
from eegproc.quality_figures import full_record_qc,style
from test_pipeline import fixture


def test_stages_distinguish_complete_skip_and_failure():
    r={};s=StageRecorder(r);s.start('channel_detection');s.skip('asr','Disabled');s.start('ica');s.finish('failed','controlled')
    assert [x['status'] for x in r['execution']]==['completed','skipped','failed']
    assert r['execution'][-1]['message']=='controlled' and all(x['elapsed_seconds']>=0 for x in r['execution'])


def test_actual_metadata_audit_detects_duplicate_annotation_loss_and_aux_change():
    raw=fixture();raw.annotations.append(raw.annotations[0]['onset'],0,'target')
    clean=raw.copy();clean.annotations.delete([0]);clean._data[-2,0]+=1
    r={};capture_signal_audit(r,raw,clean)
    assert r['metadata_audit']['checks']['annotations'] is False
    assert r['metadata_audit']['checks']['auxiliary_data'] is False
    assert r['metadata_audit']['checks']['sample_grid'] is True
    assert r['continuous_segments']['nonbad_segment_count']==2
    assert r['continuous_segments']['longest_seconds']==29.


def test_whole_run_metrics_have_exact_clock_partial_bin_and_scaling(tmp_path):
    raw=fixture().crop(tmax=3.5,include_tmax=False);clean=raw.copy();clean._data[:12]*=.5
    clean.annotations.append(raw.first_time+1,.5,'BAD_residual')
    before=raw.get_data().copy();after=clean.get_data().copy()
    with style():fig,rows,meta=full_record_qc(raw,clean,raw.ch_names[:12],[],tmp_path)
    assert len(rows)==4 and rows[-1]['duration_seconds']==.5
    assert rows[1]['output_bad_fraction']==.5 and rows[1]['input_bad_fraction']==0.
    assert rows[0]['start_sample']==0 and rows[-1]['stop_sample']==raw.n_times
    for r in rows:assert np.isclose(r['output_max_ptp_uv'],r['input_max_ptp_uv']*.5)
    np.testing.assert_array_equal(before,raw.get_data());np.testing.assert_array_equal(after,clean.get_data())


def test_tables_define_every_column_and_do_not_claim_stale_output_as_current(tmp_path):
    raw=fixture();report=dict(status='failed',config={},outputs={},execution=[],first_samp=raw.first_samp,input_summary={'sfreq':256.})
    capture_signal_audit(report,raw,raw.copy())
    stale=tmp_path/'old_raw.fif';stale.write_bytes(b'old file');report['outputs']['raw']=str(stale)
    report['event_id']={'标准':1}
    report['epochs']={'input_events':1,'retained_epochs':0,'condition_retention':{'1':{'input':1,'eligible':0,'retained':0}},
        'records':[dict(input_event_index=0,event_sample=raw.first_samp+256,condition=1,retained=False,drop_reasons=['BAD_manual'],interpolated_channels=[])]}
    from eegproc.quality_report import save_quality_report
    save_quality_report(report,tmp_path/'sub_report.html')
    assert not report['report_audit']['data_files'][0]['produced_this_run']
    assert report['report_audit']['data_files'][0]['exists']
    assert 'Processing is incomplete' in methods_text(report)
    assert report['report_audit']['tables']=={}
    assert not list(tmp_path.glob('*.tsv'))
    assert 'Channel table' in (tmp_path/'sub_report.html').read_text(encoding='utf8')


def test_provenance_has_source_hashes_without_claiming_bids_or_inventing_command():
    p=capture_provenance(fixture(),'example')
    assert p['software']['source_files_sha256']['eegproc/pipeline.py']
    assert p['software']['packages']['mne']!='not installed'
    assert not p['compliance']['bids_validated'] and p['invocation']['argv'] is None
    assert p['sources']==[]


def test_pipeline_failure_saves_failed_step_without_claiming_unwritten_data(tmp_path,monkeypatch):
    """Fresh output family: collisions are rejected separately before processing."""
    import eegproc.pipeline as pipeline
    raw=fixture();unwritten=tmp_path/'failure_cont_raw.fif'
    def fail(*args,**kwargs):raise RuntimeError('controlled ICA failure')
    import eegproc.engine as engine
    monkeypatch.setattr(engine,'fit_ica',fail)
    with pytest.raises(RuntimeError,match='controlled ICA'):
        pipeline.preprocess_raw(raw,tmp_path,'failure',config=pipeline.config_for(asr_backend='mne_native',asr_cutoff=None,detect_ransac=False))
    report=read_report((tmp_path/'failure_report.html').read_text(encoding='utf8'))
    assert report['execution'][-1]['stage']=='ica_fit' and report['execution'][-1]['status']=='failed'
    assert any(s['stage']=='asr' and s['status']=='skipped' for s in report['execution'])
    assert not report['human_review']['processing_completed'] and not report['human_review']['automatic_acceptance']
    assert not report['report_audit']['data_files'][0]['produced_this_run'] and not unwritten.exists()
