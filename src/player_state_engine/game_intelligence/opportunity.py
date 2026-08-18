from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

import numpy as np
import pandas as pd

_CONTEXT_COLUMNS = (
    "red_zone",
    "third_down",
    "early_down",
    "late_game",
    "score_state",
    "distance_bucket",
    "field_zone",
)


def _chronology(frame: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(frame["season"], errors="coerce") * 25 + pd.to_numeric(
        frame["week"], errors="coerce"
    )


def _context_frame(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    down = pd.to_numeric(data.get("down"), errors="coerce")
    score = pd.to_numeric(data.get("score_differential"), errors="coerce").fillna(0.0)
    clock = pd.to_numeric(data.get("game_seconds_remaining"), errors="coerce").fillna(3600.0)
    yardline = pd.to_numeric(data.get("yardline_100"), errors="coerce")
    ydstogo = pd.to_numeric(data.get("ydstogo"), errors="coerce")

    if "red_zone" not in data:
        data["red_zone"] = (yardline <= 20).astype(float)
    data["third_down"] = down.eq(3).astype(float)
    data["early_down"] = down.le(2).astype(float)
    data["late_game"] = clock.le(900).astype(float)
    data["score_state"] = np.select(
        [score <= -8, score >= 8],
        ["trailing", "leading"],
        default="neutral",
    )
    if "distance_bucket" not in data:
        data["distance_bucket"] = np.select(
            [ydstogo <= 2, ydstogo <= 6, ydstogo <= 10],
            [0, 1, 2],
            default=3,
        )
    if "field_zone" not in data:
        data["field_zone"] = np.select(
            [yardline <= 20, yardline <= 40, yardline <= 60, yardline <= 80],
            [0, 1, 2, 3],
            default=4,
        )
    return data


def _events(frame: pd.DataFrame) -> pd.DataFrame:
    data = _context_frame(frame)
    rows: list[pd.DataFrame] = []
    if {"play_family", "rusher_player_id"} <= set(data):
        rush = data.loc[data["play_family"].eq("RUSH") & data["rusher_player_id"].notna()].copy()
        if not rush.empty:
            rush["player_id"] = rush["rusher_player_id"].astype(str)
            rush["opportunity_type"] = "carry"
            rows.append(rush)
    if {"play_family", "receiver_player_id"} <= set(data):
        target = data.loc[
            data["play_family"].eq("DROPBACK") & data["receiver_player_id"].notna()
        ].copy()
        if not target.empty:
            target["player_id"] = target["receiver_player_id"].astype(str)
            target["opportunity_type"] = "target"
            rows.append(target)
    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True, sort=False)


def _normalize(weights: pd.Series) -> pd.Series:
    values = pd.to_numeric(weights, errors="coerce").fillna(0.0).clip(lower=0.0)
    total = float(values.sum())
    if total <= 0:
        return pd.Series(1.0 / max(len(values), 1), index=values.index, dtype=float)
    return values / total


@dataclass(slots=True)
class StateConditionedOpportunityModel:
    """Hierarchical empirical carry/target allocator with point-in-time recency weighting.

    The model keeps player identity explicit and shrinks every situational distribution toward
    the team's recent base allocation. It is intentionally transparent and is evaluated as an
    isolated challenger before it is allowed to alter Monte Carlo game paths.
    """

    prior_strength: float = 12.0
    half_life_weeks: float = 4.0
    context_columns: tuple[str, ...] = _CONTEXT_COLUMNS
    fitted: bool = False
    train_max_season: int | None = None
    train_max_week: int | None = None
    base_counts: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)
    context_counts: dict[str, pd.DataFrame] = field(default_factory=dict, repr=False)

    def fit(self, play_frame: pd.DataFrame) -> StateConditionedOpportunityModel:
        required = {"season", "week", "posteam", "play_family"}
        missing = required - set(play_frame)
        if missing:
            raise ValueError(f"Opportunity model missing columns: {sorted(missing)}")
        events = _events(play_frame)
        if len(events) < 30:
            raise ValueError("Opportunity model requires at least 30 labeled carry/target events")

        ordinal = _chronology(events)
        latest = int(ordinal.max())
        age = (latest - ordinal).clip(lower=0)
        events["recency_weight"] = np.power(
            0.5,
            age / max(float(self.half_life_weeks), 0.25),
        )
        events["team"] = events["posteam"].astype(str)

        self.base_counts = (
            events.groupby(["team", "opportunity_type", "player_id"], dropna=False)
            .agg(weight=("recency_weight", "sum"), events=("player_id", "size"))
            .reset_index()
        )
        self.context_counts = {}
        for column in self.context_columns:
            if column not in events:
                continue
            table = (
                events.groupby(
                    ["team", "opportunity_type", column, "player_id"],
                    dropna=False,
                )
                .agg(weight=("recency_weight", "sum"), events=("player_id", "size"))
                .reset_index()
            )
            self.context_counts[column] = table

        cutoff = events[["season", "week"]].copy()
        cutoff["season"] = pd.to_numeric(cutoff["season"], errors="coerce")
        cutoff["week"] = pd.to_numeric(cutoff["week"], errors="coerce")
        cutoff = cutoff.dropna().sort_values(["season", "week"], kind="mergesort")
        if not cutoff.empty:
            latest_row = cutoff.iloc[-1]
            self.train_max_season = int(latest_row["season"])
            self.train_max_week = int(latest_row["week"])
        self.fitted = True
        return self

    def _base_distribution(self, team: str, opportunity_type: str) -> pd.DataFrame:
        if not self.fitted:
            raise RuntimeError("Opportunity model must be fitted before prediction")
        pool = self.base_counts.loc[
            self.base_counts["team"].astype(str).eq(str(team))
            & self.base_counts["opportunity_type"].eq(str(opportunity_type))
        ].copy()
        if pool.empty:
            return pd.DataFrame(columns=["player_id", "probability", "base_probability"])
        pool["base_probability"] = _normalize(pool["weight"])
        pool["probability"] = pool["base_probability"]
        return pool[["player_id", "probability", "base_probability"]].reset_index(drop=True)

    def distribution(
        self,
        *,
        team: str,
        opportunity_type: str,
        state: pd.Series | dict[str, object] | None = None,
        use_context: bool = True,
    ) -> pd.DataFrame:
        """Return a normalized player allocation distribution for one play state."""
        base = self._base_distribution(team, opportunity_type)
        if base.empty or not use_context or state is None:
            result = base.copy()
            if not result.empty:
                result["context_evidence"] = 0.0
            return result

        if isinstance(state, pd.Series):
            state_dict = state.to_dict()
        else:
            state_dict = dict(state)
        state_frame = _context_frame(pd.DataFrame([state_dict])).iloc[0]
        index = pd.Index(base["player_id"].astype(str), name="player_id")
        base_probability = pd.Series(
            base["base_probability"].to_numpy(dtype=float),
            index=index,
        )
        numerator = base_probability.copy()
        denominator = 1.0
        context_evidence = 0.0

        for column, table in self.context_counts.items():
            if column not in state_frame or pd.isna(state_frame[column]):
                continue
            value = state_frame[column]
            subset = table.loc[
                table["team"].astype(str).eq(str(team))
                & table["opportunity_type"].eq(str(opportunity_type))
                & table[column].astype(str).eq(str(value))
            ].copy()
            if subset.empty:
                continue
            evidence = float(pd.to_numeric(subset["weight"], errors="coerce").fillna(0).sum())
            alpha = evidence / (evidence + max(float(self.prior_strength), 1e-6))
            if alpha <= 0:
                continue
            conditional = subset.set_index(subset["player_id"].astype(str))["weight"]
            conditional = conditional.reindex(index, fill_value=0.0)
            conditional = _normalize(conditional)
            numerator = numerator.add(alpha * conditional, fill_value=0.0)
            denominator += alpha
            context_evidence += alpha

        probability = _normalize(numerator / denominator)
        result = pd.DataFrame(
            {
                "player_id": index.astype(str),
                "probability": probability.to_numpy(dtype=float),
                "base_probability": base_probability.to_numpy(dtype=float),
                "context_evidence": context_evidence,
            }
        )
        return result.sort_values("probability", ascending=False, kind="mergesort").reset_index(
            drop=True
        )

    def score_events(
        self,
        play_frame: pd.DataFrame,
        *,
        use_context: bool = True,
    ) -> pd.DataFrame:
        """Score realized carries/targets without using their outcome identity as a feature."""
        events = _events(play_frame)
        rows: list[dict[str, object]] = []
        for _, row in events.iterrows():
            distribution = self.distribution(
                team=str(row["posteam"]),
                opportunity_type=str(row["opportunity_type"]),
                state=row,
                use_context=use_context,
            )
            if distribution.empty:
                continue
            actual = str(row["player_id"])
            probability_map = distribution.set_index("player_id")["probability"]
            base_map = distribution.set_index("player_id")["base_probability"]
            actual_probability = float(probability_map.get(actual, 1e-9))
            base_probability = float(base_map.get(actual, 1e-9))
            ranked = distribution["player_id"].astype(str).tolist()
            rows.append(
                {
                    "season": int(row["season"]),
                    "week": int(row["week"]),
                    "game_id": str(row.get("game_id", "")),
                    "team": str(row["posteam"]),
                    "opportunity_type": str(row["opportunity_type"]),
                    "actual_player_id": actual,
                    "actual_probability": max(actual_probability, 1e-9),
                    "base_probability": max(base_probability, 1e-9),
                    "top1_hit": float(bool(ranked) and ranked[0] == actual),
                    "top3_hit": float(actual in ranked[:3]),
                    "context_evidence": float(
                        distribution["context_evidence"].iloc[0]
                        if "context_evidence" in distribution
                        else 0.0
                    ),
                }
            )
        return pd.DataFrame(rows)

    def expected_opportunity_from_realized_states(
        self,
        play_frame: pd.DataFrame,
        *,
        use_context: bool = True,
    ) -> pd.DataFrame:
        """Isolate allocation quality by conditioning on the realized sequence of play states.

        This is deliberately *not* a deployable pregame forecast. It is an oracle-state diagnostic:
        team play volume and play family are held fixed to reality so only player allocation is tested.
        """
        events = _events(play_frame)
        totals: dict[tuple[str, str, str], dict[str, float]] = {}
        for _, row in events.iterrows():
            distribution = self.distribution(
                team=str(row["posteam"]),
                opportunity_type=str(row["opportunity_type"]),
                state=row,
                use_context=use_context,
            )
            for _, player in distribution.iterrows():
                key = (str(row.get("game_id", "")), str(row["posteam"]), str(player["player_id"]))
                record = totals.setdefault(key, {"carries": 0.0, "targets": 0.0})
                column = "carries" if row["opportunity_type"] == "carry" else "targets"
                record[column] += float(player["probability"])
        rows = [
            {
                "game_id": game_id,
                "team": team,
                "player_id": player_id,
                **values,
            }
            for (game_id, team, player_id), values in totals.items()
        ]
        return pd.DataFrame(rows)


