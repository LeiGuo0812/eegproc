"""Standalone epoch orchestration; no continuous preprocessing is performed."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, fields, replace
from pathlib import Path
import re
import time
import warnings

import mne
import numpy as np
from threadpoolctl import threadpool_limits

from .epoch_metadata import EPOCH_PARAMETERS, read_metadata


def build_epochs(raw, config, events, event_id, epoch_config=None):
    """The shared online/standalone epoch stage with unchanged QC numerics."""
    from .configuration import resolve_epoch_config
    from .epoch_export import make_strict_epochs
    from .epochs import repair_epochs

    metadata = read_metadata(raw)
    bads = sorted(set(metadata.get('global_bads', ())) | set(raw.info['bads']))
    bads = [name for name in bads if name in raw.ch_names]
    selected_qc = ('annotations' if config.epoch_mode == 'fixed' else 'event-window') if config.epoch_qc == 'auto' else config.epoch_qc
    ec = resolve_epoch_config(config, epoch_config, sfreq=raw.info['sfreq'])
    if config.repair_epochs:
        epochs, qc = repair_epochs(raw, None, events, event_id, global_bads=bads, config=ec)
    else:
        epochs, qc = make_strict_epochs(raw, None, events, event_id, global_bads=bads,
                                       config=ec, annotation_policy=selected_qc)
    qc['epoch_mode'] = config.epoch_mode
    return epochs, qc


def _report_candidates(raw, metadata, source_report):
    if source_report is not None:
        return [Path(source_report).expanduser().resolve()]
    candidates = []
    for filename in raw.filenames:
        if not filename:
            continue
        filename = Path(filename)
        # The first member of a split FIF is normally listed first. Restrict
        # discovery to actual cleaned outputs, never prepared-input filenames.
        match = re.fullmatch(r'(.+)_cont_raw(?:-\d+)?\.fif(?:\.gz)?', filename.name, re.I)
        if match:
            stem = match.group(1)
            candidates.extend([filename.with_name(stem + '_report.html'),
                               filename.with_name(stem + '_report_data.npz')])
    hint = metadata.get('report_path')
    if hint:
        path = Path(hint)
        candidates.extend([path, path.with_name(path.stem.removesuffix('_report') + '_report_data.npz')])
    return list(dict.fromkeys(path.resolve() for path in candidates))


def _load_source(raw, metadata, source_report):
    from .reporting import read_report_source
    messages = []
    try:
        candidates = _report_candidates(raw, metadata, source_report)
    except (TypeError, ValueError, OSError) as exc:
        candidates = []
        messages.append(f'Source report path could not be used: {exc}')
    for candidate in candidates:
        try:
            if not candidate.is_file():
                continue
            return read_report_source(candidate), candidate, messages
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as exc:
            messages.append(f'Source report could not be read ({candidate.name}): {exc}')
    messages.append('No readable preprocessing report was found; provide source_report to include prior figures. Epoching continues with a standalone report.')
    return None, None, messages


def _resolve_config(raw, metadata, config, config_file, parameters, epoch_config, source=None):
    from .configuration import _config_values, resolve_config
    from .parameter_resolution import adjustment, append_adjustments
    from .epochs import EpochConfig
    from .settings import PipelineConfig

    allowed = set(EPOCH_PARAMETERS) | {field.name for field in fields(PipelineConfig) if field.name.startswith('report_')}
    aliases = dict(tmin='epoch_tmin', tmax='epoch_tmax', baseline='epoch_baseline',
                   duration='fixed_epoch_duration', overlap='fixed_epoch_overlap',
                   peak_uv='residual_peak_uv', ptp_uv='residual_ptp_uv',
                   robust_z='residual_robust_z', relative_min_ptp_uv='residual_relative_min_ptp_uv')
    inherited = dict(metadata.get('parameters') or {})
    source_config=(source or {}).get('config',{})
    inherited.update({name:value for name,value in source_config.items() if name.startswith('report_')})
    # An independent call requests epochs unless explicitly disabled. It must
    # not inherit epoch_mode='none' from a continuous-only preprocessing run.
    if inherited.get('epoch_mode') in (None,'none'):
        inherited['epoch_mode'] = 'events'
    values = {key: value for key, value in inherited.items() if key in allowed}
    audit = []
    repair_names = {'max_interpolate', 'max_local_fraction', 'min_fit_epochs', 'cv'}
    repair = dict(metadata.get('repair_parameters') or {})
    for supplied in (_config_values(config_file), _config_values(config), parameters):
        audit.extend(getattr(supplied, 'adjustments', ()))
        for name, value in supplied.items():
            name = aliases.get(name, name)
            if name in allowed:
                values[name] = value
            elif name in repair_names:
                repair[name] = value
            else:
                audit.append(adjustment(name, value, None, 'Parameter is not used by standalone epoching; no continuous preprocessing is performed'))
    effective = append_adjustments(resolve_config(values), audit)
    # Source figures/materials describe already captured samples. Do not label
    # them with a newly requested window or pretend cached HTML was redrawn.
    if source is not None:
        cached_images=bool(source.get('visualizations',{}).get('figures'))
        capture_fields={'report_window_seconds','report_waveform_windows','report_max_channels',
                        'report_psd_windows','report_psd_window_seconds','report_full_record_heatmap'}
        retained={name:value for name,value in source_config.items()
                  if name.startswith('report_') and (cached_images or name in capture_fields)
                  and name in allowed and getattr(effective,name)!=value}
        if retained:
            changes=[adjustment(name,getattr(effective,name),value,
                'Existing preprocessing report material is reused; its recorded display/capture setting is retained')
                for name,value in retained.items()]
            effective=append_adjustments(resolve_config(effective,**retained),changes)
    # Retain the same fixed-window sample-grid normalization as the complete
    # pipeline without resolving filters, line noise or ICA dependencies.
    if effective.epoch_mode == 'fixed':
        sfreq = float(raw.info['sfreq'])
        sample_period = 1. / sfreq
        recording_seconds = raw.n_times / sfreq
        if raw.n_times < 2:
            return effective, epoch_config
        duration = effective.fixed_epoch_duration
        changes = []
        overrides = {}
        if duration <= sample_period or duration > recording_seconds:
            corrected = min(recording_seconds, max(2., 2 * sample_period))
            changes.append(adjustment('fixed_epoch_duration', duration, corrected,
                                      'Fixed duration adjusted to contain at least two samples within this recording'))
            overrides['fixed_epoch_duration'] = corrected
            duration = corrected
        if duration - effective.fixed_epoch_overlap < sample_period:
            changes.append(adjustment('fixed_epoch_overlap', effective.fixed_epoch_overlap, 0.,
                                      'Overlap leaves less than one sample between epoch starts; selected zero overlap'))
            overrides['fixed_epoch_overlap'] = 0.
        if overrides:
            effective = append_adjustments(resolve_config(effective, **overrides), changes)
    if repair:
        if isinstance(epoch_config, EpochConfig):
            epoch_config = asdict(epoch_config)
        elif not isinstance(epoch_config, dict):
            epoch_config = {}
        epoch_config = {**repair, **epoch_config}
        epoch_config.update({name:value for name,value in parameters.items() if name in repair_names})
    return effective, epoch_config


def epoch_raw(raw, save_path, subject=None, *, config=None, config_file=None,
              events=None, event_id=None, epoch_config=None, source_report=None,
              keep_source_report=True, report=True, **parameters):
    """Epoch an already processed Raw and optionally extend its HTML report."""
    from . import __version__
    from .engine import _resolve_epoch_request
    from .storage import OutputPlan, OutputStore
    from .report_provenance import StageRecorder, utc_now
    from .reporting import emit_report

    if not isinstance(raw, mne.io.BaseRaw):
        raise TypeError('Input must be an already preprocessed continuous MNE Raw')
    if raw.n_times < 2 or not np.isfinite(raw.info['sfreq']) or raw.info['sfreq'] <= 0:
        raise ValueError('Epoching needs at least two samples and a positive sampling frequency')
    metadata = read_metadata(raw)
    subject = subject or metadata.get('subject') or 'subject'
    if not isinstance(subject, str) or not re.fullmatch(r'[\w.-]+', subject) or subject in ('.', '..'):
        raise ValueError('subject must be a safe basename')
    source, source_path, messages = _load_source(raw, metadata, source_report)
    effective, epoch_config = _resolve_config(raw, metadata, config, config_file, parameters, epoch_config, source)
    effective, events, event_id, epoch_config, resolution = _resolve_epoch_request(
        raw, effective, events, event_id, epoch_config)
    if not metadata.get('bad_sources_recorded'):
        messages.append('BAD source metadata is unavailable; unlabelled BAD annotations remain hard exclusions.')
    if not isinstance(report, bool):
        messages.append('report must be a boolean; immediate report generation selected.')
        report = True
    if not isinstance(keep_source_report, bool):
        messages.append('keep_source_report must be a boolean; the original report will be retained.')
        keep_source_report = True
    for message in messages:
        warnings.warn(message, RuntimeWarning, stacklevel=2)
    directory = Path(save_path).resolve()
    input_paths = tuple(path for path in raw.filenames if path)
    if source_path is not None:
        input_paths += (source_path,)
    OutputPlan(directory, subject, input_paths).preflight()
    directory.mkdir(parents=True, exist_ok=True)
    record = deepcopy(source) if source is not None else {}
    if source is not None:
        record['preprocessing_outputs'] = dict(source.get('preprocessing_outputs', source.get('outputs', {})))
        for key in ('execution','parameter_adjustments','elapsed_seconds'):
            recorded='preprocessing_'+key
            if recorded in source:
                record[recorded]=deepcopy(source[recorded])
            elif not source.get('epoching') and key in source:
                record[recorded]=deepcopy(source[key])
    if source is not None and not source.get('epoching') and 'preprocessing_methods' not in record:
        from .report_provenance import methods_text
        record['preprocessing_methods'] = methods_text(source)
    prior_flags = [flag for flag in record.get('quality_flags', [])
                   if flag != 'Epoch retention is below 50 percent; inspect epoch QC'
                   and flag != 'Epoch parameters were adjusted automatically; review the effective settings.']
    prior_config = dict(record.get('config', {}))
    config_values = asdict(effective)
    if prior_config:
        prior_config.update({key: config_values[key] for key in EPOCH_PARAMETERS})
        prior_config.update({key: value for key, value in config_values.items() if key.startswith('report_')})
        config_values = prior_config
    else:
        # Display the actual delivered band, not a request to refilter it.
        config_values.update(highpass=float(raw.info['highpass']), lowpass=float(raw.info['lowpass']))
    for key in ('epochs', 'report_storage', 'report_error', 'report_status', 'report_generation'):
        record.pop(key, None)
    record.update(pipeline='eegproc', workflow_id='eegproc', workflow_revision=__version__,
                  status='running', config=config_values, task_name=effective.task_name,
                  event_id=dict(event_id or {}), epoch_resolution=resolution,
                  quality_flags=prior_flags, warnings=[*record.get('warnings', []), *messages], execution=[], stage_files=[], output_files=[], outputs={},
                  first_samp=int(raw.first_samp), input_annotations=len(raw.annotations),
                  input_summary=dict(sfreq=float(raw.info['sfreq']), n_times=int(raw.n_times),
                                     duration_seconds=float(raw.n_times/raw.info['sfreq']), first_samp=int(raw.first_samp)),
                  parameter_adjustments=[dict(item) for item in effective.adjustments])
    if record['parameter_adjustments']:
        record['quality_flags'].append('Epoch parameters were adjusted automatically; review the effective settings.')
    record.setdefault('provenance', dict(subject_label=subject, started_utc=utc_now()))
    record['bad_channels'] = list(metadata.get('global_bads', raw.info['bads']))
    record['epoching'] = dict(entrypoint='eegproc.epoch', source_report=str(source_path) if source_path else None,
                             source_report_loaded=source is not None, continuous_processing_repeated=False,
                             continuous_data_modified=False, keep_source_report=keep_source_report,
                             started_utc=utc_now())
    record['epoch_annotations'] = [dict(
        onset_seconds=float(annotation['onset']-raw.first_time),
        duration_seconds=float(annotation['duration']),description=annotation['description'],
        channels=list(annotation.get('ch_names',())),
        origin=annotation.get('extras',{}).get('eegproc_origin','input/manual/unknown'),
    ) for annotation in raw.annotations if annotation['description'].lower().startswith('bad')]
    paths = {'quality_report': directory / f'{subject}_report.html'}
    store = OutputStore(record)
    execution = StageRecorder(record)
    started = time.perf_counter()
    epochs = None
    try:
        if events is None:
            execution.skip('epochs', resolution.get('reason', 'No usable epoch request'))
            record['status'] = 'skipped'
        else:
            execution.start('epochs')
            with threadpool_limits(limits=effective.n_threads):
                epochs, qc = build_epochs(raw, effective, events, event_id, epoch_config)
            record['epochs'] = qc
            record['effective_epoch_config'] = qc['config']
            if len(epochs):
                paths['epochs'] = directory / f'{subject}_clean-epo.fif'
                store.save_epochs(epochs, paths['epochs'])
            if qc['status'] == 'review_required':
                record['quality_flags'].append('Epoch retention is below 50 percent; inspect epoch QC')
            record['status'] = 'review_required' if record['quality_flags'] else 'completed'
            execution.finish()
    except Exception as exc:
        execution.finish('failed', str(exc))
        record.update(status='failed', error=dict(type=type(exc).__name__, message=str(exc)))
        raise
    finally:
        record['elapsed_seconds'] = time.perf_counter() - started
        record['epoching']['elapsed_seconds'] = record['elapsed_seconds']
        record['outputs'] = {key: str(value) for key, value in paths.items()}
        record['epoching']['finished_utc'] = utc_now()
        ok = emit_report(record, paths['quality_report'], generate=report)
        if (ok and report and record.get('report_status') == 'completed'
                and record['status'] in ('completed','review_required')
                and not keep_source_report and source_path is not None
                and source_path.suffix.lower() == '.html' and source_path != paths['quality_report']):
            try:
                source_path.unlink()
            except OSError as exc:
                message = f'The new report was saved but the original HTML could not be removed: {exc}'
                record['warnings'].append(message)
                warnings.warn(message, RuntimeWarning, stacklevel=2)
    return epochs, record
