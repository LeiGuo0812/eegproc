"""Compatibility aliases for eegproc.mne_asr."""
from importlib import import_module
import sys

_implementation = import_module("eegproc.mne_asr")
for _name in ('_calibrate', '_math', '_process', '_reference', '_signal', '_stats', '_yulewalk', 'api'):
    sys.modules[f"{__name__}.{_name}"] = import_module(f"eegproc.mne_asr.{_name}")
sys.modules[__name__] = _implementation
