"""Create a compact, reviewed source snapshot without deleting project records.

Only the allowlist below is copied. Existing snapshots are moved to an archive
inside the source project. No source package, numerical fixture or old result is
changed. This script uses only the Python standard library.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil


ROOT_FILES = (
    '.gitignore', 'README.md', 'pyproject.toml', 'MANIFEST.in',
    'erp_outputs.py', 'mne_bridge.py', 'neuracle_io.py', 'prepare_data.py',
    'preprocess.py', 'project_layout.py',
)
OPTIONAL_ROOT_FILES = ('LICENSE', 'LICENSE.md', 'NOTICE', 'NOTICE.md', 'README.zh-CN.md', 'CHANGELOG.md', '.gitattributes')
PATTERNS = (
    'requirements*.txt', 'constraints*.txt', 'constraints/*.txt',
    'eegproc/**/*.py', 'eeg_pipeline/**/*.py', 'mne_asr/*.py',
    'eegproc/RELEASE_STATUS.md', 'eegproc/resources/*.elc',
    'eegproc/resources/LICENSE-MNE.txt', 'eegproc/resources/PROVENANCE.json',
    'eegproc/mne_asr/LICENSE', 'eegproc/mne_asr/PROVENANCE.json',
    'eegproc/mne_asr/README.md', 'configs/*.json', 'examples/*.py',
    'docs/en/*.md', 'docs/zh-CN/*.md',
    'docs/assets/*.png', 'docs/assets/*.md',
    'tests/*.py', '.github/workflows/*.yml', '.github/workflows/*.yaml',
)
DOCS = (
    'ARCHITECTURE.md', 'ARCHITECTURE.html', 'PARAMETERS.md', 'PARAMETERS.html',
    'INSTALLATION.md', 'RELEASE_AUDIT.md', 'THIRD_PARTY_NOTICES.md',
)
SCRIPTS = (
    'stage_release.py', 'validate_pipeline.py', 'validate_report_browser.py',
    'validate_install.py', 'validate_parameter_resolution.py',
    'validate_release.py', 'smoke_installed.py', 'validate_clean_install.py',
    'offline_build.py', 'generate_parameter_reference.py',
)
FIXTURE_FILES = (
    'input_raw.fif', 'p16_rest_cont_raw.fif', 'p16_erp_cont_raw.fif',
    'fixture_manifest.json', 'p16_rest_manifest.json', 'p16_erp_manifest.json',
    'original_validation_summary.json', 'README.md',
)
IGNORED_PARTS = {'__pycache__', '.pytest_cache', '.git', '.venv'}
PERSONAL_PATH = re.compile(r'(?:[A-Za-z]:[/\\]+Users[/\\]+|/(?:Users|home)/)[^\s"<>]+', re.I)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _within(path: Path, parent: Path) -> bool:
    return path != parent and path.is_relative_to(parent)


def _linked_directory(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path, 'is_junction', lambda: False)())


def selected_files(source: Path) -> list[Path]:
    chosen: set[Path] = set()
    for name in ROOT_FILES:
        path = source / name
        if not path.is_file():
            raise FileNotFoundError(f'Required release source is missing: {name}')
        chosen.add(path)
    for name in OPTIONAL_ROOT_FILES:
        if (source / name).is_file():
            chosen.add(source / name)
    for pattern in PATTERNS:
        chosen.update(path for path in source.glob(pattern) if path.is_file())
    for parent, names in (('docs', DOCS), ('scripts', SCRIPTS),
                          ('tests/fixtures/staged_v3', FIXTURE_FILES)):
        chosen.update(source / parent / name for name in names
                      if (source / parent / name).is_file())
    result = []
    for path in sorted(chosen):
        if any(part in IGNORED_PARTS for part in path.relative_to(source).parts):
            continue
        if path.is_symlink() or not _within(path.resolve(), source):
            raise ValueError(f'Refusing linked or external source file: {path}')
        result.append(path)
    return result


def sanitize_fixture(value, source: Path):
    """Remove machine-specific prefixes, retaining semantic keys and file names."""
    if isinstance(value, dict):
        return {key: sanitize_fixture(item, source) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize_fixture(item, source) for item in value]
    if not isinstance(value, str):
        return value
    normalized = value.replace('\\', '/')
    source_prefix = source.as_posix().rstrip('/') + '/'
    # The historical source may have moved since the records were generated.
    if normalized.casefold().startswith(source_prefix.casefold()):
        return normalized[len(source_prefix):]
    marker = '/' + source.name + '/'
    if PERSONAL_PATH.search(value) and marker in normalized:
        return normalized.split(marker, 1)[1]
    if PERSONAL_PATH.search(value):
        return 'historical/' + normalized.rsplit('/', 1)[-1]
    return value


def render_fixture_readme() -> str:
    return '''# Synthetic numerical regression fixtures

These fixed 40-second recordings contain 12 EEG channels, EOG/STIM, 256 Hz,
two events and a synthetic BAD annotation. They contain no participant data.

* `input_raw.fif`: synthetic input.
* `p16_rest_cont_raw.fif`: historical resting-state reference.
* `p16_erp_cont_raw.fif`: historical ERP reference (ASR disabled in that reference).
* JSON manifests: historical parameter/provenance records. Machine-specific
  path prefixes were removed for this source snapshot; numerical values and
  recorded data hashes were preserved. These are historical software checks,
  not physiological ground truth or current-default outputs.

The three FIF files are copied byte-for-byte. `RELEASE_MANIFEST.json` records
both source and staged hashes, including every sanitized metadata file.
Run `python scripts/validate_pipeline.py --output outputs/validation` with the
documented optional dependencies to regenerate a current comparison.
'''


def sanitize_document_links(text: str) -> str:
    """Keep history labels without publishing links to excluded local evidence."""
    excluded = r'(?:\.\./)?results/[^\s\)"<>]+|(?:\.\./docs/)?REFACTOR_VALIDATION\.(?:md|html)'
    text = re.sub(r'\[([^\]]+)\]\((' + excluded + r')\)',
                  r'\1 (local research record; excluded from this source snapshot)', text)
    return re.sub(r'<a href="(' + excluded + r')">(.*?)</a>',
                  r'\2 (local research record; excluded from this source snapshot)',
                  text, flags=re.DOTALL)


def stage(source: Path, destination: Path, *, dry_run: bool = False) -> dict:
    source = source.expanduser().resolve()
    release_root = source / 'release'
    if _linked_directory(release_root) or _linked_directory(destination.expanduser()):
        raise ValueError('Release directories must not be symbolic links or junctions.')
    destination = destination.expanduser().resolve()
    if not _within(destination, release_root) or destination.parent != release_root:
        raise ValueError('Destination must be one direct child of SOURCE/release/.')
    files = selected_files(source)
    plan = {'schema_version': 1, 'files': len(files),
            'source_bytes': sum(path.stat().st_size for path in files),
            'destination': destination.relative_to(source).as_posix(),
            'dry_run': dry_run,
            'excluded': ['results/', '.work/', 'build/', 'dist/', '*.egg-info/',
                         'caches', 'real recordings', 'historical reports',
                         'obsolete CleanLine license (no CleanLine code bundled)']}
    if dry_run:
        plan['paths'] = [path.relative_to(source).as_posix() for path in files]
        return plan
    archive = None
    if destination.exists():
        if not destination.is_dir():
            raise ValueError('Existing staging destination is not a directory.')
        if (destination / '.git').exists():
            raise ValueError('Destination is a Git checkout; use a new release destination to preserve its history.')
        stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        archive_root = source / ('_待手动删除_release_' + stamp)
        if _linked_directory(archive_root) or not _within(archive_root.resolve(), source):
            raise ValueError('Invalid in-project archive directory.')
        archive_root.mkdir()
        archive = archive_root / destination.name
        if not _within(destination.resolve(), source) or not _within(archive.resolve(), source):
            raise ValueError('Source and archive must remain inside the project.')
        destination.rename(archive)
    destination.mkdir(parents=True, exist_ok=False)
    records = []
    for path in files:
        relative = path.relative_to(source)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        transform = None
        if relative.parent.as_posix() == 'tests/fixtures/staged_v3' and path.suffix == '.json':
            value = sanitize_fixture(json.loads(path.read_text(encoding='utf-8')), source)
            if path.name == 'fixture_manifest.json' and isinstance(value, dict):
                value['release_snapshot_note'] = (
                    'Existing file hashes describe the original historical fixture files. '
                    'FIF bytes are unchanged; JSON path prefixes were sanitized. '
                    'Use RELEASE_MANIFEST.json at the source root for staged-file hashes.')
            target.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
            transform = 'Historical fixture metadata: removed machine-specific path prefixes.'
        elif relative.as_posix() == 'tests/fixtures/staged_v3/README.md':
            target.write_text(render_fixture_readme(), encoding='utf-8')
            transform = 'Release fixture documentation; historical metadata sanitization disclosed.'
        elif relative.parts[0] == 'docs' and path.suffix in {'.md', '.html'}:
            original = path.read_text(encoding='utf-8')
            cleaned = sanitize_document_links(original)
            if cleaned != original:
                target.write_text(cleaned, encoding='utf-8')
                transform = 'Removed links to historical local evidence excluded from the release allowlist.'
            else:
                shutil.copy2(path, target)
        else:
            shutil.copy2(path, target)
        source_hash, target_hash = sha256(path), sha256(target)
        if transform is None and source_hash != target_hash:
            raise RuntimeError(f'Source changed while staging: {relative.as_posix()}')
        records.append({'path': relative.as_posix(), 'bytes': target.stat().st_size,
                        'source_sha256': source_hash, 'sha256': target_hash,
                        'transformation': transform})
    findings = []
    for record in records:
        path = destination / record['path']
        if path.suffix.lower() not in {'.py', '.md', '.html', '.json', '.txt', '.yml', '.yaml', '.toml', '.in'}:
            continue
        text = path.read_text(encoding='utf-8')
        if PERSONAL_PATH.search(text):
            findings.append({'path': record['path'], 'issue': 'Personal absolute path remains'})
        if 'data:image/' in text and len(text) > 2_000_000:
            findings.append({'path': record['path'], 'issue': 'Large embedded image document'})
    manifest = dict(plan, created_utc=datetime.now(timezone.utc).isoformat(),
                    staged_bytes=sum(row['bytes'] for row in records),
                    artifacts=records, privacy_scan=findings,
                    archive=archive.relative_to(source).as_posix() if archive else None,
                    readiness='Technical source snapshot; see docs/RELEASE_AUDIT.md for release gates.')
    (destination / 'RELEASE_MANIFEST.json').write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    if findings:
        raise ValueError('Staging privacy scan found unresolved items; inspect RELEASE_MANIFEST.json.')
    return {key: value for key, value in manifest.items() if key != 'artifacts'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--destination', type=Path, help='Direct child of SOURCE/release/; default: release/eegproc')
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args(argv)
    source = args.source.expanduser().resolve()
    destination = args.destination or source / 'release' / 'eegproc'
    print(json.dumps(stage(source, destination, dry_run=args.dry_run), indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
