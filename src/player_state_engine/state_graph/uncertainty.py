from __future__ import annotations

from collections.abc import Mapping

import numpy as np

from player_state_engine.state_graph.types import UncertaintyBreakdown


def decompose_counterfactual_variance(
    total_draws: np.ndarray,
    fixed_component_draws: Mapping[str, np.ndarray],
) -> UncertaintyBreakdown:
    """Estimate uncertainty shares by freezing one latent component at a time.

    ``fixed_component_draws[name]`` should be generated with the named component fixed to its
    posterior central value while preserving the same common random numbers for all other state
    nodes. The reduction in variance is attributed to that component. Overlap is normalized,
    because interacting latent states need not produce an additive ANOVA decomposition.
    """
    total = np.asarray(total_draws, dtype=float)
    total = total[np.isfinite(total)]
    if len(total) < 20:
        raise ValueError("At least 20 total draws are required")
    total_variance = float(np.var(total, ddof=1))
    components: dict[str, float] = {}
    for name, values in fixed_component_draws.items():
        array = np.asarray(values, dtype=float)
        array = array[np.isfinite(array)]
        if len(array) < 20:
            raise ValueError(f"At least 20 fixed draws are required for {name}")
        variance = float(np.var(array, ddof=1))
        components[str(name)] = max(0.0, total_variance - variance)
    explained = sum(components.values())
    residual = max(0.0, total_variance - min(total_variance, explained))
    components["residual_model"] = residual
    return UncertaintyBreakdown(total_variance=total_variance, components=components)


def bootstrap_quantile_uncertainty(
    draws: np.ndarray,
    *,
    quantile: float = 0.50,
    bootstrap_samples: int = 500,
    seed: int = 42,
) -> tuple[float, float, float]:
    values = np.asarray(draws, dtype=float)
    values = values[np.isfinite(values)]
    if len(values) < 30:
        raise ValueError("At least 30 draws are required")
    rng = np.random.default_rng(seed)
    estimates = np.empty(max(100, int(bootstrap_samples)), dtype=float)
    for index in range(len(estimates)):
        sample = rng.choice(values, size=len(values), replace=True)
        estimates[index] = np.quantile(sample, quantile)
    low, center, high = np.quantile(estimates, [0.10, 0.50, 0.90])
    return float(low), float(center), float(high)
