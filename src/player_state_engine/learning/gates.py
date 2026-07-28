from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from player_state_engine.config import ContinualLearningConfig


@dataclass(slots=True)
class PromotionDecision:
    approved: bool
    reasons: list[str]
    metrics: dict[str, float]


def evaluate_benchmark_gate(
    summary_metrics: pd.DataFrame,
    position_metrics: pd.DataFrame,
    config: ContinualLearningConfig,
) -> PromotionDecision:
    engine = summary_metrics.loc[summary_metrics["method"] == "quantile_engine"]
    baselines = summary_metrics.loc[summary_metrics["method"] != "quantile_engine"]
    if engine.empty or baselines.empty:
        return PromotionDecision(False, ["Benchmark is missing engine or baseline rows."], {})
    engine_row = engine.iloc[0]
    baseline = baselines.sort_values("mean_pinball").iloc[0]
    improvement = (
        100.0
        * (float(baseline["mean_pinball"]) - float(engine_row["mean_pinball"]))
        / max(float(baseline["mean_pinball"]), 1e-12)
    )
    coverage_error = abs(float(engine_row["interval_coverage"]) - 0.8)
    reasons: list[str] = []
    if improvement < config.min_pinball_improvement_pct:
        reasons.append(
            f"Mean pinball improvement {improvement:.2f}% is below {config.min_pinball_improvement_pct:.2f}%."
        )
    if coverage_error > config.max_coverage_error:
        reasons.append(
            f"80% interval coverage error {coverage_error:.3f} exceeds {config.max_coverage_error:.3f}."
        )

    regressions: list[float] = []
    for position, subset in position_metrics.groupby("position"):
        e = subset.loc[subset["method"] == "quantile_engine"]
        b = subset.loc[subset["method"] != "quantile_engine"]
        if e.empty or b.empty:
            continue
        best = b.sort_values("mean_pinball").iloc[0]
        regression = (
            100.0
            * (float(e.iloc[0]["mean_pinball"]) - float(best["mean_pinball"]))
            / max(float(best["mean_pinball"]), 1e-12)
        )
        if regression > config.max_position_regression_pct:
            reasons.append(f"{position} pinball regression is {regression:.2f}%.")
        regressions.append(regression)

    metrics = {
        "mean_pinball": float(engine_row["mean_pinball"]),
        "mae": float(engine_row["mae"]),
        "interval_coverage": float(engine_row["interval_coverage"]),
        "pinball_improvement_pct": improvement,
        "max_position_regression_pct": max(regressions, default=0.0),
    }
    return PromotionDecision(not reasons, reasons or ["All configured gates passed."], metrics)


def evaluate_intelligence_promotion_gate(
    ablation_summary: pd.DataFrame,
    season_metrics: pd.DataFrame,
    *,
    candidate: str = "public_context_only",
    reference: str = "objective_opportunity_only",
    min_improvement_pct: float = 0.25,
    min_seasons_won: int = 2,
    max_shuffled_gain_pct: float = 0.15,
) -> PromotionDecision:
    """Require soft intelligence to beat objective context across seasons.

    The shuffled-player control must not reproduce the candidate gain. The
    shifted-time control is diagnostic only and can never be promotion-eligible.
    """

    index = ablation_summary.set_index("ablation") if not ablation_summary.empty else pd.DataFrame()
    required = {candidate, reference, "shuffled_player_control"}
    if not required.issubset(set(index.index)):
        return PromotionDecision(
            False, [f"Ablation summary is missing {sorted(required - set(index.index))}."], {}
        )
    candidate_loss = float(index.loc[candidate, "mean_pinball"])
    reference_loss = float(index.loc[reference, "mean_pinball"])
    shuffled_loss = float(index.loc["shuffled_player_control", "mean_pinball"])
    improvement = 100.0 * (reference_loss - candidate_loss) / max(reference_loss, 1e-12)
    shuffled_gain = 100.0 * (reference_loss - shuffled_loss) / max(reference_loss, 1e-12)

    wins = 0
    if not season_metrics.empty and {"ablation", "season", "mean_pinball"}.issubset(season_metrics):
        pivot = season_metrics.pivot_table(
            index="season", columns="ablation", values="mean_pinball", aggfunc="first"
        )
        if candidate in pivot and reference in pivot:
            wins = int((pivot[candidate] < pivot[reference]).sum())

    reasons: list[str] = []
    if improvement < min_improvement_pct:
        reasons.append(
            f"Candidate improvement {improvement:.3f}% is below {min_improvement_pct:.3f}%."
        )
    if wins < min_seasons_won:
        reasons.append(
            f"Candidate won {wins} held-out seasons; at least {min_seasons_won} are required."
        )
    if shuffled_gain > max_shuffled_gain_pct:
        reasons.append(
            f"Shuffled-player control gained {shuffled_gain:.3f}%, suggesting identity-insensitive or confounded signal."
        )
    metrics = {
        "candidate_pinball": candidate_loss,
        "reference_pinball": reference_loss,
        "improvement_pct": improvement,
        "seasons_won": float(wins),
        "shuffled_control_gain_pct": shuffled_gain,
    }
    return PromotionDecision(
        not reasons, reasons or ["All intelligence promotion gates passed."], metrics
    )
