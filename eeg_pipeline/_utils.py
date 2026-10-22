"""Compatibility alias for eegproc._utils."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("eegproc._utils")
