"""Array-only reference selection, adapted from EEGPrep 0.4.0 clean_windows.

Copyright (c) 2025 SCCN. BSD-2-Clause; see LICENSE and PROVENANCE.json.
MATLAB terminal bounds are explicit; no EEG dictionary or sample deletion.
"""
import numpy as np
from ._math import round_mat, colon_starts
from ._stats import fit_eeg_distribution


def select_reference(data, sfreq, *, window=1., overlap=.66, max_bad=.075,
                     tolerances=(-3.5, 5.5)):
    x = np.asarray(data, dtype=float)
    c, size = x.shape
    width = int(round_mat(window * sfreq))
    starts = round_mat(colon_starts(1, size-width, width*(1-overlap))).astype(int)-1
    if width < 1 or len(starts) < 3:
        raise ValueError('Insufficient uninterrupted data for reference-window fitting')
    indices = starts[:, None] + np.arange(width)
    z = np.empty((c, len(starts)))
    for ch in reversed(range(c)):
        rms = np.sqrt(np.sum((x[ch]**2)[indices], axis=1)/width)
        mu, sigma, *_ = fit_eeg_distribution(rms)
        if sigma == 0 or np.isnan(sigma):
            sigma = np.median(np.abs(rms-np.median(rms))) * 1.4826
            mu = np.median(rms)
            if sigma == 0:
                sigma = 1.
        if not np.isfinite([mu, sigma]).all():
            raise FloatingPointError('Reference distribution is nonfinite')
        z[ch] = (rms-mu)/sigma
    z.sort(axis=0)
    count = int(round_mat(c*max_bad))
    rejected = (z[np.clip(c-count-1, 0, c-1)] > tolerances[1])
    rejected |= z[np.clip(count, 0, c-1)] < tolerances[0]
    mask = np.ones(size, dtype=bool)
    for start in starts[rejected]:
        mask[start:start+width] = False
    return mask
