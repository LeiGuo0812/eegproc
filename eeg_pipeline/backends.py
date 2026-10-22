"""Compatibility alias for eegproc.backends."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("eegproc.backends")
