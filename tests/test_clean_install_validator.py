"""Ensure validation modes cannot silently mislabel source-only checks as clean."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest


SOURCE = Path(__file__).resolve().parents[1]/'scripts/validate_clean_install.py'
SPEC = importlib.util.spec_from_file_location('clean_install_validator', SOURCE)
validator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(validator)


def test_existing_environment_mode_never_installs_and_cannot_certify_clean(tmp_path, monkeypatch):
    output = tmp_path/'evidence'
    commands = []

    def execute(command, **kwargs):
        commands.append(command)
        assert '-I' not in command and 'existing' == command[-1]
        assert 'pip' not in command and 'venv' not in command
        (output/'worker_validation.json').write_text(json.dumps({'status':'passed'}), encoding='utf8')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(validator.subprocess, 'run', execute)
    validator.main(['--existing-environment-check','--output',str(output)])
    report = json.loads((output/'clean_install_validation.json').read_text(encoding='utf8'))
    assert report['status'] == 'passed'
    assert report['clean_install_verified'] is False
    assert report['dependency_install_requested'] is False
    assert report['validation_kind'] == 'existing_environment_worker'
    assert len(commands) == 1


def test_skip_install_rejects_inherited_site_packages_before_execution(tmp_path, monkeypatch):
    venv = tmp_path/'environment'
    venv.mkdir()
    (venv/'pyvenv.cfg').write_text('include-system-site-packages = true\n', encoding='utf8')
    def forbidden(*args, **kwargs):
        raise AssertionError('A non-isolated environment must be rejected before any subprocess')
    monkeypatch.setattr(validator.subprocess, 'run', forbidden)
    output = tmp_path/'evidence'
    with pytest.raises(ValueError, match='include-system-site-packages'):
        validator.main(['--skip-install','--venv',str(venv),'--output',str(output)])
    report = json.loads((output/'clean_install_validation.json').read_text(encoding='utf8'))
    assert report['status'] == 'failed' and report['clean_install_verified'] is False


def test_skip_install_uses_actual_console_paths_without_installation(tmp_path, monkeypatch):
    venv = tmp_path/'environment'
    executable = validator.venv_python(venv)
    executable.parent.mkdir(parents=True)
    executable.touch()
    for name in ('eegproc','eegproc-prepare'):
        (executable.parent/(name+('.exe' if os.name=='nt' else ''))).touch()
    (venv/'pyvenv.cfg').write_text('include-system-site-packages = false\n', encoding='utf8')
    output = tmp_path/'evidence'
    commands = []
    def execute(command, **kwargs):
        commands.append(command)
        assert 'install' not in command and 'download' not in command
        if command[-1] == 'clean':
            assert '-I' in command
            (output/'worker_validation.json').write_text(json.dumps({'status':'passed'}), encoding='utf8')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(validator.subprocess, 'run', execute)
    validator.main(['--skip-install','--venv',str(venv),'--output',str(output)])
    assert any(command[1:] == ['-m','pip','check'] for command in commands)
    helps = [command for command in commands if command[-1] == '--help']
    assert len(helps) == 2
    assert all(Path(command[0]).parent == executable.parent for command in helps)
    assert all(Path(command[0]).stem in ('eegproc','eegproc-prepare') for command in helps)


@pytest.mark.parametrize('options', [
    ['--existing-environment-check','--skip-install'],
    ['--existing-environment-check','--venv','environment'],
    ['--existing-environment-check','--wheel','package.whl'],
    ['--skip-install'],
])
def test_ambiguous_modes_are_rejected(options, tmp_path):
    with pytest.raises(SystemExit):
        validator.main([*options,'--output',str(tmp_path/'evidence')])


def test_python_environment_paths_are_removed(monkeypatch):
    monkeypatch.setenv('PYTHONPATH','unrelated/site-packages')
    monkeypatch.setenv('PYTHONHOME','unrelated/python')
    env = validator.clean_environment()
    assert 'PYTHONPATH' not in env and 'PYTHONHOME' not in env
