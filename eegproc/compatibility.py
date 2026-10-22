"""Versioned computation contracts for portable ICA checkpoints.

Report rendering and command-line files remain in the full provenance audit,
but do not determine whether an existing ICA decomposition can be applied.
Scientific-source changes require an exact match or an explicitly verified
compatibility transition. This is not a numerical-compatibility guess.
"""
from pathlib import Path, PureWindowsPath
import hashlib
import importlib.metadata
import json

CHECKPOINT_SCHEMA = 'eeg-ica-review-v2'
COMPUTATION_CONTRACT = 'eeg-computation-v1'
INPUT_IDENTITY_VERSION = 2
CRITICAL_PACKAGES = ('mne', 'numpy', 'scipy', 'mne-icalabel', 'pyprep',
                     'python-picard', 'autoreject', 'scikit-learn', 'torch',
                     'onnxruntime', 'eegprep')

# Historical canonical keys remain stable across the eegproc rename. Physical
# sources are always the implementation, never the eeg_pipeline import aliases.
SOURCE_PATHS = {
    **{f'eeg_pipeline/{name}.py': (f'eegproc/{name}.py', f'eeg_pipeline/{name}.py') for name in (
        '_utils', 'backends', 'checkpoint_input', 'configuration', 'delivery',
        'engine', 'epochs', 'ica', 'raw_helpers', 'review', 'settings',
        'signal_ops', 'stages', 'storage', 'parameter_resolution', 'runtime_parameters')},
    'eeg_pipeline/epoch_export.py': ('eegproc/epoch_export.py', 'eeg_pipeline/epoch_export.py', 'erp_outputs.py'),
    **{f'eeg_pipeline/mne_asr/{name}.py': (
        f'eegproc/mne_asr/{name}.py', f'eeg_pipeline/mne_asr/{name}.py', f'python/common/mne_asr/{name}.py')
       for name in ('__init__', 'api', '_calibrate', '_math', '_process',
                    '_reference', '_signal', '_stats', '_yulewalk')},
}

