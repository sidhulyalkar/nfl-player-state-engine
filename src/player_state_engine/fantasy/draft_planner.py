from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(slots=True)
class TwoTurnDraftPlan:
    player_id: str
    player_name: str
    position: str
    current_value: float
    expected_next_pick_value: float
    expected_two_pick_value: float
    two_pick_q10: float
    two_pick_q50: float
    two_pick_q90: float
    probability_no_preferred_target_survives: float
    most_common_next_targets: list[dict[str, object]]
    simulations: int
    model_source: str = "two_turn_survival_lookahead_research_v1"
    promoted: bool = False

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _numeric(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(default)


def plan_two_turn_draft(
    board: pd.DataFrame,
    candidate_player_ids: Iterable[str],
    *,
    value_column: str = "decision_specific_score",
    survival_column: str = "survival_to_next_pick",
    simulations: int = 2000,
    seed: int = 42,
    next_pick_pool: int = 80,
) -> list[TwoTurnDraftPlan]:
    """Approximate current-pick + next-turn value under draft-room survival uncertainty.

    This is deliberately a research challenger. It does not yet rebuild every opponent roster or
    re-run the manager's full roster counterfactual after each simulated intervening pick. Its
    purpose is to make the value of waiting measurable and to generate a testable path toward a
    full expected-marginal-draft-utility planner.
    """
    required = {"player_id", "player_name", "position", value_column}
    missing = required - set(board)
    if missing:
        raise ValueError(f"Two-turn planner missing board columns: {sorted(missing)}")
    simulations = max(200, min(int(simulations), 20000))
    data = board.copy()
    data["_value"] = _numeric(data, value_column)
    data["_survival"] = _numeric(data, survival_column, 0.5).clip(0.0, 1.0)
    requested = [str(player_id) for player_id in candidate_player_ids]
    candidates = data.loc[data["player_id"].astype(str).isin(requested)].copy()
    found = set(candidates["player_id"].astype(str))
    missing_candidates = [player_id for player_id in requested if player_id not in found]
    if missing_candidates:
        raise ValueError(f"Candidates are not on the available board: {missing_candidates}")

    results: list[TwoTurnDraftPlan] = []
    order = {player_id: index for index, player_id in enumerate(requested)}
    for candidate_index, candidate in candidates.iterrows():
        candidate_id = str(candidate["player_id"])
        current_value = float(candidate["_value"])
        alternatives = data.loc[data["player_id"].astype(str).ne(candidate_id)].copy()
        alternatives = alternatives.sort_values("_value", ascending=False).head(int(next_pick_pool))
        if alternatives.empty:
            results.append(
                TwoTurnDraftPlan(
                    player_id=candidate_id,
                    player_name=str(candidate["player_name"]),
                    position=str(candidate["position"]),
                    current_value=current_value,
                    expected_next_pick_value=0.0,
                    expected_two_pick_value=current_value,
                    two_pick_q10=current_value,
                    two_pick_q50=current_value,
                    two_pick_q90=current_value,
                    probability_no_preferred_target_survives=1.0,
                    most_common_next_targets=[],
                    simulations=simulations,
                )
            )
            continue

        rng = np.random.default_rng(seed + int(candidate_index) * 104729)
        survival = alternatives["_survival"].to_numpy(dtype=float)
        values = alternatives["_value"].to_numpy(dtype=float)
        player_ids = alternatives["player_id"].astype(str).to_numpy()
        names = alternatives["player_name"].astype(str).to_numpy()
        positions = alternatives["position"].astype(str).to_numpy()
        survive = rng.random((simulations, len(alternatives))) < survival
        masked_values = np.where(survive, values[None, :], -np.inf)
        best_indexes = np.argmax(masked_values, axis=1)
        has_survivor = survive.any(axis=1)
        next_values = np.where(
            has_survivor,
            masked_values[np.arange(simulations), best_indexes],
            0.0,
        )
        two_pick_values = current_value + next_values

        target_counts: dict[int, int] = {}
        for best_index, available in zip(best_indexes, has_survivor, strict=False):
            if available:
                index = int(best_index)
                target_counts[index] = target_counts.get(index, 0) + 1
        common = sorted(target_counts.items(), key=lambda item: item[1], reverse=True)[:5]
        most_common = [
            {
                "player_id": str(player_ids[index]),
                "player_name": str(names[index]),
                "position": str(positions[index]),
                "probability_selected_next": count / simulations,
                "value": float(values[index]),
                "survival_to_next_pick": float(survival[index]),
            }
            for index, count in common
        ]
        q10, q50, q90 = np.quantile(two_pick_values, [0.10, 0.50, 0.90])
        results.append(
            TwoTurnDraftPlan(
                player_id=candidate_id,
                player_name=str(candidate["player_name"]),
                position=str(candidate["position"]),
                current_value=current_value,
                expected_next_pick_value=float(next_values.mean()),
                expected_two_pick_value=float(two_pick_values.mean()),
                two_pick_q10=float(q10),
                two_pick_q50=float(q50),
                two_pick_q90=float(q90),
                probability_no_preferred_target_survives=float((~has_survivor).mean()),
                most_common_next_targets=most_common,
                simulations=simulations,
            )
        )
    results.sort(key=lambda item: order.get(item.player_id, len(order)))
    return results
