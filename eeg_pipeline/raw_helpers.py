"""Compatibility alias for eegproc.raw_helpers."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("eegproc.raw_helpers")
