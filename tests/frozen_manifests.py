"""Frozen critical-source manifests for historical checkpoint transitions.

The source bytes are from the released 0.4.0a2 manifest (028ffbd...), with
the recorded pre-rename engine/review and pre-annotation raw-helper hashes.
They intentionally do not depend on current implementation files. Dependency
versions are supplied by the running environment so each test isolates source
transitions; separate assertions explicitly exercise dependency rejection.
"""
from copy import deepcopy

from eegproc import compatibility


ANNOTATION_V031_SOURCES = {
    'eeg_pipeline/_utils.py': '560369b76e2d1d91fa79f4cf5c23daae093a3c2acbbdb48ed1b3deacde229d4a',
    'eeg_pipeline/backends.py': '1adac2ce715aa1a8238db5610978d9551cf312d6d15c941a75b8d85acb954fa3',
    'eeg_pipeline/checkpoint_input.py': 'aa9a4c07dca36332903bde2e9841150d82172cf18166cc678a1024bd03ade7e5',
    'eeg_pipeline/configuration.py': 'e113b02e82021390387a21eac112403764d875257845788d042f426fe8104f09',
    'eeg_pipeline/delivery.py': '01d023674d2c434c5428b5379a4ca905a7e62dff63ef319d66a05884eda4ea8a',
    'eeg_pipeline/engine.py': 'bed1f8dc5c9fed88de1b2f65a68b402190592365116c753bdcee79b31ab19cd9',
    'eeg_pipeline/epochs.py': '0f04a1259607fd026242b8df8fd8eb374eca6a8476d64b95441821a9422f16b2',
    'eeg_pipeline/ica.py': '1932d91c477e06da793bbf9c95bde31c56a5d6eae91b206449e0239a7974244c',
    'eeg_pipeline/raw_helpers.py': 'a52101246b611bc39dbe94dd95493cc0d43599e33ebdeb0f29d57a388ec0bf89',
    'eeg_pipeline/review.py': '3242464b8d4feed507142baf4fb88821c0b58590456b7e73d6e10bea76b26dec',
    'eeg_pipeline/settings.py': '0d48c90c66f76eadab1189ae8764a5b9a11a925291bc566e6dcae2979047b556',
    'eeg_pipeline/signal_ops.py': 'e9362e914d65041ec393ca38b278abe944469fdc7924bfc5f355a135cec327ab',
    'eeg_pipeline/stages.py': '38937b2fcc9ab6e43b24f24b4a888a08164dd29ec56eb95cdc32c23720a46c8d',
    'eeg_pipeline/storage.py': '75a86031ce4b45fcbec85cde9228c9334ced9e4791d1113cf62f6c7968ddfae4',
    'eeg_pipeline/parameter_resolution.py': '43313a9703d5755763c708056b6b5ced3fe9115a8e74061570a2a2a64e1556ca',
    'eeg_pipeline/runtime_parameters.py': '418517d150bc2a8856860c8f05e703dd7cc11617da2adcad2226d8be2809f584',
    'eeg_pipeline/epoch_export.py': '2d1b1f84b6bdb588a5663bdb0c3d5e7d56cf5ddd794c00213fdb3b83a42d2bdf',
    'eeg_pipeline/mne_asr/__init__.py': 'ffbf4b911b736ca3855690f7ef325d42d4a61207f3fbe82758bc6dfcdd2a9477',
    'eeg_pipeline/mne_asr/api.py': 'a3b09b369ff579409f10de895b38ced491e28bab342caddb907972cf802b708e',
    'eeg_pipeline/mne_asr/_calibrate.py': '25edb8a05162110f86039a73d8b7e4405f34dbe469b1241ab222e913753837ea',
    'eeg_pipeline/mne_asr/_math.py': '6200550b336163f7b9eecd5c3f92fb32cca86c9f641c4122b81cf7d46de6e9dc',
    'eeg_pipeline/mne_asr/_process.py': 'f32c8809b6253e69aaf021e68d137cafb4a1f2399156eecb79e1c8e853d2a601',
    'eeg_pipeline/mne_asr/_reference.py': 'fcda4d5e898b42721784d5860dc6603bdef0b591fd7e7d366e482b0354c63a2f',
    'eeg_pipeline/mne_asr/_signal.py': '1c9dcaa2e853c0bec1e7117a106d16f1d81e312145eb0b391bd907605bc1f10c',
    'eeg_pipeline/mne_asr/_stats.py': '931bd068666e3f4f3ac9c4e52476055ded34c51425eb027151342acf00a89fa2',
    'eeg_pipeline/mne_asr/_yulewalk.py': '58c790dfda61c8b7d409bdf5489ad3bf79564735e2e3b5ae7ca04a183b9267c3',
}


def annotation_v031_manifest():
    files = deepcopy(ANNOTATION_V031_SOURCES)
    digest = compatibility._bundle(files)
    assert digest == '2c490917fc68b6e29156787ba49fdaa3031194f8d26247d1f9dda36bb2d601e3'
    return dict(contract=compatibility.COMPUTATION_CONTRACT, source_files_sha256=files,
                source_bundle_sha256=digest, packages=compatibility.critical_versions())


def packaged_v031_manifest():
    prior = annotation_v031_manifest()
    prior['source_files_sha256']['eeg_pipeline/raw_helpers.py'] = '14abf5e6fc0518d948f236eb3f628e8bbeb5cf631a538a9512a37e0843f34ecd'
    prior['source_bundle_sha256'] = compatibility._bundle(prior['source_files_sha256'])
    assert prior['source_bundle_sha256'] == '2530e65f73803eb58aaa5496946b2227ca9bd6fafed78f4377a39b49b54a5984'
    return prior
