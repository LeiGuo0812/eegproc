"""Resolve acquisition-dependent parameters without modifying an MNE Raw.

This module adjusts processing requests to the band that the input can support.
It never resamples, restores removed frequencies, guesses electrode positions,
or repairs invalid acquisition metadata. Every changed request is recorded.
"""
from __future__ import annotations

from dataclasses import asdict
import json
from numbers import Integral

import mne
import numpy as np

from .settings import PipelineConfig


def spectrum_fit_support(window_seconds,bandwidth,sfreq,n_times):
    """Check MNE DPSS/COLA constraints using a safely capped sample count.

    MNE uses min(ceil(window_seconds * sfreq), segment_length). Comparing the
    duration before multiplying avoids overflow for finite oversized requests.
    No scientific minimum duration is asserted by this numerical check.
    """
    if n_times<=0:
        count=0
    elif window_seconds>=n_times/sfreq:
        count=int(n_times)
    else:
        count=min(max(1,int(np.ceil(window_seconds*sfreq))),int(n_times))
    half_nbw=(bandwidth/sfreq)*count/2. if bandwidth<sfreq else None
    if count<2:
        reason='Spectrum fitting needs at least two samples for a positive COLA step.'
    elif bandwidth>=sfreq:
        reason='DPSS bandwidth must be strictly below sampling frequency.'
    elif half_nbw<.5:
        reason='DPSS normalized half-bandwidth is below 0.5 for the available window.'
    else:
        reason=None
    return dict(supported=reason is None,window_samples=count,
        normalized_half_bandwidth=half_nbw,reason=reason)


def _input_limits(raw):
    if not isinstance(raw,mne.io.BaseRaw):
        raise TypeError('Input must be a continuous MNE Raw object in SI units')
    try:
        sfreq=float(raw.info['sfreq'])
        highpass=float(raw.info['highpass'])
        lowpass=float(raw.info['lowpass'])
    except (KeyError,TypeError,ValueError) as exc:
        raise ValueError('Input sampling/filter metadata must be finite numeric values') from exc
    nyquist=sfreq/2
    if not np.isfinite([sfreq,highpass,lowpass]).all() or sfreq<=0:
        raise ValueError('Input sampling/filter metadata must be finite with positive sampling frequency')
    if not 0<=highpass<lowpass or lowpass>nyquist*(1+1e-12):
        raise ValueError('Inconsistent input filter metadata: require 0 <= highpass < lowpass <= Nyquist')
    return dict(sfreq_hz=sfreq,nyquist_hz=nyquist,input_highpass_hz=highpass,
                input_lowpass_hz=min(lowpass,nyquist))


def _clip_band(lower,upper,limits):
    """Intersect with acquisition limits; reserve transition width only if needed."""
    nyquist=limits['nyquist_hz'];input_lower=limits['input_highpass_hz']
    lower=max(float(lower),input_lower)
    upper=min(float(upper),limits['input_lowpass_hz'])
    # A valid caller-selected edge strictly below Nyquist is preserved exactly.
    # Only an edge at/above Nyquist needs a positive FIR transition interval.
    if upper>=nyquist:
        anchor=lower if lower<nyquist else input_lower
        reserve=min(2.,.05*nyquist,(nyquist-anchor)/4.)
        upper=nyquist-reserve
    return lower,upper


def _resolve_band(requested,nominal,limits):
    lower,upper=_clip_band(*requested,limits)
    fallback=False
    if not 0<lower<upper:
        # The requested band no longer exists in the input. First retain the
        # purpose/preset's nominal band to the extent acquisition permits.
        lower,upper=_clip_band(*nominal,limits)
        fallback=True
    if not 0<lower<upper:
        # Even the nominal band has no overlap. Use an explicitly reported
        # available interval instead of claiming the requested signal exists.
        _,upper=_clip_band(limits['input_highpass_hz'],limits['input_lowpass_hz'],limits)
        lower=max(limits['input_highpass_hz'],min(float(nominal[0]),upper/2.))
    if not 0<lower<upper<limits['nyquist_hz']:
        raise ValueError('Input filter metadata leaves no positive-width supported processing band')
    return (float(lower),float(upper)),fallback


