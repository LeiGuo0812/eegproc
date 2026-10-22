"""Python-first configuration: preset defaults < optional base < overrides."""
from dataclasses import asdict, fields, replace
from collections.abc import Mapping
import json
from numbers import Integral, Real
from os import PathLike
from pathlib import Path
from types import UnionType
from typing import get_args, get_origin
import numpy as np
from .settings import PipelineConfig

class _ConfigValues(dict):
    """Mergeable values carrying optional-source diagnostics outside parameters."""
    def __init__(self,values=(),adjustments=()):
        super().__init__(values);self.adjustments=list(adjustments)

    def update(self,values=(),**kwargs):
        super().update(values,**kwargs)
        self.adjustments.extend(getattr(values,'adjustments',()))


def _config_values(source):
    """Read one explicit source without expanding defaults prematurely."""
    from .parameter_resolution import adjustment
    audit=[]
    if source is None:
        values = {}
    elif isinstance(source, PipelineConfig):
        values = asdict(source)
        audit.extend(source.adjustments)
    elif isinstance(source, Mapping):
        values = dict(source)
        audit.extend(getattr(source,'adjustments',()))
    elif isinstance(source, (str, PathLike)):
        try:values=json.loads(Path(source).read_text(encoding='utf-8-sig'))
        except (OSError,UnicodeError,json.JSONDecodeError) as exc:
            values={};audit.append(adjustment('config_file',str(source),None,
                f'Optional configuration could not be read ({type(exc).__name__}: {exc}); defaults and code parameters used'))
    else:
        values={};audit.append(adjustment('config',source,None,'Unsupported optional configuration source; defaults and code parameters used'))
    if not isinstance(values, dict):
        audit.append(adjustment('config',values,None,'Configuration must be an object; defaults and code parameters used'));values={}
    for key in list(values):
        if not isinstance(key,str):
            audit.append(adjustment(key,values.pop(key),None,'Non-string parameter name ignored'))
    return _ConfigValues(values,audit)


def resolve_config(path=None, **overrides) -> PipelineConfig:
    """Resolve keyword parameters, optionally on a mapping/config/JSON base.

    ``resolve_config(purpose='erp', task_name='oddball')`` is the primary
    interface. The positional ``path`` argument retains its original name for
    compatibility but also accepts a mapping or resolved ``PipelineConfig``.
    No configuration file is discovered or loaded implicitly.
    """
    values = _config_values(path)
    from .parameter_resolution import append_adjustments
    result=PipelineConfig(**{**values,**overrides})
    current=result.adjustments
    object.__setattr__(result,'_adjustments',())
    append_adjustments(result,values.adjustments)
    return append_adjustments(result,current)


def _validate_types(c):
    """Reject invalid Python types before numeric comparisons or I/O."""
    for field in fields(PipelineConfig):
        value = getattr(c, field.name)
        allowed = get_args(field.type) if get_origin(field.type) is UnionType else (field.type,)
        if value is None and type(None) in allowed:
            continue
        if bool in allowed:
            valid = isinstance(value, bool)
        elif int in allowed:
            valid = isinstance(value, Integral) and not isinstance(value, (bool, np.bool_))
        elif float in allowed:
            valid = isinstance(value, Real) and not isinstance(value, (bool, np.bool_)) and np.isfinite(value)
        elif str in allowed:
            valid = isinstance(value, str)
        elif dict in allowed:
            valid = isinstance(value, dict)
        elif tuple in allowed:
            valid = isinstance(value, tuple)
        else:
            valid = False
        if not valid:
            raise ValueError(f'{field.name} has an invalid type or nonfinite value (expected {field.type})')
    if c.ica_exclude is not None:
        if any(isinstance(v, (bool, np.bool_)) or not isinstance(v, Integral) or v < 0 for v in c.ica_exclude):
            raise ValueError('ica_exclude must contain nonnegative integer component indices')
        if len(set(c.ica_exclude)) != len(c.ica_exclude):
            raise ValueError('ica_exclude must not contain duplicate indices')
    if c.event_names is not None and any(not isinstance(v, str) or not v.strip() for v in c.event_names):
        raise ValueError('event_names must contain nonempty strings')
    if c.epoch_baseline is not None and any(v is not None and
            (isinstance(v, (bool, np.bool_)) or not isinstance(v, Real) or not np.isfinite(v)) for v in c.epoch_baseline):
        raise ValueError('epoch_baseline must contain finite numeric endpoints or None')


