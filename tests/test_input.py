"""Input conversion must preserve voltage, event timing and head geometry."""
import mne
import numpy as np
from mne_bridge import eeg_to_raw, export_mne_fif


def test_mne_input_units_geometry_and_saved_events(tmp_path):
    data = np.arange(4 * 2048, dtype=float).reshape(4, -1) * .001
    eeg = dict(data=data, srate=256., trials=1, ref='averef',
        chaninfo={'nosedir': '+X'},
        chanlocs=[{'labels':'Fp1','type':'EEG','X':83.9171,'Y':29.4367,'Z':-6.99},
                  {'labels':'Fp2','type':'EEG','X':84.8959,'Y':-29.8723,'Z':-7.08},
                  {'labels':'Cz','type':'EEG','X':0,'Y':0,'Z':95},
                  {'labels':'EOG','type':'EOG'}],
        event=[{'type':1,'latency':257.,'duration':32.},
               {'type':'stimulus','latency':769.,'duration':0.}])
    raw = eeg_to_raw(eeg)
    np.testing.assert_array_equal(raw.get_data(), data * 1e-6)
    assert raw.get_channel_types() == ['eeg', 'eeg', 'eeg', 'eog']
    assert raw.info['custom_ref_applied']
    geometry = raw.get_montage().get_positions()
    assert abs(geometry['nasion'][0]) < 1e-12
    assert abs(geometry['nasion'][2]) < 1e-12
    assert geometry['nasion'][1] > 0
    assert geometry['lpa'][0] < 0 < geometry['rpa'][0]
    path = export_mne_fif(eeg, tmp_path / 'input_raw.fif', highpass=.5, lowpass=100.)
    reread = mne.io.read_raw_fif(path, preload=True, verbose=False)
    np.testing.assert_array_equal(reread.get_data(), raw.get_data())
    events, ids = mne.events_from_annotations(reread, verbose=False)
    np.testing.assert_array_equal(events[:, 0], [256, 768])
    assert set(ids) == {'1', 'stimulus'}
    assert reread.info['highpass'] == .5 and reread.info['lowpass'] == 100.
