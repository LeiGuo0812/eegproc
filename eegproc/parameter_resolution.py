"""Audited parameter normalization; valid scientific settings are unchanged."""
from dataclasses import fields
from numbers import Integral, Real
from types import UnionType
from typing import get_args, get_origin
import math
import numpy as np


def audit_value(value):
    """A compact JSON-safe requested/effective value for the HTML audit."""
    if value is None or isinstance(value,(str,bool,int)):
        return value
    if isinstance(value,(float,np.floating)):
        return float(value) if math.isfinite(value) else str(value)
    if isinstance(value,np.integer):return int(value)
    if isinstance(value,np.bool_):return bool(value)
    if isinstance(value,np.ndarray):return audit_value(value.tolist())
    if isinstance(value,dict):return {str(k):audit_value(v) for k,v in value.items()}
    if isinstance(value,(tuple,list)):return [audit_value(v) for v in value]
    return repr(value)


def adjustment(field,requested,effective,reason):
    return dict(field=str(field),requested=audit_value(requested),effective=audit_value(effective),reason=str(reason))


def append_adjustments(config,records):
    """Attach immutable non-scientific audit records without adding config fields."""
    from .settings import _freeze_options
    previous=list(getattr(config,'adjustments',()))
    for record in records:
        item=adjustment(record['field'],record.get('requested'),record.get('effective'),record['reason'])
        frozen=_freeze_options(item)
        if frozen not in previous:previous.append(frozen)
    object.__setattr__(config,'_adjustments',tuple(previous))
    return config


def _valid_type(value,annotation):
    allowed=get_args(annotation) if get_origin(annotation) is UnionType else (annotation,)
    if value is None:return type(None) in allowed
    if bool in allowed:return isinstance(value,bool)
    if int in allowed:return isinstance(value,Integral) and not isinstance(value,(bool,np.bool_))
    if float in allowed:return isinstance(value,Real) and not isinstance(value,(bool,np.bool_)) and np.isfinite(value)
    if str in allowed:return isinstance(value,str)
    if tuple in allowed:return isinstance(value,(tuple,list))
    if dict in allowed:return isinstance(value,dict)
    return False


