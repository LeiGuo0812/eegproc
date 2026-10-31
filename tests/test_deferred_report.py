"""Report material is compact and plotting can be postponed across sessions."""
from copy import deepcopy
from dataclasses import asdict

import mne
import numpy as np
import pytest

from eegproc import PipelineResult, render_report, resolve_config
from eegproc.reporting import emit_report, read_report_source, _read_html
from test_pipeline import fixture


def report_record():
    return dict(status='completed', config=asdict(resolve_config(report_psd_windows=3)),
        bad_channels=[], quality_flags=[], warnings=[], outputs={},
        input_summary=dict(sfreq=256., n_times=10240, duration_seconds=40.),
        provenance=dict(subject_label='subject'), event_id={'target': 1},
        epochs=dict(input_events=5, retained_epochs=4,
                    condition_retention={'1': dict(input=5, eligible=4, retained=4)}))


def forbidden(*args, **kwargs):
    raise AssertionError('Deferred report must use captured numeric material')


def test_deferred_capture_does_not_plot_and_render_needs_no_raw_or_ica(tmp_path, monkeypatch):
    import eegproc.quality_figures as figures
    import eegproc.ica as ica_module
    original = fixture()
    clean = original.copy()
    clean._data[:12] *= .7
    clean.annotations.append(clean.first_time + 24, 1., 'BAD_residual')
    before = original.get_data().copy()
    after = clean.get_data().copy()
    annotations = clean.annotations.copy()
    training = original.copy().pick('eeg')
    model = mne.preprocessing.ICA(n_components=4, method='picard', random_state=7,
                                 max_iter=100, verbose=False)
    with pytest.warns(RuntimeWarning, match='high-pass'):
        model.fit(training, verbose=False)
    record = report_record()
    record['ica'] = dict(probabilities=[[.95, .01, .01, .01, .01, .005, .005]] * 4,
                         removed_components_0based=[1], automatic_proposal_0based=[1],
                         decision_status='automatic')
    record['config']['report_full_record_heatmap'] = True
    immediate = deepcopy(record)
    assert emit_report(immediate, tmp_path/'immediate_report.html', original=original,
                       clean=clean, ica=model, training=training)
    expected = _read_html(tmp_path/'immediate_report.html')
    deferred = deepcopy(record)
    folder = tmp_path/'deferred'
    with monkeypatch.context() as patch:
        patch.setattr(figures, 'figure', forbidden)
        patch.setattr(figures, 'asset', forbidden)
        assert emit_report(deferred, folder/'subject_report.html', generate=False,
                           original=original, clean=clean, ica=model, training=training)
    assert deferred['report_status'] == 'deferred'
    assert 'quality_report' not in deferred['outputs']
    bundle = folder/'subject_report_data.npz'
    assert sorted(p.name for p in folder.iterdir()) == [bundle.name]
    with np.load(bundle, allow_pickle=False) as archive:
        assert all(not archive[key].dtype.hasobject for key in archive.files)
    assert bundle.stat().st_size < original.get_data().nbytes
    restored = read_report_source(bundle)
    assert restored['report_materials']['waveforms']['records'] == expected['visualizations']['waveform_windows']
    assert restored['report_materials']['psd']['metadata'] == expected['visualizations']['psd_sampling']
    with monkeypatch.context() as patch:
        for module, name in [(mne.io, 'read_raw_fif'), (mne.preprocessing, 'read_ica'),
                             (ica_module, 'fit_ica'), (ica_module, 'apply_ica')]:
            patch.setattr(module, name, forbidden)
        patch.setattr(mne.preprocessing.ICA, 'get_sources', forbidden)
        patch.setattr(mne.preprocessing.ICA, 'get_components', forbidden)
        target = render_report(bundle, folder/'subject_report.html')
    actual = _read_html(target)
    assert actual['report_status'] == 'completed'
    assert not actual['visualizations']['errors']
    assert actual['ica_diagnostics'] == expected['ica_diagnostics']
    assert actual['metadata_audit'] == expected['metadata_audit']
    assert {f['key']: f['sha256'] for f in actual['visualizations']['figures']} == {
        f['key']: f['sha256'] for f in expected['visualizations']['figures']}
    np.testing.assert_array_equal(original.get_data(), before)
    np.testing.assert_array_equal(clean.get_data(), after)
    assert clean.annotations == annotations


def test_epoch_only_deferred_result_and_archive_rebuild_without_signal_material(tmp_path):
    record = report_record()
    assert emit_report(record, tmp_path/'subject_report.html', generate=False)
    result = PipelineResult(None, record, {})
    target = render_report(result, tmp_path/'final_report.html')
    actual = _read_html(target)
    assert actual['epochs']['retained_epochs'] == 4
    assert [f['key'] for f in actual['visualizations']['figures']] == ['epoch_retention']
    assert record['report_status'] == 'deferred'
    assert not (tmp_path/'subject_report.html').exists()


