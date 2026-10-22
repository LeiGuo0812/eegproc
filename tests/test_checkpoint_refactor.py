"""Computation compatibility, portable paths, and complete MNE input identity."""
import copy
from pathlib import Path

import mne
import numpy as np
import pytest

from eeg_pipeline import compatibility
from eeg_pipeline.checkpoint_input import input_reference,load_original,input_identity,identity_matches
from eeg_pipeline.report_provenance import capture_signal_audit,_auxiliary_equal
from test_pipeline import fixture


@pytest.fixture(autouse=True)
def isolate_older_transition_pins(monkeypatch):
    """Each transition test controls exactly the source/target it exercises."""
    monkeypatch.setattr(compatibility, 'VERIFIED_RENAME_TARGET_SHA256', None)


def test_checkpoint_contract_ignores_rendering_audit_but_rejects_algorithm_changes():
    manifest=compatibility.computation_manifest()
    payload=dict(schema=compatibility.CHECKPOINT_SCHEMA,compatibility=copy.deepcopy(manifest),
                 report={'provenance':{'software':{'source_files_sha256':{
                     'eeg_pipeline/report_layout.py':'rendering changed'}}}})
    result=compatibility.validate_checkpoint_compatibility(payload)
    assert result['transition']=='exact-computation-match'
    payload['compatibility']['source_files_sha256']['eeg_pipeline/ica.py']='arbitrary edit'
    payload['compatibility']['source_bundle_sha256']=compatibility._bundle(
        payload['compatibility']['source_files_sha256'])
    with pytest.raises(ValueError,match='Source changed'):
        compatibility.validate_checkpoint_compatibility(payload)


def test_checkpoint_contract_rejects_changed_critical_dependency():
    manifest=compatibility.computation_manifest()
    manifest['packages']['mne']='different-version'
    with pytest.raises(ValueError,match='Critical dependency changed.*mne'):
        compatibility.validate_checkpoint_compatibility(dict(schema=compatibility.CHECKPOINT_SCHEMA,
                                                              compatibility=manifest))


def test_legacy_transition_is_pinned_at_both_ends(monkeypatch):
    monkeypatch.setattr(compatibility,'VERIFIED_ANNOTATION_TARGET_SHA256',None)
    manifest=compatibility.computation_manifest()
    payload=dict(schema=compatibility.CHECKPOINT_SCHEMA,report={'provenance':{'software':{
        'source_files_sha256':copy.deepcopy(compatibility.LEGACY_V2_SOURCE_FILES),
        'source_bundle_sha256':compatibility._bundle(compatibility.LEGACY_V2_SOURCE_FILES),
        'packages':manifest['packages']}}})
    monkeypatch.setattr(compatibility,'VERIFIED_LEGACY_TARGET_SHA256',None)
    monkeypatch.setattr(compatibility,'VERIFIED_NORMALIZATION_TARGET_SHA256',None)
    with pytest.raises(ValueError,match='verified compatibility target'):
        compatibility.validate_checkpoint_compatibility(payload)
    monkeypatch.setattr(compatibility,'VERIFIED_LEGACY_TARGET_SHA256',manifest['source_bundle_sha256'])
    assert compatibility.validate_checkpoint_compatibility(payload)['transition'].startswith('verified-')
    payload['report']['provenance']['software']['source_files_sha256']['eeg_pipeline/ica.py']='unverified'
    payload['report']['provenance']['software']['source_bundle_sha256']=compatibility._bundle(
        payload['report']['provenance']['software']['source_files_sha256'])
    with pytest.raises(ValueError,match='explicitly verified baseline'):
        compatibility.validate_checkpoint_compatibility(payload)


