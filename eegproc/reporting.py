"""Rebuild report presentation from recorded plots, without signal processing."""
from __future__ import annotations

import base64
from copy import deepcopy
import hashlib
from html.parser import HTMLParser
import json
from os import PathLike
from pathlib import Path
import re


class _EmbeddedReport(HTMLParser):
    """Read only inert JSON script payloads and embedded image attributes."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.scripts = {}
        self.images = []
        self._script_id = None
        self._parts = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'script' and attributes.get('id') in ('run-record', 'component-data'):
            identifier = attributes['id']
            if identifier in self.scripts:
                raise ValueError(f'Duplicate embedded report record: {identifier}')
            if attributes.get('type') != 'application/json':
                raise ValueError(f'Embedded {identifier} must be application/json')
            self._script_id = identifier
            self._parts = []
        elif tag == 'img' and attributes.get('src', '').startswith('data:image/'):
            self.images.append(attributes)

    def handle_data(self, data):
        if self._script_id is not None:
            self._parts.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self._script_id is not None:
            self.scripts[self._script_id] = ''.join(self._parts)
            self._script_id = None
            self._parts = []


def _read_html(path):
    document = Path(path).read_text(encoding='utf-8-sig')
    parser = _EmbeddedReport()
    parser.feed(document)
    try:
        report = json.loads(parser.scripts['run-record'])
        components = json.loads(parser.scripts.get('component-data', '{}'))
    except (KeyError, json.JSONDecodeError) as exc:
        raise ValueError('HTML has no usable machine-readable run record') from exc
    if not isinstance(report, dict) or not isinstance(report.get('config'), dict) or not isinstance(report.get('status'), str):
        raise ValueError('HTML has no usable machine-readable run record')
    if not isinstance(components, dict) or not isinstance(components.get('components', []), list):
        raise ValueError('HTML component diagnostics are malformed')
    details = components.get('components', [])
    _restore_images(report, parser.images, details)
    report['ica_diagnostics'] = deepcopy(details)
    return report


def _restore_images(report, images, details):
    figures = report.get('visualizations', {}).get('figures', [])
    if not isinstance(figures, list):
        raise ValueError('HTML figure inventory is malformed')
    by_key = {image['data-figure-key']: image['src'] for image in images if image.get('data-figure-key')}
    by_alt = {}
    for image in images:
        by_alt.setdefault(image.get('alt', ''), []).append(image['src'])
    # Older standalone reports omit explicit image keys. IC maps have stable
    # diagnostic keys and component-specific alt text, other plots use titles.
    for detail in details:
        key = detail.get('topomap_key')
        alternatives = by_alt.get(f"IC {detail.get('component')} topography", [])
        if key and len(set(alternatives)) == 1:
            by_key.setdefault(key, alternatives[0])
    missing = []
    for figure in figures:
        uri = figure.get('data_uri') or by_key.get(figure.get('key'))
        if not uri:
            alternatives = by_alt.get(figure.get('title', ''), [])
            if len(set(alternatives)) == 1:
                uri = alternatives[0]
        if uri:
            figure['data_uri'] = uri
        else:
            missing.append(figure.get('key', '<unnamed>'))
    if missing:
        raise ValueError('Report is missing recorded embedded images: '+', '.join(missing))


def _check_record(report):
    if not isinstance(report, dict) or not isinstance(report.get('status'), str) or not isinstance(report.get('config'), dict):
        raise ValueError('Source has no usable machine-readable run record')
    if report.get('report_materials') is not None:
        return
    figures = report.get('visualizations', {}).get('figures', [])
    if not figures:
        raise ValueError('Source has no usable embedded images; waveform redraw requires the original data')
    for figure in figures:
        uri = figure.get('data_uri', '')
        if not re.match(r'^data:image/(png|jpeg|webp);base64,', uri):
            raise ValueError(f"Recorded image is unavailable or unsupported: {figure.get('key')}")
        try:
            payload = base64.b64decode(uri.split(',', 1)[1], validate=True)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"Invalid embedded image: {figure.get('key')}") from exc
        if not payload or (figure.get('sha256') and hashlib.sha256(payload).hexdigest() != figure['sha256']):
            raise ValueError(f"Embedded image integrity check failed: {figure.get('key')}")
    probabilities = report.get('ica', {}).get('probabilities', [])
    details = report.get('ica_diagnostics', [])
    if probabilities and ({d.get('component') for d in details} != set(range(len(probabilities)))):
        raise ValueError('Source does not contain complete ICA component diagnostics')


def read_report_source(source):
    """Read a result, HTML or report-data archive without reading EEG files."""
    from .api import PipelineResult
    if isinstance(source, PipelineResult):
        report = deepcopy(source.report)
        outputs = report.get('outputs', {})
        path = outputs.get('report_data') or outputs.get('quality_report')
        figures = report.get('visualizations', {}).get('figures', [])
        missing = any(not figure.get('data_uri') for figure in figures)
        if path and (missing or (report.get('report_status') == 'deferred' and 'report_materials' not in report)):
            return read_report_source(path)
        return report
    if not isinstance(source, (str, PathLike)):
        raise TypeError('source must be a result, HTML report or report-data archive')
    path = Path(source)
    if path.suffix.lower() == '.npz':
        from .report_data import read_report_data
        return read_report_data(path)
    return _read_html(path)


def emit_report(record, path, *, generate=True, original=None, clean=None, ica=None, training=None):
    """Write HTML now, or collect numeric display material for later plotting."""
    from .quality_report import safe_report
    target = Path(path).resolve()
    if generate:
        record.setdefault('outputs', {}).pop('expected_report', None)
        return safe_report(record, target, original=original, clean=clean, ica=ica, training=training)
    outputs = record.setdefault('outputs', {})
    outputs.pop('quality_report', None)
    outputs['expected_report'] = str(target)
    bundle = target.with_name(target.stem + '_data.npz')
    record['processing_status'] = record.get('status', 'unknown')
    record['delivery_status'] = ('completed' if record.get('status') in
        ('completed', 'review_required', 'awaiting_ica_review') else 'incomplete')
    record['report_status'] = 'deferred'
    try:
        if original is not None and clean is not None:
            from .quality_figures import collect_report_materials
            from .report_provenance import capture_signal_audit
            record['report_materials'] = collect_report_materials(record, original, clean, ica, training)
            capture_signal_audit(record, original, clean)
        outputs['report_data'] = str(bundle)
        from .report_data import save_report_data
        save_report_data(record, bundle)
        return True
    except Exception as exc:
        outputs.pop('report_data', None)
        record['report_status'] = 'failed'
        record['report_error'] = dict(type=type(exc).__name__, message=str(exc))
        return False


def render_report(source, report_path: str | PathLike[str]) -> Path:
    """Render current HTML layout from a PipelineResult or a previous HTML.

    Existing HTML plots are reused exactly. Deferred numeric material is plotted
    without loading Raw/FIF or rerunning filters, ASR, ICA or epoching.
    The target must be a new HTML file; source results and their provenance are
    unchanged. Waveform windows and other plot settings cannot be changed here.
    """
    from .api import PipelineResult
    from .quality_report import safe_report
    from .report_provenance import file_hash, utc_now
    from . import __version__

    target = Path(report_path).resolve()
    if target.suffix.lower() != '.html':
        raise ValueError('report_path must end in .html')
    if target.exists():
        raise FileExistsError('Report target already exists; choose a new HTML path')
    source_path = None
    if isinstance(source, PipelineResult):
        path = source.report.get('outputs', {}).get('report_data') or source.report.get('outputs', {}).get('quality_report')
        if path and Path(path).is_file():
            source_path = Path(path).resolve()
        report = read_report_source(source)
    elif isinstance(source, (str, PathLike)):
        source_path = Path(source).resolve()
        report = read_report_source(source_path)
    else:
        raise TypeError('source must be a PipelineResult, HTML report or report-data archive')
    deferred = report.get('report_status') == 'deferred' or 'report_materials' in report
    if not deferred:
        _check_record(report)
    if source_path == target:
        raise ValueError('The report source must remain unchanged; choose another HTML path')
    prior = deepcopy(report.get('report_generation'))
    report['report_generation'] = dict(
        schema='eeg-report-render-v1', generated_utc=utc_now(), renderer_version=__version__,
        source_report=str(source_path) if source_path else None,
        source_report_sha256=file_hash(source_path) if source_path else None,
        reused_embedded_figures=not deferred, reused_component_diagnostics=True,
        signal_processing_repeated=False, waveform_redrawn=bool(report.get('report_materials')),
        renderer_sha256={name:file_hash(Path(__file__).with_name(name))
                         for name in ('reporting.py','quality_report.py','report_layout.py')},
    )
    if prior:
        report['report_generation']['previous_generation'] = prior
    report.setdefault('outputs', {}).pop('expected_report', None)
    if not safe_report(report,target,reuse_figures=not deferred):
        error = report.get('report_error', {}).get('message', 'unknown rendering error')
        raise RuntimeError('Report rendering failed: '+error)
    epoching = report.get('epoching', {})
    previous = epoching.get('source_report')
    if (previous and epoching.get('keep_source_report', True) is False
            and report.get('status') in ('completed', 'review_required')):
        old = Path(previous).resolve()
        if old.suffix.lower() == '.html' and old != target and old.is_file():
            try:
                old.unlink()
            except OSError as exc:
                import warnings
                warnings.warn(f'The new report was saved but the original HTML could not be removed: {exc}',
                              RuntimeWarning, stacklevel=2)
    return target
