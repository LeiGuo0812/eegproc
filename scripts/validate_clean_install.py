"""Validate a real venv installation, without using checkout imports or user data.

This script installs dependencies unless --skip-install is explicitly supplied.
Use --existing-environment-check to exercise its synthetic worker without any
installation; that mode is recorded as NOT a clean-install validation.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]

WORKER = r'''
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import asdict
from importlib import metadata, import_module
import hashlib, json, socket, sys, traceback

output = Path(sys.argv[1]).resolve()
checkout = Path(sys.argv[2]).resolve()
clean = sys.argv[3] == 'clean'
record = dict(validation_kind='clean_install' if clean else 'existing_environment_worker',
              clean_install_verified=False, executable=sys.executable,
              prefix=sys.prefix, base_prefix=sys.base_prefix, sys_path=list(sys.path),
              cwd=str(Path.cwd()), synthetic_only=True,
              scientific_equivalence_to_other_versions='not claimed')
record['dependency_environment'] = ('isolated venv; user site disabled' if clean
                                    else 'existing interpreter including its user site')

def save():
    (output/'worker_validation.json').write_text(json.dumps(record, indent=2), encoding='utf8')

def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

try:
    assert not any(Path(p).resolve().is_relative_to(checkout) for p in sys.path if p), sys.path
    if clean:
        assert sys.prefix != sys.base_prefix, 'Worker is not running in a venv'
        cfg = Path(sys.prefix)/'pyvenv.cfg'
        cfg_text = cfg.read_text(encoding='utf8').lower()
        assert 'include-system-site-packages = false' in cfg_text, cfg_text
        record['pyvenv_cfg'] = cfg_text
    else:
        # This explicit development-only mode tests the worker using installed
        # scientific dependencies and the checkout. It cannot certify packaging.
        sys.path.insert(0, str(checkout))
    record['checkout_on_import_path'] = not clean
    import eegproc
    import mne
    import numpy as np
    from scipy.signal import lfilter
    from eegproc import PipelineConfig, run, resume, render_report
    from eegproc.reporting import _read_html
    imported = Path(eegproc.__file__).resolve()
    if clean:
        assert imported.is_relative_to(Path(sys.prefix).resolve()), imported
    record['imported_from'] = str(imported)
    record['imported_package_version'] = eegproc.__version__
    record['installed_versions'] = {
        dist.metadata['Name']: dist.version for dist in metadata.distributions()
        if dist.metadata.get('Name')
    }
    # Existing environments may contain both user-site and environment copies.
    # Record the modules actually selected, separately from distribution metadata.
    record['imported_scientific_modules'] = {}
    for module_name in ('mne','numpy','scipy','matplotlib','torch','pyprep','mne_icalabel','picard','sklearn'):
        module = import_module(module_name)
        record['imported_scientific_modules'][module_name] = {
            'version': getattr(module, '__version__', None),
            'path': str(Path(module.__file__).resolve()),
        }
    record['optional_imports'] = {}
    for distribution, module in [('eegprep','eegprep'), ('autoreject','autoreject'), ('pyedflib','pyedflib')]:
        try:
            version = metadata.version(distribution)
        except metadata.PackageNotFoundError:
            record['optional_imports'][distribution] = {'installed': False}
        else:
            __import__(module)
            record['optional_imports'][distribution] = {'installed': True, 'version': version,
                                                       'validation': 'import only'}

    # Block network connections for all scientific work, after dependency
    # imports. This worker uses generated arrays and bundled ICLabel weights.
    def no_network(*args, **kwargs):
        raise AssertionError('Scientific validation must not open network connections')
    socket.socket.connect = no_network
    socket.socket.connect_ex = no_network
    socket.create_connection = no_network
    record['network_connections_blocked_during_processing'] = True

    sfreq = 256.
    samples = 60*int(sfreq)
    time_axis = np.arange(samples)/sfreq
    names = ['Fp1','Fp2','F7','F3','Fz','F4','F8','FC5','FC1','FC2','FC6',
             'T7','C3','Cz','C4','T8','CP5','CP1','CP2','CP6','P7','P3','Pz',
             'P4','P8','PO7','PO3','POz','PO4','PO8','O1','O2']
    montage = mne.channels.make_standard_montage('standard_1020')
    positions = np.array([montage.get_positions()['ch_pos'][name] for name in names])
    positions /= np.linalg.norm(positions, axis=1, keepdims=True)
    x, y, z = positions.T
    spatial = np.column_stack([x, y, z, x*y, x*z, y*z, x*x-y*y, z*z])
    rng = np.random.default_rng(20261022)
    sources = lfilter([1.], [1., -.96], rng.normal(size=(spatial.shape[1], samples)))
    sources /= sources.std(axis=1, keepdims=True)
    sources[0] += np.sin(2*np.pi*10*time_axis)
    sources[1] += .5*np.sin(2*np.pi*6*time_axis)
    eeg = spatial@sources*7e-6 + rng.normal(scale=.5e-6, size=(len(names), samples))
    eeg += np.sin(2*np.pi*50*time_axis)[None, :]*1.5e-6
    eog = sum(np.exp(-.5*((time_axis-t)/.12)**2) for t in (15., 35., 49.))*120e-6
    eeg += np.maximum(y, 0)[:, None]*eog*.15
    ecg = sum(np.exp(-.5*((time_axis-t)/.015)**2) for t in np.arange(.6, 60, .85))*150e-6
    stim = np.zeros(samples)
    event_times = np.arange(5., 57., 3.)
    codes = np.resize([1, 2], len(event_times))
    for onset, code in zip(event_times, codes):
        stim[int(onset*sfreq)] = code
    all_names = names+['EOG','ECG','STI']
    info = mne.create_info(all_names, sfreq, ['eeg']*len(names)+['eog','ecg','stim'])
    raw = mne.io.RawArray(np.vstack([eeg,eog,ecg,stim]), info, first_samp=2048, verbose=False)
    raw.set_montage(montage, verbose=False)
    raw.set_meas_date(datetime(2020, 1, 2, tzinfo=timezone.utc))
    raw.info['subject_info'] = dict(id=7, his_id='synthetic-install-validation')
    raw.info['description'] = 'Generated synthetic fixture; not participant data'
    raw.set_annotations(mne.Annotations([11., *event_times], [.35, *np.zeros(len(event_times))],
        ['BAD_manual', *[str(code) for code in codes]],
        ch_names=[('F3',), *[() for _ in event_times]],
        extras=[{'source':'manual validation'}, *[{'source':'synthetic stimulus'} for _ in event_times]]))
    input_path = output/'synthetic_input_raw.fif'
    raw.save(input_path, fmt='double', overwrite=False, verbose=False)
    raw = mne.io.read_raw_fif(input_path, preload=True, verbose=False)
    input_hash = digest(input_path)
    input_data = raw.get_data()
    input_info = raw.info.copy()
    input_annotations = raw.annotations.copy()
    raw._data.setflags(write=False)
    record['fixture'] = dict(duration_seconds=60, eeg_channels=32, auxiliary_channels=['EOG','ECG','STI'],
        sfreq=sfreq, first_samp=2048, event_count=len(event_times), input_sha256=input_hash,
        provenance='Generated in isolated worker with numpy seed 20261022; no external EEG files read')
    defaults = asdict(PipelineConfig())
    assert defaults['detect_ransac'] is True and defaults['asr_cutoff'] == 20.
    assert defaults['ica_enabled'] is True
    record['runs'] = {}

    def check(name, result, *, reviewing=False):
        report = result.report
        assert result.status in (('awaiting_ica_review',) if reviewing else ('completed','review_required')), report.get('error')
        assert report['report_status'] == 'completed', report.get('report_error')
        assert not report['visualizations']['errors'], report['visualizations']['errors']
        assert report['config']['detect_ransac'] is True
        assert report['config']['asr_cutoff'] == 20. and report['config']['ica_enabled'] is True
        assert report.get('asr'), 'ASR stage did not run'
        assert report.get('ica', {}).get('rank', 0) > 0, report.get('ica')
        html = Path(result.outputs['quality_report'])
        assert html.is_file()
        assert _read_html(html)['config'] == json.loads(json.dumps(report['config']))
        np.testing.assert_array_equal(raw.get_data(), input_data)
        assert raw.annotations == input_annotations
        assert digest(input_path) == input_hash
        assert not list((output/name).rglob('original_raw.fif'))
        assert not list((output/name).rglob('preview_raw.fif'))
        if not reviewing:
            actual = result.raw
            assert actual.first_samp == raw.first_samp and actual.n_times == raw.n_times
            assert actual.ch_names == raw.ch_names and actual.get_channel_types() == raw.get_channel_types()
            assert actual.info['meas_date'] == input_info['meas_date']
            assert actual.info['subject_info'] == input_info['subject_info']
            assert actual.info['description'] == input_info['description']
            np.testing.assert_array_equal(actual.get_data(picks=['EOG','ECG','STI']), raw.get_data(picks=['EOG','ECG','STI']))
            for original in input_annotations:
                matches = [a for a in actual.annotations if a['description'] == original['description']
                           and a['onset'] == original['onset']]
                assert len(matches) == 1
                match = matches[0]
                for key in ('onset','duration','description','ch_names','extras'):
                    assert match[key] == original[key], (key, match, original)
            assert actual.annotations.orig_time == raw.annotations.orig_time
            assert all(v is not False for v in report['metadata_audit']['checks'].values())
            saved = mne.io.read_raw_fif(result.outputs['raw'], preload=True, verbose=False)
            np.testing.assert_array_equal(saved.get_data(), actual.get_data())
            assert saved.annotations == actual.annotations
        record['runs'][name] = dict(status=result.status, effective_config=report['config'],
            outputs=result.outputs, metadata=report.get('metadata_audit'),
            bad_channels=report.get('bad_channels'), ica_components=report['ica'].get('rank'),
            removed=report['ica'].get('removed_components_0based'),
            epoch_retention=report.get('epochs',{}).get('condition_retention'),
            html_bytes=html.stat().st_size)
        save()

    rest = run(raw, output/'rest', 'rest')
    check('rest', rest)
    erp = run(raw, output/'erp', 'erp', purpose='erp', task_name='synthetic-events', epoch_mode='events')
    check('erp', erp)
    assert erp.report['epochs']['input_events'] == len(event_times)
    assert erp.report['epochs']['retained_epochs'] > 0
    assert any('BAD_manual' in row['drop_reasons'] for row in erp.report['epochs']['records'])
    assert set(erp.report['epochs']['condition_retention']) == {'1','2'}
    review = run(raw, output/'review', 'review', ica_mode='review')
    check('review', review, reviewing=True)
    checkpoint = Path(review.outputs['checkpoint'])
    checkpoint_hash = digest(checkpoint)
    assert sorted(p.name for p in checkpoint.parent.iterdir()) == ['checkpoint.json','decomposition-ica.fif','pre_ica_raw.fif']

    def no_fit(*args, **kwargs):
        raise AssertionError('Resume must not fit ICA or repeat ICLabel')
    import eegproc.ica as component_module
    import mne_icalabel.iclabel as iclabel
    mne.preprocessing.ICA.fit = no_fit
    component_module.fit_ica = no_fit
    iclabel.iclabel_label_components = no_fit
    proposed = rest.report['ica']['removed_components_0based']
    resumed = resume(checkpoint, output/'resumed', 'resumed', exclude=proposed,
        original_raw=raw, reviewer='Install validation', reason='Confirm same exclusion without refitting')
    check('resumed', resumed)
    assert resumed.report['parent_run']['fit_repeated'] is False
    assert resumed.report['ica']['removed_components_0based'] == proposed
    maximum = float(np.max(np.abs(resumed.raw.get_data()-rest.raw.get_data())))
    np.testing.assert_allclose(resumed.raw.get_data(), rest.raw.get_data(), rtol=0, atol=1e-12)
    assert resumed.raw.annotations == rest.raw.annotations
    assert digest(checkpoint) == checkpoint_hash and digest(input_path) == input_hash
    source_html = Path(resumed.outputs['quality_report'])
    source_record = _read_html(source_html)
    source_digest = digest(source_html)
    def no_data_read(*args, **kwargs):
        raise AssertionError('HTML rebuild must not read signal or ICA files')
    mne.io.read_raw_fif = no_data_read
    mne.preprocessing.read_ica = no_data_read
    rebuilt = render_report(source_html, output/'rebuilt_report.html')
    rebuilt_record = _read_html(rebuilt)
    assert source_record['ica_diagnostics'] == rebuilt_record['ica_diagnostics']
    assert source_record['config'] == rebuilt_record['config']
    assert digest(source_html) == source_digest
    assert defaults == asdict(PipelineConfig())
    record.update(status='passed', input_unchanged=True, auxiliary_channels_unchanged=True,
        manual_BAD_preserved_and_used_for_epoch_rejection=True, same_environment_resume_max_abs_v=maximum,
        resume_without_refit=True, html_rebuild_without_signal_reads=True,
        default_scientific_parameters_used=True, clean_install_verified=clean)
    save()
except BaseException as exc:
    record.update(status='failed', error=f'{type(exc).__name__}: {exc}', traceback=traceback.format_exc())
    save()
    raise
'''


def venv_python(directory):
    return directory/('Scripts/python.exe' if os.name == 'nt' else 'bin/python')


def clean_environment():
    env = os.environ.copy()
    for key in ('PYTHONPATH', 'PYTHONHOME'):
        env.pop(key, None)
    env.update(PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', MPLBACKEND='Agg',
               OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
    return env


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--wheel', type=Path, help='Built wheel to install with dependencies')
    parser.add_argument('--venv', type=Path, help='New venv or an existing isolated venv')
    parser.add_argument('--output', type=Path, required=True, help='New or empty evidence directory')
    parser.add_argument('--extras', default='', help='Comma-separated package extras, e.g. eegprep,autoreject,device')
    parser.add_argument('--constraints', type=Path, help='Optional recorded dependency constraints')
    parser.add_argument('--skip-install', action='store_true', help='Verify an already populated isolated venv; no installation')
    parser.add_argument('--existing-environment-check', action='store_true',
                        help='Run only the synthetic worker using this interpreter; explicitly NOT clean installation')
    parser.add_argument('--timeout', type=int, default=1800, help='Timeout in seconds for each subprocess')
    args = parser.parse_args(argv)
    if args.timeout < 1:
        parser.error('--timeout must be positive')
    if args.existing_environment_check and any((args.venv, args.wheel, args.constraints, args.skip_install, args.extras)):
        parser.error('--existing-environment-check cannot be combined with installation options')
    if not args.existing_environment_check and not args.skip_install and args.wheel is None:
        parser.error('--wheel is required unless --skip-install is used')
    if args.skip_install and args.venv is None:
        parser.error('--skip-install requires --venv')
    root = args.output.expanduser().resolve()
    if root.exists() and any(root.iterdir()):
        parser.error('Output directory must be new or empty: '+str(root))
    root.mkdir(parents=True, exist_ok=True)
    env = clean_environment()
    evidence = dict(validation_kind='existing_environment_worker' if args.existing_environment_check else 'clean_install',
                    clean_install_verified=False, commands=[], status='running', source_checkout=str(ROOT),
                    dependency_install_requested=not(args.skip_install or args.existing_environment_check))

    def save():
        (root/'clean_install_validation.json').write_text(json.dumps(evidence, indent=2), encoding='utf8')

    def execute(label, command, cwd):
        log = root/(label+'.log')
        started = time.perf_counter()
        print(label, flush=True)
        with log.open('w', encoding='utf8') as handle:
            proc = subprocess.run([str(value) for value in command], cwd=cwd, env=env,
                                  stdout=handle, stderr=subprocess.STDOUT, timeout=args.timeout)
        entry = dict(stage=label, command=[str(value) for value in command],
                     cwd=str(cwd), log=str(log), seconds=time.perf_counter()-started, exit_code=proc.returncode)
        evidence['commands'].append(entry)
        save()
        if proc.returncode:
            raise RuntimeError(f'{label} failed with exit {proc.returncode}; see {log}')

    try:
        with tempfile.TemporaryDirectory(prefix='eeg-clean-install-worker-') as working:
            working = Path(working).resolve()
            # A clean check must not inherit stale font cache entries or user
            # plotting styles from another installation. Do not edit that cache.
            env['MPLCONFIGDIR'] = str(working/'matplotlib')
            if args.existing_environment_check:
                executable = Path(sys.executable).resolve()
                evidence['console_entrypoints'] = 'not tested; worker-only existing environment'
            else:
                venv = args.venv.expanduser().resolve() if args.venv else root/'venv'
                if not venv.exists():
                    if args.skip_install:
                        raise ValueError('--skip-install venv does not exist')
                    execute('create_venv', [sys.executable, '-m', 'venv', str(venv)], working)
                cfg = venv/'pyvenv.cfg'
                if not cfg.is_file() or 'include-system-site-packages = false' not in cfg.read_text(encoding='utf8').lower():
                    raise ValueError('Expected a venv with include-system-site-packages = false')
                executable = venv_python(venv)
                if not executable.is_file():
                    raise ValueError('Venv interpreter missing: '+str(executable))
                evidence['venv'] = str(venv)
                evidence['pyvenv_cfg'] = cfg.read_text(encoding='utf8')
                if not args.skip_install:
                    wheel = args.wheel.expanduser().resolve()
                    if not wheel.is_file() or wheel.suffix != '.whl':
                        raise ValueError('Wheel file does not exist: '+str(wheel))
                    spec = str(wheel)+(f'[{args.extras}]' if args.extras else '')
                    command = [executable, '-m', 'pip', 'install', spec]
                    if args.constraints:
                        constraints = args.constraints.expanduser().resolve()
                        if not constraints.is_file():
                            raise ValueError('Constraints file does not exist')
                        command += ['--constraint', str(constraints)]
                    execute('install_dependencies', command, working)
                execute('pip_check', [executable, '-m', 'pip', 'check'], working)
                execute('pip_freeze', [executable, '-m', 'pip', 'freeze', '--all'], working)
                for name in ('eegproc', 'eegproc-prepare'):
                    console = executable.parent/(name+('.exe' if os.name == 'nt' else ''))
                    if not console.is_file():
                        raise ValueError('Console script missing: '+str(console))
                    execute(name+'_help', [console, '--help'], working)
                evidence['console_entrypoints'] = 'actual installed executables'
            script = working/'isolated_worker.py'
            script.write_text(WORKER, encoding='utf8')
            # -I strips user site packages and Python environment variables.
            # Clean mode never inserts a source path; the explicit development
            # worker-only mode records its checkout import separately.
            isolation = [] if args.existing_environment_check else ['-I']
            execute('scientific_worker', [executable, *isolation, '-B', script, root, ROOT,
                    'existing' if args.existing_environment_check else 'clean'], working)
            worker = json.loads((root/'worker_validation.json').read_text(encoding='utf8'))
            if worker.get('status') != 'passed':
                raise RuntimeError('Scientific worker did not finish successfully')
            requested_extras = {value.strip() for value in args.extras.split(',') if value.strip()}
            for extra, distribution in {'eegprep':'eegprep','autoreject':'autoreject','device':'pyedflib'}.items():
                if extra in requested_extras and not worker.get('optional_imports', {}).get(distribution, {}).get('installed'):
                    raise RuntimeError(f'Requested extra {extra} was not importable in the worker')
            evidence.update(status='passed', clean_install_verified=not args.existing_environment_check,
                            worker_evidence=str(root/'worker_validation.json'))
    except BaseException as exc:
        evidence.update(status='failed', error=f'{type(exc).__name__}: {exc}')
        save()
        raise
    save()
    print(json.dumps(evidence, indent=2), flush=True)


if __name__ == '__main__':
    main()
