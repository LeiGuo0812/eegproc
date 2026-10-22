"""Compatibility alias for eegproc.line_diagnostics."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("eegproc.line_diagnostics")
