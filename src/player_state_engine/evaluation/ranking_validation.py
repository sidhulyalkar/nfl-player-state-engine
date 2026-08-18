from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import kendalltau, spearmanr

from player_state_engine.fantasy.decision_board import DecisionType, build_decision_board
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.rankings import (
    attach_external_ranking_context,
    format_signature,
)


@dataclass(slots=True)
class FormatScenario:
    name: str
    config: LeagueConfig
    tags: tuple[str, ...] = ()


@dataclass(slots=True)
class RankingMetrics:
    rows: int
    spearman: float
    kendall: float
    rank_mae: float
    top12_overlap: float
    top24_overlap: float
    top50_overlap: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class StructuralCheck:
    name: str
    status: str
    observed: float | str | None
    expected: str
    details: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class RankingPromotionGate:
    promoted: bool
    candidate: str
    baseline: str
    checks: list[StructuralCheck]
    metrics: dict[str, float | int | str | bool | None] = field(default_factory=dict)
    reason: str = ""

    def to_dict(self) -> dict[str, object]:
        return {
            "promoted": self.promoted,
            "candidate": self.candidate,
            "baseline": self.baseline,
            "checks": [check.to_dict() for check in self.checks],
            "metrics": self.metrics,
            "reason": self.reason,
        }


def default_format_scenarios() -> list[FormatScenario]:
    """Small but adversarial matrix spanning common and intentionally unusual formats."""
    return [
        FormatScenario(
            "12t_half_1qb",
            LeagueConfig(
                teams=12,
                scoring="half_ppr",
                roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 6},
            ),
            ("baseline", "1qb", "half_ppr"),
        ),
        FormatScenario(
            "12t_half_2qb",
            LeagueConfig(
                teams=12,
                scoring="half_ppr",
                roster_slots={"QB": 2, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 6},
            ),
            ("2qb", "half_ppr"),
        ),
        FormatScenario(
            "12t_half_superflex",
            LeagueConfig(
                teams=12,
                scoring="half_ppr",
                roster_slots={
                    "QB": 1,
                    "RB": 2,
                    "WR": 2,
                    "TE": 1,
                    "SUPER_FLEX": 1,
                    "BENCH": 6,
                },
            ),
            ("superflex", "half_ppr"),
        ),
        FormatScenario(
            "12t_standard_1qb",
            LeagueConfig(
                teams=12,
                scoring="standard",
                roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 6},
            ),
            ("standard", "1qb"),
        ),
        FormatScenario(
            "12t_ppr_1qb",
            LeagueConfig(
                teams=12,
                scoring="ppr",
                roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 6},
            ),
            ("ppr", "1qb"),
        ),
        FormatScenario(
            "12t_ppr_te_premium",
            LeagueConfig(
                teams=12,
                scoring="ppr",
                tight_end_premium=0.5,
                roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 6},
            ),
            ("ppr", "te_premium"),
        ),
        FormatScenario(
            "8t_ppr_1qb_expanded",
            LeagueConfig(
                teams=8,
                scoring="ppr",
                roster_slots={"QB": 1, "RB": 3, "WR": 3, "TE": 1, "FLEX": 3, "BENCH": 8},
            ),
            ("8_team", "expanded", "1qb"),
        ),
        FormatScenario(
            "8t_ppr_2qb_expanded",
            LeagueConfig(
                teams=8,
                scoring="ppr",
                roster_slots={"QB": 2, "RB": 3, "WR": 3, "TE": 1, "FLEX": 3, "BENCH": 8},
            ),
            ("8_team", "expanded", "2qb"),
        ),
        FormatScenario(
            "14t_half_1qb",
            LeagueConfig(
                teams=14,
                scoring="half_ppr",
                roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 6},
            ),
            ("14_team", "1qb", "half_ppr"),
        ),
    ]


def compare_rankings(
    model: pd.DataFrame,
    external: pd.DataFrame,
    *,
    player_column: str = "player_id",
    model_rank_column: str = "rank",
    external_rank_column: str = "rank",
) -> RankingMetrics:
    left = model[[player_column, model_rank_column]].rename(columns={model_rank_column: "model_rank"})
    right = external[[player_column, external_rank_column]].rename(
        columns={external_rank_column: "external_rank"}
    )
    merged = left.merge(right, on=player_column, how="inner")
    merged["model_rank"] = pd.to_numeric(merged["model_rank"], errors="coerce")
    merged["external_rank"] = pd.to_numeric(merged["external_rank"], errors="coerce")
    merged = merged.dropna(subset=["model_rank", "external_rank"])
    if len(merged) < 2:
        return RankingMetrics(len(merged), np.nan, np.nan, np.nan, 0.0, 0.0, 0.0)
    spear = spearmanr(merged["model_rank"], merged["external_rank"]).statistic
    kendall = kendalltau(merged["model_rank"], merged["external_rank"]).statistic

    def overlap(k: int) -> float:
        model_ids = set(merged.nsmallest(k, "model_rank")[player_column].astype(str))
        external_ids = set(merged.nsmallest(k, "external_rank")[player_column].astype(str))
        denominator = max(1, min(k, len(merged)))
        return len(model_ids & external_ids) / denominator

    return RankingMetrics(
        rows=len(merged),
        spearman=float(spear),
        kendall=float(kendall),
        rank_mae=float(np.mean(np.abs(merged["model_rank"] - merged["external_rank"]))),
        top12_overlap=overlap(12),
        top24_overlap=overlap(24),
        top50_overlap=overlap(50),
    )