def resolve_for_raw(config,raw):
    """Return ``(effective_config, audit)`` after input-dependent normalization.

    The static resolver supplies a valid PipelineConfig. Existing valid bands
    are unchanged, including a deliberate cutoff close to Nyquist. Acquisition
    limits take priority over requests; changes require later human review.
    A sampling frequency <=80 Hz disables the native ASR backend because its
    spectral shaping explicitly rejects that sampling range.
    Below 100 Hz, the current ICLabel backend cannot produce its required
    autocorrelation feature length, so the ICA/labeling step is disabled.
    """
    from .configuration import resolve_config
    from .parameter_resolution import append_adjustments

    if not isinstance(config,PipelineConfig):
        raise TypeError('config must be a resolved PipelineConfig')
    limits=_input_limits(raw)
    nominal=PipelineConfig(purpose=config.purpose,preset=config.preset)
    overrides={};changes=[];notes=[];bands={}
    for name,fields in [('analysis',('highpass','lowpass')),
                        ('ica_training',('training_highpass','training_lowpass'))]:
        requested=tuple(float(getattr(config,field)) for field in fields)
        default=tuple(float(getattr(nominal,field)) for field in fields)
        effective,fallback=_resolve_band(requested,default,limits)
        bands[name]=dict(requested_hz=list(requested),effective_hz=list(effective),
                         requested_band_unavailable=fallback)
        for field,old,new in zip(fields,requested,effective):
            if old==new:
                continue
            reason=(f'Input supports highpass >= {limits["input_highpass_hz"]:g} Hz and '
                    f'lowpass <= {limits["input_lowpass_hz"]:g} Hz, strictly below '
                    f'Nyquist {limits["nyquist_hz"]:g} Hz. ')
            if fallback:
                reason+='The requested band has no usable overlap; selected a supported purpose/preset or acquisition band. '
            elif new<old and field.endswith('lowpass'):
                reason+='Clipped the upper edge to input limits with a positive transition interval when at Nyquist. '
            else:
                reason+='Raised the lower edge to the already-applied input highpass. '
            reason+='Removed or unrecorded frequencies cannot be restored.'
            changes.append(dict(field=field,requested=old,effective=new,reason=reason))
            overrides[field]=new
    if config.asr_cutoff is not None and limits['sfreq_hz']<=80:
        reason=('Native ASR spectral shaping requires sfreq > 80 Hz; disabled ASR for '
                f'the {limits["sfreq_hz"]:g} Hz input without changing samples or sampling frequency.')
        changes.append(dict(field='asr_cutoff',requested=config.asr_cutoff,effective=None,reason=reason))
        overrides['asr_cutoff']=None
    if config.ica_enabled and limits['sfreq_hz']<100:
        reason=('The current ICLabel backend autocorrelation feature implementation is unsupported '
                f'below 100 Hz (input: {limits["sfreq_hz"]:g} Hz); disabled the ICA/ICLabel step. '
                'This is a dependency implementation limit, not a general limit of ICA. '
                'No component probabilities or alternative automatic exclusions were generated.')
        changes.append(dict(field='ica_enabled',requested=True,effective=False,reason=reason))
        overrides['ica_enabled']=False
    if config.epoch_mode=='fixed':
        sample_period=1./limits['sfreq_hz']
        recording_seconds=raw.n_times/limits['sfreq_hz']
        if raw.n_times<2:
            raise ValueError('Fixed epochs require an input with at least two samples')
        duration=float(config.fixed_epoch_duration)
        if duration<=sample_period or duration>recording_seconds:
            corrected=min(recording_seconds,max(2.,2*sample_period))
            changes.append(dict(field='fixed_epoch_duration',requested=duration,effective=corrected,
                reason='Requested fixed-epoch duration cannot contain at least two samples within this recording; '
                       'selected the 2 s default limited by the available sample grid.'))
            overrides['fixed_epoch_duration']=corrected;duration=corrected
        if duration-config.fixed_epoch_overlap<sample_period:
            changes.append(dict(field='fixed_epoch_overlap',requested=config.fixed_epoch_overlap,effective=0.,
                reason='Requested overlap leaves less than one sample between epoch starts; '
                       'selected zero overlap to avoid duplicate or reversed event samples.'))
            overrides['fixed_epoch_overlap']=0.
    line_support=None
    if config.line_method=='spectrum_fit' and config.line_frequency is not None:
        window=config.line_window_seconds;bandwidth=config.line_bandwidth
        if not np.isfinite(float(window)*float(limits['sfreq_hz'])):
            capped=raw.n_times/limits['sfreq_hz']
            changes.append(dict(field='line_window_seconds',requested=window,effective=capped,
                reason='Requested window-to-sample conversion overflows; limited to the complete recording duration.'))
            overrides['line_window_seconds']=capped;window=capped
        line_support=spectrum_fit_support(window,bandwidth,limits['sfreq_hz'],raw.n_times)
        if not line_support['supported']:
            for field,old,new in [('line_window_seconds',window,4.),('line_bandwidth',bandwidth,2.)]:
                if old!=new:
                    changes.append(dict(field=field,requested=old,effective=new,
                        reason=line_support['reason']+' Selected the standard 4 s / 2 Hz pair; '
                               'segments still too short will be left unchanged and reported.'))
                    overrides[field]=new
            window=4.;bandwidth=2.
            line_support=spectrum_fit_support(window,bandwidth,limits['sfreq_hz'],raw.n_times)
    effective=resolve_config(config,**overrides) if overrides else config
    if changes:
        effective=append_adjustments(effective,changes)
        notes.append('Processing parameters were adjusted to acquisition limits; review effective bands, epoch timing and disabled steps before analysis.')
    training=bands['ica_training']['effective_hz']
    nominal_iclabel_band=training==[1.,100.]
    training_adjusted=any(row['field'] in ('training_highpass','training_lowpass') for row in changes)
    if effective.ica_enabled and training_adjusted and not nominal_iclabel_band:
        notes.append(f'ICA training uses {training[0]:g}–{training[1]:g} Hz rather than 1–100 Hz. '
                     'ICLabel results require manual review; this is not the nominal ICLabel training band.')
    audit=dict(schema_version=1,input_limits=limits,bands=bands,adjustments=changes,
        review_notes=notes,manual_review_required=bool(changes or notes),
        iclabel_nominal_training_band=nominal_iclabel_band,
        line_spectrum_fit=line_support,
        asr_enabled=effective.asr_cutoff is not None,ica_enabled=effective.ica_enabled,data_modified=False,
        resampling_applied=False,removed_frequencies_restored=False)
    return effective,audit


