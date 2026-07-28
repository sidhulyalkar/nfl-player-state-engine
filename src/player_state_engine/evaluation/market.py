from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

_Z90 = float(norm.ppf(0.9))


def american_to_implied_probability(odds: float) -> float:
    odds = float(odds)
    if odds == 0:
        raise ValueError("American odds cannot be zero.")
    if odds > 0:
        return 100.0 / (odds + 100.0)
    return -odds / (-odds + 100.0)


def american_profit_per_dollar(odds: float) -> float:
    odds = float(odds)
    if odds > 0:
        return odds / 100.0
    return 100.0 / -odds


def remove_two_way_vig(over_odds: float, under_odds: float) -> tuple[float, float]:
    over = american_to_implied_probability(over_odds)
    under = american_to_implied_probability(under_odds)
    total = over + under
    return over / total, under / total


def probability_above_line(line: float, q10: float, q50: float, q90: float) -> float:
    low_scale = max((q50 - q10) / _Z90, 1e-6)
    high_scale = max((q90 - q50) / _Z90, 1e-6)
    scale = low_scale if line < q50 else high_scale
    return float(1.0 - norm.cdf((line - q50) / scale))


def expected_value_per_dollar(probability: float, odds: float) -> float:
    profit = american_profit_per_dollar(odds)
    return float(probability * profit - (1.0 - probability))


def score_prop_board(predictions: pd.DataFrame, props: pd.DataFrame) -> pd.DataFrame:
    """Score a timestamped prop board without placing bets.

    Required prop columns: player_id, target, line, over_odds, under_odds.
    The function intentionally does not fetch odds or execute wagers.
    """
    required = {"player_id", "target", "line", "over_odds", "under_odds"}
    missing = required - set(props.columns)
    if missing:
        raise ValueError(f"Prop board missing columns: {sorted(missing)}")

    prediction_index = predictions.set_index("player_id", drop=False)
    rows: list[dict[str, object]] = []
    for _, prop in props.iterrows():
        player_id = str(prop["player_id"])
        target = str(prop["target"])
        if player_id not in prediction_index.index:
            continue
        player = prediction_index.loc[player_id]
        if isinstance(player, pd.DataFrame):
            player = player.iloc[0]
        columns = [f"{target}_q10", f"{target}_q50", f"{target}_q90"]
        if not all(column in predictions.columns for column in columns):
            continue
        q10, q50, q90 = (float(player[column]) for column in columns)
        line = float(prop["line"])
        over_probability = probability_above_line(line, q10, q50, q90)
        under_probability = 1.0 - over_probability
        market_over, market_under = remove_two_way_vig(
            float(prop["over_odds"]), float(prop["under_odds"])
        )
        over_ev = expected_value_per_dollar(over_probability, float(prop["over_odds"]))
        under_ev = expected_value_per_dollar(under_probability, float(prop["under_odds"]))
        side = "over" if over_ev >= under_ev else "under"
        rows.append(
            {
                **{
                    column: player[column]
                    for column in (
                        "season",
                        "week",
                        "game_id",
                        "player_id",
                        "player_name",
                        "recent_team",
                        "opponent_team",
                        "position",
                    )
                    if column in player.index
                },
                "target": target,
                "line": line,
                "over_odds": float(prop["over_odds"]),
                "under_odds": float(prop["under_odds"]),
                "model_over_probability": over_probability,
                "model_under_probability": under_probability,
                "market_no_vig_over_probability": market_over,
                "market_no_vig_under_probability": market_under,
                "over_probability_edge": over_probability - market_over,
                "under_probability_edge": under_probability - market_under,
                "over_ev_per_dollar": over_ev,
                "under_ev_per_dollar": under_ev,
                "preferred_side": side,
                "preferred_ev_per_dollar": max(over_ev, under_ev),
            }
        )
    if not rows:
        return pd.DataFrame()
    return (
        pd.DataFrame(rows)
        .sort_values("preferred_ev_per_dollar", ascending=False)
        .reset_index(drop=True)
    )


def settle_paper_ledger(scored_props: pd.DataFrame, outcomes: pd.DataFrame) -> pd.DataFrame:
    """Settle recommendations against outcomes for research-only tracking.

    Outcomes require player_id, target and actual. Pushes return zero profit.
    """
    required = {"player_id", "target", "actual"}
    missing = required - set(outcomes.columns)
    if missing:
        raise ValueError(f"Outcomes missing columns: {sorted(missing)}")
    ledger = scored_props.merge(outcomes[list(required)], on=["player_id", "target"], how="left")

    def settle(row: pd.Series) -> pd.Series:
        if pd.isna(row["actual"]):
            return pd.Series({"result": "unsettled", "profit_per_dollar": np.nan})
        if float(row["actual"]) == float(row["line"]):
            return pd.Series({"result": "push", "profit_per_dollar": 0.0})
        won = (row["preferred_side"] == "over" and row["actual"] > row["line"]) or (
            row["preferred_side"] == "under" and row["actual"] < row["line"]
        )
        odds = row["over_odds"] if row["preferred_side"] == "over" else row["under_odds"]
        return pd.Series(
            {
                "result": "win" if won else "loss",
                "profit_per_dollar": american_profit_per_dollar(odds) if won else -1.0,
            }
        )

    return pd.concat([ledger, ledger.apply(settle, axis=1)], axis=1)
