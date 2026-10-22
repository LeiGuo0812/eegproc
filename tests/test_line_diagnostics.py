"""Direct stage spectra must retain common-mode line power and paired samples."""
from datetime import datetime, timezone
import json
import mne
import numpy as np
import pytest

from eeg_pipeline import resolve_config
from eeg_pipeline.backends import clean_line
from eeg_pipeline.line_diagnostics import capture_line_input, finish_line_diagnostics
from eeg_pipeline.quality_figures import line_noise_figure, waveform_figures, style
from test_pipeline import fixture


@pytest.mark.parametrize('frequency,method',[(50.,'spectrum_fit'),(60.,'spectrum_fit'),(50.,'notch')])
def test_actual_line_cleaning_with_paired_reference_windows_and_harmonics(frequency,method,tmp_path):
    sf=256.;n=32*256;t=np.arange(n)/sf;rng=np.random.default_rng(31)
    common=12e-6*np.sin(2*np.pi*frequency*t)
    if frequency==50:common+=5e-6*np.sin(2*np.pi*100*t)
    data=common[None,:]+np.array([3e-6*np.sin(2*np.pi*(8+i)*t+i) for i in range(8)])
    data+=rng.normal(0,1e-7,(8,n))
    raw=mne.io.RawArray(data,mne.create_info([f'E{i}' for i in range(8)],sf,'eeg'),
        first_samp=4096,verbose=False)
    raw.set_meas_date(datetime(2020,1,1,tzinfo=timezone.utc))
    raw.set_annotations(mne.Annotations([8],[2],['BAD_manual']))
    raw.info['bads']=['E1']
    cfg=resolve_config(line_frequency=frequency,line_method=method,report_psd_windows=3)
    before=raw.get_data().copy();annotations=raw.annotations.copy()
    state=capture_line_input(raw,cfg)
    np.testing.assert_array_equal(before,raw.get_data())
    assert state['window_count']==3 and state['window_seconds']==4.
    assert 'E1' not in state['channels']
    assert all(start+state['window_samples']<=8*sf or start>=10*sf for start in state['starts_samples'])
    processed=clean_line(raw,cfg)
    after=raw.get_data().copy()
    report=finish_line_diagnostics(raw,state)
    np.testing.assert_array_equal(after,raw.get_data())
    assert raw.annotations==annotations
    assert report['status']=='available'
    assert report['targets_hz']==processed['frequencies_hz']==([50.,100.] if frequency==50 else [60.])
    assert report['frequency_resolution_hz']==.25
    assert report['metrics'][0]['before_median_power_uv2']>60  # shared line noise was not cancelled by CAR
    assert all(m['median_reduction_db']>15 for m in report['metrics'])
    assert not any(k.startswith('_') for k in report)
    json.dumps(report,allow_nan=False)
    with style():fig=line_noise_figure({'line_diagnostics':report},tmp_path)
    assert fig['key']=='line_noise' and fig['data_uri'].startswith('data:image/png;base64,')
    assert not list(tmp_path.iterdir())


def test_no_change_has_zero_reduction_and_no_safe_windows_are_explicit():
    raw=fixture().pick('eeg')
    cfg=resolve_config()
    state=capture_line_input(raw,cfg)
    report=finish_line_diagnostics(raw,state)
    assert all(row['median_reduction_db']==0 for row in report['metrics'])
    raw.annotations.append(raw.first_time,raw.times[-1]+1/raw.info['sfreq'],'BAD_all')
    state=capture_line_input(raw,cfg)
    assert state['status']=='unavailable' and 'window_count' not in state
    assert finish_line_diagnostics(raw,state)==state
    for settings in [dict(line_method='off'),dict(line_frequency=None)]:
        state=capture_line_input(raw,resolve_config(**settings))
        assert state['status']=='disabled'
        assert line_noise_figure({'line_diagnostics':state},None) is None
    state=capture_line_input(fixture(),resolve_config(line_frequency=200.))
    assert state['status']=='not_applied'


@pytest.mark.parametrize('seconds',[4.,2.])
def test_waveform_window_default_and_override_preserve_samples(seconds,tmp_path):
    raw=fixture();clean=raw.copy();before=raw.get_data().copy()
    assert resolve_config().report_window_seconds==4.
    with style({'report_window_seconds':seconds}):
        _,windows=waveform_figures(raw,clean,raw.ch_names[:12],[],tmp_path)
    assert all(row['stop_sample']-row['start_sample']==round(seconds*256) for row in windows)
    np.testing.assert_array_equal(raw.get_data(),before)
    np.testing.assert_array_equal(clean.get_data(),before)