def _packaged_v030_manifest():
    """Frozen 0.3.0 wheel manifest, independent of current source files."""
    files=copy.deepcopy(compatibility.LEGACY_V2_SOURCE_FILES)
    files.update({
        'eeg_pipeline/checkpoint_input.py':'aa9a4c07dca36332903bde2e9841150d82172cf18166cc678a1024bd03ade7e5',
        'eeg_pipeline/configuration.py':'d3fb83a383cc474123ed5b1a442db0f46e2e053bae387d75b98d9d7cb1a807a3',
        'eeg_pipeline/delivery.py':'405ebee09114ea6f7e1e8caf30f900e36d69bb86aef32b55f9a3e6fc5ab5d8a4',
        'eeg_pipeline/engine.py':'262164a434658407b473040950518d8cbd9d7032d4cca9800e7fdcabe926c6ea',
        'eeg_pipeline/epoch_export.py':'2d1b1f84b6bdb588a5663bdb0c3d5e7d56cf5ddd794c00213fdb3b83a42d2bdf',
        'eeg_pipeline/mne_asr/api.py':'a3b09b369ff579409f10de895b38ced491e28bab342caddb907972cf802b708e',
        'eeg_pipeline/raw_helpers.py':'14abf5e6fc0518d948f236eb3f628e8bbeb5cf631a538a9512a37e0843f34ecd',
        'eeg_pipeline/review.py':'33d0e3265c4bc145725b83d1a8151b8302983b4f7b5a7a39dd6ba180e5d62531',
        'eeg_pipeline/settings.py':'e7fb082e9b14055e2162f9610b133e24ab0b4461da3cbbc2fa0e37e845bf9c5d',
        'eeg_pipeline/signal_ops.py':'e9362e914d65041ec393ca38b278abe944469fdc7924bfc5f355a135cec327ab',
        'eeg_pipeline/stages.py':'b314e4c634063d74a32ada5734f601dfebeb8ea5ae67055ca7b1f2615f243668',
        'eeg_pipeline/storage.py':'75a86031ce4b45fcbec85cde9228c9334ced9e4791d1113cf62f6c7968ddfae4',
    })
    digest=compatibility._bundle(files)
    assert digest=='0e39e0d4c67acaedf615a800a50efd11ee674a4891ac53f55b950f9471b25ff6'
    return dict(contract=compatibility.COMPUTATION_CONTRACT,source_files_sha256=files,
        source_bundle_sha256=digest,packages=compatibility.critical_versions())


def test_current_manifest_includes_both_parameter_resolvers():
    sources=compatibility.computation_manifest()['source_files_sha256']
    assert 'eeg_pipeline/parameter_resolution.py' in sources
    assert 'eeg_pipeline/runtime_parameters.py' in sources


def test_previous_packaged_transition_requires_exact_source_and_target(monkeypatch):
    monkeypatch.setattr(compatibility,'VERIFIED_ANNOTATION_TARGET_SHA256',None)
    current=compatibility.computation_manifest()
    payload=dict(schema=compatibility.CHECKPOINT_SCHEMA,compatibility=_packaged_v030_manifest())
    monkeypatch.setattr(compatibility,'VERIFIED_LEGACY_TARGET_SHA256',None)
    monkeypatch.setattr(compatibility,'VERIFIED_NORMALIZATION_TARGET_SHA256',None)
    with pytest.raises(ValueError,match='no verified source/target transition'):
        compatibility.validate_checkpoint_compatibility(payload)
    monkeypatch.setattr(compatibility,'VERIFIED_NORMALIZATION_TARGET_SHA256',current['source_bundle_sha256'])
    assert compatibility.validate_checkpoint_compatibility(payload)['transition']=='verified-0.3.0-to-parameter-resolution-v1'
    monkeypatch.setattr(compatibility,'VERIFIED_NORMALIZATION_TARGET_SHA256','different target')
    with pytest.raises(ValueError,match='no verified source/target transition'):
        compatibility.validate_checkpoint_compatibility(payload)
    monkeypatch.setattr(compatibility,'VERIFIED_NORMALIZATION_TARGET_SHA256',current['source_bundle_sha256'])
    payload['compatibility']['source_files_sha256']['eeg_pipeline/ica.py']='f'*64
    payload['compatibility']['source_bundle_sha256']=compatibility._bundle(payload['compatibility']['source_files_sha256'])
    with pytest.raises(ValueError,match='no verified source/target transition'):
        compatibility.validate_checkpoint_compatibility(payload)


