"""Run corrected parameter requests on real MNE containers and verify delivery."""
from pathlib import Path
import argparse
import json
import re
import sys

import mne
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eegproc import run, resume


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=False)
    fixture = mne.io.read_raw_fif(ROOT/'tests/fixtures/staged_v3/input_raw.fif', preload=True, verbose=False)
    summary = dict(status='running', cases={})

    def record(name, result, original, before):
        assert result.status == 'review_required'
        assert result.report['parameter_adjustments']
        assert result.report['report_status'] == 'completed'
        assert not result.report['visualizations']['errors']
        assert all(value is not False for value in result.report['metadata_audit']['checks'].values())
        assert np.array_equal(original.get_data(), before)
        html = Path(result.outputs['quality_report']).read_text(encoding='utf8')
        saved = json.loads(re.search(r'<script id="run-record" type="application/json">(.*?)</script>', html, re.S).group(1))
        assert saved['parameter_adjustments'] == result.report['parameter_adjustments']
        assert saved['provenance']['invocation']['effective_config'] == saved['config']
        assert 'Parameter adjustments' in html
        if 'checkpoint' in result.outputs:
            assert len(list(Path(result.outputs['checkpoint']).parent.iterdir())) == 3
        summary['cases'][name] = dict(status=result.status, adjustments=result.report['parameter_adjustments'],
            outputs=result.outputs, metadata_checks=result.report['metadata_audit']['checks'],
            epoch_resolution=result.report.get('epoch_resolution'),
            excluded=result.report.get('ica',{}).get('removed_components_0based'),
            input_unchanged=True)

    raw = fixture.copy()
    before = raw.get_data().copy()
    result = run(raw, folder/'corrected', 'corrected', config_file=folder/'missing_optional.json',
        purpose='erp', task_name='validation', n_threads=0, lowpass=float('nan'),
        asr_cutoff=-1, line_bandwidth=.01, ica_exclude=[999999], epoch_mode='events',
        event_names=['nonexistent'], repair_epochs=True, epoch_config={'cv':'invalid'},
        collect_stages='false', invocation=42, detect_ransac=False,
        unknown_parameter=True)
    record('corrected', result, raw, before)
    assert result.report['ica']['decision_status'] == 'manual'
    assert result.report['ica']['removed_components_0based'] == []
    assert result.report['epoch_resolution']['status'] == 'skipped'
    assert 'epochs' not in result.outputs and result.report['config']['repair_epochs'] is False

    restored = resume(result.outputs['checkpoint'], folder/'manual_revision', 'manual_revision',
        exclude=[0, 999999], original_raw=raw, collect_stages='false')
    record('manual_revision', restored, raw, before)
    assert restored.report['ica']['removed_components_0based'] == [0]
    assert not restored.report['parent_run']['fit_repeated']

    raw = fixture.copy().resample(128., verbose=False)
    ecg = mne.io.RawArray(15e-6*np.sin(2*np.pi*1.2*raw.times)[None, :],
        mne.create_info(['ECG'], raw.info['sfreq'], 'ecg'), first_samp=raw.first_samp, verbose=False)
    raw.add_channels([ecg], force_update_info=True)
    before = raw.get_data().copy()
    result = run(raw, folder/'128_hz', 'rate128', detect_ransac=False)
    record('128_hz', result, raw, before)
    assert result.report['config']['asr_cutoff'] == 20.
    assert result.report['config']['training_lowpass'] < 64.
    assert result.report['ecg_assistance']['usable_channels'] == ['ECG']
    assert np.array_equal(raw.get_data(picks=['ECG']), result.raw.get_data(picks=['ECG']))

    raw = raw.copy().resample(64., verbose=False)
    before = raw.get_data().copy()
    result = run(raw, folder/'64_hz', 'rate64', detect_ransac=False)
    record('64_hz', result, raw, before)
    assert result.report['config']['asr_cutoff'] is None
    assert result.report['config']['ica_enabled'] is False
    assert result.report['config']['training_lowpass'] < 32.
    assert 'checkpoint' not in result.outputs and 'ica' not in result.outputs
    assert np.array_equal(raw.get_data(picks=['ECG']), result.raw.get_data(picks=['ECG']))
    summary['status'] = 'passed'
    (folder/'validation.json').write_text(json.dumps(summary, indent=2), encoding='utf8')
    print(json.dumps(dict(status='passed', cases=list(summary['cases']), evidence=str(folder/'validation.json'))))


if __name__ == '__main__':
    main()
