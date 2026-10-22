"""Compatibility alias for :mod:`eegproc.io.bridge`."""
import sys
from eegproc.io import bridge as _implementation

sys.modules[__name__] = _implementation
