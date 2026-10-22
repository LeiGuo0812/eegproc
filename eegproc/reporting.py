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


def render_report(source, report_path: str | PathLike[str]) -> Path:
    """Render current HTML layout from a PipelineResult or a previous HTML.

    Existing plots and component numeric diagnostics are reused exactly. This
    function never loads Raw/FIF or reruns filters, ASR, ICA, epoching or plotting.
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
        report = deepcopy(source.report)
        path = report.get('outputs', {}).get('quality_report')
        if path and Path(path).is_file():
            source_path = Path(path).resolve()
        figures = report.get('visualizations', {}).get('figures', [])
        if any(not figure.get('data_uri') for figure in figures) and source_path:
            cached = _read_html(source_path)
            report['visualizations'] = cached['visualizations']
            report['ica_diagnostics'] = cached.get('ica_diagnostics', [])
    elif isinstance(source, (str, PathLike)):
        source_path = Path(source).resolve()
        report = _read_html(source_path)
    else:
        raise TypeError('source must be a PipelineResult or an existing standalone HTML report')
    _check_record(report)
    if source_path == target:
        raise ValueError('The report source must remain unchanged; choose another HTML path')
    prior = deepcopy(report.get('report_generation'))
    report['report_generation'] = dict(
        schema='eeg-report-render-v1', generated_utc=utc_now(), renderer_version=__version__,
        source_report=str(source_path) if source_path else None,
        source_report_sha256=file_hash(source_path) if source_path else None,
        reused_embedded_figures=True, reused_component_diagnostics=True,
        signal_processing_repeated=False, waveform_redrawn=False,
        renderer_sha256={name:file_hash(Path(__file__).with_name(name))
                         for name in ('reporting.py','quality_report.py','report_layout.py')},
    )
    if prior:
        report['report_generation']['previous_generation'] = prior
    if not safe_report(report,target,reuse_figures=True):
        error = report.get('report_error', {}).get('message', 'unknown rendering error')
        raise RuntimeError('Report rendering failed: '+error)
    return target
