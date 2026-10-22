"""Build or accept a wheel, install it locally, and validate outside the checkout.

No dependencies are installed or upgraded. The interpreter running this script
must already provide the project's scientific dependencies. Each validation uses
a fresh target directory and an isolated child interpreter at an unrelated cwd.
"""
from pathlib import Path
import argparse
import json
import math
import os
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[1]

SMOKE=r'''
from pathlib import Path
from datetime import datetime,timezone
from dataclasses import asdict
import importlib.resources
import json,sys
target=Path(sys.argv[1]).resolve();destination=Path(sys.argv[2]).resolve();checkout=Path(sys.argv[3]).resolve()
assert str(checkout) not in sys.path,sys.path
sys.path.insert(0,str(target))
before=list(sys.path)
import eegproc
assert before==sys.path
assert Path(eegproc.__file__).resolve().is_relative_to(target)
from eegproc import run,PipelineConfig
from eegproc.io.bridge import _template_geometry
from eegproc.mne_asr import ASRConfig
import eegproc.mne_asr.api as canonical_asr
import mne_asr.api as old_asr
import neuracle_io,mne_bridge,erp_outputs
from eegproc.io import neuracle,bridge
from eegproc import epoch_export
assert old_asr is canonical_asr
assert neuracle_io is neuracle and mne_bridge is bridge and erp_outputs is epoch_export
matrix,fiducials=_template_geometry()
assert matrix.shape==(4,4) and len(fiducials)==3
for name in ('LICENSE','PROVENANCE.json'):
    assert importlib.resources.files('eegproc.mne_asr').joinpath(name).is_file()
assert PipelineConfig(purpose='erp').highpass==.1
defaults_before=asdict(PipelineConfig())
assert defaults_before['asr_cutoff']==20. and defaults_before['ica_enabled'] is True
assert defaults_before['highpass']==.5 and defaults_before['lowpass']==80.
import mne,numpy as np
from mne.utils import object_diff
names=['Fp1','Fp2','F3','F4','C3','C4','P3','P4','O1','O2','Fz','Cz','ECG','STI']
data=np.random.default_rng(52).normal(size=(len(names),12*256))*1e-6
data[-1]=0;data[-1,512]=1
raw=mne.io.RawArray(data,mne.create_info(names,256,['eeg']*12+['ecg','stim']),first_samp=2048,verbose=False)
raw.set_montage('standard_1020',verbose=False)
raw.set_meas_date(datetime(2020,1,2,tzinfo=timezone.utc))
raw.info['subject_info']=dict(id=7,his_id='installed-wheel')
raw.info['description']='Isolated installed-package validation'
raw.set_annotations(mne.Annotations([5.],[.25],['BAD_manual'],ch_names=[('F3',)],extras=[{'source':'manual'}]))
original=raw.copy()
# Explicit overrides make this a short installation/I/O check. Numerical ASR
# and ICA equivalence are covered by the separate full regression validation.
result=run(raw,destination,'installed',task_name='installation-check',ica_enabled=False,
    asr_cutoff=None,channel_method='off',line_method='off',filter_method='off',
    reference='unchanged',final_reference=False,interpolate_bads=False,residual_qc=False,
    detect_ransac=False,report_waveform_windows=1,report_psd_windows=1)
assert result.status in ('completed','review_required'),result.report.get('error')
assert result.report['report_status']=='completed',result.report.get('report_error')
np.testing.assert_array_equal(raw.get_data(),original.get_data())
np.testing.assert_array_equal(result.raw.get_data(),original.get_data())
assert object_diff(result.raw.info,original.info)==''
assert result.raw.annotations==original.annotations
saved=mne.io.read_raw_fif(result.outputs['raw'],preload=True,verbose=False)
np.testing.assert_array_equal(saved.get_data(),original.get_data())
assert saved.first_samp==original.first_samp and saved.n_times==original.n_times
assert saved.info['meas_date']==original.info['meas_date']
assert saved.info['subject_info']==original.info['subject_info']
assert saved.annotations.extras==original.annotations.extras
assert list(saved.annotations.ch_names)==list(original.annotations.ch_names)
assert Path(result.outputs['quality_report']).is_file()
assert not list(destination.rglob('*-ica.fif')) and not list(destination.rglob('checkpoint.json'))
assert asdict(PipelineConfig())==defaults_before
checks=dict(imported_from=str(Path(eegproc.__file__).resolve()),cwd=str(Path.cwd()),
    version=eegproc.__version__,checkout_absent_from_sys_path=True,canonical_aliases=True,
    packaged_template=True,packaged_asr_notices=True,input_unchanged=True,roundtrip_exact=True,
    metadata_preserved=True,html_created=True,ica_disabled=True,asr_disabled=True,
    production_defaults_unchanged=True,outputs=result.outputs)
(destination.parent/'install_validation.json').write_text(json.dumps(checks,indent=2),encoding='utf8')
print('INSTALLED PACKAGE VALIDATED',json.dumps(checks))
'''