def test_annotation_transition_requires_exact_source_target_and_dependencies(monkeypatch):
    current=compatibility.computation_manifest()
    prior=copy.deepcopy(current)
    prior['source_files_sha256']['eeg_pipeline/engine.py']='bed1f8dc5c9fed88de1b2f65a68b402190592365116c753bdcee79b31ab19cd9'
    prior['source_files_sha256']['eeg_pipeline/review.py']='3242464b8d4feed507142baf4fb88821c0b58590456b7e73d6e10bea76b26dec'
    prior['source_files_sha256']['eeg_pipeline/raw_helpers.py']='14abf5e6fc0518d948f236eb3f628e8bbeb5cf631a538a9512a37e0843f34ecd'
    prior['source_bundle_sha256']=compatibility._bundle(prior['source_files_sha256'])
    assert prior['source_bundle_sha256']==compatibility.PACKAGED_V031_SOURCE_SHA256
    payload=dict(schema=compatibility.CHECKPOINT_SCHEMA,compatibility=prior)
    monkeypatch.setattr(compatibility,'VERIFIED_ANNOTATION_TARGET_SHA256',None)
    with pytest.raises(ValueError,match='no verified source/target transition'):
        compatibility.validate_checkpoint_compatibility(payload)
    monkeypatch.setattr(compatibility,'VERIFIED_ANNOTATION_TARGET_SHA256',current['source_bundle_sha256'])
    assert compatibility.validate_checkpoint_compatibility(payload)['transition']=='verified-0.3.1-to-annotation-selection-v1'
    monkeypatch.setattr(compatibility,'VERIFIED_ANNOTATION_TARGET_SHA256','different-target')
    with pytest.raises(ValueError,match='no verified source/target transition'):
        compatibility.validate_checkpoint_compatibility(payload)
    monkeypatch.setattr(compatibility,'VERIFIED_ANNOTATION_TARGET_SHA256',current['source_bundle_sha256'])
    prior['packages']['mne']='different'
    with pytest.raises(ValueError,match='Critical dependency changed'):
        compatibility.validate_checkpoint_compatibility(payload)
    prior['packages']=current['packages']
    prior['source_files_sha256']['eeg_pipeline/ica.py']='f'*64
    prior['source_bundle_sha256']=compatibility._bundle(prior['source_files_sha256'])
    with pytest.raises(ValueError,match='no verified source/target transition'):
        compatibility.validate_checkpoint_compatibility(payload)


@pytest.mark.parametrize('corruption',['missing-source','wrong-digest','dependency'])
def test_allowlisted_previous_source_still_checks_manifest_and_packages(monkeypatch,corruption):
    current=compatibility.computation_manifest()
    monkeypatch.setattr(compatibility,'VERIFIED_NORMALIZATION_TARGET_SHA256',current['source_bundle_sha256'])
    payload=dict(schema=compatibility.CHECKPOINT_SCHEMA,compatibility=_packaged_v030_manifest())
    if corruption=='missing-source':payload['compatibility']['source_files_sha256'].pop('eeg_pipeline/ica.py')
    elif corruption=='wrong-digest':payload['compatibility']['source_bundle_sha256']='f'*64
    else:payload['compatibility']['packages']['mne']='different'
    with pytest.raises(ValueError,match='manifest hash mismatch|Critical dependency changed'):
        compatibility.validate_checkpoint_compatibility(payload)


def test_legacy_subset_does_not_require_future_modules_and_whole_manifest_is_checked(monkeypatch):
    current=compatibility.computation_manifest()
    monkeypatch.setattr(compatibility,'VERIFIED_NORMALIZATION_TARGET_SHA256',current['source_bundle_sha256'])
    software=dict(source_files_sha256=copy.deepcopy(compatibility.LEGACY_V2_SOURCE_FILES),
        source_bundle_sha256=compatibility._bundle(compatibility.LEGACY_V2_SOURCE_FILES),
        packages=current['packages'])
    payload=dict(schema=compatibility.CHECKPOINT_SCHEMA,report={'provenance':{'software':software}})
    assert compatibility.validate_checkpoint_compatibility(payload)['transition']=='verified-0.2.0-to-parameter-resolution-v1'
    software['source_files_sha256']['eeg_pipeline/report_layout.py']='f'*64
    with pytest.raises(ValueError,match='Legacy checkpoint source manifest hash mismatch'):
        compatibility.validate_checkpoint_compatibility(payload)
    software['source_bundle_sha256']=compatibility._bundle(software['source_files_sha256'])
    assert compatibility.validate_checkpoint_compatibility(payload)['transition'].startswith('verified-0.2.0')


