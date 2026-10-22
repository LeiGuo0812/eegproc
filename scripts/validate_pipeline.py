"""Exercise the unified workflow and compact report on a deterministic fixture."""
from pathlib import Path
import argparse
import json
import sys
import tempfile
import numpy as np
import mne

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from eegproc import run,resume,resolve_config


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,help='New or empty output directory; defaults to a new temporary directory')
    args=parser.parse_args(argv)
    root=args.output.expanduser().resolve() if args.output else Path(tempfile.mkdtemp(prefix='eegproc-validation-'))
    if root.exists() and any(root.iterdir()):
        parser.error('Output directory must be new or empty: '+str(root))
    root.mkdir(parents=True,exist_ok=True)
    print('OUTPUT',root,flush=True)
    fixtures=ROOT/'tests/fixtures/staged_v3'
    source=fixtures/'input_raw.fif'
    raw=mne.io.read_raw_fif(source,preload=True,verbose=False)
    before=raw.get_data().copy();summary={'fixture':'40 s synthetic; 12 EEG + EOG + STIM; 256 Hz; input BAD and two events',
        'output_root':str(root),'example_overrides':{'detect_ransac':False,'epoch_mode':'events'},'runs':{}}
    def record(name,result):
        report=result.report
        files=[p for p in (root/name).rglob('*') if p.is_file()]
        summary['runs'][name]=dict(status=result.status,stage_files=len(report['stage_files']),file_count=len(files),
            output_bytes=sum(p.stat().st_size for p in files),html_bytes=Path(result.outputs['quality_report']).stat().st_size,
            excluded=report.get('ica',{}).get('removed_components_0based'),epochs=report.get('epochs',{}).get('retained_epochs'),
            asr_cutoff=report['config']['asr_cutoff'],ica_rule=report['config']['ica_rule'],
            waveform_window_seconds=report['config']['report_window_seconds'],
            line_diagnostics=report.get('line_diagnostics',{}),
            metadata_checks=report.get('metadata_audit',{}).get('checks'),plot_errors=report['visualizations']['errors'],
            stage_order=[r['stage'] for r in report['execution']],report=str(Path(result.outputs['quality_report']).relative_to(root)))
        assert not report['visualizations']['errors']
        assert all(v is not False for v in summary['runs'][name]['metadata_checks'].values())
        assert all(abs(w['stop_seconds']-w['start_seconds']-4.)<1e-8 for w in report['visualizations']['waveform_windows'])
        assert report['line_diagnostics']['status']=='available'
        assert any(f['key']=='line_noise' for f in report['visualizations']['figures'])
        assert not list((root/name).rglob('original_raw.fif'))
        assert not list((root/name).rglob('preview_raw.fif'))
        assert not list((root/name).rglob('container_raw.fif'))
        summary['runs'][name]['task_name']=report['config']['task_name']
        print(name,summary['runs'][name]['file_count'],result.status,flush=True)
    for purpose in ['rest','erp']:
        name=purpose
        result=run(raw,root/name,name,purpose=purpose,
            task_name='rest' if purpose=='rest' else 'synthetic-events',detect_ransac=False,epoch_mode='events')
        if purpose=='rest':automatic_rest=result
        record(name,result)
        assert result.report['config']['asr_cutoff']==20
        expected=mne.io.read_raw_fif(fixtures/f'p16_{purpose}_cont_raw.fif',preload=True,verbose=False)
        difference=float(np.max(np.abs(result.raw.get_data()-expected.get_data())))
        summary['runs'][name]['max_difference_from_historical_volts']=difference
        if purpose=='rest':assert difference<1e-12
    # Reopen a completed automatic result and restore previously excluded components.
    result=resume(automatic_rest.outputs['checkpoint'],root/'reselected','reselected',
        exclude=[],reviewer='Validation',reason='Restore all components from the untouched pre-ICA checkpoint')
    record('reselected',result)
    assert result.report['ica']['removed_components_0based']==[]
    assert not result.report['parent_run']['fit_repeated']
    assert result.outputs['checkpoint']==automatic_rest.outputs['checkpoint']
    assert result.report['line_diagnostics']==automatic_rest.report['line_diagnostics']
    summary['automatic_reselection_no_refit']=True
    # Historical ERP disabled ASR. Keep that comparison separate from the new default.
    result=run(raw,root/'erp_no_asr','erp_no_asr',config=resolve_config(
        purpose='erp',asr_cutoff=None,detect_ransac=False,epoch_mode='events'))
    record('erp_no_asr',result)
    expected=mne.io.read_raw_fif(fixtures/'p16_erp_cont_raw.fif',preload=True,verbose=False)
    difference=float(np.max(np.abs(result.raw.get_data()-expected.get_data())))
    summary['runs']['erp_no_asr']['max_difference_from_historical_volts']=difference
    assert difference<1e-12
    result=run(raw,root/'class_max','class_max',config=resolve_config(
        ica_rule='class_max',detect_ransac=False,epoch_mode='events'))
    record('class_max',result)
    review=run(raw,root/'review','review',config=resolve_config(ica_mode='review',epoch_mode='events',detect_ransac=False))
    record('review',review)
    # Confirm the same automatic proposal to isolate save/resume effects.
    selection=dict(review.report['ica_checkpoint']['selection_template'])
    selection.update(reviewed=True,reviewer='Validation',reason='Confirm automatic proposal for resume regression')
    path=root/'selection_confirmed.json';path.write_text(json.dumps(selection,indent=2),encoding='utf8')
    result=resume(review.outputs['checkpoint'],root/'resumed','resumed',selection_json=path)
    record('resumed',result)
    expected=mne.io.read_raw_fif(root/'rest/rest_cont_raw.fif',preload=True,verbose=False)
    summary['resume_max_difference_volts']=float(np.max(np.abs(result.raw.get_data()-expected.get_data())))
    assert summary['resume_max_difference_volts']<1e-12
    result=run(raw,root/'eeglab','eeglab',config=resolve_config(preset='eeglab',epoch_mode='events'))
    record('eeglab',result)
    assert summary['runs']['rest']['stage_order']==summary['runs']['eeglab']['stage_order']
    summary['identical_stage_order']=True
    assert np.array_equal(raw.get_data(),before)
    summary['input_unchanged']=True
    (root/'validation_summary.json').write_text(json.dumps(summary,indent=2),encoding='utf8')
    print('VALIDATED',root/'validation_summary.json',flush=True)


if __name__=='__main__':main()
