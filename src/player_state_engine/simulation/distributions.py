from __future__ import annotations

import numpy as np
from scipy.stats import norm

_Z90 = float(norm.ppf(0.9))


def split_normal_ppf(
    uniforms: np.ndarray,
    q10: np.ndarray,
    q50: np.ndarray,
    q90: np.ndarray,
    nonnegative: bool = True,
) -> np.ndarray:
    """Approximate an inverse CDF from three predicted quantiles.

    A two-piece normal is anchored at q10, q50 and q90. This preserves the
    model's asymmetric uncertainty without claiming a richer learned density.
    """

    u = np.clip(uniforms, 1e-6, 1 - 1e-6)
    z = norm.ppf(u)
    low_scale = np.maximum((q50 - q10) / _Z90, 1e-6)
    high_scale = np.maximum((q90 - q50) / _Z90, 1e-6)
    samples = q50 + np.where(z < 0, z * low_scale, z * high_scale)
    if nonnegative:
        samples = np.clip(samples, 0.0, None)
    return samples