def evaluate_opportunity_event_scores(scores: pd.DataFrame) -> dict[str, float]:
    if scores.empty:
        raise ValueError("No scored opportunity events")
    actual_probability = pd.to_numeric(scores["actual_probability"], errors="coerce").clip(1e-9, 1.0)
    base_probability = pd.to_numeric(scores["base_probability"], errors="coerce").clip(1e-9, 1.0)
    valid = actual_probability.notna() & base_probability.notna()
    if not valid.any():
        raise ValueError("No valid opportunity probabilities")
    actual_probability = actual_probability.loc[valid]
    base_probability = base_probability.loc[valid]
    result = {
        "event_rows": float(valid.sum()),
        "state_conditioned_log_loss": float(-np.log(actual_probability).mean()),
        "static_share_log_loss": float(-np.log(base_probability).mean()),
        "state_conditioned_mean_actual_probability": float(actual_probability.mean()),
        "static_share_mean_actual_probability": float(base_probability.mean()),
        "top1_hit_rate": float(pd.to_numeric(scores.loc[valid, "top1_hit"], errors="coerce").mean()),
        "top3_hit_rate": float(pd.to_numeric(scores.loc[valid, "top3_hit"], errors="coerce").mean()),
        "mean_context_evidence": float(
            pd.to_numeric(scores.loc[valid, "context_evidence"], errors="coerce").fillna(0.0).mean()
        ),
    }
    for opportunity_type, subset in scores.loc[valid].groupby("opportunity_type", sort=False):
        probability = pd.to_numeric(subset["actual_probability"], errors="coerce").clip(1e-9, 1.0)
        baseline = pd.to_numeric(subset["base_probability"], errors="coerce").clip(1e-9, 1.0)
        prefix = str(opportunity_type)
        result[f"{prefix}_rows"] = float(len(subset))
        result[f"{prefix}_state_log_loss"] = float(-np.log(probability).mean())
        result[f"{prefix}_static_log_loss"] = float(-np.log(baseline).mean())
    return result


