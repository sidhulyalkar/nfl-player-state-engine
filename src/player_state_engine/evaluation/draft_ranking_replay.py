from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Sequence

import numpy as np
import pandas as pd


@dataclass(slots=True)
class PolicyReplayResult:
    policy: str
    decisions: int
    mean_utility: float
    median_utility: float
    total_utility: float
    mean_oracle_regret: float
    p10_utility: float
    p90_utility: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def replay_ranking_policy(
    decisions: pd.DataFrame,
    *,
    policy: str,
    score_column: str,
    utility_column: str,
    group_columns: Sequence[str] = ("draft_id", "current_pick"),
    higher_score_is_better: bool = True,
) -> tuple[PolicyReplayResult, pd.DataFrame]:
    """Replay a ranking policy over frozen historical decision sets.

    Each group must represent the candidate set that was genuinely available at that historical
    decision time. ``utility_column`` must also be derived from a frozen outcome definition, such
    as rest-of-season roster utility or realized starter contribution. This function deliberately
    does not manufacture either piece from final-season data.
    """
    missing = {score_column, utility_column, *group_columns} - set(decisions.columns)
    if missing:
        raise ValueError(f"Ranking replay missing columns: {sorted(missing)}")
    data = decisions.copy()
    data[score_column] = pd.to_numeric(data[score_column], errors="coerce")
    data[utility_column] = pd.to_numeric(data[utility_column], errors="coerce")
    data = data.dropna(subset=[score_column, utility_column, *group_columns])
    if data.empty:
        raise ValueError("Ranking replay has no complete decision rows.")

    selected_rows: list[pd.Series] = []
    for _, group in data.groupby(list(group_columns), sort=False, dropna=False):
        ordered = group.sort_values(
            score_column,
            ascending=not higher_score_is_better,
            kind="mergesort",
        )
        chosen = ordered.iloc[0].copy()
        oracle = float(group[utility_column].max())
        chosen["policy"] = policy
        chosen["oracle_utility"] = oracle
        chosen["oracle_regret"] = oracle - float(chosen[utility_column])
        selected_rows.append(chosen)

    selections = pd.DataFrame(selected_rows).reset_index(drop=True)
    utilities = pd.to_numeric(selections[utility_column], errors="coerce").astype(float)
    result = PolicyReplayResult(
        policy=policy,
        decisions=len(selections),
        mean_utility=float(utilities.mean()),
        median_utility=float(utilities.median()),
        total_utility=float(utilities.sum()),
        mean_oracle_regret=float(
            pd.to_numeric(selections["oracle_regret"], errors="coerce").mean()
        ),
        p10_utility=float(np.quantile(utilities, 0.10)),
        p90_utility=float(np.quantile(utilities, 0.90)),
    )
    return result, selections


def compare_ranking_policies(
    decisions: pd.DataFrame,
    *,
    baseline_score: str,
    candidate_score: str,
    utility_column: str,
    baseline_name: str = "baseline",
    candidate_name: str = "candidate",
    group_columns: Sequence[str] = ("draft_id", "current_pick"),
) -> dict[str, object]:
    """Compare production and challenger ranks on exactly the same historical decisions."""
    baseline, baseline_rows = replay_ranking_policy(
        decisions,
        policy=baseline_name,
        score_column=baseline_score,
        utility_column=utility_column,
        group_columns=group_columns,
    )
    candidate, candidate_rows = replay_ranking_policy(
        decisions,
        policy=candidate_name,
        score_column=candidate_score,
        utility_column=utility_column,
        group_columns=group_columns,
    )
    baseline_keys = baseline_rows.loc[:, list(group_columns)].astype(str).agg("|".join, axis=1)
    candidate_keys = candidate_rows.loc[:, list(group_columns)].astype(str).agg("|".join, axis=1)
    if set(baseline_keys) != set(candidate_keys):
        raise ValueError("Baseline and candidate replay decision sets do not match.")
    utility_delta = candidate.mean_utility - baseline.mean_utility
    regret_delta = candidate.mean_oracle_regret - baseline.mean_oracle_regret
    return {
        "baseline": baseline.to_dict(),
        "candidate": candidate.to_dict(),
        "mean_utility_improvement": float(utility_delta),
        "mean_oracle_regret_change": float(regret_delta),
        "candidate_wins": bool(utility_delta > 0.0 and regret_delta <= 0.0),
    }
