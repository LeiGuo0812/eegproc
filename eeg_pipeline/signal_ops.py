"""Compatibility alias for eegproc.signal_ops."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("eegproc.signal_ops")
