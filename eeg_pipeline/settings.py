"""Compatibility alias for eegproc.settings."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("eegproc.settings")
