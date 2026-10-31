"""Standalone epoching preserves data and works with optional report sources."""
from dataclasses import asdict
from pathlib import Path

import mne
import numpy as np
import pytest
from mne.utils import object_diff

from eegproc import PipelineConfig, epoch, render_report
from eegproc.epoching import build_epochs
from eegproc.epoch_metadata import save_epoch_metadata
from eegproc.epochs import EpochConfig
from eegproc.reporting import emit_report, read_report_source
from test_epoch_metadata import recording


def prepared(tmp_path):
    raw,events=recording(True)
    config=PipelineConfig(purpose='erp',epoch_mode='events',task_name='oddball')
    save_epoch_metadata(raw,config,['Pz'],tmp_path/'subject_report.html','subject')
    return raw,events,config


def write_source(path,config):
    record=dict(pipeline='eegproc',workflow_revision='0.4.0a2',status='completed',
                config=asdict(config),warnings=['Original report content'],quality_flags=[],outputs={})
    assert emit_report(record,path)
    return path.read_bytes()


def forbid(*args,**kwargs):
    raise AssertionError('Standalone epoching repeated continuous preprocessing')


def test_public_epoch_matches_shared_stage_without_any_cleaning_or_input_mutation(tmp_path,monkeypatch):
    raw,events,config=prepared(tmp_path)
    expected,qc=build_epochs(raw,config,events,{'target':1})
    before=raw.get_data().copy();info=raw.info.copy();ann=raw.annotations.copy()
    import eegproc.engine as engine
    import eegproc.backends as backends
    import eegproc.ica as ica
    import eegproc.signal_ops as signal_ops
    monkeypatch.setattr(engine,'preprocess_raw',forbid)
    for name in ('apply_filter','clean_line','detect_channels','reference'):
        monkeypatch.setattr(backends,name,forbid)
    monkeypatch.setattr(ica,'fit_ica',forbid);monkeypatch.setattr(ica,'apply_ica',forbid)
    monkeypatch.setattr(signal_ops,'_asr_segments',forbid)
    with pytest.warns(RuntimeWarning,match='No readable preprocessing report'):
        result=epoch(raw,tmp_path/'epochs','subject',events=events,event_id={'target':1},report=False)
    np.testing.assert_array_equal(result.epochs.get_data(),expected.get_data())
    np.testing.assert_array_equal(result.epochs.selection,expected.selection)
    assert result.epochs.drop_log==expected.drop_log
    assert result.report['epochs']['condition_retention']==qc['condition_retention']
    np.testing.assert_array_equal(raw.get_data(),before)
    assert object_diff(raw.info,info)=='' and raw.annotations==ann
    assert result.raw is None and result.report['epoching']['continuous_processing_repeated'] is False
    assert result.report['report_status']=='deferred'
    assert sorted(p.name for p in (tmp_path/'epochs').iterdir())==['subject_clean-epo.fif','subject_report_data.npz']
    # Deferred report rendering is likewise independent of any cleaning code.
    output=render_report(result,tmp_path/'epochs/subject_report.html')
    assert output.is_file()
    saved=read_report_source(output)
    assert saved['epochs']['retained_epochs']==len(expected)


def test_source_lookup_prefers_moved_fif_neighbor_and_retains_original_report(tmp_path):
    raw,events,config=prepared(tmp_path)
    hint=tmp_path/'subject_report.html'
    write_source(hint,config)
    moved=tmp_path/'moved';moved.mkdir()
    filename=moved/'subject_cont_raw.fif'
    raw.save(filename,fmt='double',overwrite=False,verbose=False)
    neighbor=moved/'subject_report.html'
    content=write_source(neighbor,config)
    with mne.io.read_raw_fif(filename,preload=False,verbose=False) as loaded:
        result=epoch(loaded,tmp_path/'epochs',events=events,event_id={'target':1})
    assert result.report['epoching']['source_report']==str(neighbor.resolve())
    assert neighbor.read_bytes()==content and hint.exists()
    assert result.report['warnings']==['Original report content']
    assert result.report['report_status']=='completed'


def test_manual_report_override_and_explicit_deletion_only_after_new_html(tmp_path):
    raw,events,config=prepared(tmp_path)
    first=tmp_path/'subject_report.html';write_source(first,config)
    chosen=tmp_path/'chosen.html';write_source(chosen,config)
    deferred=epoch(raw,tmp_path/'deferred','subject',events=events,event_id={'target':1},
                   source_report=chosen,keep_source_report=False,report=False)
    assert chosen.exists() and first.exists()
    assert deferred.report['epoching']['source_report']==str(chosen.resolve())
    result=epoch(raw,tmp_path/'immediate','subject',events=events,event_id={'target':1},
                 source_report=chosen,keep_source_report=False)
    assert result.report['report_status']=='completed'
    assert not chosen.exists() and first.exists()


