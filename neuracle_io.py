"""Compatibility alias for :mod:`eegproc.io.neuracle`."""
import sys
from eegproc.io import neuracle as _implementation

sys.modules[__name__] = _implementation
