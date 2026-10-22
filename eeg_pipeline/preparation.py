"""Compatibility alias for eegproc.preparation."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("eegproc.preparation")
