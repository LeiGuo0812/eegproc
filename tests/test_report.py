"""Unified workflow, compact output and single-file report contracts."""
import json
import re
from pathlib import Path
import numpy as np
import pytest
from eeg_pipeline.configuration import resolve_config
from eeg_pipeline.api import run
from test_pipeline import fixture
from report_helpers import read_report


@pytest.mark.parametrize('preset',['standard','eeglab'])
def test_presets_keep_stage_order_and_qc(preset):
    c=resolve_config(preset=preset)
    assert c.filter_position=='after_reference'
    assert not c.interpolate_before_asr
    assert c.final_interpolation and c.final_reference and c.residual_qc and c.exclude_gross_from_training
    resolved=resolve_config(preset=preset,filter_position='before_line')
    assert resolved.filter_position=='after_reference'
    assert any(r['field']=='filter_position' and r['requested']=='before_line' and
               r['effective']=='after_reference' for r in resolved.adjustments)


@pytest.mark.parametrize('key',['save_stages','stage_output','export_audit_files','save_ica_training','report_embed_images','report_level'])
def test_retired_output_options_are_ignored_and_audited(key):
    config=resolve_config(**{key:True})
    assert not hasattr(config,key)
    assert any(r['field']==key and r['requested'] is True and r['effective'] is None
               for r in config.adjustments)


def test_one_html_has_all_decisions_and_no_default_sidecars(tmp_path,monkeypatch):
    import mne_icalabel.iclabel as labels
    def known(training,model,inplace=True):
        p=np.zeros((model.n_components_,7));p[:,0]=1.;p[0]=[.01,.01,.94,.01,.01,.01,.01];return p
    monkeypatch.setattr(labels,'iclabel_label_components',known)
    cfg=resolve_config(asr_cutoff=None,line_frequency=None,channel_method='off',epoch_mode='events')
    result=run(fixture(),tmp_path,'sample',config=cfg)
    html=Path(result.outputs['quality_report']).read_text(encoding='utf8')
    payload=json.loads(re.search(r'<script id="component-data" type="application/json">(.*?)</script>',html,re.S).group(1))
    assert len(payload['components'])==result.report['ica']['rank']
    assert payload['components'][0]['decision']=='Excluded'
    assert all(c['decision']=='Retained' for c in payload['components'][1:])
    assert 'class="ic-name excluded">IC 0' in html
    assert 'Epoch decisions' in html and 'BAD_manual' in html and 'Effective parameters' in html
    assert '<html lang="en">' in html and 'Component probabilities and decisions' in html
    assert 'data:image/png;base64,' in html
    assert not (tmp_path/'sample_quality_assets').exists()
    assert not list(tmp_path.rglob('*.tsv')) and not list(tmp_path.rglob('*.md'))
    assert not (tmp_path/'sample_epoch_qc.json').exists()
    assert len(list(tmp_path.rglob('*fif')))==5  # final data/model/epochs + pre-ICA/model
    assert len(list(p for p in tmp_path.rglob('*') if p.is_file()))==7
    assert not list(tmp_path.rglob('original_raw.fif'))
    assert not list(tmp_path.rglob('preview_raw.fif'))
    assert not list(tmp_path.rglob('container_raw.fif'))
    assert result.report['report_storage']['total_bytes']<2*1024**2
    assert not result.report['visualizations']['errors']
    saved=read_report(html)
    assert saved['report_storage']==result.report['report_storage']
    assert saved['report_storage']['html_bytes']==Path(result.outputs['quality_report']).stat().st_size
    assert saved['config']['preset']=='standard' and saved['config']['ica_rule']=='threshold'
    assert list(tmp_path.rglob('*.json'))==[Path(result.outputs['checkpoint'])]
    assert payload['selection']['exclude']==[0]  # completed automatic results remain editable


def test_all_rejected_run_uses_fresh_output_and_preserves_existing_epochs(tmp_path):
    raw=fixture()
    raw.annotations.append(raw.first_time,raw.times[-1],'BAD_manual_all')
    stale=tmp_path/'sample_clean-epo.fif'
    stale.write_bytes(b'previous successful export')
    cfg=resolve_config(asr_cutoff=None,line_frequency=None,channel_method='off',
                       ica_enabled=False,epoch_mode='events',residual_qc=False)
    with pytest.raises(FileExistsError,match='Output already exists'):
        run(raw,tmp_path,'sample',config=cfg)
    assert stale.read_bytes()==b'previous successful export'
    result=run(raw,tmp_path/'fresh','sample',config=cfg)
    assert result.report['epochs']['retained_epochs']==0
    assert 'epochs' not in result.outputs
    assert not (tmp_path/'fresh'/'sample_clean-epo.fif').exists()
    assert stale.read_bytes()==b'previous successful export'
