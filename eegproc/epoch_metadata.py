"""Small FIF-persistent processing hints used by standalone epoching.

These fields describe processing semantics, not recording identities. Original
annotation names, sample clocks and user extras are left intact.
"""
from dataclasses import asdict
import json
from pathlib import Path


ORIGIN_KEY = 'eegproc_origin'
AUTOMATIC_RESIDUAL = 'automatic_residual'
_START = '\n[eegproc-epoch]\n'
_END = '\n[/eegproc-epoch]'

EPOCH_PARAMETERS = (
    'purpose', 'task_name', 'epoch_mode', 'epoch_qc', 'repair_epochs',
    'epoch_tmin', 'epoch_tmax', 'epoch_baseline', 'fixed_epoch_duration',
    'fixed_epoch_overlap', 'event_source', 'event_names', 'stim_channel',
    'residual_peak_uv', 'residual_ptp_uv', 'residual_robust_z',
    'residual_relative_min_ptp_uv', 'seed', 'n_threads',
)


def read_metadata(raw):
    """Return optional processing hints without requiring another file."""
    description = raw.info.get('description') or ''
    if _START not in description:
        return {}
    payload = description.rsplit(_START, 1)[1].split(_END, 1)[0]
    try:
        value = json.loads(payload)
    except (ValueError, TypeError):
        return {}
    if not isinstance(value,dict):
        return {}
    for key in ('parameters','repair_parameters'):
        if not isinstance(value.get(key,{}),dict):value[key]={}
    for key in ('global_bads','interpolated_channels'):
        channels=value.get(key,[])
        value[key]=[name for name in channels if isinstance(name,str)] if isinstance(channels,list) else []
    if value.get('subject') is not None and not isinstance(value['subject'],str):value.pop('subject')
    return value


def prepare_annotations(raw):
    """Treat all incoming BAD as protected input to a new preprocessing run.

    Only the package-owned source label changes when an already processed Raw
    is deliberately preprocessed again. User extras are never replaced.
    """
    for annotation, extra in zip(raw.annotations, raw.annotations.extras):
        if annotation['description'].lower().startswith('bad') and extra.get(ORIGIN_KEY) == AUTOMATIC_RESIDUAL:
            extra[ORIGIN_KEY] = 'input'


def is_automatic_residual(annotation):
    return (annotation['description'] == 'BAD_residual' and
            annotation.get('extras', {}).get(ORIGIN_KEY) == AUTOMATIC_RESIDUAL)


def add_residual_annotations(raw, mask):
    """Append the existing residual windows with a scalar source label."""
    from .signal_ops import contiguous_spans
    for start, end in contiguous_spans(mask):
        raw.annotations.append(
            raw.first_time + start / raw.info['sfreq'],
            (end - start) / raw.info['sfreq'], 'BAD_residual',
            extras=[{ORIGIN_KEY: AUTOMATIC_RESIDUAL}],
        )


def save_epoch_metadata(raw, config, bads, report_path, subject=None, epoch_config=None):
    """Attach only settings required to repeat the epoch stage after FIF IO."""
    description = raw.info.get('description') or ''
    if _START in description:
        before, tail = description.split(_START, 1)
        description = before + (tail.split(_END, 1)[1] if _END in tail else '')
    values = asdict(config)
    parameters={name: values[name] for name in EPOCH_PARAMETERS}
    repair_parameters={}
    if epoch_config is not None:
        epoch_values=asdict(epoch_config) if hasattr(epoch_config,'__dataclass_fields__') else dict(epoch_config)
        aliases=dict(tmin='epoch_tmin',tmax='epoch_tmax',baseline='epoch_baseline',
                     peak_uv='residual_peak_uv',ptp_uv='residual_ptp_uv',robust_z='residual_robust_z',
                     relative_min_ptp_uv='residual_relative_min_ptp_uv',seed='seed')
        parameters.update({aliases[key]:value for key,value in epoch_values.items() if key in aliases})
        repair_parameters={key:epoch_values[key] for key in ('max_interpolate','max_local_fraction','min_fit_epochs','cv') if key in epoch_values}
    payload = dict(
        global_bads=list(bads),
        interpolated_channels=list(bads) if config.interpolate_bads else [],
        parameters=parameters,
        repair_parameters=repair_parameters,
        subject=subject,
        report_path=str(Path(report_path).resolve()),
        bad_sources_recorded=True,
    )
    raw.info['description'] = description + _START + json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + _END
    return payload