def _validate_asr_options(c):
    from .mne_asr import ASRConfig
    if not isinstance(c.asr_options, dict) or set(c.asr_options) & {'cutoff', 'min_segment_seconds'}:
        raise ValueError('asr_options must be a dict; cutoff/min_segment_seconds use their top-level settings')
    known = {field.name for field in fields(ASRConfig)}
    unknown = set(c.asr_options) - known
    if unknown:
        raise ValueError('Unknown ASR options: '+', '.join(sorted(unknown)))
    for key, value in c.asr_options.items():
        if key == 'reference_tolerances':
            if not isinstance(value, tuple) or len(value) != 2 or any(
                    isinstance(v, (bool, np.bool_)) or not isinstance(v, Real) for v in value):
                raise ValueError('ASR reference_tolerances requires two numeric endpoints')
        elif value is None and key in ('processing_window', 'step_size'):
            continue
        elif key == 'step_size':
            if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral):
                raise ValueError('ASR step_size must be an integer or None')
        elif isinstance(value, (bool, np.bool_)) or not isinstance(value, Real) or not np.isfinite(value):
            raise ValueError(f'ASR {key} must be a finite number')
    ASRConfig(cutoff=c.asr_cutoff or 20., min_segment_seconds=c.min_training_seconds, **c.asr_options).validate()


