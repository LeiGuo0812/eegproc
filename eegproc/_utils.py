"""Shared logging and serialization helpers."""
import contextlib
import logging
from pathlib import Path
import sys
import numpy as np


def _json_default(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f'Cannot serialize {type(value).__name__}')


@contextlib.contextmanager
def _backend_logging():
    """Keep the existing logging scope without importing any EEGPrep code."""
    logger = logging.getLogger('eegprep')
    previous_level, previous_propagate = logger.level, logger.propagate
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter('%(name)s: %(message)s'))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    try:
        yield
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous_level)
        logger.propagate = previous_propagate
        handler.close()
