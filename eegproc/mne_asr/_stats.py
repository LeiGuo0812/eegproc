# Derived from EEGPrep 0.4.0, Copyright (c) 2025 SCCN.
# BSD-2-Clause; see LICENSE and PROVENANCE.json in this directory.
# Local ASR port: no EEGPrep or ASRpy runtime imports.

import math,logging
import numpy as np
from numpy.linalg import norm as np_norm
from scipy.special import gamma,gammaincinv
from ._math import round_mat
logger=logging.getLogger(__name__)

def fit_eeg_distribution(
    X, min_clean_fraction=None, max_dropout_fraction=None, quants=None, step_sizes=None, beta=None
):
    """Estimate the mean and standard deviation of clean EEG from contaminated data.

    Mu,Sigma,Alpha,Beta = fit_eeg_distribution(X,MinCleanFraction,MaxDropoutFraction,FitQuantiles,StepSizes,ShapeRange)

    This function estimates the mean and standard deviation of clean EEG from a
    sample of amplitude values (that have preferably been computed over short
    windows) that may include a large fraction of contaminated samples. The
    clean EEG is assumed to represent a generalized Gaussian component in a
    mixture with near-arbitrary artifact components. By default, at least 25%
    (MinCleanFraction) of the data must be clean EEG, and the rest can be
    contaminated. No more than 10% (MaxDropoutFraction) of the data is
    allowed to come from contaminations that cause lower-than-EEG amplitudes
    (e.g., sensor unplugged). There are no restrictions on artifacts causing
    larger-than-EEG amplitudes, i.e., virtually anything is handled (with the
    exception of a very unlikely type of distribution that combines with the
    clean EEG samples into a larger symmetric generalized Gaussian peak and
    thereby "fools" the estimator). The default parameters should be fine for
    a wide range of settings but may be adapted to accomodate special
    circumstances.

    The method works by fitting a truncated generalized Gaussian whose
    parameters are constrained by MinCleanFraction, MaxDropoutFraction,
    FitQuantiles, and ShapeRange. The alpha and beta parameters of the gen.
    Gaussian are also returned. The fit is performed by a grid search that
    always finds a close-to-optimal solution if the above assumptions are
    fulfilled.

    Args:
      X : array-like
          Vector of amplitude values of EEG, possible containing artifacts
          (coming from single samples or windowed averages).
      min_clean_fraction : float, optional
          Minimum fraction of values in X that needs to be clean
          (default: 0.25).
      max_dropout_fraction : float, optional
          Maximum fraction of values in X that can be subject to
          signal dropouts (e.g., sensor unplugged) (default: 0.1).
      quants : tuple or list, optional
          Quantile range [lower,upper] of the truncated generalized Gaussian
          distribution that shall be fit to the EEG contents
          (default: (0.022, 0.6)).
      step_sizes : tuple or list, optional
          Step size of the grid search; the first value is the stepping of the
          lower bound (which essentially steps over any dropout samples), and
          the second value is the stepping over possible scales (i.e.,
          clean-data quantiles) (default: (0.01, 0.01)).
      beta : array-like, optional
          Range that the clean EEG distribution's shape parameter beta may take
          (default: np.arange(1.7, 3.6, 0.15)).

    Returns
    -------
      tuple:
          - mu (float): estimated mean of the clean EEG distribution.
          - sig (float): estimated standard deviation of the clean EEG distribution.
          - alpha (float): estimated scale parameter of the generalized Gaussian
                           clean EEG distribution.
          - beta (float): estimated shape parameter of the generalized Gaussian
                          clean EEG distribution.
    """
    # --- Assign defaults ---
    if min_clean_fraction is None:
        min_clean_fraction = 0.25
    if max_dropout_fraction is None:
        max_dropout_fraction = 0.1
    if quants is None:
        # Use tuple for immutability, common practice in Python for fixed sequences
        quants = (0.022, 0.6)
    if step_sizes is None:
        step_sizes = (0.01, 0.01)
    if beta is None:
        beta = np.arange(1.7, 3.6, 0.15)

    # Convert potentially list inputs to numpy arrays for consistency
    quants = np.array(quants)
    step_sizes = np.array(step_sizes)
    beta = np.array(beta)

    # --- Sanity checks ---
    # Use isinstance for type checking, len() for number of elements
    if not isinstance(quants, np.ndarray) or quants.ndim != 1 or len(quants) != 2:
        raise ValueError('Fit quantiles needs to be a 2-element vector.')
    if np.any(quants < 0) or np.any(quants > 1):
        raise ValueError('Unreasonable fit quantiles.')
    if np.any(step_sizes < 0.0001) or np.any(step_sizes > 0.1):
        raise ValueError('Unreasonable step sizes.')
    # Allow slightly wider range check than MATLAB's >=7, <=1
    if np.any(beta > 7) or np.any(beta < 1):
        raise ValueError('Unreasonable shape range.')

    # --- Sort data so we can access quantiles directly ---
    # Ensure X is a numpy array, convert to float (like MATLAB's double), flatten
    X = np.asarray(X, dtype=float).flatten()
    X.sort()
    n = len(X)

    # --- Calc z bounds for the truncated standard generalized Gaussian pdf and pdf rescaler ---
    zbounds = []  # Use a list to store bounds for each beta
    rescale = np.zeros_like(beta, dtype=float)  # Pre-allocate rescale array
    for i, b_val in enumerate(beta):
        # Calculate bounds using gammaincinv
        # Note: MATLAB's gammaincinv(A,X) finds y where gammainc(y,A,'lower') = X.
        # scipy.special.gammaincinv(a, y) finds x where gammainc(a, x) = y.
        # The argument sign(q-0.5)*(2*q-1) simplifies to abs(2*q-1).
        # We need y such that P(1/b, y) = abs(2*q-1), so y = gammaincinv(1/b, abs(2*q-1)).
        # The final z is sign(q-0.5) * y**(1/b).
        lower_bound_arg = abs(2 * quants[0] - 1)
        upper_bound_arg = abs(2 * quants[1] - 1)

        lower_y = gammaincinv(1.0 / b_val, lower_bound_arg)
        upper_y = gammaincinv(1.0 / b_val, upper_bound_arg)

        lower_z = np.sign(quants[0] - 0.5) * np.power(lower_y, 1.0 / b_val)
        upper_z = np.sign(quants[1] - 0.5) * np.power(upper_y, 1.0 / b_val)

        zbounds.append(np.array([lower_z, upper_z]))
        rescale[i] = b_val / (2.0 * gamma(1.0 / b_val))

    # --- Determine the quantile-dependent limits for the grid search ---
    lower_min = np.min(quants)  # we can generally skip the tail below the lower quantile
    max_width = np.diff(quants)[0]  # maximum width is the fit interval if all data is clean
    min_width = min_clean_fraction * max_width  # minimum width of the fit interval, as fraction of data

    # --- Get matrix of shifted data ranges ---
    # Generate start indices based on lower quantile, dropout fraction, and step size
    # Use np.arange; add a small fraction of step_sizes[0] to ensure the endpoint is included if it's a multiple of the step
    start_indices = round_mat(
        n * np.arange(lower_min, lower_min + max_dropout_fraction + 0.99 * step_sizes[0], step_sizes[0])
    ).astype(int)

    # Generate indices within each window based on max_width
    max_window_len = int(round_mat(n * max_width))
    window_indices = np.arange(max_window_len)

    # Use broadcasting to create the matrix of indices (equivalent to bsxfun(@plus, ...))
    # Indices shape: (num_starts, max_window_len)
    all_indices = start_indices[:, None] + window_indices[None, :]

    # Index into sorted data X to get the windows
    X_windows = X[all_indices]

    # Get the first element (lower bound) of each window
    X1 = X_windows[:, 0].copy()  # Use .copy() to avoid potential view issues

    # Subtract the lower bound from each element in its respective window (equivalent to bsxfun(@minus, X, X1))
    X_shifted = X_windows - X1[:, None]  # Broadcasting subtraction

    # --- Grid search ---
    opt_val = np.inf
    opt_beta = np.nan
    opt_bounds = np.array([np.nan, np.nan])
    opt_lu = np.array([np.nan, np.nan])  # Lower and Upper data values of the optimal interval

    # Iterate through possible interval widths 'm' exactly as in-house
    m_steps = np.int32(round_mat(n * np.arange(max_width, min_width, -step_sizes[1])))

    for m in m_steps:
        if m <= 0:
            continue  # Skip if width is non-positive

        # --- Scale and bin the data in the intervals ---
        nbins = int(round_mat(3 * math.log2(1 + m / 2)))
        if nbins <= 0:
            continue  # Skip if nbins is non-positive

        # scale and bin the data in the intervals exactly as in the MATLAB code
        with np.errstate(invalid="ignore", divide="ignore"):
            H = np.asarray(X_shifted[:, :m] * nbins / X_shifted[:, m - 1].reshape((-1, 1)))
        H[np.isnan(H)] = -1
        bins = list(range(nbins))
        bins.append(np.inf)
        logq = np.zeros((H.shape[0], nbins))
        for k in range(H.shape[0]):
            h, _ = np.histogram(H[k, :], bins=bins, density=False)
            logq[k, :] = np.log(np.asarray(h) + 0.01)

        # --- Inner loop: Iterate through shape parameters (beta) ---
        for b in range(len(beta)):
            bounds = zbounds[b]
            x_vals = bounds[0] + (0.5 + np.arange(nbins)) / nbins * np.diff(bounds)
            p = np.exp(-(np.abs(x_vals) ** beta[b])) * rescale[b]
            p /= np.sum(p)
            kl = np.sum(p * (np.log(p) - logq), axis=1) + np.log(m)
            min_val = np.min(kl)
            idx = np.where(kl == min_val)[0][0]
            if min_val < opt_val:
                opt_val = min_val
                opt_beta = beta[b]
                opt_bounds = bounds
                opt_lu = [X1[idx], X1[idx] + X_shifted[idx, m - 1]]

    # --- Recover distribution parameters at optimum ---
    if np.any(np.isnan(opt_lu)) or np.any(np.isnan(opt_bounds)):
        logger.warning("Optimal parameters not found; returning NaNs.")
        return np.nan, np.nan, np.nan, np.nan

    bound_diff = opt_bounds[1] - opt_bounds[0]
    if abs(bound_diff) < 1e-9:
        logger.warning("Optimal bounds are too close; returning NaNs.")
        return np.nan, np.nan, np.nan, np.nan

    # alpha = (opt_lu(2)-opt_lu(1))/diff(opt_bounds);
    alpha = (opt_lu[1] - opt_lu[0]) / bound_diff

    # mu = opt_lu(1)-opt_bounds(1)*alpha;
    mu = opt_lu[0] - opt_bounds[0] * alpha

    # beta is already opt_beta
    final_beta = opt_beta

    # --- Calculate the distribution's standard deviation from alpha and beta ---
    # sig = sqrt((alpha^2)*gamma(3/beta)/gamma(1/beta));
    try:
        gamma_3_over_beta = gamma(3.0 / final_beta)
        gamma_1_over_beta = gamma(1.0 / final_beta)
        if gamma_1_over_beta < 1e-9:  # Avoid division by near-zero
            sig = np.nan
            logger.warning("gamma(1/beta) is close to zero; std dev calculation failed.")
        else:
            sig = np.sqrt((alpha**2) * gamma_3_over_beta / gamma_1_over_beta)
    except ValueError:  # Catches potential issues with gamma function inputs (e.g., non-positive)
        sig = np.nan
        logger.warning("Could not calculate std dev due to invalid gamma function input.")

    # Ensure output types are standard Python floats if they are scalar
    mu = float(mu) if np.isscalar(mu) else mu
    sig = float(sig) if np.isscalar(sig) else sig
    alpha = float(alpha) if np.isscalar(alpha) else alpha
    final_beta = float(final_beta) if np.isscalar(final_beta) else final_beta

    return mu, sig, alpha, final_beta


