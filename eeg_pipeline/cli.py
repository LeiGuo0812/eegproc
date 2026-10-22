"""Compatibility alias for eegproc.cli."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("eegproc.cli")
