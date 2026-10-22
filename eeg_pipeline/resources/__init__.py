"""Compatibility aliases for eegproc.resources."""
from importlib import import_module
import sys

_implementation = import_module("eegproc.resources")
for _name in ():
    sys.modules[f"{__name__}.{_name}"] = import_module(f"eegproc.resources.{_name}")
sys.modules[__name__] = _implementation