def validate_options(c):
    if not isinstance(c, PipelineConfig):
        raise TypeError('config must be a resolved PipelineConfig')
    _validate_types(c)
    if c.task_name is not None and (not isinstance(c.task_name,str) or not c.task_name.strip()
            or c.task_name!=c.task_name.strip() or len(c.task_name)>100 or any(ord(x)<32 for x in c.task_name)):
        raise ValueError('task_name must be a nonempty label of at most 100 characters without surrounding whitespace or control characters')
    choices = dict(preset=('standard','eeglab'), filter_method=('mne_fir','eeglab_fir','off'),
        filter_position=('after_reference',), line_method=('spectrum_fit','notch','off'),
        channel_method=('pyprep','eegprep','off'), reference=('average','unchanged'),
        ica_mode=('auto','review','manual'), ica_rule=('threshold','class_max'),
        rank_method=('relative','covariance'), purpose=('rest','erp'), ica_backend=('mne',),
        asr_backend=('mne_native',), bad_channel_policy=('auto','report','stop'),
        ica_method=('picard','infomax'))
    for key, allowed in choices.items():
        if getattr(c,key) not in allowed: raise ValueError(f'{key} must be one of {allowed}')
    if isinstance(c.filter_order,bool) or not isinstance(c.filter_order,int) or c.filter_order<2 or c.filter_order%2:
        raise ValueError('filter_order must be a positive even integer >= 2')
    if c.ica_mode=='manual' and c.ica_exclude is None:
        raise ValueError('manual ICA requires ica_exclude; [] explicitly keeps all components')
    if c.ica_mode!='manual' and c.ica_exclude is not None:
        raise ValueError('ica_exclude is only used with ica_mode=manual')
    if not c.ica_enabled and c.ica_mode!='auto':
        raise ValueError('Disabled ICA cannot be paused for review or manually applied')
    if c.interpolate_before_asr and not c.interpolate_bads:
        raise ValueError('interpolate_before_asr requires interpolate_bads=True')
    if c.interpolate_bads and not (c.interpolate_before_asr or c.final_interpolation):
        raise ValueError('Interpolation is enabled but no interpolation stage is selected')
    if c.asr_options is not None:
        _validate_asr_options(c)
    if not (0 < c.highpass < c.lowpass and 0 < c.training_highpass < c.training_lowpass):
        raise ValueError('Invalid analysis/training bands; require 0 < highpass < lowpass')
    if not (.5 <= c.artifact_threshold <= 1 and 0 <= c.brain_probability_max <= .5):
        raise ValueError('Invalid IC probabilities')
    if c.asr_cutoff is not None and c.asr_cutoff <= 0:
        raise ValueError('ASR cutoff must be positive or None')
    if c.line_frequency is not None and c.line_frequency <= 0:
        raise ValueError('line_frequency must be positive or None')
    if not 0 <= c.seed < 2**32:
        raise ValueError('seed must be an unsigned 32 bit integer')
    if c.n_threads < 1 or c.ica_max_iter < 1:
        raise ValueError('Thread and iteration counts must be positive')
    if not 0 < c.bad_channel_fraction_limit < 1 or c.guard_seconds < 0:
        raise ValueError('Invalid QC settings')
    if not 0 <= c.heart_min_ecg_correlation <= 1:
        raise ValueError('Invalid ECG support threshold')
    for key in ('min_training_seconds','gross_peak_uv','residual_peak_uv','residual_ptp_uv',
                'residual_robust_z','residual_relative_min_ptp_uv','window_seconds','ica_tolerance'):
        if getattr(c,key) <= 0:
            raise ValueError(key+' must be positive')
    for key in ['flatline_seconds','line_window_seconds','line_bandwidth']:
        if not np.isfinite(getattr(c,key)) or getattr(c,key)<=0:raise ValueError(key+' must be positive')
    for key in ['channel_correlation','channel_broken_fraction','line_p_value']:
        if not np.isfinite(getattr(c,key)) or not 0<getattr(c,key)<1:raise ValueError(key+' must lie between 0 and 1')
    if c.epoch_mode not in ('none', 'events', 'fixed'):
        raise ValueError('epoch_mode must be none/events/fixed')
    if c.epoch_qc not in ('auto', 'event-window', 'annotations'):
        raise ValueError('epoch_qc must be auto/event-window/annotations')
    if c.event_source not in ('auto', 'annotations', 'stim'):
        raise ValueError('event_source must be auto/annotations/stim')
    if not np.isfinite([c.epoch_tmin,c.epoch_tmax,c.fixed_epoch_duration,c.fixed_epoch_overlap]).all():
        raise ValueError('Epoch timing must be finite')
    if not c.epoch_tmin <= 0 < c.epoch_tmax:
        raise ValueError('Event epochs require tmin <= 0 < tmax')
    if c.epoch_baseline is not None:
        if len(c.epoch_baseline)!=2 or any(v is not None and not np.isfinite(v) for v in c.epoch_baseline):
            raise ValueError('epoch_baseline must be None or two finite endpoints/None')
        lo,hi=c.epoch_baseline
        lo=c.epoch_tmin if lo is None else lo
        hi=c.epoch_tmax if hi is None else hi
        if not c.epoch_tmin <= lo <= hi <= c.epoch_tmax:
            raise ValueError('Baseline must lie inside the event epoch')
    if not 0 <= c.fixed_epoch_overlap < c.fixed_epoch_duration:
        raise ValueError('Require 0 <= fixed_epoch_overlap < fixed_epoch_duration')
    if c.repair_epochs and (c.epoch_mode not in ('none','events') or c.purpose != 'erp' or c.epoch_qc == 'annotations'):
        raise ValueError('Local repair requires ERP event epochs with event-window QC')
    for key in ['report_waveform_windows','report_max_channels','report_dpi','report_max_width','report_psd_windows']:
        value=getattr(c,key)
        if isinstance(value,bool) or not isinstance(value,int) or value<1:
            raise ValueError(key+' must be a positive integer')
    if c.report_max_channels<2 or c.report_dpi<60 or c.report_max_width<600:
        raise ValueError('Report requires >=2 channels, >=60 dpi and >=600 pixel width')
    for key in ['report_window_seconds','report_psd_window_seconds']:
        value=getattr(c,key)
        if key=='report_window_seconds' and value is None:raise ValueError('report_window_seconds is required')
        if value is not None and (not np.isfinite(value) or value<=0):
            raise ValueError(key+' must be positive')