def normalize_parameters(supplied,definitions,preset_defaults):
    """Return complete valid parameters plus every fallback/dependency action."""
    base={field.name:field.default for field in definitions}
    known={field.name:field for field in definitions};audit=[]
    raw=dict(supplied)
    for key in list(raw):
        if key not in known:
            audit.append(adjustment(key,raw.pop(key),None,'Unknown or retired parameter ignored'))
    purpose=raw.get('purpose',base['purpose']);preset=raw.get('preset',base['preset'])
    if not isinstance(purpose,str) or purpose not in ('rest','erp'):
        audit.append(adjustment('purpose',purpose,base['purpose'],'Invalid purpose; selected standard default'))
        purpose=base['purpose'];raw['purpose']=purpose
    if not isinstance(preset,str) or preset not in ('standard','eeglab'):
        audit.append(adjustment('preset',preset,base['preset'],'Invalid preset; selected standard default'))
        preset=base['preset'];raw['preset']=preset
    base.update(preset_defaults(purpose,preset))
    values={**base,**raw}
    def set_value(key,value,reason):
        audit.append(adjustment(key,values[key],value,reason));values[key]=value
    def fallback(key,reason):set_value(key,base[key],reason+'; selected preset default')
    for key,field in known.items():
        if key=='ica_exclude':continue  # Preserve manual intent even when malformed.
        value=values[key]
        if not _valid_type(value,field.type):
            fallback(key,'Invalid type or nonfinite value')
        elif isinstance(value,np.integer):values[key]=int(value)
        elif isinstance(value,(list,tuple)) and key in ('epoch_baseline','event_names'):
            values[key]=tuple(value)
    choices=dict(filter_method=('mne_fir','eeglab_fir','off'),filter_position=('after_reference',),
        line_method=('spectrum_fit','notch','off'),channel_method=('pyprep','eegprep','off'),
        reference=('average','unchanged'),ica_mode=('auto','review','manual'),
        ica_rule=('threshold','class_max'),rank_method=('relative','covariance'),
        ica_backend=('mne',),asr_backend=('mne_native',),bad_channel_policy=('auto','report','stop'),
        ica_method=('picard','infomax'),epoch_mode=('none','events','fixed'),
        epoch_qc=('auto','event-window','annotations'),event_source=('auto','annotations','stim'))
    for key,allowed in choices.items():
        if values[key] not in allowed:fallback(key,'Unsupported choice')
    if values['task_name'] is not None:
        value=values['task_name']
        if not value.strip() or value!=value.strip() or len(value)>100 or any(ord(c)<32 for c in value):
            fallback('task_name','Invalid task label')
    if values['event_names'] is not None and any(not isinstance(v,str) or not v.strip() for v in values['event_names']):
        fallback('event_names','Invalid event-name sequence')
    for key in ('highpass','lowpass','training_highpass','training_lowpass','min_training_seconds',
                'gross_peak_uv','residual_peak_uv','residual_ptp_uv','residual_robust_z',
                'residual_relative_min_ptp_uv','window_seconds','ica_tolerance','flatline_seconds',
                'line_window_seconds','line_bandwidth','fixed_epoch_duration','report_window_seconds'):
        if values[key]<=0:fallback(key,'Value must be positive')
    for key in ('asr_cutoff','line_frequency','report_psd_window_seconds'):
        if values[key] is not None and values[key]<=0:fallback(key,'Value must be positive or None')
    for key in ('bad_channel_fraction_limit','channel_correlation','channel_broken_fraction','line_p_value'):
        if not 0<values[key]<1:fallback(key,'Value must lie strictly between zero and one')
    for key,lo,hi in [('artifact_threshold',.5,1.),('brain_probability_max',0.,.5),('heart_min_ecg_correlation',0.,1.)]:
        if not lo<=values[key]<=hi:fallback(key,'Probability/support threshold outside supported range')
    for key in ('n_threads','ica_max_iter','report_waveform_windows','report_psd_windows'):
        if values[key]<1:fallback(key,'Count must be a positive integer')
    for key,minimum in [('report_max_channels',2),('report_dpi',60),('report_max_width',600)]:
        if values[key]<minimum:fallback(key,'Value below supported display minimum')
    if values['filter_order']<2 or values['filter_order']%2:fallback('filter_order','Filter order must be even and at least two')
    if not 0<=values['seed']<2**32:fallback('seed','Seed must be an unsigned 32-bit integer')
    if values['guard_seconds']<0:fallback('guard_seconds','Guard duration must be nonnegative')
    for low,high in [('highpass','lowpass'),('training_highpass','training_lowpass')]:
        if values[low]>=values[high]:
            fallback(low,'Inverted or empty frequency band');fallback(high,'Inverted or empty frequency band')
    if values['epoch_tmin']>0:fallback('epoch_tmin','Event window must start at or before zero')
    if values['epoch_tmax']<=0:fallback('epoch_tmax','Event window must end after zero')
    if not 0<=values['fixed_epoch_overlap']<values['fixed_epoch_duration']:
        fallback('fixed_epoch_overlap','Overlap must be nonnegative and shorter than each epoch')
    baseline=values['epoch_baseline']
    if baseline is not None:
        valid=len(baseline)==2 and all(v is None or (isinstance(v,Real) and not isinstance(v,(bool,np.bool_)) and np.isfinite(v)) for v in baseline)
        if valid:
            lo=values['epoch_tmin'] if baseline[0] is None else baseline[0]
            hi=values['epoch_tmax'] if baseline[1] is None else baseline[1]
            valid=values['epoch_tmin']<=lo<=hi<=values['epoch_tmax']
        if not valid:fallback('epoch_baseline','Baseline must be contained in the resolved event window')

    exclusion=values['ica_exclude']
    if not values['ica_enabled']:
        if values['ica_mode']!='auto':set_value('ica_mode','auto','ICA is explicitly disabled; review/manual mode is inactive')
        if exclusion is not None:set_value('ica_exclude',None,'ICA is disabled; component selection is inactive')
    elif values['ica_mode']=='review':
        if exclusion is not None:set_value('ica_exclude',None,'Review mode pauses before applying a final selection')
    else:
        if values['ica_mode']=='auto' and exclusion is not None:
            set_value('ica_mode','manual','An explicit component list selects manual application')
        if values['ica_mode']=='manual':
            valid=isinstance(exclusion,(tuple,list)) and all(isinstance(v,Integral) and not isinstance(v,(bool,np.bool_)) and v>=0 for v in exclusion)
            if not valid:set_value('ica_exclude',(),'Missing or malformed manual selection; keep all components and require human review')
            elif len(set(exclusion))!=len(exclusion):set_value('ica_exclude',tuple(dict.fromkeys(int(v) for v in exclusion)),'Duplicate manual component indices removed; selection unchanged')
            else:values['ica_exclude']=tuple(int(v) for v in exclusion)
    if values['interpolate_before_asr'] and not values['interpolate_bads']:
        set_value('interpolate_before_asr',False,'Global interpolation is explicitly disabled')
    if values['interpolate_bads'] and not (values['interpolate_before_asr'] or values['final_interpolation']):
        set_value('interpolate_bads',False,'Both interpolation stages are disabled')
    if values['repair_epochs'] and (values['purpose']!='erp' or values['epoch_mode']=='fixed' or values['epoch_qc']=='annotations'):
        set_value('repair_epochs',False,'Local repair is inapplicable to the selected purpose, epoch mode or annotation-only QC')
    options=values['asr_options']
    if options is not None:
        from .mne_asr import ASRConfig
        option_fields={field.name:field for field in fields(ASRConfig)};effective={}
        for key,value in options.items():
            reason=None;candidate=value
            if key not in option_fields:reason='Unknown ASR option ignored'
            elif key in ('cutoff','min_segment_seconds'):reason='ASR option is controlled by its top-level parameter'
            elif key=='reference_tolerances':
                if not isinstance(value,(list,tuple)) or len(value)!=2 or any(not isinstance(v,Real) or isinstance(v,(bool,np.bool_)) for v in value):reason='Malformed ASR reference interval ignored'
                else:candidate=tuple(value)
            elif key=='step_size':
                if value is not None and (not isinstance(value,Integral) or isinstance(value,(bool,np.bool_))):reason='Invalid ASR integer option ignored'
                elif value is not None:candidate=int(value)
            elif value is None and key=='processing_window':pass
            elif not isinstance(value,Real) or isinstance(value,(bool,np.bool_)) or not np.isfinite(value):reason='Invalid ASR numeric option ignored'
            if reason is None:
                try:ASRConfig(**{key:candidate}).validate()
                except (ValueError,TypeError,OverflowError):reason='ASR option outside supported range; backend default used'
            if reason is None:effective[key]=candidate
            else:audit.append(adjustment('asr_options.'+str(key),value,None,reason))
        if effective!=options:values['asr_options']=effective
    return values,audit
