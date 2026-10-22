"""Hash-checked ICA checkpoints with an external input; resume never refits ICA."""
from dataclasses import asdict, replace
from pathlib import Path
import copy
import html
import json
import time
import uuid
import warnings
import mne
import numpy as np
from threadpoolctl import threadpool_limits
from ._utils import _json_default
from .report_provenance import file_hash, StageRecorder, capture_provenance, utc_now
from .ica import apply_ica, validate_exclude
from .storage import OutputStore,OutputPlan,atomic_save_raw,atomic_save_ica,atomic_write_json
from .compatibility import (CHECKPOINT_SCHEMA,checkpoint_path,validate_checkpoint_compatibility)


def _write(path,payload):
    atomic_write_json(path,payload)


def save_checkpoint(original,current,analysis,preview,model,config,report,directory,subject,events,event_id,epoch_config,paths):
    from .checkpoint_input import input_reference
    from .quality_figures import ica_figures,style
    started=time.perf_counter()
    if report['ica'].get('applied') or model.exclude:
        raise ValueError('ICA checkpoint must be saved before applying component exclusions')
    folder=directory/f'{subject}_ica_review'
    folder.mkdir(parents=True,exist_ok=True)
    files=[];artifacts={}
    # One complete MNE container: analysis EEG, untouched auxiliaries, original
    # time/annotations, and bad-channel slots needed by final reconstruction.
    pre_ica=current.copy()
    for i,name in enumerate(analysis.ch_names):
        pre_ica._data[pre_ica.ch_names.index(name)]=analysis._data[i]
    pre_ica.info['bads']=[name for name in dict.fromkeys([*current.info['bads'],*report['bad_channels']])
                          if name not in analysis.ch_names]
    with pre_ica.info._unlock():
        for key in ('highpass','lowpass','custom_ref_applied'):
            pre_ica.info[key]=analysis.info[key]
    target=folder/'pre_ica_raw.fif'
    saved=atomic_save_raw(pre_ica,target)
    artifacts['pre_ica']=target.relative_to(directory).as_posix()
    files.extend(dict(path=Path(p).relative_to(directory).as_posix(),sha256=file_hash(p)) for p in saved)
    del pre_ica
    # Persist only component plots and downsampled numeric diagnostics, never
    # another original or training-preview recording.
    with style(report.get('config',{})):
        figures,notes=ica_figures(report,folder,model,preview)
    report['ica_display']=dict(figures=figures,notes=notes,
                              diagnostics=report.get('ica_diagnostics',[]))
    # The final model records applied exclusions. Keep a separate frozen decomposition
    # so later saves cannot invalidate the pre-application checkpoint.
    frozen_model=folder/'decomposition-ica.fif'
    atomic_save_ica(model,frozen_model)
    artifacts['ica']=frozen_model.relative_to(directory).as_posix()
    files.append(dict(path=artifacts['ica'],sha256=file_hash(frozen_model)))
    checkpoint=folder/'checkpoint.json'
    identifier=str(uuid.uuid4())
    for item in files:
        path=checkpoint_path(directory,item['path'])
        report.setdefault('output_files',[]).append(dict(path=str(path),
            kind='pre_ica' if path in saved else 'decomposition',bytes=path.stat().st_size,
            sha256=item['sha256'],status='committed'))
    payload=dict(schema=CHECKPOINT_SCHEMA,checkpoint_id=identifier,subject=subject,
        config=asdict(config),report=copy.deepcopy(report),artifacts=artifacts,files=files,
        events=events,event_id=event_id,epoch_config=asdict(epoch_config) if epoch_config else None,
        root='..',model_sha256=file_hash(frozen_model),applied=False,
        original_input=input_reference(original,report['input_sha256']),
        compatibility=copy.deepcopy(report['provenance']['computation']))
    payload['report'].pop('ica_diagnostics',None)  # Stored once in ica_display.
    # The checkpoint save is complete once this JSON is committed.
    for step in payload['report'].get('execution',[]):
        if step['stage']=='save_ica_checkpoint' and step['status']=='running':
            step.update(status='completed',ended_utc=utc_now(),elapsed_seconds=time.perf_counter()-started)
    _write(checkpoint,payload)
    report.setdefault('output_files',[]).append(dict(path=str(checkpoint),kind='checkpoint',
        bytes=checkpoint.stat().st_size,sha256=file_hash(checkpoint),status='committed'))
    selection=dict(schema='eeg-ica-selection-v1',checkpoint_id=identifier,
        model_sha256=payload['model_sha256'],reviewed=False,
        exclude=report['ica']['automatic_proposal_0based'],reviewer='',reason='')
    paths.update(checkpoint=checkpoint,pre_ica=folder/'pre_ica_raw.fif',decomposition=frozen_model)
    if config.ica_mode=='review':paths['ica']=frozen_model
    report['ica_checkpoint']=dict(checkpoint_id=identifier,model_sha256=payload['model_sha256'],
        status='available',selection_template=selection,files=files,root=str(directory))


