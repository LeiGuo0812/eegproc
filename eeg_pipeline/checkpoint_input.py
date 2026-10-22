"""Compatibility alias for eegproc.checkpoint_input."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("eegproc.checkpoint_input")
