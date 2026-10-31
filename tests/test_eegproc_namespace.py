"""Public package entry points and computation-checkpoint boundaries."""
import copy
import hashlib
import importlib
from pathlib import Path
import subprocess
import sys
import tomllib

import pytest

import eegproc
from eegproc import compatibility
from frozen_manifests import annotation_v031_manifest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def isolate_epoch_transition_pin(monkeypatch):
    """Namespace transition tests exercise their own source/target pin only."""
    monkeypatch.setattr(compatibility, 'VERIFIED_EPOCH_TARGET_SHA256', None)


def test_distribution_import_and_console_names_are_eegproc():
    metadata = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    assert metadata['project']['name'] == 'eegproc'
    assert metadata['project']['scripts']['eegproc'] == 'eegproc.cli:main'
    assert metadata['project']['scripts']['eegproc-prepare'] == 'eegproc.prepare_cli:main'
    assert metadata['project']['urls']['Repository'] == 'https://github.com/LeiGuo0812/eegproc'
    assert eegproc.__version__ == '0.4.0a3'



@pytest.mark.parametrize('package', ['eegproc', 'eegproc.prepare_cli'])
def test_public_module_command_works(package):
    result = subprocess.run([sys.executable, '-B', '-m', package, '--help'],
                            cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert ('--input-fif' in result.stdout and '--resume' in result.stdout
            if package == 'eegproc' else '--output-fif' in result.stdout)


def test_manifest_hashes_real_code_under_stable_canonical_keys():
    manifest = compatibility.computation_manifest()
    for key, digest in manifest['source_files_sha256'].items():
        assert key.startswith('eeg_pipeline/')
        implementation = ROOT / key.replace('eeg_pipeline/', 'eegproc/', 1)
        assert hashlib.sha256(implementation.read_bytes()).hexdigest() == digest


def _previous_annotation_manifest():
    prior = annotation_v031_manifest()
    assert prior['source_bundle_sha256'] == compatibility.ANNOTATION_V031_SOURCE_SHA256
    return prior


def test_rename_transition_requires_exact_source_target_and_dependencies(monkeypatch):
    current = compatibility.computation_manifest()
    prior = _previous_annotation_manifest()
    payload = dict(schema=compatibility.CHECKPOINT_SCHEMA, compatibility=prior)
    monkeypatch.setattr(compatibility, 'VERIFIED_RENAME_TARGET_SHA256', None)
    with pytest.raises(ValueError, match='no verified source/target transition'):
        compatibility.validate_checkpoint_compatibility(payload)
    monkeypatch.setattr(compatibility, 'VERIFIED_RENAME_TARGET_SHA256', current['source_bundle_sha256'])
    assert compatibility.validate_checkpoint_compatibility(payload)['transition'] == 'verified-0.3.1-annotation-to-eegproc-v1'
    monkeypatch.setattr(compatibility, 'VERIFIED_RENAME_TARGET_SHA256', 'different-target')
    with pytest.raises(ValueError, match='no verified source/target transition'):
        compatibility.validate_checkpoint_compatibility(payload)
    monkeypatch.setattr(compatibility, 'VERIFIED_RENAME_TARGET_SHA256', current['source_bundle_sha256'])
    prior['packages']['mne'] = 'different'
    with pytest.raises(ValueError, match='Critical dependency changed'):
        compatibility.validate_checkpoint_compatibility(payload)
    prior['packages'] = current['packages']
    prior['source_files_sha256']['eeg_pipeline/ica.py'] = 'f' * 64
    prior['source_bundle_sha256'] = compatibility._bundle(prior['source_files_sha256'])
    with pytest.raises(ValueError, match='no verified source/target transition'):
        compatibility.validate_checkpoint_compatibility(payload)
