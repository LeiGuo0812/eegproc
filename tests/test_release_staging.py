"""The release exporter must never touch records outside its source allowlist."""
import importlib.util
import json
from pathlib import Path

import pytest


_spec = importlib.util.spec_from_file_location(
    'stage_release', Path(__file__).parents[1] / 'scripts/stage_release.py')
release = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(release)


@pytest.fixture
def project(tmp_path):
    source = tmp_path / 'project'
    source.mkdir()
    for name in release.ROOT_FILES:
        (source / name).write_text('source\n', encoding='utf-8')
    (source / 'eeg_pipeline').mkdir()
    (source / 'eeg_pipeline' / '__init__.py').write_text('VALUE = 1\n')
    fixture = source / 'tests/fixtures/staged_v3'
    fixture.mkdir(parents=True)
    (fixture / 'input_raw.fif').write_bytes(b'SYNTHETIC-FIXTURE')
    (fixture / 'fixture_manifest.json').write_text(json.dumps({
        'path': str(source / 'results' / 'synthetic.fif'), 'sha256': 'unchanged',
        'historical': chr(92).join(['C:', 'Users', 'Researcher', 'project', 'results', 'input_raw.fif']),
    }), encoding='utf-8')
    (source / 'results').mkdir()
    (source / 'results' / 'private.bdf').write_bytes(b'PRIVATE-DATA')
    return source


def test_stage_preserves_source_and_omits_results(project):
    target = project / 'release/eeg-pipeline'
    original = (project / 'tests/fixtures/staged_v3/fixture_manifest.json').read_bytes()
    report = release.stage(project, target)
    assert not (target / 'results').exists()
    assert (project / 'results/private.bdf').read_bytes() == b'PRIVATE-DATA'
    assert (target / 'tests/fixtures/staged_v3/input_raw.fif').read_bytes() == b'SYNTHETIC-FIXTURE'
    assert (project / 'tests/fixtures/staged_v3/fixture_manifest.json').read_bytes() == original
    data = json.loads((target / 'tests/fixtures/staged_v3/fixture_manifest.json').read_text())
    assert data['path'] == 'results/synthetic.fif'
    assert data['historical'] == 'results/input_raw.fif'
    assert data['sha256'] == 'unchanged'
    assert report['privacy_scan'] == []


def test_existing_stage_is_archived_inside_project(project):
    target = project / 'release/eeg-pipeline'
    release.stage(project, target)
    (target / 'keep-me.txt').write_text('previous snapshot')
    report = release.stage(project, target)
    archive = (project / report['archive']).resolve()
    assert archive.is_relative_to(project.resolve())
    assert (archive / 'keep-me.txt').read_text() == 'previous snapshot'
    assert not (target / 'keep-me.txt').exists()


def test_unsafe_destination_is_rejected_without_writes(project, tmp_path):
    target = tmp_path / 'outside'
    with pytest.raises(ValueError, match='direct child'):
        release.stage(project, target)
    assert not target.exists()


def test_existing_git_checkout_is_preserved(project):
    target = project / 'release/eegproc'
    release.stage(project, target)
    (target / '.git').mkdir()
    marker = target / '.git/HEAD'
    marker.write_text('ref: refs/heads/main\n')
    with pytest.raises(ValueError, match='Git checkout'):
        release.stage(project, target)
    assert marker.read_text() == 'ref: refs/heads/main\n'
    assert not list(project.glob('_待手动删除_release_*'))


def test_dry_run_creates_no_directories(project):
    report = release.stage(project, project / 'release/eeg-pipeline', dry_run=True)
    assert report['dry_run']
    assert not (project / 'release').exists()


def test_source_symlink_is_rejected(project):
    path = project / 'eeg_pipeline/linked.py'
    try:
        path.symlink_to(project / 'README.md')
    except OSError:
        pytest.skip('This account cannot create symlinks')
    with pytest.raises(ValueError, match='linked'):
        release.stage(project, project / 'release/eeg-pipeline')


def test_historical_document_links_become_labels():
    text = '[Plot](../results/run/plot.html) [History](REFACTOR_VALIDATION.md) '
    text += '<a href="../results/run/report.html">Report</a> '
    text += '[Current](PARAMETERS.html)'
    staged = release.sanitize_document_links(text)
    assert 'results/' not in staged and 'REFACTOR_VALIDATION.md' not in staged
    assert '[Current](PARAMETERS.html)' in staged
    assert staged.count('local research record') == 3
