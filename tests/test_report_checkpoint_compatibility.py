"""Report isolation preserves exact-pinned continuation of existing ICA fits."""
import copy
import json
from pathlib import Path

import pytest

from eegproc import compatibility as module


def frozen_checkpoint():
    path = Path(__file__).parent/'fixtures/computation_v040a3.json'
    manifest = json.loads(path.read_text(encoding='utf-8'))
    assert manifest['source_bundle_sha256'] == module.PACKAGED_V040A3_SOURCE_SHA256
    manifest['packages'] = module.critical_versions()
    return {'schema': module.CHECKPOINT_SCHEMA, 'compatibility': manifest}


def test_frozen_a3_requires_exact_verified_source_target_and_dependencies(monkeypatch):
    payload = frozen_checkpoint()
    target = module.computation_manifest()['source_bundle_sha256']
    monkeypatch.setattr(module, 'VERIFIED_REPORT_TARGET_SHA256', None)
    with pytest.raises(ValueError, match='no verified source/target transition'):
        module.validate_checkpoint_compatibility(payload)
    monkeypatch.setattr(module, 'VERIFIED_REPORT_TARGET_SHA256', target)
    assert module.validate_checkpoint_compatibility(payload)['transition'] == 'verified-0.4.0a3-to-isolated-reports'
    monkeypatch.setattr(module, 'VERIFIED_REPORT_TARGET_SHA256', 'unverified-target')
    with pytest.raises(ValueError, match='no verified source/target transition'):
        module.validate_checkpoint_compatibility(payload)
    monkeypatch.setattr(module, 'VERIFIED_REPORT_TARGET_SHA256', target)
    changed = copy.deepcopy(payload)
    changed['compatibility']['packages']['numpy'] = 'unverified-version'
    with pytest.raises(ValueError, match='Critical dependency changed'):
        module.validate_checkpoint_compatibility(changed)
    changed = copy.deepcopy(payload)
    files = changed['compatibility']['source_files_sha256']
    files['eeg_pipeline/ica.py'] = 'unverified-source'
    changed['compatibility']['source_bundle_sha256'] = module._bundle(files)
    with pytest.raises(ValueError, match='no verified source/target transition'):
        module.validate_checkpoint_compatibility(changed)


def test_verified_chains_have_no_version_wide_bypass(monkeypatch):
    monkeypatch.setattr(module, '_verified_transitions', lambda: {
        ('frozen-a2', 'frozen-a3'): 'verified-a2-a3',
        ('frozen-a3', 'frozen-a4'): 'verified-a3-a4',
        ('frozen-a4', 'frozen-a2'): 'verified-cycle',
    })
    assert module._verified_transition('frozen-a2', 'frozen-a4') == 'verified-a2-a3 -> verified-a3-a4'
    assert module._verified_transition('unverified-a3', 'frozen-a4') is None
    assert module._verified_transition('frozen-a2', 'unverified-target') is None
