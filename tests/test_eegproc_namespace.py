"""The public rename shares implementation and preserves checkpoint boundaries."""
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


ROOT = Path(__file__).resolve().parents[1]


def test_distribution_import_and_console_names_are_eegproc():
    metadata = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))
    assert metadata['project']['name'] == 'eegproc'
    assert metadata['project']['scripts']['eegproc'] == 'eegproc.cli:main'
    assert metadata['project']['scripts']['eegproc-prepare'] == 'prepare_data:main'
    assert metadata['project']['urls']['Repository'] == 'https://github.com/LeiGuo0812/eegproc'
    assert eegproc.__version__ == '0.4.0a1'


def test_legacy_api_and_submodules_are_the_same_objects():
    legacy = importlib.import_module('eeg_pipeline')
    for name in eegproc.__all__:
        assert getattr(legacy, name) is getattr(eegproc, name), name
    for path in (ROOT / 'eegproc').rglob('*.py'):
        relative = path.relative_to(ROOT / 'eegproc')
        if relative.name == '__main__.py' or str(relative) == '__init__.py':
            continue
        parts = list(relative.with_suffix('').parts)
        if parts[-1] == '__init__':
            parts.pop()
        suffix = '.'.join(parts)
        assert importlib.import_module('eeg_pipeline.' + suffix) is importlib.import_module('eegproc.' + suffix), suffix


@pytest.mark.parametrize('package', ['eegproc', 'eeg_pipeline'])
def test_new_and_legacy_module_commands_work(package):
    result = subprocess.run([sys.executable, '-B', '-m', package, '--help'],
                            cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert '--input-fif' in result.stdout and '--resume' in result.stdout


def test_manifest_hashes_real_code_under_stable_canonical_keys():
    manifest = compatibility.computation_manifest()
    for key, digest in manifest['source_files_sha256'].items():
        assert key.startswith('eeg_pipeline/')
        implementation = ROOT / key.replace('eeg_pipeline/', 'eegproc/', 1)
        assert hashlib.sha256(implementation.read_bytes()).hexdigest() == digest


def _previous_annotation_manifest():
    prior = copy.deepcopy(compatibility.computation_manifest())
    prior['source_files_sha256']['eeg_pipeline/engine.py'] = 'bed1f8dc5c9fed88de1b2f65a68b402190592365116c753bdcee79b31ab19cd9'
    prior['source_files_sha256']['eeg_pipeline/review.py'] = '3242464b8d4feed507142baf4fb88821c0b58590456b7e73d6e10bea76b26dec'
    prior['source_bundle_sha256'] = compatibility._bundle(prior['source_files_sha256'])
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
