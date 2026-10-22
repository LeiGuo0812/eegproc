"""Compatibility alias for eegproc.quality_figures."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("eegproc.quality_figures")
