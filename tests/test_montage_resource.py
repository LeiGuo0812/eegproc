"""Licensed montage replacement preserves the historical bridge geometry.

The frozen values below were calculated before release from the original
DIPFIT template (SHA-256 02764b11d930639b5c888a186833086aaef4e499dd5fdcaa4e1af493ac8603ea),
not from the replacement resource or its provenance metadata.
"""
import hashlib
from importlib.resources import as_file, files
import json

import mne
import numpy as np

from eegproc.io.bridge import eeg_to_raw


OLD_NATIVE_FIDUCIALS = {
    'nasion': [8.3e-06, 0.08681100000000001, -0.039983],
    'lpa': [-0.0860761, -0.0199897, -0.047986],
    'rpa': [0.08579389999999999, -0.0200093, -0.048031],
}
OLD_TRANSFORM = np.array([
    [0.9999999592211036, -0.0001140396765039576, -0.0002618257878916978, -8.868681781826247e-06],
    [0.00013333690143166392, 0.9971890236660729, 0.07492685300461356, 0.023540426515118406],
    [0.0002525451677202167, -0.07492688486021845, 0.9971889982075022, 0.04637508342080609],
    [0., 0., 0., 1.],
])
OLD_HEAD_FIDUCIALS = {
    'nasion': [-2.3987973066241786e-18, 0.10711160359160668, 0.0],
    'lpa': [-0.08607012158051429, 1.734723475976807e-18, 0.0],
    'rpa': [0.08579988542815489, -2.6020852139652106e-18, -6.938893903907228e-18],
}
OLD_HEAD_POINTS = np.array([
    [-0.020017863036605688, 0.035757455603888905, 0.07553643361507456],
    [-0.03500584753043344, 0.008203290103554138, 0.04250420262180165],
    [0.009979622212463658, 0.079885693245859, 0.06220041016932132],
])


def test_montage_resource_has_exact_upstream_bytes_and_license():
    resource = files('eegproc.resources')
    digest = hashlib.sha256(resource.joinpath('standard_1005.elc').read_bytes()).hexdigest()
    assert digest == '1ee59197946d62de872db2ac7f2243a596662c231427366f6dc5d84ed237f853'
    provenance = json.loads(resource.joinpath('PROVENANCE.json').read_text(encoding='utf-8'))
    assert provenance['sha256'] == digest
    assert provenance['source'] == 'MNE-Python' and provenance['version'] == '1.12.1'
    assert provenance['license'] == 'BSD-3-Clause'
    notice = resource.joinpath('LICENSE-MNE.txt').read_text(encoding='utf-8')
    assert 'MNE-Python authors' in notice and 'Redistribution and use' in notice
    assert 'Neither the name of the copyright holder' in notice


def test_replacement_native_geometry_equals_frozen_legacy_geometry():
    with as_file(files('eegproc.resources').joinpath('standard_1005.elc')) as path:
        montage = mne.channels.read_custom_montage(path, head_size=None)
    positions = montage.get_positions()
    for name, expected in OLD_NATIVE_FIDUCIALS.items():
        np.testing.assert_array_equal(positions[name], expected)
    transform = mne.channels.compute_native_head_t(montage, on_missing='raise')['trans']
    np.testing.assert_array_equal(transform, OLD_TRANSFORM)


def test_actual_eeg_to_raw_preserves_legacy_positions_and_auxiliary_geometry():
    coordinates = [[10., 20., 30.], [-15., 35., -5.], [55., -10., 20.]]
    names = ['F3', 'F4', 'ECG']
    eeg = dict(data=np.arange(36, dtype=float).reshape(3, 12), srate=256., trials=1,
               chanlocs=[dict(labels=name, X=point[0], Y=point[1], Z=point[2],
                              type='ECG' if name == 'ECG' else 'EEG')
                         for name, point in zip(names, coordinates)])
    raw = eeg_to_raw(eeg, position_unit='mm', coordinate_mode='template')
    actual = np.array([channel['loc'][:3] for channel in raw.info['chs']])
    # The frozen expected coordinates exercise axis signs, units and origin.
    np.testing.assert_allclose(actual, OLD_HEAD_POINTS, rtol=0., atol=1e-16)
    assert raw.get_channel_types() == ['eeg', 'eeg', 'ecg']
    np.testing.assert_array_equal(raw.get_data(), eeg['data'] * 1e-6)
    metadata = json.loads(raw.info['description'].split('\n', 1)[1])
    np.testing.assert_array_equal(metadata['template_native_to_head'], OLD_TRANSFORM)
    for name, expected in OLD_HEAD_FIDUCIALS.items():
        np.testing.assert_allclose(metadata['template_fiducials_head'][name], expected,
                                   rtol=0., atol=1e-16)
