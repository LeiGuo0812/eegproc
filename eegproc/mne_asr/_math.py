# Derived from EEGPrep 0.4.0, Copyright (c) 2025 SCCN.
# BSD-2-Clause; see LICENSE and PROVENANCE.json in this directory.
# Local ASR port: no EEGPrep or ASRpy runtime imports.

import math,warnings
from typing import Callable
import numpy as np

def finite_matmul(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    """Compute a matrix product, suppressing only warnings from finite results."""
    left = np.asarray(left)
    right = np.asarray(right)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        result = left @ right
    if caught and not (_is_finite_array(left) and _is_finite_array(right) and _is_finite_array(result)):
        _reissue_warnings(caught)
    return result


def finite_pinv(matrix: np.ndarray, solver: Callable[[np.ndarray], np.ndarray] | None = None) -> np.ndarray:
    """Compute a pseudo-inverse, suppressing only warnings from finite results."""
    matrix = np.asarray(matrix)
    solver = solver or pinv_matlab
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always", RuntimeWarning)
        result = solver(matrix)
    if caught and not (_is_finite_array(matrix) and _is_finite_array(result)):
        _reissue_warnings(caught)
    return result


def _is_finite_array(value: np.ndarray) -> bool:
    return bool(np.isfinite(np.asarray(value)).all())


def _reissue_warnings(caught) -> None:
    for warning in caught:
        warnings.warn(warning.message, warning.category, stacklevel=3)


def canonicalize_signs(V):
    """Canonicalize signs of column matrix V so that the largest absolute value is positive."""
    # V: columns are eigenvectors
    idx = np.argmax(np.abs(V), axis=0)
    pivot = V[idx, range(V.shape[1])]
    phase = np.ones_like(pivot, dtype=np.result_type(V.dtype, float))
    nonzero = pivot != 0
    phase[nonzero] = np.conj(pivot[nonzero]) / np.abs(pivot[nonzero])
    return V * phase


def round_mat(x, decimals=0):
    """MATLAB-style rounding function.

    - ties (.5 within fp error) round AWAY from zero
    - supports positive/zero/negative `decimals` like MATLAB round(x, N)
    - NaN/Inf propagate naturally
    - does NOT return integer-typed results

    This can be applied to numpy arrays and acts as a drop-in replacement
    for np.round(), but also works for pure-Python float values; however,
    to get a 1:1 replacement for a use of round(x) you need to write
    int(round_mat(x)) since round() returns integers.

    Parameters
    ----------
    x : array_like
        The value(s) to round.
    decimals : int
        Number of decimals to round to.

    Returns
    -------
    array_like
        The rounded value(s).
    """
    if isinstance(x, (float, int)):
        # Propagate NaN/Inf instead of throwing in math.floor(...)
        if math.isnan(x) or math.isinf(x):
            return x
        xp = math
    else:
        xp = np
        x = np.asarray(x)  # ensure ndarray

    if decimals == 0:
        return xp.copysign(xp.floor(abs(x) + 0.5), x)

    if decimals > 0:
        factor = 10.0**decimals
        y = xp.copysign(xp.floor(abs(x) * factor + 0.5), x)
        return y / factor

    # decimals < 0  -> round to tens/hundreds/…
    factor = 10.0 ** (-decimals)
    y = xp.copysign(xp.floor(abs(x) / factor + 0.5), x)
    return y * factor


def colon_starts(start, last, step):
    """Real starts through MATLAB's inclusive bound, before rounding indices."""
    values = np.arange(start, last + 1, step)
    return values[values <= last + 4 * np.spacing(float(max(abs(last), 1)))]


def pinv_matlab(matrix):
    """Use max(size(A))*eps(norm(A)), not NumPy's fixed default rcond."""
    a = np.asarray(matrix)
    singular = np.linalg.svd(a, compute_uv=False)
    if not len(singular) or singular[0] == 0:
        return np.zeros(a.T.shape, dtype=a.dtype)
    tolerance = max(a.shape) * np.spacing(singular[0])
    return np.linalg.pinv(a, rcond=tolerance / singular[0])
