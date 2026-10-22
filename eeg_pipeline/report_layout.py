"""Compatibility alias for eegproc.report_layout."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("eegproc.report_layout")
