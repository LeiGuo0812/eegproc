"""Dependency declarations and source-package boundaries for clean installs."""
import ast
from pathlib import Path
import subprocess
import sys
import tomllib

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


ROOT = Path(__file__).resolve().parents[1]
PROJECT = tomllib.loads((ROOT / 'pyproject.toml').read_text(encoding='utf-8'))


def requirements(group=None):
    project = PROJECT['project']
    values = project['dependencies'] if group is None else project['optional-dependencies'][group]
    return {canonicalize_name(Requirement(value).name): Requirement(value) for value in values}


def test_default_runtime_dependencies_are_explicit():
    base = requirements()
    assert {'numpy', 'scipy', 'mne', 'mne-icalabel', 'torch', 'pyprep',
            'python-picard', 'scikit-learn', 'matplotlib', 'pillow', 'threadpoolctl'} <= base.keys()
    assert not {'eegprep', 'autoreject', 'pyedflib', 'pytest', 'playwright'} & base.keys()
    assert requirements('eegprep').keys() == {'eegprep'}
    assert requirements('autoreject').keys() == {'autoreject'}
    assert requirements('device').keys() == {'pyedflib'}
    assert {'pytest', 'build', 'wheel', 'packaging', 'twine', 'psutil', 'markdown-it-py'} <= requirements('dev').keys()


def test_runtime_imports_have_declared_distributions():
    imports = set()
    for path in (ROOT / 'eegproc').rglob('*.py'):
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8-sig'))):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split('.')[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                imports.add(node.module.split('.')[0])
    internal = {'eegproc'}
    distributions = {'PIL': 'pillow', 'mne_icalabel': 'mne-icalabel',
                     'sklearn': 'scikit-learn', 'picard': 'python-picard'}
    declared = set(requirements())
    for group in PROJECT['project']['optional-dependencies']:
        declared.update(requirements(group))
    external = imports - sys.stdlib_module_names - internal
    assert {canonicalize_name(distributions.get(name, name)) for name in external} <= declared


def test_requirements_files_delegate_to_single_project_metadata():
    expected = {
        'requirements.txt': '.',
        'requirements-dev.txt': '.[dev,eegprep,autoreject,device]',
        'requirements-eeglab.txt': '.[eegprep]',
        'requirements-autoreject.txt': '.[autoreject]',
        'requirements-device.txt': '.[device]',
        'requirements-all.txt': '.[eegprep,autoreject,device]',
    }
    for name, entry in expected.items():
        entries = [line.strip() for line in (ROOT / name).read_text(encoding='utf-8').splitlines()
                   if line.strip() and not line.lstrip().startswith('#')]
        assert entries == [entry], name


def test_license_files_are_explicit_and_keep_applicable_asr_notices():
    notices = PROJECT['tool']['setuptools']['license-files']
    assert 'LICENSE' in notices
    assert 'LICENSE' in PROJECT['tool']['setuptools']['package-data']['eegproc.mne_asr']
    # Older setuptools flattens license metadata paths: avoid two LICENSE
    # basenames overwriting each other; retain ASR's terms in package data.
    assert len({Path(name).name for name in notices}) == len(notices)
    assert 'docs/THIRD_PARTY_NOTICES.md' in notices
    assert all('*' not in name for name in notices)
    assert not any('CleanLine' in name for name in notices)


def test_build_version_can_be_read_without_runtime_imports():
    # PEP 517's isolated build environment initially contains build tools only.
    code = '''
import importlib.abc,sys
class RejectRuntime(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if fullname.split('.')[0] in {'eegproc','numpy','scipy','mne','torch'}:
            raise AssertionError('Build tried to import runtime: '+fullname)
sys.meta_path.insert(0,RejectRuntime())
from setuptools.config.expand import read_attr
print(read_attr('eegproc.__version__',root_dir=sys.argv[1]))
'''
    result = subprocess.run([sys.executable, '-B', '-c', code, str(ROOT)],
                            capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stdout + result.stderr
    assignments = ast.parse((ROOT / 'eegproc/__init__.py').read_text(encoding='utf-8'))
    expected = next(ast.literal_eval(node.value) for node in assignments.body
                    if isinstance(node, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == '__version__'
                            for target in node.targets))
    assert result.stdout.strip() == expected