def compare_rank_deltas(
    model_a: pd.DataFrame,
    model_b: pd.DataFrame,
    external_a: pd.DataFrame,
    external_b: pd.DataFrame,
    *,
    player_column: str = "player_id",
    rank_column: str = "rank",
) -> dict[str, float | int]:
    """Compare how players move when the format changes, not merely absolute consensus."""

    def delta(a: pd.DataFrame, b: pd.DataFrame, label: str) -> pd.DataFrame:
        first = a[[player_column, rank_column]].rename(columns={rank_column: f"{label}_a"})
        second = b[[player_column, rank_column]].rename(columns={rank_column: f"{label}_b"})
        joined = first.merge(second, on=player_column, how="inner")
        joined[f"{label}_delta"] = pd.to_numeric(joined[f"{label}_b"], errors="coerce") - pd.to_numeric(
            joined[f"{label}_a"], errors="coerce"
        )
        return joined[[player_column, f"{label}_delta"]]

    model_delta = delta(model_a, model_b, "model")
    external_delta = delta(external_a, external_b, "external")
    merged = model_delta.merge(external_delta, on=player_column, how="inner").dropna()
    if len(merged) < 2:
        return {"rows": len(merged), "spearman_delta": np.nan, "kendall_delta": np.nan}
    return {
        "rows": len(merged),
        "spearman_delta": float(
            spearmanr(merged["model_delta"], merged["external_delta"]).statistic
        ),
        "kendall_delta": float(
            kendalltau(merged["model_delta"], merged["external_delta"]).statistic
        ),
    }


def _position_summary(board: pd.DataFrame, scenario: FormatScenario) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for position, group in board.groupby("position", sort=True):
        rows.append(
            {
                "scenario": scenario.name,
                "position": str(position),
                "teams": scenario.config.teams,
                "scoring": scenario.config.scoring,
                "qb_format": format_signature(scenario.config)["qb_format"],
                "league_starter_demand": int(group["league_starter_demand"].iloc[0]),
                "replacement_rank": int(group["replacement_rank"].iloc[0]),
                "replacement_points": float(group["replacement_points"].iloc[0]),
                "mean_positive_vorp": float(group["vorp"].clip(lower=0).mean()),
                "max_dynamic_scarcity": float(group["dynamic_scarcity_score"].max()),
                "scoring_exact_share": float(
                    (~group["league_scoring_fallback"].astype(bool)).mean()
                    if "league_scoring_fallback" in group
                    else 0.0
                ),
            }
        )
    return rows


def run_format_matrix(
    projections: pd.DataFrame,
    *,
    scenarios: list[FormatScenario] | None = None,
    rankings: pd.DataFrame | None = None,
) -> tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame]:
    """Build league-specific draft boards plus summaries and external validation metrics."""
    scenarios = scenarios or default_format_scenarios()
    boards: dict[str, pd.DataFrame] = {}
    summary_rows: list[dict[str, object]] = []
    metric_rows: list[dict[str, object]] = []
    for scenario in scenarios:
        board = build_decision_board(projections, scenario.config, DecisionType.DRAFT)
        board["rank"] = board["overall_rank"]
        ranking_metadata: dict[str, Any] = {"available": False}
        if rankings is not None and not rankings.empty:
            board, ranking_metadata = attach_external_ranking_context(board, rankings, scenario.config)
            external = board.loc[board["external_consensus_rank"].notna(), ["player_id", "external_consensus_rank"]].rename(
                columns={"external_consensus_rank": "rank"}
            )
            if not external.empty:
                metrics = compare_rankings(board[["player_id", "rank"]], external)
                metric_rows.append(
                    {
                        "scenario": scenario.name,
                        **metrics.to_dict(),
                        "sources": ",".join(ranking_metadata.get("expert_sources", [])),
                    }
                )
        boards[scenario.name] = board
        summary_rows.extend(_position_summary(board, scenario))
    return boards, pd.DataFrame(summary_rows), pd.DataFrame(metric_rows)