def resume_ica(checkpoint,save_path,subject=None,*,selection_json=None,exclude=None,reviewer='',reason='',collect_stages=False,
               original_raw=None,original_fif=None):
    from .configuration import resolve_config
    from .delivery import ProcessingContext,finish_processing
    from .quality_report import safe_report
    checkpoint=Path(checkpoint).resolve();payload=json.loads(checkpoint.read_text(encoding='utf-8-sig'))
    if payload.get('schema')!=CHECKPOINT_SCHEMA or payload.get('applied') is not False:
        raise ValueError('Unsupported or already applied ICA checkpoint; legacy v1 requires its original source version')
    if selection_json is not None and exclude is not None:raise ValueError('Supply selection_json or exclude, not both')
    if selection_json is not None:
        chosen=json.loads(Path(selection_json).read_text(encoding='utf-8-sig'))
        if chosen.get('schema')!='eeg-ica-selection-v1' or chosen.get('reviewed') is not True:
            raise ValueError('Selection must be explicitly reviewed=true')
        if chosen.get('checkpoint_id')!=payload['checkpoint_id'] or chosen.get('model_sha256')!=payload['model_sha256']:
            raise ValueError('Selection belongs to a different ICA checkpoint/model')
        exclude=chosen.get('exclude');reviewer=chosen.get('reviewer','');reason=chosen.get('reason','')
    if payload.get('root')!='..':raise ValueError('Unsupported checkpoint root layout')
    root=checkpoint.parent.parent.resolve()
    def source(path):
        return checkpoint_path(root,path)
    for record in payload['files']:
        if file_hash(source(record['path']))!=record['sha256']:raise ValueError('Checkpoint artifact hash mismatch: '+record['path'])
    config=resolve_config(**{**payload['config'],'ica_mode':'manual','ica_exclude':exclude,
        'review_author':reviewer,'review_reason':reason})
    from .parameter_resolution import append_adjustments, adjustment
    if not isinstance(collect_stages, bool):
        append_adjustments(config, [adjustment('collect_stages', collect_stages, False,
            'Expected a boolean; optional in-memory stage collection disabled')])
        collect_stages = False
    compatibility=validate_checkpoint_compatibility(payload)
    directory=Path(save_path).resolve()
    if directory.is_relative_to(root) or root.is_relative_to(directory):
        raise ValueError('Resume requires a separate output directory; never overwrite the checkpoint')
    subject=subject or payload['subject']
    import re
    if not re.fullmatch(r'[\w.-]+',subject) or subject in ('.','..'):raise ValueError('subject must be a safe basename')
    artifacts=payload['artifacts']
    model=mne.preprocessing.read_ica(source(artifacts['ica']),verbose='warning')
    from .runtime_parameters import resolve_manual_exclude, update_parameter_report
    config, _ = resolve_manual_exclude(config, model.n_components_)
    exclude=validate_exclude(config.ica_exclude,model.n_components_)
    from .checkpoint_input import load_original
    original=load_original(payload['original_input'],original_raw=original_raw,original_fif=original_fif)
    OutputPlan(directory,subject,source_paths=[p for p in original.filenames if p]).preflight()
    pre_ica=mne.io.read_raw_fif(source(artifacts['pre_ica']),preload=False,verbose=False)
    analysis=pre_ica.copy().pick(model.ch_names).load_data()
    # Reuse exact input metadata rather than introducing FIF rounding changes.
    current=original.copy().load_data()
    if payload['report']['provenance'].get('montage_override'):
        current.set_montage(pre_ica.get_montage(),on_missing='raise',verbose=False)
    directory.mkdir(parents=True,exist_ok=True)
    report=copy.deepcopy(payload['report']);report.update(config=asdict(config),task_name=config.task_name,
        status='running',stage_files=[],output_files=[])
    report['parent_run']=dict(checkpoint=str(checkpoint),checkpoint_id=payload['checkpoint_id'],
        model_sha256=payload['model_sha256'],fit_repeated=False,source_run_uuid=report['provenance']['run_uuid'],
        execution=report.pop('execution',[]),compatibility=compatibility)
    report['provenance']=capture_provenance(original,subject,dict(entrypoint='eegproc.resume',input_paths=[str(checkpoint)]))
    report['provenance']['montage_override']=payload['report']['provenance'].get('montage_override')
    update_parameter_report(report, config)
    paths=dict(raw=directory/f'{subject}_cont_raw.fif',ica=directory/f'{subject}-ica.fif',quality_report=directory/f'{subject}_report.html')
    # Revisions reuse the same immutable checkpoint, including for subsequent revisions.
    # No additional copies of the pre-ICA data are needed.
    paths.update(checkpoint=checkpoint,pre_ica=source(artifacts['pre_ica']),decomposition=source(artifacts['ica']))
    report['ica_checkpoint']=dict(checkpoint_id=payload['checkpoint_id'],model_sha256=payload['model_sha256'],
        status='available',root=str(root),reused=True,files=payload['files'],
        selection_template=dict(schema='eeg-ica-selection-v1',checkpoint_id=payload['checkpoint_id'],
            model_sha256=payload['model_sha256'],reviewed=False,exclude=exclude,reviewer='',reason=''))
    store=OutputStore(report);execution=StageRecorder(report)
    started=time.perf_counter();stages={}
    try:
        with threadpool_limits(limits=config.n_threads),warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always')
            execution.start('ica_apply')
            clean=apply_ica(model,analysis,report['ica'],config,exclude=exclude)
            from .epochs import EpochConfig
            ec=EpochConfig(**payload['epoch_config']) if payload['epoch_config'] else None
            context=ProcessingContext(config=config,report=report,execution=execution,store=store,
                paths=paths,directory=directory,subject=subject,
                events=np.asarray(payload['events'],dtype=int) if payload['events'] is not None else None,
                event_id=payload['event_id'],epoch_config=ec,collect_stages=collect_stages,stages=stages)
            current=finish_processing(current,original,clean,model,context=context)
            report['warnings']=sorted(set(report.get('warnings',[])+[str(w.message) for w in caught]))
    except Exception as exc:
        execution.finish('failed',str(exc));report.update(status='failed',error=dict(type=type(exc).__name__,message=str(exc)));raise
    finally:
        report['elapsed_seconds']=time.perf_counter()-started
        report['provenance']['processing_finished_utc']=utc_now()
        report['outputs']={k:str(v) for k,v in paths.items()}
        completed=report['status'] in ('completed','review_required')
        safe_report(report,paths['quality_report'],original=original if completed else None,
            clean=current if completed else None,ica=model)
    return current,report,stages
