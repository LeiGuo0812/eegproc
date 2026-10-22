"""Report presentation can be rebuilt without reading or processing EEG."""
import base64
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path

import pytest

from eeg_pipeline import PipelineResult, render_report, resolve_config
from eeg_pipeline.reporting import _read_html


PNG='iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+j2ioAAAAASUVORK5CYII='
URI='data:image/png;base64,'+PNG


def legacy_report(tmp_path):
    """Build the former standalone format, with alt text but no image keys."""
    data_path=tmp_path/'subject_cont_raw.fif';data_path.write_bytes(b'original recording')
    checkpoint=tmp_path/'checkpoint.json';checkpoint.write_bytes(b'original checkpoint')
    figures=[dict(key=key,title=title,caption=title,bytes=len(base64.b64decode(PNG)),
        sha256=hashlib.sha256(base64.b64decode(PNG)).hexdigest(),width_px=1,height_px=1)
        for key,title in [('waveform_1','Waveform sample'),('ica_topomap_0','IC 0'),('epoch_retention','Epoch retention by condition')]]
    details=[dict(component=0,topomap_key='ica_topomap_0',time_seconds=[0.,.1],activation=[0.,1.],
        frequency_hz=[1.,2.],power_db=[-1.,-2.],spectrum_duration_seconds=20.,
        probabilities=[.01,.01,.94,.01,.01,.01,.01],decision='Excluded',proposal='Exclude')]
    report=dict(status='completed',config=asdict(resolve_config()),workflow_revision='0.2.0',
        outputs=dict(raw=str(data_path),checkpoint=str(checkpoint)),quality_flags=[],
        visualizations=dict(figures=figures,notes=[],errors=[]),
        provenance=dict(subject_label='subject',run_uuid='original-run',software={'source_bundle_sha256':'original'},
            started_utc='2026-10-20T00:00:00+00:00',processing_finished_utc='2026-10-20T00:01:00+00:00'),
        metadata_audit={'checks':{'annotations':True,'channel_names':True}},
        qc_annotations=[dict(onset=.2,duration=.1,description='BAD_manual')],
        execution=[dict(stage='save_continuous',status='completed')],
        ica=dict(probabilities=[details[0]['probabilities']],removed_components_0based=[0],
            automatic_proposal_0based=[0],decision_status='automatic'),
        ica_checkpoint=dict(checkpoint_id='immutable-id',model_sha256='immutable-model'),
        event_id={'target':1},epochs=dict(input_events=10,retained_epochs=8,
            condition_retention={'1':dict(input=10,eligible=9,retained=8)}))
    payload={'components':details,'classes':['Brain','Muscle','Eye','Heart','Line noise','Channel noise','Other']}
    document='<html><body>'+''.join(f'<img src="{URI}" alt="{alt}">' for alt in
        ('Waveform sample','IC 0 topography','Epoch retention by condition'))
    document+='<script id="run-record" type="application/json">'+json.dumps(report)+'</script>'
    document+='<script id="component-data" type="application/json">'+json.dumps(payload)+'</script></body></html>'
    source=tmp_path/'subject_report.html';source.write_text(document,encoding='utf8')
    return source,report,details


@pytest.fixture
def prohibit_processing(monkeypatch):
    import mne
    import eeg_pipeline.engine as engine
    import eeg_pipeline.review as review
    import eeg_pipeline.ica as ica
    import eeg_pipeline.quality_figures as figures
    def forbidden(*args,**kwargs):raise AssertionError('Report-only rendering must reuse recorded plots')
    for module,name in [(engine,'preprocess_raw'),(review,'resume_ica'),(ica,'fit_ica'),(ica,'apply_ica'),
            (figures,'build_signal_figures'),(figures,'retention_figure'),
            (mne.io,'read_raw_fif'),(mne.preprocessing,'read_ica')]:
        monkeypatch.setattr(module,name,forbidden)


