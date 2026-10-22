"""Compatibility aliases for :mod:`eegproc.mne_asr`.

Only the canonical package contains algorithm code. Submodule aliases preserve
imports and monkeypatching used by existing scripts without modifying sys.path.
"""
from importlib import import_module
import sys

_implementation = import_module('eegproc.mne_asr')
for _name in ('api', '_calibrate', '_math', '_process', '_reference', '_signal', '_stats', '_yulewalk'):
    sys.modules[f'{__name__}.{_name}'] = import_module(f'eegproc.mne_asr.{_name}')
sys.modules[__name__] = _implementation