RESUME=r'''
from pathlib import Path
from copy import deepcopy
import hashlib,json,sys
target=Path(sys.argv[1]).resolve();destination=Path(sys.argv[2]).resolve();checkout=Path(sys.argv[3]).resolve()
checkpoint=Path(sys.argv[4]).resolve();expected_path=Path(sys.argv[5]).resolve()
original_path=Path(sys.argv[6]).resolve() if sys.argv[6] else None
requested_exclude=json.loads(sys.argv[7]);atol=float(sys.argv[8])
assert str(checkout) not in sys.path,sys.path
sys.path.insert(0,str(target));before=list(sys.path)
import eegproc
assert sys.path==before
assert Path(eegproc.__file__).resolve().is_relative_to(target)
from eegproc import resume,render_report
from eegproc.compatibility import checkpoint_path
from eegproc.reporting import _read_html
import eegproc.ica as component_module
import mne,numpy as np
from mne.utils import object_diff
import mne_icalabel.iclabel as labels

payload=json.loads(checkpoint.read_text(encoding='utf-8-sig'))
exclude=sorted(requested_exclude if requested_exclude is not None else payload['report']['ica']['automatic_proposal_0based'])
def digest(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
sources=[checkpoint,*[checkpoint_path(checkpoint.parent.parent,item['path']) for item in payload['files']]]
expected=mne.io.read_raw_fif(expected_path,preload=False,verbose=False)
sources.extend(Path(path).resolve() for path in expected.filenames if path)
reference=original_path or payload['original_input'].get('fif_path')
if reference:
    original=mne.io.read_raw_fif(reference,preload=False,verbose=False)
    sources.extend(Path(path).resolve() for path in original.filenames if path)
    original.close()
before_hashes={str(path):digest(path) for path in dict.fromkeys(sources)}

def forbidden(*args,**kwargs):raise AssertionError('Installed checkpoint resume must not fit ICA or rerun classification')
mne.preprocessing.ICA.fit=forbidden
component_module.fit_ica=forbidden
labels.iclabel_label_components=forbidden
result=resume(checkpoint,destination,exclude=exclude,original_fif=original_path,
    reviewer='Installed-wheel validation',reason='Same decomposition and exclusion list')
assert result.status in ('completed','review_required'),result.report.get('error')
assert result.report['report_status']=='completed',result.report.get('report_error')
assert result.report['parent_run']['fit_repeated'] is False
assert result.report['ica']['removed_components_0based']==exclude
saved=mne.io.read_raw_fif(result.outputs['raw'],preload=False,verbose=False)
assert saved.n_times==expected.n_times and saved.first_samp==expected.first_samp
assert saved.ch_names==expected.ch_names and saved.get_channel_types()==expected.get_channel_types()
maximum=0.
for start in range(0,saved.n_times,65536):
    stop=min(start+65536,saved.n_times)
    actual=saved.get_data(start=start,stop=stop);reference_data=expected.get_data(start=start,stop=stop)
    np.testing.assert_allclose(actual,reference_data,rtol=0,atol=atol,equal_nan=True)
    finite=np.isfinite(actual)&np.isfinite(reference_data)
    if finite.any():maximum=max(maximum,float(np.max(np.abs(actual[finite]-reference_data[finite]))))
full_info_diff=object_diff(saved.info,expected.info)
excluded_storage_fields=[]
if full_info_diff:
    # FIF file IDs identify physical files, not the EEG measurement. Exclude
    # only this one field if it is the sole cause of the otherwise exact diff.
    left=deepcopy(saved.info);right=deepcopy(expected.info)
    left.pop('file_id',None);right.pop('file_id',None)
    remaining=object_diff(left,right)
    assert remaining=='',remaining
    excluded_storage_fields=['file_id']
assert saved.annotations==expected.annotations
assert saved.annotations.orig_time==expected.annotations.orig_time
assert saved.annotations.extras==expected.annotations.extras
assert list(saved.annotations.ch_names)==list(expected.annotations.ch_names)
assert saved.info['bads']==expected.info['bads']
assert saved.info['subject_info']==expected.info['subject_info']
assert saved.info['meas_date']==expected.info['meas_date']
saved.close();expected.close()

source_html=Path(result.outputs['quality_report']);source_record=_read_html(source_html)
source_html_hash=digest(source_html)
def no_data_read(*args,**kwargs):raise AssertionError('Report-only rebuild must not read Raw or ICA files')
mne.io.read_raw_fif=no_data_read;mne.preprocessing.read_ica=no_data_read
rebuilt=render_report(source_html,destination/'installed_rebuilt_report.html')
rendered=_read_html(rebuilt)
for key in ('config','ica','ica_checkpoint','qc_annotations','metadata_audit','provenance','epochs'):
    assert rendered.get(key)==source_record.get(key),key
assert rendered['ica_diagnostics']==source_record['ica_diagnostics']
assert [f['sha256'] for f in rendered['visualizations']['figures']]==[f['sha256'] for f in source_record['visualizations']['figures']]
assert digest(source_html)==source_html_hash
assert all(digest(path)==old_hash for path,old_hash in before_hashes.items())
checks=dict(imported_from=str(Path(eegproc.__file__).resolve()),cwd=str(Path.cwd()),
    checkpoint=str(checkpoint),expected_raw=str(expected_path),original_fif=str(original_path) if original_path else None,
    exclude=exclude,absolute_tolerance_v=atol,max_absolute_difference_v=maximum,
    full_info_equal=not bool(full_info_diff),metadata_equal_except_storage_id=True,
    excluded_storage_identity_fields=excluded_storage_fields,annotations_preserved=True,
    ica_fit_repeated=False,classification_repeated=False,source_artifacts_unchanged=True,
    report_rebuilt_without_data_reads=True,report_figures_identical=True,rebuilt_report=str(rebuilt),
    compatibility=result.report['parent_run']['compatibility'],outputs=result.outputs)
(destination.parent/'resume_validation.json').write_text(json.dumps(checks,indent=2),encoding='utf8')
print('INSTALLED RESUME VALIDATED',json.dumps(checks))
'''


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel',type=Path,help='Existing wheel; if omitted, build the checkout with --no-deps --no-build-isolation')
    parser.add_argument('--output',type=Path,help='New or empty validation directory; defaults to a temporary directory')
    parser.add_argument('--checkpoint',type=Path,help='Optional existing ICA checkpoint to resume from the installed wheel')
    parser.add_argument('--original-fif',type=Path,help='Original prepared FIF for the optional checkpoint resume')
    parser.add_argument('--expected-raw',type=Path,help='Same-source final FIF expected from that checkpoint/exclusion list')
    parser.add_argument('--exclude',type=int,nargs='*',default=None,
        help='Optional complete exclusion list; otherwise reuse the checkpoint automatic proposal')
    parser.add_argument('--atol',type=float,default=1e-12,help='Absolute signal tolerance in volts for optional resume comparison')
    parser.add_argument('--timeout',type=int,default=180,help='Maximum seconds for each child process')
    args=parser.parse_args(argv)
    if args.checkpoint is None and (args.original_fif is not None or args.expected_raw is not None or args.exclude is not None):
        parser.error('--original-fif, --expected-raw and --exclude require --checkpoint')
    if args.checkpoint is not None and args.expected_raw is None:
        parser.error('--checkpoint requires --expected-raw for a meaningful numerical comparison')
    if not math.isfinite(args.atol) or args.atol<0 or args.timeout<1:
        parser.error('--atol must be finite and nonnegative; --timeout must be positive')
    for name in ('checkpoint','original_fif','expected_raw'):
        value=getattr(args,name)
        if value is not None:
            value=value.expanduser().resolve()
            if not value.is_file():parser.error(name+' not found: '+str(value))
            setattr(args,name,value)
    root=args.output.expanduser().resolve() if args.output else Path(tempfile.mkdtemp(prefix='eeg-install-validation-'))
    if root.exists() and any(root.iterdir()):parser.error('Output directory must be new or empty: '+str(root))
    root.mkdir(parents=True,exist_ok=True)
    print('OUTPUT',root,flush=True)
    env=os.environ.copy();env['PYTHONUTF8']='1';env['PYTHONDONTWRITEBYTECODE']='1'
    def execute(command,name,cwd):
        completed=subprocess.run(command,cwd=cwd,env=env,capture_output=True,text=True,
            encoding='utf8',errors='replace',timeout=args.timeout,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        (root/f'{name}.log').write_text(completed.stdout+'\n'+completed.stderr,encoding='utf8')
        if completed.returncode:
            raise RuntimeError(f'{name} failed; see {root/name}.log\n'+completed.stdout[-2500:]+completed.stderr[-2500:])
        return completed.stdout
    if args.wheel:
        wheel=args.wheel.expanduser().resolve()
        if not wheel.is_file():parser.error('Wheel not found: '+str(wheel))
    else:
        wheel_dir=root/'wheels';wheel_dir.mkdir()
        execute([sys.executable,'-B','-m','pip','wheel',str(ROOT),'--no-deps','--no-build-isolation',
            '--disable-pip-version-check','--wheel-dir',str(wheel_dir)],'build',ROOT)
        wheels=list(wheel_dir.glob('eegproc-*.whl'))
        if len(wheels)!=1:raise RuntimeError('Expected exactly one project wheel')
        wheel=wheels[0]
    target=root/'installed'
    execute([sys.executable,'-B','-m','pip','install',str(wheel),'--no-deps','--no-compile',
        '--disable-pip-version-check','--target',str(target)],'install',root)
    foreign=root/'unrelated_cwd';foreign.mkdir()
    execute([sys.executable,'-I','-B','-c',SMOKE,str(target),str(root/'roundtrip'),str(ROOT)],'roundtrip',foreign)
    for name,entrypoint in [('preprocess','eegproc.cli'),('prepare','prepare_data')]:
        command="import sys;sys.path.insert(0,sys.argv[1]);from "+entrypoint+" import main;sys.argv=[sys.argv[0],'--help'];main()"
        help_text=execute([sys.executable,'-I','-B','-c',command,str(target)],name+'_help',foreign)
        if 'usage:' not in help_text.lower():raise RuntimeError(name+' CLI did not print usage')
    record=json.loads((root/'install_validation.json').read_text(encoding='utf8'))
    record.update(wheel=str(wheel),preprocess_help=True,prepare_help=True,dependencies_installed=False)
    if args.checkpoint:
        execute([sys.executable,'-I','-B','-c',RESUME,str(target),str(root/'resumed'),str(ROOT),
            str(args.checkpoint),str(args.expected_raw),str(args.original_fif) if args.original_fif else '',
            json.dumps(args.exclude),str(args.atol)],'resume',foreign)
        record['checkpoint_resume']=json.loads((root/'resume_validation.json').read_text(encoding='utf8'))
    (root/'install_validation.json').write_text(json.dumps(record,indent=2),encoding='utf8')
    print('VALIDATED',root/'install_validation.json',flush=True)


if __name__=='__main__':main()
