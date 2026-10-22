"""Independent, MNE-native Euclidean ASR, derived from the EEGLAB algorithm.

Only NumPy, SciPy and MNE are needed. See README.md and PROVENANCE.json.
"""
from .api import ASR, ASRConfig, clean_asr_raw

__version__ = '0.1.0'
__all__ = ['ASR', 'ASRConfig', 'clean_asr_raw']
