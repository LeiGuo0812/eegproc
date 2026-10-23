"""Thin FIF-to-Raw adapter; device preparation lives in eegproc-prepare."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import sys
import mne


def number(value):
    """Parse valid CLI numbers; retain invalid values for central resolution."""
    try:
        return float(value)
    except ValueError:
        return value


def integer(value):
    try:
        return int(value)
    except ValueError:
        return value


def optional_number(value):
    return None if value.lower() in ('off','none') else number(value)


def option(p, name, choices, **kwargs):
    """Document choices without bypassing the shared configuration audit."""
    p.add_argument('--'+name, metavar='{'+','.join(choices)+'}', default=None, **kwargs)


def parser():
    p=argparse.ArgumentParser(description='EEG preprocessing from prepared MNE Raw/FIF. Device input: eegproc-prepare. Priority: preset < JSON < explicit flags. Invalid scientific settings are resolved by the shared configuration policy and recorded in the report.')
    start=p.add_mutually_exclusive_group(required=True)
    start.add_argument('--input-fif');start.add_argument('--resume',help='ICA review checkpoint.json; resumes without refitting')
    p.add_argument('--save-path',required=True);p.add_argument('--subject',required=True)
    option(p,'preset',['standard','eeglab'])
    option(p,'ica-mode',['auto','review','manual'])
    p.add_argument('--ica-exclude',nargs='*',type=integer,default=None,help='Zero-based final list; an empty list explicitly keeps all')
    p.add_argument('--selection-json');p.add_argument('--review-author',default=None);p.add_argument('--review-reason',default=None)
    p.add_argument('--original-fif',help='Original prepared FIF for resume if moved or not recorded; no new copy is saved')
    for name in ['ica-enabled','interpolate-bads','interpolate-before-asr','exclude-gross-from-training','residual-qc']:
        p.add_argument('--'+name,action=argparse.BooleanOptionalAction,default=None)
    for name,choices in {'filter-method':['mne_fir','eeglab_fir','off'],'filter-position':['after_reference'],
        'line-method':['spectrum_fit','notch','off'],'channel-method':['pyprep','eegprep','off'],
        'reference':['average','unchanged'],'rank-method':['relative','covariance']}.items():
        option(p,name,choices)
    option(p,'ica-rule',['threshold','class_max'],
        help='threshold: probability cutoffs and ECG support when available; class_max: original script rule (Eye, or Muscle/Line/Channel with Brain <= 0.5; ties count; no Heart/Other)')
    # JSON-valued overrides expose every field, including rarely adjusted thresholds.
    p.add_argument('--set',dest='settings',action='append',default=[],metavar='KEY=JSON',help='Example: --set ica_max_iter=4096')
    p.add_argument('--config');option(p,'purpose',['rest','erp'])
    p.add_argument('--task-name',default=None,help='Recording task label, e.g. rest, oddball or stroop; independent of purpose')
    for name in ['highpass','lowpass','artifact-threshold','brain-probability-max','heart-min-ecg-correlation']:
        p.add_argument('--'+name,type=number,default=None)
    p.add_argument('--line-frequency',type=optional_number,default=argparse.SUPPRESS,help='50, 60, another known frequency, or off')
    p.add_argument('--asr-cutoff',type=optional_number,default=argparse.SUPPRESS,help='Positive cutoff or off; default 20 for both rest and ERP')
    option(p,'bad-channel-policy',['auto','report','stop'])
    option(p,'ica-method',['picard','infomax'])
    p.add_argument('--seed',type=integer,default=None);p.add_argument('--n-threads',type=integer,default=None)
    p.add_argument('--detect-ransac',action=argparse.BooleanOptionalAction,default=None)
    ep=p.add_mutually_exclusive_group()
    ep.add_argument('--epochs',dest='epoch_mode',action='store_const',const='events',default=None)
    option(ep,'epoch-mode',['none','events','fixed'])
    ep.add_argument('--fixed-epochs',dest='fixed_epoch_duration',type=number,default=None,metavar='SECONDS')
    option(p,'epoch-qc',['auto','event-window','annotations'])
    p.add_argument('--repair-epochs',action=argparse.BooleanOptionalAction,default=None)
    p.add_argument('--event-names',nargs='+',default=None)
    option(p,'event-source',['auto','annotations','stim'])
    p.add_argument('--stim-channel',default=None)
    p.add_argument('--events-json',help='Explicit {events, event_id}; prepared sibling .events.json is read automatically when nonempty')
    p.add_argument('--tmin',dest='epoch_tmin',type=number,default=None);p.add_argument('--tmax',dest='epoch_tmax',type=number,default=None)
    p.add_argument('--baseline',nargs='+',help='Two endpoints (e.g. -0.2 0), or off')
    p.add_argument('--fixed-overlap',dest='fixed_epoch_overlap',type=number,default=None)
    for name in ['report-full-record-heatmap']:
        p.add_argument('--'+name,action=argparse.BooleanOptionalAction,default=None)
    for name in ['report-waveform-windows','report-max-channels','report-dpi','report-max-width','report-psd-windows']:
        p.add_argument('--'+name,type=integer,default=None)
    for name in ['report-window-seconds','report-psd-window-seconds']:
        p.add_argument('--'+name,type=number,default=None)
    return p


def main(argv=None):
    from eegproc.configuration import resolve_config
    from eegproc.api import run, resume
    p=parser();a=p.parse_args(argv)
    if a.resume:
        allowed={'resume','save_path','subject','selection_json','ica_exclude','review_author','review_reason','settings','original_fif'}
        unexpected=[k for k,v in vars(a).items() if k not in allowed and v is not None]
        if unexpected or a.settings:p.error('Resume freezes the original configuration; only selection/reviewer/reason and output are accepted')
        result=resume(a.resume,a.save_path,a.subject,selection_json=a.selection_json,
            exclude=a.ica_exclude,reviewer=a.review_author or '',reason=a.review_reason or '',
            original_fif=a.original_fif)
        report=result.report
        print(json.dumps(dict(status=report['status'],outputs=report['outputs']),ensure_ascii=False,indent=2));return
    if a.selection_json:p.error('--selection-json requires --resume')
    if a.original_fif:p.error('--original-fif is only used with --resume')
    io_keys={'input_fif','resume','save_path','subject','config','events_json','baseline','settings','selection_json','original_fif'}
    overrides={k:v for k,v in vars(a).items() if k not in io_keys and (v is not None or k in ('asr_cutoff','line_frequency'))}
    for setting in a.settings:
        try:key,value=setting.split('=',1);value=json.loads(value)
        except (ValueError,json.JSONDecodeError):p.error('--set requires KEY=JSON')
        if key in overrides:p.error('Duplicate explicit override: '+key)
        overrides[key]=value
    if a.fixed_epoch_duration is not None:overrides['epoch_mode']='fixed'
    if a.baseline is not None:
        if a.baseline==['off']:overrides['epoch_baseline']=None
        else:overrides['epoch_baseline']=tuple(optional_number(x) for x in a.baseline)
    try:config=resolve_config(a.config,**overrides)
    except (ValueError,TypeError) as exc:p.error(str(exc))
    raw=mne.io.read_raw_fif(a.input_fif,preload=False,verbose=False)
    events=event_id=None
    sibling=Path(a.input_fif).with_suffix('.events.json')
    events_path=Path(a.events_json) if a.events_json else sibling
    if config.epoch_mode=='events' and (a.events_json or (config.event_source=='auto' and events_path.is_file())):
        try:
            payload=json.loads(events_path.read_text(encoding='utf-8-sig'))
            if not isinstance(payload,dict):
                raise ValueError('Event JSON must be an object with events and optional event_id')
            if payload.get('events'):
                events,event_id=payload['events'],payload.get('event_id')
            elif a.events_json:
                raise ValueError('Explicit events JSON contains no events')
        except (OSError,UnicodeError,ValueError,TypeError) as exc:
            from .parameter_resolution import adjustment,append_adjustments
            # An empty explicit array makes the epoch resolver skip this request.
            # None would silently switch a failed explicit request to annotations.
            events=[];event_id=None
            config=append_adjustments(config,[adjustment('events_json',str(events_path),[],
                f'Optional event input could not be used ({type(exc).__name__}: {exc}); '
                'skip epoch export and continue continuous preprocessing')])
    sources=[a.input_fif]
    if events is not None:sources.append(str(events_path))
    prep=Path(a.input_fif).with_suffix('.preparation.json')
    if prep.is_file():sources.append(str(prep))
    result=run(raw,a.save_path,a.subject,config=config,events=events,event_id=event_id,
        invocation=dict(entrypoint='eegproc',argv=[sys.executable,*sys.argv] if argv is None else list(argv),
            cwd=str(Path.cwd()),input_paths=sources,config_path=str(Path(a.config).resolve()) if a.config else None,
            config_precedence='preset < JSON < explicit flags',explicit_overrides=overrides,effective_config=asdict(config)))
    report=result.report
    print(json.dumps(dict(status=report['status'],flags=report['quality_flags'],
        epochs_retained=report.get('epochs',{}).get('retained_epochs'),report_storage=report.get('report_storage'),
        outputs=report['outputs']),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
