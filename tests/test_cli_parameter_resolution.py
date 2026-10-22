"""CLI science settings use the same audited policy as the Python API."""
import json

import mne
import numpy as np
import pytest

from eeg_pipeline import api, cli


@pytest.fixture
def invoke_cli(monkeypatch, tmp_path):
    captured = []
    raw = object()
    monkeypatch.setattr(cli.mne.io, 'read_raw_fif', lambda *args, **kwargs: raw)

    def run(prepared, save_path, subject, **kwargs):
        assert prepared is raw
        captured.append(kwargs)
        return api.PipelineResult(raw, {
            'status': 'completed', 'quality_flags': [], 'outputs': {},
        }, {})

    monkeypatch.setattr(api, 'run', run)

    def invoke(*arguments):
        cli.main([
            '--input-fif', str(tmp_path / 'source_raw.fif'),
            '--save-path', str(tmp_path / 'output'), '--subject', 'subject',
            *arguments,
        ])
        return captured[-1]

    return invoke


@pytest.mark.parametrize('flag,field,default', [
    ('--preset', 'preset', 'standard'),
    ('--purpose', 'purpose', 'rest'),
    ('--filter-method', 'filter_method', 'mne_fir'),
    ('--filter-position', 'filter_position', 'after_reference'),
    ('--line-method', 'line_method', 'spectrum_fit'),
    ('--channel-method', 'channel_method', 'pyprep'),
    ('--reference', 'reference', 'average'),
    ('--rank-method', 'rank_method', 'relative'),
    ('--ica-rule', 'ica_rule', 'threshold'),
    ('--ica-method', 'ica_method', 'picard'),
    ('--bad-channel-policy', 'bad_channel_policy', 'report'),
    ('--epoch-mode', 'epoch_mode', 'none'),
    ('--epoch-qc', 'epoch_qc', 'auto'),
    ('--event-source', 'event_source', 'auto'),
    ('--highpass', 'highpass', .5),
    ('--asr-cutoff', 'asr_cutoff', 20.),
    ('--line-frequency', 'line_frequency', 50.),
    ('--seed', 'seed', 20261018),
    ('--n-threads', 'n_threads', 1),
    ('--report-dpi', 'report_dpi', 100),
])
def test_invalid_science_values_reach_central_resolver(invoke_cli, flag, field, default):
    call = invoke_cli(flag, 'invalid')
    config = call['config']
    assert getattr(config, field) == default
    assert any(record['field'] == field for record in config.adjustments)
    assert call['invocation']['explicit_overrides'][field] == 'invalid'


def test_invalid_numeric_value_uses_selected_purpose_default(invoke_cli):
    config = invoke_cli('--purpose', 'erp', '--highpass', 'invalid')['config']
    assert config.purpose == 'erp' and config.highpass == .1
    assert any(record['field'] == 'highpass' for record in config.adjustments)


def test_valid_numbers_and_manual_indices_retain_types_and_values(invoke_cli):
    call = invoke_cli(
        '--purpose', 'erp', '--highpass', '.2', '--lowpass', '40',
        '--seed', '7', '--n-threads', '2', '--line-frequency', '60',
        '--asr-cutoff', 'off', '--ica-mode', 'manual', '--ica-exclude', '0', '3',
        '--baseline', 'none', '0',
    )
    config = call['config']
    assert config.highpass == .2 and config.lowpass == 40.
    assert config.seed == 7 and isinstance(config.seed, int)
    assert config.n_threads == 2 and config.line_frequency == 60.
    assert config.asr_cutoff is None and config.ica_exclude == (0, 3)
    assert config.ica_mode == 'manual' and config.epoch_baseline == (None, 0.)
    assert not config.adjustments


@pytest.mark.parametrize('indices', [('bad-index',), ('0', '-1'), ('2.5',)])
def test_invalid_manual_list_keeps_all_and_never_switches_to_automatic(invoke_cli, indices):
    config = invoke_cli('--ica-mode', 'manual', '--ica-exclude', *indices)['config']
    assert config.ica_mode == 'manual' and config.ica_exclude == ()
    assert any(record['field'] == 'ica_exclude' for record in config.adjustments)


@pytest.mark.parametrize('endpoints', [('bad-endpoint',), ('none', 'bad-endpoint'), ('0', '1', '2')])
def test_malformed_baseline_is_audited_configuration_value(invoke_cli, endpoints):
    config = invoke_cli('--baseline', *endpoints)['config']
    assert config.epoch_baseline == (None, 0.)
    assert any(record['field'] == 'epoch_baseline' for record in config.adjustments)


def test_json_override_types_and_unknown_keys_use_central_policy(invoke_cli):
    config = invoke_cli('--set', 'highpass=true', '--set', 'unknown_option=1')['config']
    assert config.highpass == .5
    assert {'highpass', 'unknown_option'} <= {record['field'] for record in config.adjustments}


@pytest.mark.parametrize('arguments', [
    ('--unrecognized-option', '1'),
    ('--set', 'missing-assignment'),
    ('--set', 'highpass=not-json'),
    ('--epochs', '--fixed-epochs', '2'),
])
def test_cli_grammar_errors_remain_errors(invoke_cli, arguments):
    with pytest.raises(SystemExit) as error:
        invoke_cli(*arguments)
    assert error.value.code == 2


def test_missing_required_input_remains_error():
    with pytest.raises(SystemExit) as error:
        cli.parser().parse_args(['--save-path', 'output', '--subject', 'subject'])
    assert error.value.code == 2


@pytest.mark.parametrize('content', [None, '{broken json', '{"events": []}', '[]'])
def test_unusable_explicit_event_json_is_audited_and_skips_epochs_without_annotation_fallback(
        invoke_cli, tmp_path, content):
    source = tmp_path/'explicit.events.json'
    if content is not None:
        source.write_text(content, encoding='utf8')
    call = invoke_cli('--epochs', '--events-json', str(source))
    assert call['events']==[] and call['event_id'] is None
    assert any(record['field']=='events_json' and record['requested']==str(source)
               for record in call['config'].adjustments)
    assert str(source) in call['invocation']['input_paths']
    # A valid annotation must not replace the explicitly requested failed file.
    from eeg_pipeline.engine import _resolve_epoch_request
    raw=mne.io.RawArray(np.zeros((1,1024)),mne.create_info(['Cz'],256.,'eeg'),verbose=False)
    raw.set_annotations(mne.Annotations([1.], [0.], ['target']))
    config,events,event_id,epoch_config,resolution=_resolve_epoch_request(
        raw,call['config'],call['events'],call['event_id'],None)
    assert config.epoch_mode=='none' and resolution['status']=='skipped'
    assert events is None and event_id is None and epoch_config is None


def test_empty_automatic_sidecar_uses_annotations_but_corrupt_sidecar_is_audited(invoke_cli, tmp_path):
    sibling=tmp_path/'source_raw.events.json'
    sibling.write_text(json.dumps({'events': [], 'event_id': {}}),encoding='utf8')
    call=invoke_cli('--epochs')
    assert call['events'] is None and call['event_id'] is None
    assert not any(record['field']=='events_json' for record in call['config'].adjustments)
    sibling.write_text('{broken json',encoding='utf8')
    call=invoke_cli('--epochs')
    assert call['events']==[]
    assert any(record['field']=='events_json' for record in call['config'].adjustments)
