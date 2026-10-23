"""Build and inspect local artifacts using already installed build tools.

This command does not install dependencies, create an environment or contact
an index. Use a clean staged source tree. Build scratch files stay in the new
output directory; the source tree remains untouched.
"""
from __future__ import annotations

import argparse
from email.parser import Parser
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def inspect_artifacts(wheel, sdist):
    forbidden = {'results', '.work', '__pycache__', 'test_data', 'test data'}
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        assert not any(forbidden.intersection(Path(name).parts) for name in names)
        assert 'eegproc/resources/standard_1005.elc' in names
        assert 'eegproc/mne_asr/LICENSE' in names
        assert 'eegproc/mne_asr/PROVENANCE.json' in names
        assert 'eegproc/resources/LICENSE-MNE.txt' in names
        assert 'eegproc/resources/PROVENANCE.json' in names
        assert not any(Path(name).parts[0] in {'eeg_pipeline', 'mne_asr'} for name in names)
        for name in ('eegproc/prepare_cli.py', 'eegproc/io/neuracle.py', 'eegproc/cli.py'):
            assert name in names, name
        metadata_name = next(name for name in names if name.endswith('.dist-info/METADATA'))
        metadata = Parser().parsestr(archive.read(metadata_name).decode('utf-8'))
        entry_name = next(name for name in names if name.endswith('.dist-info/entry_points.txt'))
        entry_points = archive.read(entry_name).decode('utf-8')
        assert 'eegproc = eegproc.cli:main' in entry_points
        assert 'eegproc-prepare = eegproc.prepare_cli:main' in entry_points
        assert 'License :: OSI Approved :: BSD License' in metadata.get_all('Classifier', [])
        project_license = [name for name in names
                           if '.dist-info/' in name and name.endswith('/LICENSE')]
        assert len(project_license) == 1, project_license
        assert b'BSD 3-Clause License' in archive.read(project_license[0])
        assert b'BSD 2-Clause License' in archive.read('eegproc/mne_asr/LICENSE')
        assert metadata['Name'] == 'eegproc'
    with tarfile.open(sdist) as archive:
        members = archive.getmembers()
        assert all(member.isfile() or member.isdir() for member in members)
        relative = ['/'.join(Path(member.name).parts[1:]) for member in members]
        assert not any(forbidden.intersection(Path(name).parts) for name in relative)
        for required in ('pyproject.toml', 'requirements.txt', 'requirements-all.txt',
                         'README.md', 'README.zh-CN.md', 'LICENSE', 'NOTICE',
                         'docs/en/usage.md', 'docs/zh-CN/usage.md',
                         'docs/en/workflow.md', 'docs/zh-CN/workflow.md',
                         'docs/THIRD_PARTY_NOTICES.md'):
            assert required in relative, required
        assert not any(name.endswith('.fif') for name in relative)
    return {'name': metadata['Name'], 'version': metadata['Version'],
            'requires_python': metadata['Requires-Python'],
            'requires_dist': metadata.get_all('Requires-Dist', []),
            'extras': metadata.get_all('Provides-Extra', []),
            'entry_points': entry_points, 'wheel_files': len(names),
            'sdist_files': sum(member.isfile() for member in members),
            'bsd_license_marker': True}


def build(source, output):
    source, output = Path(source).resolve(), Path(output).resolve()
    if not (source / 'pyproject.toml').is_file():
        raise ValueError('Source must contain pyproject.toml.')
    if output.exists():
        raise ValueError('Output must be a new directory; previous evidence is preserved.')
    if output == source or output.is_relative_to(source):
        raise ValueError('Build output must be outside the source tree.')
    # Fail before creating files if offline tools are unavailable.
    versions = {name: importlib.metadata.version(name) for name in ('setuptools', 'wheel')}
    inputs = {path.relative_to(source).as_posix(): sha256(path)
              for path in source.rglob('*') if path.is_file() and not set(path.relative_to(source).parts).intersection({'.git', '__pycache__', '.pytest_cache'})}
    output.mkdir(parents=True)
    scratch = output / 'source'
    shutil.copytree(source, scratch, ignore=shutil.ignore_patterns('.git', '__pycache__', '.pytest_cache'))
    dist = output / 'dist'
    dist.mkdir()
    environment = dict(os.environ, PIP_NO_INDEX='1', PIP_DISABLE_PIP_VERSION_CHECK='1',
                       PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1')

    def backend(cwd, method):
        command = [sys.executable, '-B', '-c',
                   'import sys; from setuptools import build_meta; '
                   f'print(build_meta.{method}(sys.argv[1]))', str(dist)]
        with (output / (method + '.log')).open('w', encoding='utf-8') as stream:
            subprocess.run(command, cwd=cwd, env=environment, stdout=stream,
                           stderr=subprocess.STDOUT, check=True)

    backend(scratch, 'build_sdist')
    sdist, = dist.glob('*.tar.gz')
    unpacked = output / 'sdist_source'
    unpacked.mkdir()
    with tarfile.open(sdist) as archive:
        for member in archive.getmembers():
            target = (unpacked / member.name).resolve()
            if not target.is_relative_to(unpacked) or not (member.isfile() or member.isdir()):
                raise ValueError('Unexpected source archive member: ' + member.name)
        archive.extractall(unpacked, filter='data')
    extracted, = (path for path in unpacked.iterdir() if path.is_dir())
    backend(extracted, 'build_wheel')
    wheel, = dist.glob('*.whl')
    checks = inspect_artifacts(wheel, sdist)
    current = {path.relative_to(source).as_posix(): sha256(path)
               for path in source.rglob('*') if path.is_file() and not set(path.relative_to(source).parts).intersection({'.git', '__pycache__', '.pytest_cache'})}
    assert inputs == current, 'Source changed during build'
    summary = dict(status='passed', tools=versions, python=sys.version,
                   installation_performed=False, clean_install_verified=False,
                   wheel_built_from_sdist=True, source_unchanged=True, checks=checks,
                   artifacts=[dict(file=path.name, bytes=path.stat().st_size,
                                   sha256=sha256(path)) for path in (wheel, sdist)])
    (output / 'build_validation.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(build(args.source, args.output), indent=2))


if __name__ == '__main__':
    main()
