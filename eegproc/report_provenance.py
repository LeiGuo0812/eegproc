"""EEG report provenance and portable QC tables, inspired by NiPreps reports.

These are project-specific derivatives, not a BIDS validation claim and not
fMRI confound regressors. Reporting never changes EEG or exclusion decisions.
"""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import csv
import hashlib
import importlib.metadata
import json
import platform
import sys
import time
import uuid
import numpy as np

SCHEMA_VERSION='1.1'


def utc_now():return datetime.now(timezone.utc).isoformat(timespec='seconds')


def file_hash(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


class StageRecorder:
    def __init__(self,report):
        self.rows=report.setdefault('execution',[]);self.current=None;self.started=None

    def finish(self,status='completed',message=None):
        if self.current is not None:
            self.current.update(status=status,ended_utc=utc_now(),elapsed_seconds=time.perf_counter()-self.started)
            if message:self.current['message']=message
            self.current=None

    def start(self,name):
        self.finish();self.current=dict(stage=name,status='running',started_utc=utc_now())
        self.rows.append(self.current);self.started=time.perf_counter()

    def skip(self,name,reason):
        self.finish();self.rows.append(dict(stage=name,status='skipped',reason=reason,elapsed_seconds=0.))


def capture_provenance(raw,subject,invocation=None,montage=None):
    root=Path(__file__).resolve().parents[1]
    files=list((root/'eegproc').rglob('*.py'))+list((root/'python/common/mne_asr').glob('*.py'))
    files += [p for p in (root/'eegproc').rglob('*')
              if p.is_file() and (p.name in ('LICENSE','PROVENANCE.json') or p.suffix=='.elc')]
    files += [root/p for p in ['project_layout.py','erp_outputs.py','preprocess.py','prepare_data.py','python/common/mne_bridge.py','python/common/neuracle_io.py','python/common/mne_asr/PROVENANCE.json','python/common/mne_asr/LICENSE','requirements.txt'] if (root/p).exists()]
    code={p.relative_to(root).as_posix():file_hash(p) for p in sorted(set(files))}
    bundle=hashlib.sha256(json.dumps(code,sort_keys=True).encode()).hexdigest()
    sources=[]
    paths=list(dict.fromkeys(str(Path(p).resolve()) for p in [*(invocation or {}).get('input_paths',[]),*[p for p in raw.filenames if p]]))
    for name in paths:
        p=Path(name).resolve()
        sources.append(dict(name=p.name,path=str(p),bytes=p.stat().st_size,sha256=file_hash(p)) if p.is_file() else dict(name=p.name,path=str(p),unavailable=True))
    versions={}
    for name in ['mne','numpy','scipy','matplotlib','mne-icalabel','pyprep','python-picard','autoreject','scikit-learn','threadpoolctl','asrpy','eegprep','project-mne-asr','torch','onnxruntime','pyedflib','joblib']:
        try:versions[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:versions[name]='not installed'
    invocation=dict(invocation or {'entrypoint':'eegproc.run','argv':None})
    invocation['entrypoint']={'Python API':'eegproc.run','preprocess.py':'eegproc.cli',
        'resume_ica':'eegproc.resume'}.get(invocation.get('entrypoint'),invocation.get('entrypoint'))
    invocation.setdefault('argv',None)
    if invocation.get('config_path') and Path(invocation['config_path']).is_file():
        invocation['config_file_sha256']=file_hash(invocation['config_path'])
    from .compatibility import computation_manifest
    return dict(report_schema_version=SCHEMA_VERSION,computation=computation_manifest(),
        run_uuid=str(uuid.uuid4()),subject_label=subject,
        started_utc=utc_now(),software=dict(name='EEG preprocessing',version='local-source-'+bundle[:12],
        source_bundle_sha256=bundle,source_files_sha256=code,packages=versions),
        runtime=dict(python=sys.version.split()[0],platform=platform.platform(),executable=sys.executable),
        invocation=invocation,sources=sources,
        source_note='Input file bytes hashed before preprocessing; input_sha256 separately hashes the imported numeric array. In-memory-only inputs have no file checksum.',
        montage_override=montage,compliance=dict(preset='fMRIPrep-inspired EEG QA',bids_validated=False,
            note='Custom MNE delivery. No claim of BIDS conformance or fMRIPrep execution.'))


def _ann_key(a):
    return (round(float(a['onset']),8),round(float(a['duration']),8),str(a['description']),
            tuple(a.get('ch_names',())),json.dumps(dict(a.get('extras',{})),sort_keys=True))


def _auxiliary_equal(original,clean,picks,block_samples=65536):
    """Avoid two full auxiliary-channel arrays during the final metadata audit."""
    if not picks:return None
    if original.n_times!=clean.n_times:return False
    for start in range(0,original.n_times,block_samples):
        stop=min(start+block_samples,original.n_times)
        if not np.array_equal(original.get_data(picks=picks,start=start,stop=stop),
                              clean.get_data(picks=picks,start=start,stop=stop),equal_nan=True):
            return False
    return True


def capture_signal_audit(report,original,clean):
    from .quality_figures import bad_spans
    from .checkpoint_input import metadata_identity,metadata_equal
    types=original.get_channel_types();aux=[i for i,t in enumerate(types) if t!='eeg']
    before=Counter(_ann_key(a) for a in original.annotations);after=Counter(_ann_key(a) for a in clean.annotations)
    checks=dict(channel_names=original.ch_names==clean.ch_names,channel_types=types==clean.get_channel_types(),
        sample_grid=original.n_times==clean.n_times and original.info['sfreq']==clean.info['sfreq'] and original.first_samp==clean.first_samp,
        measurement_date=original.info['meas_date']==clean.info['meas_date'],
        annotations=all(after[k]>=v for k,v in before.items()),
        auxiliary_data=_auxiliary_equal(original,clean,aux),
        channel_units=all(a['unit']==b['unit'] and a['unit_mul']==b['unit_mul'] for a,b in zip(original.info['chs'],clean.info['chs'])))
    coord_equal=bool(np.array_equal(np.array([c['loc'] for c in original.info['chs']]),np.array([c['loc'] for c in clean.info['chs']]),equal_nan=True))
    checks['electrode_locations']=coord_equal
    before_metadata=metadata_identity(original);after_metadata=metadata_identity(clean)
    checks['annotation_orig_time']=before_metadata['annotation_orig_time']==after_metadata['annotation_orig_time']
    for key in ('coordinate_frames','digitization','transforms','projections'):
        checks[key]=metadata_equal(before_metadata[key],after_metadata[key],tolerant=False)
    report['metadata_audit']=dict(checks=checks,coordinate_change_expected=bool(report.get('provenance',{}).get('montage_override')),
        input_channel_types=dict(Counter(types)),input_bad_channels=list(original.info['bads']),
        reference_before=str(original.info['custom_ref_applied']),reference_after=str(clean.info['custom_ref_applied']),
        first_samp=clean.first_samp,annotation_orig_time=str(clean.annotations.orig_time),
        input_highpass_hz=original.info['highpass'],input_lowpass_hz=original.info['lowpass'],
        output_highpass_hz=clean.info['highpass'],output_lowpass_hz=clean.info['lowpass'],
        coordinate_frames=sorted(set(int(c['coord_frame']) for c in clean.info['chs'])),
        coordinates_units='m',auxiliary_channels=[original.ch_names[i] for i in aux])
    # Report contiguous usable lengths, not just a sum of disconnected fragments.
    mask=np.zeros(clean.n_times,bool)
    for lo,hi,_ in bad_spans(clean):mask[lo:hi]=True
    bounds=np.flatnonzero(np.diff(np.r_[False,~mask,False].astype(int)))
    lengths=(bounds[1::2]-bounds[::2])/clean.info['sfreq']
    report['continuous_segments']=dict(nonbad_segment_count=len(lengths),longest_seconds=float(max(lengths,default=0)),
        median_seconds=float(np.median(lengths)) if len(lengths) else 0.,nonbad_total_seconds=float(lengths.sum()),
        definition='Union of output BAD, EDGE and boundary intervals; zero-duration boundaries occupy one sample for diagnostic accounting.')
    annotations=[];remaining=before.copy()
    for a in clean.annotations:
        key=_ann_key(a);origin='input' if remaining[key] else 'new_processing'
        if remaining[key]:remaining[key]-=1
        annotations.append(dict(onset_seconds=float(a['onset']-clean.first_time),duration_seconds=float(a['duration']),
            description=str(a['description']),origin=origin))
    channels=[];criteria=report.get('channel_detection',{}).get('criteria',{})
    for i,(name,typ) in enumerate(zip(clean.ch_names,types)):
        loc=clean.info['chs'][i]['loc'][:3];has_pos=bool(np.isfinite(loc).all() and np.linalg.norm(loc)>0)
        channels.append(dict(name=name,type=typ,input_bad=name in original.info['bads'],
            interpolated=name in report.get('quality',{}).get('interpolated_channels',[]),output_bad=name in clean.info['bads'],
            detection_reasons=[k for k,v in criteria.items() if isinstance(v,(list,tuple)) and name in v],
            x_m=float(loc[0]) if has_pos else None,y_m=float(loc[1]) if has_pos else None,z_m=float(loc[2]) if has_pos else None,
            coord_frame=int(clean.info['chs'][i]['coord_frame'])))
    report['qc_channels']=channels;report['qc_annotations']=annotations


def write_table(path,rows,columns,descriptions):
    """UTF-8 TSV plus column dictionary. Missing data is n/a, never zero."""
    def value(v):
        if v is None:return 'n/a'
        if isinstance(v,(bool,np.bool_)):return int(v)
        if isinstance(v,(float,np.floating)) and not np.isfinite(v):return 'n/a'
        if isinstance(v,(list,tuple,dict)):return json.dumps(v,ensure_ascii=False)
        return v
    with path.open('w',encoding='utf8',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=columns,delimiter='\t',lineterminator='\n')
        writer.writeheader();writer.writerows({c:value(row.get(c)) for c in columns} for row in rows)
    path.with_suffix('.json').write_text(json.dumps({c:descriptions[c] for c in columns},ensure_ascii=False,indent=2),encoding='utf8')


def references(report):
    c=report.get('config',{});refs=[
        ('Gramfort A, et al. (2013). MEG and EEG data analysis with MNE-Python. Frontiers in Neuroscience, 7, 267.', 'https://doi.org/10.3389/fnins.2013.00267')]
    if c.get('channel_method','pyprep')=='pyprep':refs.append(('Bigdely-Shamlo N, et al. (2015). The PREP pipeline: standardized preprocessing for large-scale EEG analysis. Frontiers in Neuroinformatics, 9, 16.','https://doi.org/10.3389/fninf.2015.00016'))
    if c.get('channel_method')=='eegprep' or c.get('filter_method')=='eeglab_fir':refs.append(('EEGPrep. Python implementations of EEGLAB preprocessing methods.','https://eegprep.org/'))
    if report.get('ica'):
        refs.extend([('Pion-Tonachini L, Kreutz-Delgado K, Makeig S. (2019). ICLabel: An automated electroencephalographic independent component classifier, dataset, and website. NeuroImage, 198, 181–197.','https://doi.org/10.1016/j.neuroimage.2019.05.026'),
            ('Li A, et al. (2022). MNE-ICALabel: Automatically annotating ICA components with MNE-Python. Journal of Open Source Software, 7(76), 4484.','https://doi.org/10.21105/joss.04484')])
        if c.get('ica_method')=='picard':refs.append(('Ablin P, Cardoso JF, Gramfort A. (2018). Faster independent component analysis by preconditioning with Hessian approximations. IEEE Transactions on Signal Processing.','https://arxiv.org/abs/1706.08171'))
    if c.get('asr_cutoff') is not None and report.get('asr'):refs.append(('Mullen TR, et al. (2015). Real-time neuroimaging and cognitive monitoring using wearable dry EEG. IEEE Transactions on Biomedical Engineering.','https://pubmed.ncbi.nlm.nih.gov/26415149/'))
    if report.get('epochs',{}).get('enabled'):refs.append(('Jas M, et al. (2017). Autoreject: Automated artifact rejection for MEG and EEG data. NeuroImage, 159, 417–429.','https://autoreject.github.io/stable/index.html'))
    return refs


def methods_text(report):
    c=report.get('config',{});ic=report.get('ica',{});ep=report.get('epochs',{})
    text=['# Methods',f"EEG preprocessing used eegproc ({report.get('workflow_revision','local')}) with the {c.get('preset','standard')} parameter preset. Random seed: {c.get('seed','not recorded')}; threads: {c.get('n_threads','not recorded')}."]
    if report.get('status') not in ('completed','review_required'):text.append('Processing is incomplete; the following describes the available stages.')
    if report.get('line_cleaning'):
        line=report['line_cleaning'];text.append(f"Line noise was processed with {line.get('backend')} at {line.get('frequencies_hz',[])} Hz. Window: {line.get('window_seconds')} s; bandwidth: {line.get('bandwidth_hz')} Hz.")
    if report.get('channel_detection'):text.append(f"Bad channels were detected with {report['channel_detection'].get('backend')} and combined with input bad channels. Detected channels: {', '.join(report.get('bad_channels',[])) or 'none'}.")
    text.append(f"The analysis band was {c.get('highpass')}–{c.get('lowpass')} Hz; the ICA training band was {c.get('training_highpass')}–{c.get('training_lowpass')} Hz. Filter: {c.get('filter_method','mne_fir')}; reference: {c.get('reference','average')}.")
    if c.get('filter_method')=='eeglab_fir':text.append(f"Successive high-pass and low-pass FIR filters used order {c.get('filter_order')}, DC padding and FFT convolution.")
    if report.get('asr'):text.append('ASR was disabled.' if c.get('asr_cutoff') is None else f"ASR used the independent MNE-native implementation with cutoff {c.get('asr_cutoff')}. Processing segments respected input BAD annotations and recording boundaries.")
    if ic:
        text.append(f"ICA used {c.get('ica_method')}, rank {ic.get('rank')}, {ic.get('fit_samples')} training samples, tolerance {c.get('ica_tolerance')} and a maximum of {c.get('ica_max_iter')} iterations. Gross-segment exclusion from training: {c.get('exclude_gross_from_training',True)}.")
        if c.get('ica_rule')=='class_max':text.append('Automatic component selection used the original script rule: Eye probability equal to the class maximum, or Muscle/Line noise/Channel noise probability equal to the class maximum with Brain probability ≤0.5. Ties were included. Heart and Other were not automatic deletion classes; ECG support was not used.')
        else:
            text.append(f"Automatic selection required artifact probability ≥{c.get('artifact_threshold')} and Brain probability ≤{c.get('brain_probability_max')}.")
            sel=ic.get('component_selection',{})
            text.append(f"With available ECG, Heart candidates also required absolute ECG correlation ≥{c.get('heart_min_ecg_correlation')}." if sel.get('ecg_available') else 'Without available ECG, Heart selection used ICLabel probabilities only.')
        text.append(f"Automatic proposal: {ic.get('automatic_proposal_0based',ic.get('removed_components_0based',[]))}. Decision: {ic.get('decision_status','recorded')}. Excluded components (zero-based): {ic.get('removed_components_0based',[])}.")
    if report.get('quality'):text.append(f"Final interpolation: {c.get('final_interpolation',True)}; final reference: {c.get('final_reference',True)}. Residual annotation: {c.get('residual_qc',True)}; peak {c.get('residual_peak_uv')} µV, peak-to-peak {c.get('residual_ptp_uv')} µV, robust z {c.get('residual_robust_z')}, window {c.get('window_seconds')} s and guard {c.get('guard_seconds')} s.")
    if ep:
        ec=ep.get('config',{});text.append(f"Epoch window: {ec.get('tmin')} to {ec.get('tmax')} s; baseline: {ec.get('baseline')}. QC: {ep.get('annotation_policy',ep.get('method'))}. Retained: {ep.get('retained_epochs')} / {ep.get('input_events')} epochs; locally repaired: {ep.get('repaired_epochs',0)}.")
    return '\n\n'.join(text)+'\n'


def data_inventory(report,root):
    rows=[];outputs=report.get('outputs',{});checkpoint=report.get('ica_checkpoint',{})
    reused=checkpoint.get('reused',False);root=Path(root).resolve();seen=set()
    receipts={Path(r['path']).resolve():r for r in report.get('output_files',[])
              if r.get('status')=='committed'}
    def display_path(p):
        return p.relative_to(root).as_posix() if p.is_relative_to(root) else str(p)
    for key,stage in [('raw','save_continuous'),('ica','save_continuous'),('epochs','epochs'),('checkpoint','save_ica_checkpoint'),
                      ('pre_ica','save_ica_checkpoint'),('decomposition','save_ica_checkpoint')]:
        if key not in outputs:continue
        p=Path(outputs[key]).resolve()
        if p in seen:continue
        seen.add(p)
        done=any(s['stage']==stage and s['status']=='completed' for s in report.get('execution',[]))
        done|=key=='ica' and bool(checkpoint) and not reused
        if 'output_files' in report:done=p in receipts
        rows.append(dict(kind=key,path=display_path(p),exists=p.is_file(),produced_this_run=done,
            reused=bool(reused and key in ('checkpoint','pre_ica','decomposition')),
            bytes=p.stat().st_size if p.is_file() else None,sha256=file_hash(p) if p.is_file() else None))
    for item in checkpoint.get('files',[]):
        from .compatibility import checkpoint_path
        p=checkpoint_path(Path(checkpoint.get('root',root)),item['path'])
        if p in seen:continue
        seen.add(p)
        rows.append(dict(kind='review_state',path=display_path(p),exists=p.is_file(),produced_this_run=not reused,reused=reused,
            bytes=p.stat().st_size if p.is_file() else None,sha256=item['sha256']))
    for p,receipt in receipts.items():
        if p in seen:continue
        seen.add(p)
        rows.append(dict(kind=receipt.get('kind','data'),path=display_path(p),exists=p.is_file(),
            produced_this_run=True,reused=False,bytes=p.stat().st_size if p.is_file() else None,
            sha256=receipt['sha256']))
    for name in report.get('final_raw_files',[])[1:]:
        p=Path(name).resolve()
        if p in seen:continue
        rows.append(dict(kind='raw_split',path=display_path(p),exists=p.is_file(),produced_this_run=True,
            bytes=p.stat().st_size if p.is_file() else None,sha256=file_hash(p) if p.is_file() else None))
    return rows