@pytest.mark.parametrize('source',['missing','corrupt'])
def test_missing_or_corrupt_html_warns_but_does_not_block_epochs(tmp_path,source):
    raw,events,_=prepared(tmp_path)
    path=tmp_path/f'{source}.html'
    if source=='corrupt':path.write_text('<html>No run record</html>',encoding='utf8')
    with pytest.warns(RuntimeWarning):
        result=epoch(raw,tmp_path/'epochs',events=events,event_id={'target':1},source_report=path)
    assert result.epochs is not None and len(result.epochs)>0
    assert not result.report['epoching']['source_report_loaded']
    assert result.report['report_status']=='completed'


def test_missing_events_and_all_rejected_have_no_stale_epoch_file(tmp_path):
    raw,_,config=prepared(tmp_path)
    # No event annotations/STIM in this recording; do not invent a condition.
    with pytest.warns(RuntimeWarning):
        skipped=epoch(raw,tmp_path/'skipped',report=False)
    assert skipped.status=='skipped' and skipped.epochs is None
    assert set(skipped.outputs)=={'expected_report','report_data'}
    raw.annotations.append(raw.first_time,20.,'BAD_all')
    events=np.array([[raw.first_samp+512,0,1]])
    with pytest.warns(RuntimeWarning):
        rejected=epoch(raw,tmp_path/'rejected',events=events,event_id={'target':1})
    assert rejected.status=='review_required' and len(rejected.epochs)==0
    assert 'epochs' not in rejected.outputs
    assert sorted(p.name for p in (tmp_path/'rejected').iterdir())==['subject_report.html']


def test_fixed_epochs_and_qc_parameters_are_resolved_without_running_filters(tmp_path):
    raw,_,_=prepared(tmp_path)
    with pytest.warns(RuntimeWarning):
        result=epoch(raw,tmp_path/'fixed',epoch_mode='fixed',duration=2.,overlap=0.,
                     baseline=(-.2,0),highpass=5.,asr_cutoff=1.,report=False)
    assert result.report['effective_epoch_config']['tmin']==0
    assert result.report['effective_epoch_config']['tmax']==2.-1/256.
    assert result.epochs.baseline is None
    assert result.report['epochs']['annotation_policy']=='annotations'
    adjustments={row['field'] for row in result.report['parameter_adjustments']}
    assert {'highpass','asr_cutoff'}<=adjustments
    assert result.report['config']['highpass']==raw.info['highpass']


def test_failure_does_not_delete_source_report(tmp_path,monkeypatch):
    raw,events,config=prepared(tmp_path)
    source=tmp_path/'subject_report.html';content=write_source(source,config)
    import eegproc.epoching as module
    monkeypatch.setattr(module,'build_epochs',lambda *args,**kwargs: (_ for _ in ()).throw(ValueError('cannot epoch')))
    with pytest.raises(ValueError,match='cannot epoch'):
        epoch(raw,tmp_path/'failure',events=events,event_id={'target':1},source_report=source,
              keep_source_report=False)
    assert source.read_bytes()==content


def test_explicit_epoch_config_settings_survive_fif_and_explicit_keywords_win(tmp_path):
    raw,events,config=prepared(tmp_path)
    ec=EpochConfig(tmin=-.1,tmax=.6,baseline=None,peak_uv=9.,ptp_uv=22.,robust_z=7.,
                   relative_min_ptp_uv=15.,max_interpolate=2,max_local_fraction=.1,
                   min_fit_epochs=12,cv=3,seed=42)
    save_epoch_metadata(raw,config,['Pz'],tmp_path/'subject_report.html','subject',ec)
    filename=tmp_path/'subject_cont_raw.fif';raw.save(filename,fmt='double',overwrite=False,verbose=False)
    with mne.io.read_raw_fif(filename,preload=False,verbose=False) as loaded:
        with pytest.warns(RuntimeWarning):
            inherited=epoch(loaded,tmp_path/'inherited',events=events,event_id={'target':1},report=False)
        assert inherited.report['effective_epoch_config']==asdict(ec)
        with pytest.warns(RuntimeWarning):
            override=epoch(loaded,tmp_path/'overridden',events=events,event_id={'target':1},
                           tmin=-.3,peak_uv=12.,cv=4,report=False)
        actual=override.report['effective_epoch_config']
        assert actual['tmin']==-.3 and actual['peak_uv']==12. and actual['cv']==4
        assert actual['baseline'] is None


