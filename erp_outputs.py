"""Compatibility alias for :mod:`eegproc.epoch_export`."""
import sys
from eegproc import epoch_export as _implementation

sys.modules[__name__] = _implementation
