"""Parameter changes and skipped epochs remain visible in standalone HTML."""
from dataclasses import asdict
import html
import json
import re

from eegproc import PipelineConfig
from eegproc.quality_report import save_quality_report


def render(tmp_path, **extra):
    report = dict(status='completed', config=asdict(PipelineConfig()),
                  outputs={}, quality_flags=[], **extra)
    target = tmp_path / 'subject_report.html'
    save_quality_report(report, target, reuse_figures=True)
    return target.read_text(encoding='utf8')


def section(document, name):
    return re.search(r'<section id="'+name+r'">(.*?)</section>', document, re.S).group(1)


def test_parameter_adjustments_are_visible_with_count_and_safe_escaping(tmp_path):
    requested = '<script>alert("requested")</script>'
    reason = 'Unsupported value <example> & fallback'
    records = [dict(field='highpass', requested=requested, effective=.5, reason=reason),
               dict(field='unknown_key', requested={'unsafe': '<img onerror="run()">'},
                    effective=None, reason='Unknown parameter ignored')]
    document = render(tmp_path, parameter_adjustments=records)
    summary = section(document, 'summary')
    assert '<td>Parameter adjustments</td><td>2</td>' in summary
    assert '<h2>Parameter adjustments</h2><p>2 recorded adjustments.</p>' in summary
    assert all('<th>'+title+'</th>' in summary for title in ['Parameter', 'Requested', 'Effective', 'Reason'])
    assert '<details' not in summary
    assert html.escape(requested, quote=True) in summary
    assert html.escape(reason, quote=True) in summary
    assert '<td>None</td>' in summary
    assert requested not in document and '<img onerror=' not in document
    payload = json.loads(re.search(r'<script id="run-record" type="application/json">(.*?)</script>', document, re.S).group(1))
    assert payload['parameter_adjustments'] == records


def test_no_adjustments_shows_zero_without_empty_extra_table(tmp_path):
    summary = section(render(tmp_path), 'summary')
    assert '<td>Parameter adjustments</td><td>0</td>' in summary
    assert '<h2>Parameter adjustments</h2>' not in summary


def test_skipped_epoch_reason_is_distinct_from_not_requested_and_escaped(tmp_path):
    reason = 'No events matched <target> & continuous data were retained.'
    document = render(tmp_path, epoch_resolution={'status': 'skipped', 'reason': reason})
    epochs = section(document, 'epochs')
    assert 'Epoching skipped.' in epochs and html.escape(reason, quote=True) in epochs
    assert 'not requested' not in epochs
    assert '<td>Epochs retained</td><td>Skipped</td>' in section(document, 'summary')


def test_unrequested_epochs_keep_existing_message(tmp_path):
    assert 'Epoching was not requested or has not been reached.' in section(render(tmp_path), 'epochs')