# Proven by the frozen before/after regression and rest/ERP/EEGLAB legacy
# checkpoint continuation in results/refactor_20261022/legacy_verified/.
# A later computation-source edit invalidates this transition until revalidated.
VERIFIED_LEGACY_TARGET_SHA256 = '0e39e0d4c67acaedf615a800a50efd11ee674a4891ac53f55b950f9471b25ff6'
# The previous packaged release is identified by its complete critical-source
# manifest, not by a version label. Verified by five unchanged full-pipeline
# comparisons and six 0.2/0.3 checkpoint transitions in
# results/parameter_resolution_20261022/{comparison.json,transitions_final/}.
PACKAGED_V030_SOURCE_SHA256 = '0e39e0d4c67acaedf615a800a50efd11ee674a4891ac53f55b950f9471b25ff6'
VERIFIED_NORMALIZATION_TARGET_SHA256 = '2530e65f73803eb58aaa5496946b2227ca9bd6fafed78f4377a39b49b54a5984'
# Container-only correction: channel-scoped annotations follow MNE selection
# semantics. Verified by five bitwise-equal scientific comparisons and nine
# 0.2/0.3/0.3.1 checkpoint continuations in results/release_audit_20261022/.
PACKAGED_V031_SOURCE_SHA256 = VERIFIED_NORMALIZATION_TARGET_SHA256
VERIFIED_ANNOTATION_TARGET_SHA256 = '2c490917fc68b6e29156787ba49fdaa3031194f8d26247d1f9dda36bb2d601e3'
# Rename-only target verified by five bitwise-equal full-pipeline comparisons
# and twelve 0.2/0.3/0.3.1 checkpoint continuations (including annotation v1)
# in results/eegproc_rename_20261022/{comparison.json,transitions/summary.json}.
ANNOTATION_V031_SOURCE_SHA256 = VERIFIED_ANNOTATION_TARGET_SHA256
VERIFIED_RENAME_TARGET_SHA256 = '028ffbd7836d8b2fe61396441a65a643619fb5184f218bd80d8d9407e2fee9d6'
LEGACY_V2_SOURCE_FILES = {
    "eeg_pipeline/_utils.py": "560369b76e2d1d91fa79f4cf5c23daae093a3c2acbbdb48ed1b3deacde229d4a",
    "eeg_pipeline/backends.py": "6baa4dd3ddafebed91086a1f1be88909eec963e91e7919cced05484c9b00e218",
    "eeg_pipeline/checkpoint_input.py": "3d8f14fe3059cf56c00e933d6b3f2b4e57a10fccdba2ac9f5eb110150d2dc117",
    "eeg_pipeline/configuration.py": "22f5d7a5f17277eaf92f6d574dae5ca2e7b69f994e57dac1640a3b53b1b0b47c",
    "eeg_pipeline/delivery.py": "710a00331543286d19f416b365f6943d82dc3daf60a007b41ff4dcca76b5ca37",
    "eeg_pipeline/engine.py": "0c146ea1d1aaaa216e4522ea0ee7eb15632ac8f6fb06458ee0cc48403bcac607",
    "eeg_pipeline/epoch_export.py": "13a63411ba07cff675c7c96c8824f1068f0ae1ccc74755c812da8b982b06e503",
    "eeg_pipeline/epochs.py": "0f04a1259607fd026242b8df8fd8eb374eca6a8476d64b95441821a9422f16b2",
    "eeg_pipeline/ica.py": "1932d91c477e06da793bbf9c95bde31c56a5d6eae91b206449e0239a7974244c",
    "eeg_pipeline/mne_asr/__init__.py": "ffbf4b911b736ca3855690f7ef325d42d4a61207f3fbe82758bc6dfcdd2a9477",
    "eeg_pipeline/mne_asr/_calibrate.py": "25edb8a05162110f86039a73d8b7e4405f34dbe469b1241ab222e913753837ea",
    "eeg_pipeline/mne_asr/_math.py": "6200550b336163f7b9eecd5c3f92fb32cca86c9f641c4122b81cf7d46de6e9dc",
    "eeg_pipeline/mne_asr/_process.py": "f32c8809b6253e69aaf021e68d137cafb4a1f2399156eecb79e1c8e853d2a601",
    "eeg_pipeline/mne_asr/_reference.py": "fcda4d5e898b42721784d5860dc6603bdef0b591fd7e7d366e482b0354c63a2f",
    "eeg_pipeline/mne_asr/_signal.py": "1c9dcaa2e853c0bec1e7117a106d16f1d81e312145eb0b391bd907605bc1f10c",
    "eeg_pipeline/mne_asr/_stats.py": "931bd068666e3f4f3ac9c4e52476055ded34c51425eb027151342acf00a89fa2",
    "eeg_pipeline/mne_asr/_yulewalk.py": "58c790dfda61c8b7d409bdf5489ad3bf79564735e2e3b5ae7ca04a183b9267c3",
    "eeg_pipeline/mne_asr/api.py": "97e78dd53f00e9a4cf713002fc3972a8a344a8c4e3d0592cd80714916e2304c1",
    "eeg_pipeline/raw_helpers.py": "020fd65d1361be9aab82721b65bc24b5fdfdcb836f89e511d468bc294bdcaf2d",
    "eeg_pipeline/review.py": "cbf884daa8a2723d333db42a69dbc816e2ba60f8e707b377db2c45ea695ff01e",
    "eeg_pipeline/settings.py": "d69947172ebf50e5a77c19301948a3a7d09de276284ffd22d876a8725eaf2740",
    "eeg_pipeline/signal_ops.py": "fc8742fb433d5c0f91fbb68f387d0dddb7852479da9f0983636753cac324d438",
    "eeg_pipeline/stages.py": "da83214d4f17deea4227f37f2a964c37f5dc1cd58f242679e0da852ed9c4001f",
    "eeg_pipeline/storage.py": "1536861a57d9f7d459554e367542cab583e2b88989f5005b5fee4165ac1fdff1"
}