def resolve_epoch_config(config, epoch_config=None, *, sfreq=None):
    """Resolve the epoch stage once, retaining legacy repair-only controls.

    A supplied EpochConfig remains an explicit, complete epoch-stage override;
    it does not change continuous QC thresholds. Fixed epochs always use their
    configured duration with no baseline, as in the existing delivery stage.
    """
    from .epochs import EpochConfig
    from .parameter_resolution import adjustment
    from .settings import _freeze_options
    base=EpochConfig(tmin=config.epoch_tmin,tmax=config.epoch_tmax,baseline=config.epoch_baseline,
        peak_uv=config.residual_peak_uv,ptp_uv=config.residual_ptp_uv,robust_z=config.residual_robust_z,
        relative_min_ptp_uv=config.residual_relative_min_ptp_uv,seed=config.seed)
    defaults=asdict(base);values=dict(defaults);audit=[]
    if isinstance(epoch_config,EpochConfig):
        supplied=asdict(epoch_config);audit.extend(getattr(epoch_config,'adjustments',()))
    elif isinstance(epoch_config,Mapping):supplied=dict(epoch_config)
    elif epoch_config is None:supplied={}
    else:
        supplied={};audit.append(adjustment('epoch_config',epoch_config,None,
            'Unsupported epoch configuration; resolved pipeline epoch defaults used'))
    for key,value in supplied.items():
        if key in values:values[key]=value
        else:audit.append(adjustment('epoch_config.'+str(key),value,None,'Unknown epoch parameter ignored'))
    def fallback(key,reason):
        audit.append(adjustment('epoch_config.'+key,values[key],defaults[key],reason+'; resolved epoch default used'))
        values[key]=defaults[key]
    for field in fields(EpochConfig):
        if field.name=='baseline':continue
        value=values[field.name];expected=Integral if field.type is int else Real
        if isinstance(value,(bool,np.bool_)) or not isinstance(value,expected) or not np.isfinite(value):
            fallback(field.name,'Invalid type or nonfinite value')
        elif isinstance(value,np.integer):values[field.name]=int(value)
    if values['tmin']>0:fallback('tmin','Epoch start must be at or before zero')
    if values['tmax']<=0:fallback('tmax','Epoch end must follow zero')
    for key in ('peak_uv','ptp_uv','robust_z','relative_min_ptp_uv'):
        if values[key]<=0:fallback(key,'Artifact limit must be positive')
    if not 0<=values['seed']<2**32:fallback('seed','Invalid random seed')
    if values['max_interpolate']<1:fallback('max_interpolate','Interpolation budget must be positive')
    if not 0<values['max_local_fraction']<=.25:fallback('max_local_fraction','Local interpolation fraction outside supported range')
    if values['cv']<2:fallback('cv','Cross-validation needs at least two folds')
    if values['min_fit_epochs']<values['cv']:
        fallback('cv','Cross-validation exceeds available fitting requirement')
        fallback('min_fit_epochs','Fitting requirement below supported cross-validation count')
    baseline=values['baseline']
    if baseline is not None:
        valid=isinstance(baseline,(list,tuple)) and len(baseline)==2 and all(v is None or (
            isinstance(v,Real) and not isinstance(v,(bool,np.bool_)) and np.isfinite(v)) for v in baseline)
        if valid:
            lo=values['tmin'] if baseline[0] is None else baseline[0]
            hi=values['tmax'] if baseline[1] is None else baseline[1]
            valid=values['tmin']<=lo<=hi<=values['tmax']
        if not valid:
            # (None, 0) is valid for every supported event window, even if a
            # separately supplied epoch window differs from the pipeline one.
            audit.append(adjustment('epoch_config.baseline',baseline,(None,0.),'Baseline outside resolved event window; standard event baseline used'))
            values['baseline']=(None,0.)
        else:values['baseline']=tuple(baseline)
    if config.repair_epochs and values['tmin']==0:
        audit.append(adjustment('epoch_config.tmin',values['tmin'],-.2,'Local repair requires a prestimulus interval; standard event start used'))
        values['tmin']=-.2
    result=EpochConfig(**values)
    if config.epoch_mode == 'fixed':
        if sfreq is None or isinstance(sfreq, bool) or not isinstance(sfreq, Real) or not np.isfinite(sfreq) or sfreq <= 0:
            raise ValueError('Fixed epochs require a finite positive sampling frequency')
        result = replace(result,tmin=0.,tmax=config.fixed_epoch_duration-1/sfreq,baseline=None)
    if not result.tmin <= 0 < result.tmax:
        raise ValueError('Invalid ERP epoch window or artifact limits')
    if min(result.peak_uv,result.ptp_uv,result.robust_z,result.relative_min_ptp_uv) <= 0:
        raise ValueError('Invalid ERP epoch window or artifact limits')
    if result.baseline is not None:
        if len(result.baseline) != 2 or any(v is not None and (isinstance(v, (bool, np.bool_)) or
                not isinstance(v, Real) or not np.isfinite(v)) for v in result.baseline):
            raise ValueError('epoch_config.baseline requires two finite endpoints or None')
        lo, hi = result.baseline
        lo = result.tmin if lo is None else lo
        hi = result.tmax if hi is None else hi
        if not result.tmin <= lo <= hi <= result.tmax:
            raise ValueError('Epoch baseline must lie inside the event epoch')
    if config.repair_epochs and (not result.tmin < 0 or not 0 < result.max_local_fraction <= .25 or
            result.max_interpolate < 1 or result.cv < 2 or result.min_fit_epochs < result.cv):
        raise ValueError('Invalid repair budget/CV or epoch window')
    object.__setattr__(result,'adjustments',tuple(_freeze_options(item) for item in audit))
    return result


