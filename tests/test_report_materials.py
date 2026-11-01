"""Numerical report capture stays independent of the rendering runtime."""
import ast
from pathlib import Path

import numpy as np
import pytest

from eegproc import report_materials as materials
from test_pipeline import fixture


def test_material_module_has_no_rendering_imports():
    tree = ast.parse(Path(materials.__file__).read_text(encoding='utf-8'))
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or '')
    assert not any(name.startswith(('matplotlib', 'PIL', 'quality_figures'))
                   for name in imported)


def test_capture_uses_numeric_options_without_plot_state(monkeypatch):
    import matplotlib as mpl
    import eegproc.quality_figures as figures

    raw = fixture()
    clean = raw.copy()
    clean._data[:12] *= .7
    before = raw.get_data().copy()
    after = clean.get_data().copy()
    annotations = raw.annotations.copy()
    settings = dict(mpl.rcParams)

    def forbidden(*args, **kwargs):
        raise AssertionError('Numerical report capture entered the renderer')

    for name in ('style', 'figure', 'asset', 'rc_context'):
        monkeypatch.setattr(figures, name, forbidden)
    record = {'config': {'highpass': .5, 'report_window_seconds': 2.,
                         'report_waveform_windows': 1, 'report_psd_windows': 3},
              'bad_channels': []}
    with materials.material_options({'outer': True}):
        data = materials.collect_report_materials(record, raw, clean)
        assert materials.PLOT_OPTIONS.get() == {'outer': True}
    assert materials.PLOT_OPTIONS.get() == {}
    assert not data['errors']
    assert len(data['waveforms']['windows']) == 1
    assert data['waveforms']['windows'][0]['width'] == 2 * 256
    assert data['psd']['metadata']['window_count'] == 3
    np.testing.assert_allclose(data['psd']['after'], data['psd']['before'] * .49,
                               rtol=1e-12)
    assert dict(mpl.rcParams) == settings
    np.testing.assert_array_equal(raw.get_data(), before)
    np.testing.assert_array_equal(clean.get_data(), after)
    assert raw.annotations == annotations


def test_failed_image_save_releases_figure(tmp_path):
    from eegproc.quality_figures import asset

    class FailedFigure:
        cleared = False

        def get_size_inches(self):
            return (10., 4.)

        def savefig(self, *args, **kwargs):
            raise RuntimeError('injected image encoding failure')

        def clear(self):
            self.cleared = True

    fig = FailedFigure()
    with pytest.raises(RuntimeError, match='injected image encoding failure'):
        asset(fig, tmp_path, 'test', 'Test', 'Test')
    assert fig.cleared