def structural_monotonicity_checks(
    boards: dict[str, pd.DataFrame],
    summary: pd.DataFrame,
) -> list[StructuralCheck]:
    """Assert properties that should hold regardless of any expert ranking source."""
    checks: list[StructuralCheck] = []

    def demand(scenario: str, position: str) -> float | None:
        rows = summary.loc[
            summary["scenario"].eq(scenario) & summary["position"].eq(position),
            "league_starter_demand",
        ]
        return float(rows.iloc[0]) if not rows.empty else None

    one_qb = demand("12t_half_1qb", "QB")
    two_qb = demand("12t_half_2qb", "QB")
    sf_qb = demand("12t_half_superflex", "QB")
    if one_qb is not None and two_qb is not None:
        checks.append(
            StructuralCheck(
                "2qb_increases_qb_demand",
                "PASS" if two_qb >= 2 * one_qb else "FAIL",
                two_qb / max(one_qb, 1.0),
                ">= 2.0x 12-team 1QB starter demand",
            )
        )
    if one_qb is not None and sf_qb is not None:
        checks.append(
            StructuralCheck(
                "superflex_increases_qb_demand",
                "PASS" if sf_qb > one_qb else "FAIL",
                sf_qb - one_qb,
                "> 0 additional QB starters vs equivalent 1QB format",
            )
        )

    expanded_one = demand("8t_ppr_1qb_expanded", "QB")
    expanded_two = demand("8t_ppr_2qb_expanded", "QB")
    if expanded_one is not None and expanded_two is not None:
        checks.append(
            StructuralCheck(
                "expanded_8t_2qb_increases_qb_demand",
                "PASS" if expanded_two > expanded_one else "FAIL",
                expanded_two - expanded_one,
                "> 0 additional QB starters",
            )
        )

    ppr_board = boards.get("12t_ppr_1qb")
    standard_board = boards.get("12t_standard_1qb")
    if ppr_board is not None and standard_board is not None:
        exact = bool(
            (~ppr_board.get("league_scoring_fallback", pd.Series(True, index=ppr_board.index))).any()
            and (~standard_board.get("league_scoring_fallback", pd.Series(True, index=standard_board.index))).any()
        )
        receivers = {"RB", "WR", "TE"}
        ppr_receiving = ppr_board.loc[ppr_board["position"].isin(receivers), "valuation_points_q50"].mean()
        std_receiving = standard_board.loc[
            standard_board["position"].isin(receivers), "valuation_points_q50"
        ].mean()
        checks.append(
            StructuralCheck(
                "ppr_scoring_transformation",
                "PASS" if exact and ppr_receiving >= std_receiving else "SKIP" if not exact else "FAIL",
                float(ppr_receiving - std_receiving),
                ">= 0 receiving-position point delta when component scoring is exact",
                "SKIP means generic fantasy-point fallback cannot validate scoring monotonicity.",
            )
        )

    te_premium = boards.get("12t_ppr_te_premium")
    ppr = boards.get("12t_ppr_1qb")
    if te_premium is not None and ppr is not None:
        exact = bool(
            (~te_premium.get("league_scoring_fallback", pd.Series(True, index=te_premium.index))).any()
            and (~ppr.get("league_scoring_fallback", pd.Series(True, index=ppr.index))).any()
        )
        premium_te = te_premium.loc[te_premium["position"].eq("TE"), "valuation_points_q50"].mean()
        normal_te = ppr.loc[ppr["position"].eq("TE"), "valuation_points_q50"].mean()
        checks.append(
            StructuralCheck(
                "te_premium_increases_te_points",
                "PASS" if exact and premium_te >= normal_te else "SKIP" if not exact else "FAIL",
                float(premium_te - normal_te),
                ">= 0 TE projection delta",
            )
        )

    return checks


def evaluate_ranking_promotion(
    checks: list[StructuralCheck],
    *,
    candidate: str,
    baseline: str,
    historical_candidate_utility: float | None = None,
    historical_baseline_utility: float | None = None,
    minimum_utility_improvement: float = 0.0,
    external_delta_correlation: float | None = None,
    minimum_external_delta_correlation: float = 0.0,
    require_historical_utility: bool = True,
) -> RankingPromotionGate:
    """Promote ranking logic only after structure and historical decision utility clear gates."""
    hard_failures = [check for check in checks if check.status == "FAIL"]
    metrics: dict[str, float | int | str | bool | None] = {
        "historical_candidate_utility": historical_candidate_utility,
        "historical_baseline_utility": historical_baseline_utility,
        "external_delta_correlation": external_delta_correlation,
        "structural_failures": len(hard_failures),
    }
    reasons: list[str] = []
    promoted = not hard_failures
    if hard_failures:
        reasons.append(f"{len(hard_failures)} structural format checks failed")

    if require_historical_utility:
        if historical_candidate_utility is None or historical_baseline_utility is None:
            promoted = False
            reasons.append("historical roster-utility replay is required")
        else:
            improvement = historical_candidate_utility - historical_baseline_utility
            metrics["historical_utility_improvement"] = improvement
            if improvement <= minimum_utility_improvement:
                promoted = False
                reasons.append(
                    f"historical utility improvement {improvement:.6f} did not clear "
                    f"{minimum_utility_improvement:.6f}"
                )

    if external_delta_correlation is not None:
        if external_delta_correlation < minimum_external_delta_correlation:
            promoted = False
            reasons.append("format-delta agreement is below the configured challenger floor")

    if promoted:
        reasons.append("all required promotion gates passed")
    return RankingPromotionGate(
        promoted=promoted,
        candidate=candidate,
        baseline=baseline,
        checks=checks,
        metrics=metrics,
        reason="; ".join(reasons),
    )