def resolve_events(raw, config, events=None, event_id=None):
    """Use absolute MNE samples; explicit events override annotation/STIM extraction."""
    import mne
    if events is None:
        if config.event_source in ('auto','annotations'):
            events, mapping=mne.events_from_annotations(raw,event_id=event_id,verbose=False)
            event_id=mapping
        if events is None or (not len(events) and config.event_source=='auto'):
            picks=mne.pick_types(raw.info,stim=True,exclude=[])
            if not len(picks):
                raise ValueError('No stimulus annotations or STIM channel; prepare events explicitly')
            events=mne.find_events(raw,stim_channel=config.stim_channel,verbose=False)
            if event_id is None or not event_id:
                event_id={str(int(code)):int(code) for code in np.unique(events[:,2])}
    events=np.asarray(events)
    if events.ndim!=2 or events.shape[1]!=3 or not len(events) or not np.isfinite(events).all() or not np.equal(events,np.round(events)).all():
        raise ValueError('events must be a nonempty integer array (n_events, 3) in absolute MNE samples')
    events=events.astype(int)
    if event_id is None:
        event_id={str(int(code)):int(code) for code in np.unique(events[:,2])}
    event_id=dict(event_id)
    if config.event_names:
        missing=set(config.event_names)-set(event_id)
        if missing:raise ValueError('Unknown event names: '+', '.join(sorted(missing)))
        event_id={name:event_id[name] for name in config.event_names}
    events=events[np.isin(events[:,2],list(event_id.values()))]
    if not len(events):raise ValueError('No selected events')
    return events,event_id