def evaluate_expected_opportunity(
    predicted: pd.DataFrame,
    observed: pd.DataFrame,
) -> dict[str, float]:
    required = {"game_id", "player_id", "carries", "targets"}
    missing_predicted = required - set(predicted)
    missing_observed = required - set(observed)
    if missing_predicted:
        raise ValueError(f"Predicted opportunity missing: {sorted(missing_predicted)}")
    if missing_observed:
        raise ValueError(f"Observed opportunity missing: {sorted(missing_observed)}")
    joined = observed.merge(
        predicted,
        on=["game_id", "player_id"],
        how="outer",
        suffixes=("_actual", "_pred"),
    ).fillna(0.0)
    if joined.empty:
        raise ValueError("No opportunity rows to evaluate")
    carry_error = np.abs(
        pd.to_numeric(joined["carries_actual"], errors="coerce").fillna(0.0)
        - pd.to_numeric(joined["carries_pred"], errors="coerce").fillna(0.0)
    )
    target_error = np.abs(
        pd.to_numeric(joined["targets_actual"], errors="coerce").fillna(0.0)
        - pd.to_numeric(joined["targets_pred"], errors="coerce").fillna(0.0)
    )
    return {
        "player_rows": float(len(joined)),
        "carries_mae": float(carry_error.mean()),
        "targets_mae": float(target_error.mean()),
        "opportunity_mae": float((carry_error + target_error).mean() / 2.0),
    }


def observed_opportunity_from_events(play_frame: pd.DataFrame) -> pd.DataFrame:
    events = _events(play_frame)
    if events.empty:
        return pd.DataFrame(columns=["game_id", "player_id", "carries", "targets"])
    events["carries"] = events["opportunity_type"].eq("carry").astype(float)
    events["targets"] = events["opportunity_type"].eq("target").astype(float)
    return (
        events.groupby(["game_id", "player_id"], dropna=False)[["carries", "targets"]]
        .sum()
        .reset_index()
    )


def concat_metric_frames(frames: Iterable[pd.DataFrame]) -> pd.DataFrame:
    valid = [frame for frame in frames if frame is not None and not frame.empty]
    return pd.concat(valid, ignore_index=True) if valid else pd.DataFrame()
