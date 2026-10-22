"""Compatibility alias for eegproc.runtime_parameters."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("eegproc.runtime_parameters")
