"""Compatibility aliases for eegproc.io."""
from importlib import import_module
import sys

_implementation = import_module("eegproc.io")
for _name in ('bridge', 'neuracle'):
    sys.modules[f"{__name__}.{_name}"] = import_module(f"eegproc.io.{_name}")
sys.modules[__name__] = _implementation
