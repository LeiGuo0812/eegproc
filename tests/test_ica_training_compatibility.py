"""A new default must not relabel a frozen ICA fit as having a new band."""
import copy
from dataclasses import asdict
import json
from pathlib import Path

import pytest

from eegproc import compatibility as module, resolve_config


def checkpoint():
    path = Path(__file__).parent/'fixtures/computation_v040a4.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    assert module._bundle(manifest['source_files_sha256']) == module.PACKAGED_V040A4_SOURCE_SHA256
    manifest['packages'] = module.critical_versions()
    return {'schema': module.CHECKPOINT_SCHEMA, 'compatibility': manifest}


def test_previous_band_default_transition_requires_verified_exact_ends(monkeypatch):
    payload = checkpoint()
    target = module.computation_manifest()['source_bundle_sha256']
    monkeypatch.setattr(module, 'VERIFIED_ICA_BAND_TARGET_SHA256', None)
    with pytest.raises(ValueError, match='no verified source/target transition'):
        module.validate_checkpoint_compatibility(payload)
    monkeypatch.setattr(module, 'VERIFIED_ICA_BAND_TARGET_SHA256', target)
    assert module.validate_checkpoint_compatibility(payload)['transition'] == 'verified-0.4.0a4-to-ica-training-defaults'
    monkeypatch.setattr(module, 'VERIFIED_ICA_BAND_TARGET_SHA256', 'unverified-target')
    with pytest.raises(ValueError, match='no verified source/target transition'):
        module.validate_checkpoint_compatibility(payload)


def test_transition_rejects_source_and_dependency_changes(monkeypatch):
    monkeypatch.setattr(module, 'VERIFIED_ICA_BAND_TARGET_SHA256', module.computation_manifest()['source_bundle_sha256'])
    payload = checkpoint()
    changed = copy.deepcopy(payload)
    changed['compatibility']['packages']['numpy'] = 'unverified-version'
    with pytest.raises(ValueError, match='Critical dependency changed'):
        module.validate_checkpoint_compatibility(changed)
    changed = copy.deepcopy(payload)
    changed['compatibility']['source_files_sha256']['eeg_pipeline/ica.py'] = 'changed-ICA'
    changed['compatibility']['source_bundle_sha256'] = module._bundle(changed['compatibility']['source_files_sha256'])
    with pytest.raises(ValueError, match='no verified source/target transition'):
        module.validate_checkpoint_compatibility(changed)


def test_old_complete_checkpoint_config_retains_actual_half_hz_training():
    old = resolve_config(preset='eeglab', training_highpass=.5)
    restored = resolve_config(**asdict(old))
    assert (restored.training_highpass, restored.training_lowpass) == (.5, 100.)
    assert (restored.highpass, restored.lowpass) == (.5, 100.)
    assert not restored.adjustments
    assert resolve_config(preset='eeglab').training_highpass == 1.
