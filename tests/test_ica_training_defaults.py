"""ICA input-band defaults are shared across presets and decision modes."""
import sys
from types import SimpleNamespace

import numpy as np
import pytest

from eegproc import resolve_config
from eegproc.backends import detect_channels, alignment_notes
from eegproc.runtime_parameters import resolve_for_raw
from test_pipeline import fixture


@pytest.mark.parametrize('preset', ['standard', 'eeglab'])
@pytest.mark.parametrize('purpose', ['rest', 'erp'])
@pytest.mark.parametrize('mode', ['auto', 'manual', 'review'])
def test_default_training_band_is_1_100_for_every_preset_purpose_and_decision_mode(preset, purpose, mode):
    config = resolve_config(preset=preset, purpose=purpose, ica_mode=mode)
    assert (config.training_highpass, config.training_lowpass) == (1., 100.)
    expected_analysis = (.5, 100.) if preset == 'eeglab' else ((.5, 80.) if purpose == 'rest' else (.1, 30.))
    assert (config.highpass, config.lowpass) == expected_analysis


@pytest.mark.parametrize('preset', ['standard', 'eeglab'])
def test_valid_explicit_training_band_still_overrides_preset(preset):
    config = resolve_config(preset=preset, training_highpass=.5, training_lowpass=90.)
    assert (config.training_highpass, config.training_lowpass) == (.5, 90.)
    assert not any(row['field'].startswith('training_') for row in config.adjustments)


@pytest.mark.parametrize('preset', ['standard', 'eeglab'])
def test_input_band_limits_remain_truthful_and_do_not_stop_processing(preset):
    raw = fixture()
    with raw.info._unlock():
        raw.info['highpass'] = 2.
        raw.info['lowpass'] = 45.
    config, audit = resolve_for_raw(resolve_config(preset=preset), raw)
    assert (config.training_highpass, config.training_lowpass) == (2., 45.)
    assert any('rather than 1' in note for note in audit['review_notes'])


def test_eeglab_channel_detection_receives_new_training_band_without_mutating_input(monkeypatch):
    import eegproc.backends as backends

    raw = fixture().pick('eeg')
    before = raw.get_data().copy()
    config = resolve_config(preset='eeglab')
    calls = []

    def capture_filter(detection, low, high, supplied):
        assert detection is not raw
        assert supplied is config
        calls.append((low, high))
        return detection

    monkeypatch.setattr(backends, 'apply_filter', capture_filter)
    monkeypatch.setitem(sys.modules, 'eegprep', SimpleNamespace(
        eeg_emptyset=lambda: {},
        clean_flatlines=lambda eeg, **kwargs: eeg,
        clean_channels=lambda eeg, **kwargs: eeg))
    bads, _ = detect_channels(raw, config)
    assert calls == [(1., 100.)]
    assert bads == []
    np.testing.assert_array_equal(raw.get_data(), before)


@pytest.mark.parametrize('method,band,expected', [
    ('mne_fir', (1., 100.), [1., 100.]),
    ('mne_fir', (2., 45.), [2., 45.]),
    ('off', (1., 100.), [0., 128.]),
])
def test_detection_band_report_describes_actual_filtered_copy(monkeypatch, method, band, expected):
    raw = fixture().pick('eeg')
    before = raw.get_data().copy()
    config = resolve_config(preset='eeglab', filter_method=method,
                            training_highpass=band[0], training_lowpass=band[1])
    monkeypatch.setitem(sys.modules, 'eegprep', SimpleNamespace(
        eeg_emptyset=lambda: {},
        clean_flatlines=lambda eeg, **kwargs: eeg,
        clean_channels=lambda eeg, **kwargs: eeg))
    _, report = detect_channels(raw, config)
    assert report['detection_band_hz'] == expected
    assert report['on_1_100_hz_copy'] == (expected == [1., 100.])
    np.testing.assert_array_equal(raw.get_data(), before)


def test_eeglab_alignment_note_preserves_explicit_band_and_original_script_difference():
    notes = alignment_notes(resolve_config(preset='eeglab', training_highpass=.5, training_lowpass=90.))
    assert any('configured 0.5–90 Hz' in note and 'original script used a 0.5 Hz' in note for note in notes)
    assert alignment_notes(resolve_config()) == []