def _hash(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _bundle(files):
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def critical_versions():
    versions = {}
    for name in CRITICAL_PACKAGES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = 'not installed'
    return versions


def canonical_sources(recorded, keys=None):
    """Extract exactly the source family recorded by that computation version."""
    result = {}
    for canonical in SOURCE_PATHS if keys is None else keys:
        alternatives=SOURCE_PATHS[canonical]
        matches = [recorded[path] for path in alternatives if path in recorded]
        if not matches:
            raise ValueError('Checkpoint computation source is missing: ' + canonical)
        if len(set(matches)) != 1:
            raise ValueError('Checkpoint has conflicting computation sources: ' + canonical)
        result[canonical] = matches[0]
    return result


def _verified_transitions():
    """Only explicit source/target pairs; no version-wide compatibility bypass."""
    legacy=_bundle(LEGACY_V2_SOURCE_FILES)
    result={}
    if VERIFIED_RENAME_TARGET_SHA256:
        for source,label in ((legacy,'0.2.0'),
                             (PACKAGED_V030_SOURCE_SHA256,'0.3.0'),
                             (PACKAGED_V031_SOURCE_SHA256,'0.3.1'),
                             (ANNOTATION_V031_SOURCE_SHA256,'0.3.1-annotation')):
            result[(source,VERIFIED_RENAME_TARGET_SHA256)]=f'verified-{label}-to-eegproc-v1'
    if VERIFIED_ANNOTATION_TARGET_SHA256:
        for source,label in ((legacy,'0.2.0'),
                             (PACKAGED_V030_SOURCE_SHA256,'0.3.0'),
                             (PACKAGED_V031_SOURCE_SHA256,'0.3.1')):
            result[(source,VERIFIED_ANNOTATION_TARGET_SHA256)]=f'verified-{label}-to-annotation-selection-v1'
    if VERIFIED_LEGACY_TARGET_SHA256:
        result[(legacy,VERIFIED_LEGACY_TARGET_SHA256)]='verified-0.2.0-to-packaged-v1'
    if VERIFIED_NORMALIZATION_TARGET_SHA256:
        result[(PACKAGED_V030_SOURCE_SHA256,VERIFIED_NORMALIZATION_TARGET_SHA256)]='verified-0.3.0-to-parameter-resolution-v1'
        result[(legacy,VERIFIED_NORMALIZATION_TARGET_SHA256)]='verified-0.2.0-to-parameter-resolution-v1'
    return result


def computation_manifest():
    root = Path(__file__).resolve().parents[1]
    files = {}
    for canonical, alternatives in SOURCE_PATHS.items():
        path = next((root / name for name in alternatives if (root / name).is_file()), None)
        if path is None:
            raise RuntimeError('Installed computation module is missing: ' + canonical)
        files[canonical] = _hash(path)
    return dict(contract=COMPUTATION_CONTRACT, source_files_sha256=files,
                source_bundle_sha256=_bundle(files), packages=critical_versions())


def validate_checkpoint_compatibility(payload):
    """Reject unverified algorithm/dependency changes; ignore rendering edits."""
    if payload.get('schema') != CHECKPOINT_SCHEMA:
        raise ValueError('Unsupported ICA checkpoint schema')
    current = computation_manifest()
    recorded = payload.get('compatibility')
    if recorded is None:
        software = payload['report']['provenance']['software']
        complete=software.get('source_files_sha256',{})
        if not isinstance(complete,dict) or not complete or software.get('source_bundle_sha256')!=_bundle(complete):
            raise ValueError('Legacy checkpoint source manifest hash mismatch')
        sources = canonical_sources(complete,keys=LEGACY_V2_SOURCE_FILES)
        if sources != LEGACY_V2_SOURCE_FILES:
            raise ValueError('Source changed: legacy ICA checkpoint is not an explicitly verified baseline')
        source_digest=_bundle(sources)
        transition=_verified_transitions().get((source_digest,current['source_bundle_sha256']))
        if transition is None:
            raise ValueError('Source changed: legacy ICA checkpoint requires a verified compatibility target')
        versions = software.get('packages', {})
    else:
        if recorded.get('contract') != COMPUTATION_CONTRACT:
            raise ValueError('Unsupported checkpoint computation contract')
        sources = recorded.get('source_files_sha256', {})
        if not isinstance(sources,dict) or not sources or recorded.get('source_bundle_sha256') != _bundle(sources):
            raise ValueError('Checkpoint computation manifest hash mismatch')
        source_digest=recorded['source_bundle_sha256']
        transition='exact-computation-match'
        if sources != current['source_files_sha256']:
            transition=_verified_transitions().get((source_digest,current['source_bundle_sha256']))
            if transition is None:
                changed = sorted(set(sources) ^ set(current['source_files_sha256']) |
                                 {p for p in sources.keys() & current['source_files_sha256'].keys()
                                  if sources[p] != current['source_files_sha256'][p]})
                raise ValueError('Source changed since ICA checkpoint; no verified source/target transition: ' + ', '.join(changed))
        versions = recorded.get('packages', {})
    changed = [p for p in CRITICAL_PACKAGES if versions.get(p) != current['packages'][p]]
    if changed:
        raise ValueError('Critical dependency changed since ICA checkpoint: ' + ', '.join(changed))
    return dict(contract=COMPUTATION_CONTRACT, transition=transition,
                source_checkpoint_sha256=source_digest,
                source_bundle_sha256=current['source_bundle_sha256'])


def checkpoint_path(root, relative):
    """Read POSIX paths and old Windows relative paths without allowing escape."""
    if not isinstance(relative, str) or not relative:
        raise ValueError('Checkpoint artifact path must be a nonempty relative path')
    windows = PureWindowsPath(relative)
    normalized = relative.replace('\\', '/')
    if windows.drive or windows.root or normalized.startswith('/'):
        raise ValueError('Checkpoint artifact escapes its output folder')
    root = Path(root).resolve()
    result = (root / normalized).resolve()
    if not result.is_relative_to(root):
        raise ValueError('Checkpoint artifact escapes its output folder')
    return result
