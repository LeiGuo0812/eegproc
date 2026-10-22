"""Continuous preprocessing using the independent MNE ASR backend.

Native MNE timing/coordinates, ASR in the common analysis/training space,
conservative ICLabel decisions, and explicit residual QC. The separate epochs
module provides bounded AutoReject repair without modifying continuous data.
No simulation truth is accepted by either production module.
"""
from __future__ import annotations

import contextlib
from dataclasses import asdict
from importlib.metadata import version, PackageNotFoundError
import hashlib
import io
import json
from pathlib import Path
import re
import time
import warnings

import mne
import numpy as np
from scipy.ndimage import binary_dilation
from threadpoolctl import threadpool_limits

from .settings import validate_config
from .ica import fit_ica, apply_ica
from .storage import OutputStore, OutputPlan
from .stages import prepare_signals, prepare_training, prepare_ecg
from .delivery import finish_processing, ProcessingContext


def _installed_versions():
    result = {}
    for name in ("mne", "mne-icalabel", "eegprep", "pyprep", "numpy", "scipy", "python-picard"):
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = None
    return result


def _resolve_epoch_request(raw, config, events, event_id, epoch_config):
    """Resolve optional epochs without inventing event identities or conditions."""
    from .configuration import resolve_config, resolve_epoch_config, resolve_events
    from .parameter_resolution import adjustment, append_adjustments
    audit = []
    resolution = dict(status='not_requested')
    if events is not None and config.epoch_mode == 'none':
        config = resolve_config(config, epoch_mode='events')
    if config.epoch_mode == 'none':
        if config.repair_epochs:
            audit.append(adjustment('repair_epochs', True, False,
                'No event epochs requested; local epoch repair disabled'))
            config = resolve_config(config, repair_epochs=False)
        return append_adjustments(config, audit), None, None, None, resolution
    resolved = resolve_epoch_config(config, epoch_config, sfreq=raw.info['sfreq'])
    audit.extend(getattr(resolved, 'adjustments', ()))
    if config.epoch_mode == 'events':
        duration = raw.n_times/raw.info['sfreq']
        if (resolved.tmin < -duration or resolved.tmax > duration or
                resolved.tmax-resolved.tmin > duration):
            reason = 'Requested event window exceeds the recording duration. Continuous processing continues; no epochs exported.'
            audit.append(adjustment('epoch_mode', 'events', 'none', reason))
            if config.repair_epochs:
                audit.append(adjustment('repair_epochs', True, False, 'No complete event window is available'))
            config = resolve_config(config, epoch_mode='none', repair_epochs=False)
            return append_adjustments(config, audit), None, None, None, dict(status='skipped', reason=reason)
        from dataclasses import replace
        sfreq = raw.info['sfreq']
        start, stop = round(resolved.tmin*sfreq), round(resolved.tmax*sfreq)
        if config.repair_epochs and start >= 0:
            audit.append(adjustment('epoch_config.tmin', resolved.tmin, -.2,
                'Local repair needs prestimulus samples on the input sample grid; standard event start used'))
            resolved = replace(resolved, tmin=-.2)
            start = round(resolved.tmin*sfreq)
        if resolved.baseline is not None:
            lo, hi = resolved.baseline
            lo = start/sfreq if lo is None else lo
            hi = stop/sfreq if hi is None else hi
            has_sample = max(start, int(np.ceil(lo*sfreq-1e-9))) <= min(stop, int(np.floor(hi*sfreq+1e-9)))
            if not has_sample or (resolved.baseline == (None, 0) and start == 0):
                audit.append(adjustment('epoch_config.baseline', resolved.baseline, None,
                    'Baseline has no usable interval on the input sample grid; baseline correction disabled'))
                resolved = replace(resolved, baseline=None)
    try:
        if config.epoch_mode == 'events':
            events, event_id = resolve_events(raw, config, events, event_id)
            # Reject optional requests that would fail later in MNE.Epochs.
            from numbers import Integral
            if any(not isinstance(k, str) or isinstance(v, (bool, np.bool_)) or
                   not isinstance(v, Integral) for k, v in event_id.items()):
                raise ValueError('event_id must map string condition names to integer codes')
            if any(v not in events[:, 2] for v in event_id.values()):
                raise ValueError('event_id contains a condition absent from selected events')
            if np.any(np.diff(events[:, 0]) <= 0):
                raise ValueError('Event sample positions must be unique and increasing')
            if np.any(events[:, 0] < raw.first_samp) or np.any(events[:, 0] >= raw.first_samp+raw.n_times):
                raise ValueError('Event positions fall outside the recording; use absolute MNE sample indices')
        else:
            if events is not None or event_id is not None:
                audit.append(adjustment('events/event_id', 'Explicit event input', None,
                    'Fixed epochs use regularly spaced windows; event-locked input ignored'))
            events = mne.make_fixed_length_events(raw, id=1, duration=config.fixed_epoch_duration,
                overlap=config.fixed_epoch_overlap, first_samp=True)
            event_id = {'fixed_window': 1}
            if not len(events):
                raise ValueError('Recording is shorter than the fixed epoch duration')
        resolution = dict(status='ready', n_events=len(events), mode=config.epoch_mode)
    except (ValueError, TypeError, RuntimeError, KeyError, IndexError) as exc:
        reason = f'{type(exc).__name__}: {exc}. Continuous processing continues; no epochs exported.'
        audit.append(adjustment('epoch_mode', config.epoch_mode, 'none', reason))
        if config.repair_epochs:
            audit.append(adjustment('repair_epochs', True, False, 'Epoch input unavailable; local repair disabled'))
        config = resolve_config(config, epoch_mode='none', repair_epochs=False)
        events = event_id = resolved = None
        resolution = dict(status='skipped', reason=reason)
    return append_adjustments(config, audit), events, event_id, resolved, resolution