def test_reused_html_can_receive_new_epoch_counts_without_mutating_source(tmp_path):
    from test_report_rebuild import legacy_report
    source, _, _ = legacy_report(tmp_path)
    original = source.read_bytes()
    record = read_report_source(source)
    record['epochs'] = dict(input_events=6, retained_epochs=2,
        condition_retention={'1': dict(input=6, eligible=4, retained=2)})
    assert emit_report(record, tmp_path/'epoch_report.html')
    updated = _read_html(tmp_path/'epoch_report.html')
    assert updated['epochs']['retained_epochs'] == 2
    assert source.read_bytes() == original
    assert sum(f['key'] == 'epoch_retention' for f in updated['visualizations']['figures']) == 1
    assert updated['ica_diagnostics'][0]['component'] == 0


def test_existing_deferred_archive_is_not_overwritten(tmp_path):
    record = report_record()
    assert emit_report(record, tmp_path/'subject_report.html', generate=False)
    bundle = tmp_path/'subject_report_data.npz'
    before = bundle.read_bytes()
    assert not emit_report(report_record(), tmp_path/'subject_report.html', generate=False)
    assert bundle.read_bytes() == before


def test_deferred_explicit_source_removal_waits_for_completed_html(tmp_path):
    from test_report_rebuild import legacy_report
    source, _, _ = legacy_report(tmp_path)
    record = read_report_source(source)
    record['epoching'] = dict(source_report=str(source), source_report_loaded=True,
                             keep_source_report=False)
    assert emit_report(record, tmp_path/'epoch_report.html', generate=False)
    assert source.exists()
    render_report(tmp_path/'epoch_report_data.npz', tmp_path/'epoch_report.html')
    assert not source.exists()
    assert (tmp_path/'subject_cont_raw.fif').exists()


def test_report_archive_preserves_user_dictionary_keys(tmp_path):
    from eegproc.report_data import save_report_data, read_report_data
    record = report_record()
    record['user_fields'] = [{'__report_array__': 'a user value'},
                             {'__report_mapping__': [1, 2]}]
    save_report_data(record, tmp_path/'report.npz')
    assert read_report_data(tmp_path/'report.npz')['user_fields'] == record['user_fields']


def test_render_uses_selected_target_without_retaining_deferred_hint(tmp_path):
    record=report_record()
    assert emit_report(record,tmp_path/'planned_report.html',generate=False)
    render_report(PipelineResult(None,record,{}),tmp_path/'selected_report.html')
    final=_read_html(tmp_path/'selected_report.html')
    assert 'expected_report' not in final['outputs']
    assert final['outputs']['quality_report']==str(tmp_path/'selected_report.html')
    assert record['outputs']['expected_report']==str(tmp_path/'planned_report.html')


@pytest.mark.parametrize('status',['failed','skipped'])
def test_incomplete_epoching_preserves_source_after_delayed_render(tmp_path,status):
    from test_report_rebuild import legacy_report
    source,_,_=legacy_report(tmp_path)
    record=read_report_source(source)
    record.update(status=status,epoching=dict(source_report=str(source),source_report_loaded=True,
                                             keep_source_report=False))
    assert emit_report(record,tmp_path/'epoch_report.html',generate=False)
    render_report(tmp_path/'epoch_report_data.npz',tmp_path/'epoch_report.html')
    assert source.exists()


def test_epoch_report_retains_reused_checkpoint_reference(tmp_path):
    from test_report_rebuild import legacy_report
    source,_,_=legacy_report(tmp_path)
    record=read_report_source(source)
    record['preprocessing_outputs']=record.pop('outputs')
    record['outputs']={}
    record['epoching']=dict(source_report=str(source),source_report_loaded=True)
    assert emit_report(record,tmp_path/'epoch_report.html')
    text=(tmp_path/'epoch_report.html').read_text(encoding='utf8')
    assert 'Checkpoint: <code>'+str(tmp_path/'checkpoint.json')+'</code>' in text
    final=_read_html(tmp_path/'epoch_report.html')
    reused=[row for row in final['report_audit']['data_files'] if row['kind']=='checkpoint']
    assert len(reused)==1 and reused[0]['reused'] and not reused[0]['produced_this_run']


def test_epoch_report_separates_preprocessing_and_epoch_execution(tmp_path):
    from test_report_rebuild import legacy_report
    source,_,_=legacy_report(tmp_path)
    record=read_report_source(source)
    record.update(preprocessing_execution=[dict(stage='asr',status='completed',elapsed_seconds=25.)],
                  preprocessing_parameter_adjustments=[dict(field='lowpass',requested=200.,effective=100.,reason='Previous adjustment')],
                  preprocessing_elapsed_seconds=90.,elapsed_seconds=2.,
                  execution=[dict(stage='epochs',status='completed',elapsed_seconds=2.)])
    record['epoching']=dict(source_report=str(source),source_report_loaded=True,
                            started_utc='2026-10-31T00:00:00+00:00',
                            finished_utc='2026-10-31T00:00:02+00:00',elapsed_seconds=2.)
    assert emit_report(record,tmp_path/'epoch_report.html')
    text=(tmp_path/'epoch_report.html').read_text(encoding='utf8')
    assert 'Recorded preprocessing execution' in text
    assert 'Recorded preprocessing parameter adjustments' in text
    assert 'Previous adjustment' in text
    assert 'Epoching elapsed' in text and '2.00 s' in text
    assert 'Preprocessing elapsed' in text and '90.00 s' in text
    final=_read_html(tmp_path/'epoch_report.html')
    assert final['execution']==record['execution']
    assert final['preprocessing_execution']==record['preprocessing_execution']
