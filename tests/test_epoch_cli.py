"""Public adapters keep epoching and reporting separate from continuous cleaning."""
import json
from pathlib import Path
import tomllib

import mne
import numpy as np

from eegproc import PipelineResult, run


def test_new_console_commands_are_in_the_distribution():
    root = Path(__file__).resolve().parents[1]
    entries = tomllib.loads((root/'pyproject.toml').read_text(encoding='utf8'))['project']['scripts']
    assert entries['eegproc-epoch'] == 'eegproc.epoch_cli:main'
    assert entries['eegproc-report'] == 'eegproc.report_cli:main'


def test_report_switch_is_not_a_scientific_parameter(monkeypatch, tmp_path):
    from eegproc import engine
    calls = []
    def capture(raw, out, subject, **kwargs):
        calls.append(kwargs)
        return raw, dict(status='completed', outputs={}), {}
    monkeypatch.setattr(engine, 'preprocess_raw', capture)
    raw = object()
    result = run(raw, tmp_path, 'subject', report=False)
    assert result.raw is raw and result.epochs is None
    assert calls[-1]['generate_report'] is False
    assert not calls[-1]['config'].adjustments
    assert calls[-1]['config'].asr_cutoff == 20


def test_epoch_cli_passes_events_and_runtime_options(monkeypatch, tmp_path, capsys):
    import eegproc.api
    from eegproc.epoch_cli import main
    raw = mne.io.RawArray(np.zeros((8, 1280)), mne.create_info(8, 128., 'eeg'), verbose=False)
    source = tmp_path/'processed_cont_raw.fif'
    raw.save(source, overwrite=False, verbose=False)
    events = [[256, 0, 1]]
    sidecar = tmp_path/'events.json'
    sidecar.write_text(json.dumps(dict(events=events, event_id={'target': 1})))
    calls = []
    def capture(raw, out, subject, **kwargs):
        assert raw.n_times == 1280
        calls.append(kwargs)
        return PipelineResult(None, dict(status='completed', outputs={}, report_status='deferred'), {})
    monkeypatch.setattr(eegproc.api, 'epoch', capture)
    main(['--input-fif', str(source), '--save-path', str(tmp_path/'out'),
          '--events-json', str(sidecar), '--source-report', str(tmp_path/'previous.html'),
          '--no-report', '--no-keep-source-report', '--tmin', '-0.3', '--tmax', '0.8',
          '--baseline', 'off', '--set', 'ptp_uv=180'])
    call = calls[-1]
    assert call['report'] is False and call['keep_source_report'] is False
    assert call['events'] == events and call['event_id'] == {'target': 1}
    assert call['baseline'] is None and call['tmin'] == -.3 and call['tmax'] == .8
    assert call['ptp_uv'] == 180
    assert json.loads(capsys.readouterr().out)['report_status'] == 'deferred'


def test_report_cli_uses_the_same_renderer(monkeypatch, tmp_path, capsys):
    import eegproc.api
    from eegproc.report_cli import main
    calls = []
    def render(source, output):
        calls.append((source, output))
        return Path(output)
    monkeypatch.setattr(eegproc.api, 'render_report', render)
    main(['--source', 'subject_report_data.npz', '--output', str(tmp_path/'report.html')])
    assert calls == [('subject_report_data.npz', str(tmp_path/'report.html'))]
    assert json.loads(capsys.readouterr().out)['status'] == 'completed'
