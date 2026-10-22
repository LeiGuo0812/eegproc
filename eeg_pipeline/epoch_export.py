"""Compatibility alias for eegproc.epoch_export."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("eegproc.epoch_export")
