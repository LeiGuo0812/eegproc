"""Compatibility alias for eegproc.review."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("eegproc.review")