def test_legacy_html_rebuild_reuses_images_diagnostics_and_current_layout(tmp_path,monkeypatch,prohibit_processing):
    import eeg_pipeline.quality_report as reporting
    source,old,details=legacy_report(tmp_path)
    originals={path:path.read_bytes() for path in tmp_path.iterdir()}
    monkeypatch.setattr(reporting,'CSS',reporting.CSS+'\n/* current-layout-marker */')
    target=render_report(source,tmp_path/'updated_report.html')
    assert target==tmp_path/'updated_report.html'
    document=target.read_text(encoding='utf8')
    assert 'current-layout-marker' in document
    rebuilt=_read_html(target)
    old=json.loads(json.dumps(old))
    for key in ('config','ica','ica_checkpoint','qc_annotations','metadata_audit','provenance','epochs'):
        assert rebuilt[key]==old[key]
    assert rebuilt['ica_diagnostics']==details
    assert all(figure['data_uri']==URI for figure in rebuilt['visualizations']['figures'])
    assert rebuilt['report_generation']['signal_processing_repeated'] is False
    assert rebuilt['report_generation']['waveform_redrawn'] is False
    assert rebuilt['report_generation']['source_report_sha256']==hashlib.sha256(originals[source]).hexdigest()
    for path,before in originals.items():assert path.read_bytes()==before
    assert len(list(tmp_path.iterdir()))==len(originals)+1


def test_pipeline_result_rebuild_does_not_mutate_source_or_access_raw(tmp_path,prohibit_processing):
    source,_,_=legacy_report(tmp_path)
    report=_read_html(source)
    snapshot=deepcopy(report)
    result=PipelineResult(object(),report,{})
    target=render_report(result,tmp_path/'from_result.html')
    assert result.report==snapshot
    rebuilt=_read_html(target)
    assert rebuilt['ica']['removed_components_0based']==[0]
    assert rebuilt['ica_diagnostics']==snapshot['ica_diagnostics']
    assert rebuilt['provenance']==snapshot['provenance']
    assert 'Exclude this component' in target.read_text(encoding='utf8')


def test_explicit_image_keys_work_when_alt_text_changes(tmp_path,prohibit_processing):
    source,_,_=legacy_report(tmp_path)
    text=source.read_text(encoding='utf8')
    for alt,key in [('Waveform sample','waveform_1'),('IC 0 topography','ica_topomap_0'),('Epoch retention by condition','epoch_retention')]:
        text=text.replace(f'alt="{alt}"',f'alt="new display text" data-figure-key="{key}"')
    source.write_text(text,encoding='utf8')
    assert render_report(source,tmp_path/'with_keys.html').is_file()


@pytest.mark.parametrize('kind',['no-record','no-images','bad-image','missing-ic-diagnostics'])
def test_unusable_source_fails_before_creating_output(tmp_path,kind):
    source,_,_=legacy_report(tmp_path)
    document=source.read_text(encoding='utf8')
    if kind=='no-record':document='<html>No machine record</html>'
    elif kind=='no-images':document=document.replace('data:image/png;base64,','not-an-image:')
    elif kind=='bad-image':document=document.replace(PNG,'aW52YWxpZA==')
    elif kind=='missing-ic-diagnostics':
        document=document.replace('"components": [{','"unavailable_components": [{')
    source.write_text(document,encoding='utf8')
    target=tmp_path/'unusable.html'
    with pytest.raises(ValueError):render_report(source,target)
    assert not target.exists()


def test_existing_report_is_never_overwritten(tmp_path):
    source,_,_=legacy_report(tmp_path);original=source.read_bytes()
    with pytest.raises(FileExistsError):render_report(source,source)
    assert source.read_bytes()==original


def test_existing_project_report_rebuild_without_processing(tmp_path,prohibit_processing):
    source=Path(__file__).parents[1]/'results/eeg_pipeline/rest/rest_report.html'
    if not source.is_file():pytest.skip('Historical project report is not distributed with the package')
    before=source.read_bytes()
    original=_read_html(source)
    target=render_report(source,tmp_path/'rest_report.html')
    rebuilt=_read_html(target)
    for key in ('ica','ica_checkpoint','config','metadata_audit','provenance','epochs'):
        assert rebuilt.get(key)==original.get(key)
    assert [figure['sha256'] for figure in rebuilt['visualizations']['figures']]==[
        figure['sha256'] for figure in original['visualizations']['figures']]
    assert rebuilt['ica_diagnostics']==original['ica_diagnostics']
    assert source.read_bytes()==before