def geometric_median(X, tol=1.0e-5, y=None, max_iter=500):
    """Calculate the geometric median for a set of observations.

    This is the mean under a Laplacian noise distribution, using
    Weiszfeld's algorithm.

    Args:
        X (np.ndarray): The data, expected shape (n_samples, n_features).
        tol (float, optional): Tolerance for convergence. Defaults to 1.e-5.
        y (np.ndarray, optional): Initial value for the geometric median.
                                  Defaults to the coordinate-wise median of X.
        max_iter (int, optional): Maximum number of iterations. Defaults to 500.

    Returns
    -------
        np.ndarray: The geometric median of X, shape (n_features,).
    """
    # Ensure X is a numpy array
    X = np.asarray(X)
    if X.ndim != 2:
        raise ValueError("Input data X must be a 2D array (samples x features).")

    # Default initial value: coordinate-wise median
    if y is None:
        y = np.median(X, axis=0)
    else:
        y = np.asarray(y)
        if y.shape != (X.shape[1],):
            raise ValueError(f"Initial guess y must have shape ({X.shape[1]},) matching the number of features in X.")

    # Small constant to prevent division by zero if a point coincides with the median
    epsilon = 1e-9

    for i in range(max_iter):
        # Calculate squared distances from each point in X to the current median y
        # X shape: (n_samples, n_features), y shape: (n_features,)
        # Broadcasting makes (X - y) shape (n_samples, n_features)
        squared_distances = np.sum((X - y) ** 2, axis=1)

        # Calculate inverse norms (distances). Add epsilon for numerical stability.
        invnorms = 1.0 / np.sqrt(squared_distances + epsilon)

        # Check for exact matches (where distance is near zero)
        # If a data point coincides with the current estimate, its weight should be handled carefully.
        # Weiszfeld's algorithm can be sensitive here. A common approach is to give these points
        # large weight or handle them separately, but simply adding epsilon often suffices.
        # Here, the epsilon already prevents division by zero.

        # Update the median estimate
        # Weighted average: sum(X * weights) / sum(weights)
        # weights are invnorms. Need to broadcast invnorms for element-wise multiplication.
        # invnorms shape: (n_samples,), X shape: (n_samples, n_features)
        # X * invnorms[:, np.newaxis] has shape (n_samples, n_features)
        new_y = np.sum(X * invnorms[:, np.newaxis], axis=0) / np.sum(invnorms)

        # Store the old median and update y
        oldy = y
        y = new_y

        # Check for convergence: relative change in norm
        # Use np.linalg.norm for vector norm
        norm_y = np_norm(y)
        if norm_y == 0:  # Avoid division by zero if the median is the zero vector
            if np_norm(y - oldy) < tol:  # Check absolute difference if norm is zero
                break
        elif np_norm(y - oldy) / norm_y < tol:
            break

    # Optional: Add a warning if max_iter was reached without convergence
    if i == max_iter - 1:
        logger.warning(f"Geometric median calculation did not converge within {max_iter} iterations.")

    return y