def preprocess_raw(raw, save_path, subject, *, config=None, montage=None, collect_stages=False,
                        events=None,event_id=None,epoch_config=None,invocation=None):
    """Preserve MNE timing, events, auxiliary channels and digitization.

    Already-applied projections cannot be undone; SSP projectors are rejected
    explicitly to avoid silently mixing projection and ICLabel assumptions.
    ``montage`` is only used when native EEG positions are incomplete.
    """
    from .configuration import resolve_config
    from .runtime_parameters import resolve_for_raw, resolve_manual_exclude, update_parameter_report
    config = resolve_config(config)
    if not re.fullmatch(r"[\w.-]+", subject) or subject in (".", ".."):
        raise ValueError("subject must be a safe basename")
    if not isinstance(raw, mne.io.BaseRaw):
        raise TypeError("Input must be a continuous MNE Raw object in SI units")
    config, raw_resolution = resolve_for_raw(config, raw)
    config, events, event_id, epoch_config, epoch_resolution = _resolve_epoch_request(
        raw, config, events, event_id, epoch_config)
    validate_config(config, raw.info["sfreq"])
    directory = Path(save_path).resolve()
    source_paths=tuple(p for p in raw.filenames if p)+tuple((invocation or {}).get('input_paths',[]))
    OutputPlan(directory,subject,source_paths).preflight()
    if raw.info["projs"]:
        raise ValueError("Resolve SSP projectors explicitly before running this ICLabel pipeline")
    from .raw_helpers import raw_slice, signal_hash
    current = raw.copy().load_data()
    picks = mne.pick_types(current.info, eeg=True, exclude=[])
    if len(picks) < 8 or any(not np.isfinite(current.get_data(picks=picks,start=a,stop=min(a+65536,current.n_times))).all()
                             for a in range(0,current.n_times,65536)):
        raise ValueError("At least eight finite EEG channels are required")
    if montage is not None:
        current.set_montage(montage, on_missing="raise", verbose="warning")
    xyz = np.array([current.info["chs"][i]["loc"][:3] for i in picks])
    if not np.isfinite(xyz).all() or np.any(np.linalg.norm(xyz, axis=1) == 0):
        raise ValueError("Missing EEG coordinates: provide the measured or correct cap montage explicitly")
    if np.max(np.linalg.norm(xyz, axis=1)) > 0.3:
        raise ValueError("EEG head coordinates must be in metres")
    directory = Path(save_path).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    paths = {"raw": directory / f"{subject}_cont_raw.fif", "quality_report": directory / f"{subject}_report.html",
             "ica": directory / f"{subject}-ica.fif"}
    from . import __version__
    report = {"pipeline": "eegproc", "workflow_id": "eegproc", "workflow_revision": __version__, "status": "running", "config": asdict(config), "task_name": config.task_name,
        "input_sha256": signal_hash(current),
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "packages": _installed_versions(),
        "first_samp": current.first_samp, "input_annotations": len(current.annotations),
        "event_id": dict(event_id or {}),
        "input_summary": {"sfreq": current.info["sfreq"], "n_times": current.n_times,
                          "duration_seconds": current.n_times/current.info["sfreq"], "first_samp": current.first_samp},
        "quality_flags": [], "warnings": [], "truth_used": False}
    from .backends import alignment_notes
    report['alignment_notes']=alignment_notes(config)
    if epoch_config is not None:report['effective_epoch_config']=asdict(epoch_config)
    store=OutputStore(report)
    stages = {}
    model = training = diagnostic_training = None
    from .report_provenance import capture_provenance, StageRecorder, utc_now
    report['provenance'] = capture_provenance(raw, subject, invocation, montage)
    report['parameter_resolution'] = raw_resolution
    report['epoch_resolution'] = epoch_resolution
    update_parameter_report(report, config)
    report['quality_flags'].extend(raw_resolution['review_notes'])
    execution = StageRecorder(report)
    started = time.perf_counter()
    try:
        with threadpool_limits(limits=config.n_threads), warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            broad,eeg_info,bads,gross=prepare_signals(current,picks,config,report,execution,store)
            if config.ica_enabled:
                analysis,training,diagnostic_training,spans=prepare_training(broad,gross,config,report,execution,store,collect_stages,stages)
                ecg_data=prepare_ecg(current,spans,config,report) if config.ica_rule=='threshold' else None
                execution.start('ica_fit')
                model,ica_report=fit_ica(training,config,ecg_data=ecg_data)
                report['ica']=ica_report
                config, _ = resolve_manual_exclude(config, model.n_components_)
                update_parameter_report(report, config)
                if any(not d['automatically_removed'] for d in ica_report['heart_support_decisions']):
                    report['quality_flags'].append('Heart candidate retained: available ECG correlation is below the support threshold; review component')
                if ica_report['iteration_limit_reached']:
                    report['quality_flags'].append('ICA iteration limit reached; inspect decomposition')
                if ica_report['samples_per_rank_squared']<20:
                    report['quality_flags'].append('Short ICA training relative to rank squared; stability needs review')
                execution.finish()
                training=None
                ecg_data=None
                from .review import save_checkpoint
                # Persist the untouched application signal before ICA.apply mutates it.
                execution.start('save_ica_checkpoint')
                save_checkpoint(raw,current,analysis,diagnostic_training,model,config,report,
                    directory,subject,events,event_id,epoch_config,paths)
                execution.finish()
                if config.ica_mode=='review':
                    report['status']='awaiting_ica_review'
                    for i,name in enumerate(analysis.ch_names):
                        current._data[current.ch_names.index(name)] = analysis._data[i]
                    with current.info._unlock():
                        for key in ['highpass','lowpass','custom_ref_applied']:current.info[key]=analysis.info[key]
                    paths.pop('raw',None)
                    report['outputs']={k:str(v) for k,v in paths.items()}
                else:
                    execution.start('ica_apply')
                    clean=apply_ica(model,analysis,ica_report,config)
            else:
                from .backends import apply_filter
                execution.skip('ica_fit','Disabled by ica_enabled=False')
                execution.skip('ica_apply','Disabled by ica_enabled=False')
                clean=apply_filter(broad,config.highpass if config.highpass>min(config.highpass,config.training_highpass) else None,
                    config.lowpass if config.lowpass<max(config.lowpass,config.training_lowpass) else None,config)
                paths.pop('ica',None)
            if report['status']!='awaiting_ica_review':
                # Training is no longer needed after classification/ECG scoring.
                training=None
                context=ProcessingContext(config=config,report=report,execution=execution,store=store,
                    paths=paths,directory=directory,subject=subject,events=events,event_id=event_id,
                    epoch_config=epoch_config,collect_stages=collect_stages,stages=stages)
                current=finish_processing(current,raw,clean,model,context=context)
            report['warnings']=sorted(set(str(w.message) for w in caught))
    except Exception as exc:
        execution.finish('failed', str(exc))
        report.update(status="failed", error={"type": type(exc).__name__, "message": str(exc)})
        raise
    finally:
        report['provenance'].setdefault('continuous_finished_utc',utc_now())
        report['provenance']['processing_finished_utc'] = utc_now()
        report["elapsed_seconds"] = time.perf_counter() - started
        report["outputs"] = {k:str(v) for k,v in paths.items()}
        from .quality_report import safe_report
        completed = report['status'] in ('completed', 'review_required', 'awaiting_ica_review')
        safe_report(report, paths['quality_report'], original=raw if completed else None,
                            clean=current if completed else None, ica=model, training=diagnostic_training)
    return current, report, stages