def test_source_report_bundle_is_discovered_when_html_was_deferred(tmp_path):
    raw,events,config=prepared(tmp_path)
    source=dict(pipeline='eegproc',workflow_revision='0.4.0a2',status='completed',
                config=asdict(config),warnings=[],quality_flags=[],outputs={})
    assert emit_report(source,tmp_path/'subject_report.html',generate=False)
    assert not (tmp_path/'subject_report.html').exists()
    result=epoch(raw,tmp_path/'epochs',events=events,event_id={'target':1})
    assert result.report['epoching']['source_report'].endswith('subject_report_data.npz')
    assert result.report['epoching']['source_report_loaded']
    assert result.report['report_status']=='completed'


def test_report_failure_keeps_original_html(tmp_path,monkeypatch):
    raw,events,config=prepared(tmp_path)
    source=tmp_path/'subject_report.html';content=write_source(source,config)
    import eegproc.reporting as module
    def fail(record,*args,**kwargs):
        record['report_status']='failed'
        return False
    monkeypatch.setattr(module,'emit_report',fail)
    result=epoch(raw,tmp_path/'failed_report',events=events,event_id={'target':1},
                 source_report=source,keep_source_report=False)
    assert result.epochs is not None and result.report['report_status']=='failed'
    assert source.read_bytes()==content


def test_merged_report_retains_parent_output_references_without_claiming_new_ica_files(tmp_path):
    raw,events,config=prepared(tmp_path)
    source_path=tmp_path/'subject_report.html'
    parent_outputs=dict(checkpoint=str(tmp_path/'subject_ica_review/checkpoint.json'),
                        ica=str(tmp_path/'subject-ica.fif'))
    parent=dict(pipeline='eegproc',workflow_revision='0.4.0a2',status='completed',
                config=asdict(config),warnings=[],quality_flags=[],outputs=parent_outputs.copy(),
                execution=[dict(stage='asr',status='completed')],elapsed_seconds=12.5,
                parameter_adjustments=[dict(field='example',requested=1,effective=2,reason='original')])
    assert emit_report(parent,source_path)
    result=epoch(raw,tmp_path/'epochs',events=events,event_id={'target':1})
    assert result.report['preprocessing_outputs']['checkpoint']==parent_outputs['checkpoint']
    assert result.report['preprocessing_outputs']['ica']==parent_outputs['ica']
    assert 'ica' not in result.outputs and 'checkpoint' not in result.outputs
    assert result.report['preprocessing_execution']==parent['execution']
    assert result.report['preprocessing_parameter_adjustments']==parent['parameter_adjustments']
    assert result.report['preprocessing_elapsed_seconds']==12.5
    assert result.report['epoching']['started_utc'] and result.report['epoching']['finished_utc']
    assert result.report['epoching']['elapsed_seconds']!=12.5
    again=epoch(raw,tmp_path/'again',events=events,event_id={'target':1},
                source_report=result.outputs['quality_report'],report=False)
    assert again.report['preprocessing_execution']==parent['execution']
    assert again.report['preprocessing_parameter_adjustments']==parent['parameter_adjustments']
    assert again.report['preprocessing_elapsed_seconds']==12.5


def test_source_capture_settings_are_inherited_and_unavailable_recapture_is_reported(tmp_path):
    raw,events,_=prepared(tmp_path)
    source_config=PipelineConfig(purpose='erp',epoch_mode='events',report_window_seconds=2.,
                                report_waveform_windows=1,report_max_channels=3,report_dpi=80,
                                report_max_width=900)
    source=dict(pipeline='eegproc',workflow_revision='0.4.0a2',status='completed',
                config=asdict(source_config),warnings=[],quality_flags=[],outputs={},
                event_id={'target':1},epochs=dict(input_events=1,retained_epochs=1,
                    condition_retention={'1':dict(input=1,eligible=1,retained=1)}))
    source_path=tmp_path/'subject_report.html';assert emit_report(source,source_path)
    inherited=epoch(raw,tmp_path/'inherited',events=events,event_id={'target':1},report=False)
    assert inherited.report['config']['report_window_seconds']==2.
    assert inherited.report['config']['report_waveform_windows']==1
    assert inherited.report['config']['report_dpi']==80
    changed=epoch(raw,tmp_path/'requested',events=events,event_id={'target':1},report=False,
                  report_window_seconds=4.,report_waveform_windows=3,report_max_channels=6,
                  report_dpi=120,report_max_width=1100)
    assert changed.report['config']['report_window_seconds']==2.
    assert changed.report['config']['report_waveform_windows']==1
    assert changed.report['config']['report_max_channels']==3
    assert changed.report['config']['report_dpi']==80
    assert changed.report['config']['report_max_width']==900
    adjustments={row['field']:row for row in changed.report['parameter_adjustments']}
    assert adjustments['report_window_seconds']['requested']==4.
    assert adjustments['report_window_seconds']['effective']==2.