def resolve_manual_exclude(config,n_components):
    """Discard unavailable manual indices without substituting automatic choices.

    Static normalization has already validated the index types and removed
    duplicates. The fitted decomposition supplies the upper bound here. An
    empty surviving list deliberately keeps every component in manual mode.
    """
    from .configuration import resolve_config
    from .parameter_resolution import adjustment,append_adjustments

    if not isinstance(config,PipelineConfig):
        raise TypeError('config must be a resolved PipelineConfig')
    if isinstance(n_components,(bool,np.bool_)) or not isinstance(n_components,Integral) or n_components<1:
        raise ValueError('n_components must be a positive integer from the fitted decomposition')
    if not config.ica_enabled or config.ica_mode!='manual':
        return config,[]
    requested=tuple(config.ica_exclude or ())
    retained=tuple(index for index in requested if index<n_components)
    if retained==requested:
        return config,[]
    record=adjustment('ica_exclude',requested,retained,
        f'Removed indices outside the fitted component range 0–{n_components-1}; '
        'manual selection is retained. An empty list keeps all components; automatic selection is not substituted.')
    effective=resolve_config(config,ica_mode='manual',ica_exclude=retained)
    return append_adjustments(effective,[record]),[record]


def update_parameter_report(report,config,extra=()):
    """Merge parameter adjustments and synchronize the report's effective config."""
    from .parameter_resolution import adjustment

    if not isinstance(config,PipelineConfig):
        raise TypeError('config must be a resolved PipelineConfig')
    records=[];seen=set()
    for record in [*report.get('parameter_adjustments',()),*config.adjustments,*extra]:
        normalized=adjustment(record['field'],record.get('requested'),record.get('effective'),record['reason'])
        key=json.dumps(normalized,sort_keys=True,ensure_ascii=False,allow_nan=False)
        if key not in seen:
            records.append(normalized);seen.add(key)
    report['parameter_adjustments']=records
    report['config']=asdict(config)
    if records:
        flag='Parameters were adjusted automatically; review the effective configuration before analysis.'
        flags=report.setdefault('quality_flags',[])
        if flag not in flags:
            flags.append(flag)
    invocation=report.get('provenance',{}).get('invocation')
    if isinstance(invocation,dict):
        invocation['effective_config']=asdict(config)
    return report
