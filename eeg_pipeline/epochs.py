"""Compatibility alias for eegproc.epochs."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("eegproc.epochs")
