"""Channel slicing follows MNE annotation scope and preserves input identity."""
from datetime import datetime, timezone

import mne
import numpy as np
import pytest
from mne.utils import object_diff

from eegproc.raw_helpers import raw_slice


@pytest.mark.parametrize('dated', [False, True])
@pytest.mark.parametrize('picks', [[2], [1, 2], None])
def test_scoped_annotations_match_mne_pick_and_crop(dated, picks):
    sfreq = 128.
    values = np.arange(3*2560, dtype=float).reshape(3, 2560)*1e-9
    raw = mne.io.RawArray(values, mne.create_info(['F3','Cz','ECG'], sfreq,
        ['eeg','eeg','ecg']), first_samp=1280, verbose=False)
    if dated:
        raw.set_meas_date(datetime(2020, 1, 2, tzinfo=timezone.utc))
    raw.set_annotations(mne.Annotations(
        onset=[.25, 2., 3., 4., 5.], duration=[.5, .25, .25, .25, .25],
        description=['BAD_global','BAD_F3','BAD_shared','BAD_eeg_only','BAD_ecg'],
        ch_names=[(), ('F3',), ('Cz','ECG'), ('F3','Cz'), ('ECG',)],
        extras=[{'original_index':i,'source':'manual'} for i in range(5)]))
    before_data = raw.get_data()
    before_info = raw.info.copy()
    before_annotations = raw.annotations.copy()
    raw._data.setflags(write=False)
    start, stop = 64, 1536
    sliced = raw_slice(raw, start=start, stop=stop, picks=picks)
    expected = raw.copy().crop(tmin=start/sfreq, tmax=(stop-1)/sfreq)
    if picks is not None:
        expected.pick(picks)

    np.testing.assert_array_equal(sliced.get_data(), expected.get_data())
    assert sliced.first_samp == expected.first_samp == raw.first_samp+start
    assert sliced.n_times == stop-start
    assert sliced.annotations == expected.annotations
    assert sliced.annotations.extras == expected.annotations.extras
    assert list(sliced.annotations.ch_names) == list(expected.annotations.ch_names)
    assert sliced.annotations.orig_time == expected.annotations.orig_time == raw.annotations.orig_time
    assert object_diff(sliced.info, expected.info) == ''

    global_annotation = next(a for a in sliced.annotations if a['description']=='BAD_global')
    assert global_annotation['ch_names'] == ()
    assert global_annotation['onset'] == raw.first_time+start/sfreq
    assert global_annotation['duration'] == .25
    if picks == [2]:
        assert list(sliced.annotations.description) == ['BAD_global','BAD_shared','BAD_ecg']
        assert list(sliced.annotations.ch_names) == [(), ('ECG',), ('ECG',)]
        assert [a['original_index'] for a in sliced.annotations.extras] == [0, 2, 4]
    elif picks == [1, 2]:
        scoped = {a['description']:a['ch_names'] for a in sliced.annotations}
        assert scoped['BAD_shared'] == ('Cz','ECG')
        assert scoped['BAD_eeg_only'] == ('Cz',)
        assert 'BAD_F3' not in scoped

    np.testing.assert_array_equal(raw.get_data(), before_data)
    assert object_diff(raw.info, before_info) == ''
    assert raw.annotations == before_annotations
    assert raw.annotations.extras == before_annotations.extras
    assert list(raw.annotations.ch_names) == list(before_annotations.ch_names)
