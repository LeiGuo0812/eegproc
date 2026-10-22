"""Compatibility alias for eegproc.delivery."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("eegproc.delivery")
