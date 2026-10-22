"""Compatibility alias for eegproc.pipeline."""
from importlib import import_module
import sys

sys.modules[__name__] = import_module("eegproc.pipeline")
