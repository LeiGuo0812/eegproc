"""Compatibility alias for eegproc.parameter_resolution."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("eegproc.parameter_resolution")