def test_checkpoint_paths_accept_windows_and_posix_but_reject_escape(tmp_path):
    assert compatibility.checkpoint_path(tmp_path,r's_ica_review\pre_ica_raw.fif')==tmp_path/'s_ica_review/pre_ica_raw.fif'
    assert compatibility.checkpoint_path(tmp_path,'s_ica_review/pre_ica_raw.fif')==tmp_path/'s_ica_review/pre_ica_raw.fif'
    for invalid in ('../secret',r'..\secret',r'C:\secret',r'\\host\share','/absolute'):
        with pytest.raises(ValueError,match='escapes'):
            compatibility.checkpoint_path(tmp_path,invalid)


@pytest.mark.parametrize('field',['coordinate_frames','digitization','transforms','projections',
                                  'annotation_orig_time','annotations'])
def test_input_identity_checks_extended_metadata(field):
    raw=fixture()
    reference=input_reference(raw)
    altered=copy.deepcopy(reference)
    identity=altered['identity']
    if field=='coordinate_frames':identity[field][0]+=1
    elif field=='digitization':identity[field][0]['r'][0]+=.001
    elif field=='transforms':identity[field]['dev_head_t']={'from':1,'to':4,'trans':np.eye(4).tolist()}
    elif field=='projections':identity[field]=[{'active':True,'desc':'changed'}]
    elif field=='annotation_orig_time':identity[field]='different clock'
    else:identity[field][0]['extras']={'reviewer':'different'}
    with pytest.raises(ValueError,match='does not match'):
        load_original(altered,original_raw=raw)


def test_input_identity_accepts_fif_rounding_and_verified_legacy_fields(tmp_path):
    raw=fixture();reference=input_reference(raw)
    path=tmp_path/'input_raw.fif';raw.save(path,fmt='double',overwrite=False,verbose=False)
    reopened=load_original(reference,original_fif=path)
    np.testing.assert_array_equal(reopened.get_data(),raw.get_data())
    legacy=copy.deepcopy(reference['identity'])
    for key in ('identity_version','coordinate_frames','digitization','transforms','projections'):
        legacy.pop(key)
    assert identity_matches(legacy,input_identity(raw))
    legacy['annotations'][0]['description']='changed'
    assert not identity_matches(legacy,input_identity(raw))


def test_audit_checks_channel_specific_annotations_extras_and_montage():
    raw=fixture();raw.annotations.extras[0]['reviewer']='original'
    clean=raw.copy();clean.annotations.extras[0]['reviewer']='changed'
    clean.info['dig'][0]['r'][0]+=.001
    report={};capture_signal_audit(report,raw,clean)
    assert report['metadata_audit']['checks']['annotations'] is False
    assert report['metadata_audit']['checks']['digitization'] is False
    assert report['metadata_audit']['checks']['annotation_orig_time'] is True


def test_auxiliary_audit_reads_bounded_blocks(monkeypatch):
    raw=fixture();clean=raw.copy();calls=[]
    original_get=mne.io.BaseRaw.get_data
    def tracked(self,*args,**kwargs):
        calls.append(kwargs['stop']-kwargs['start'])
        return original_get(self,*args,**kwargs)
    monkeypatch.setattr(mne.io.BaseRaw,'get_data',tracked)
    assert _auxiliary_equal(raw,clean,[12,13],block_samples=513)
    assert max(calls)<=513 and len(calls)>2
    clean._data[-1,-1]+=1
    assert not _auxiliary_equal(raw,clean,[12,13],block_samples=513)
