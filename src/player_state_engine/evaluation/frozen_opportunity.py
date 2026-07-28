from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OrdinalEncoder

KEYS = [
    "season",
    "week",
    "game_id",
    "player_id",
    "player_name",
    "recent_team",
    "opponent_team",
    "position",
]
VOLUME_TARGETS = [
    "carries",
    "targets",
    "receptions",
    "receiving_yards",
    "rushing_yards",
    "passing_yards",
]
QUANTILES = (0.1, 0.5, 0.9)


@dataclass(slots=True)
class FrozenAblationResult:
    predictions: pd.DataFrame
    summary: pd.DataFrame
    season_metrics: pd.DataFrame
    feature_manifest: pd.DataFrame


def load_frozen_prediction_panel(root: str | Path) -> pd.DataFrame:
    """Reconstruct a player-week panel from frozen v0.3/v0.4 OOS predictions."""
    root = Path(root)
    fantasy_path = root / "fantasy_points_ppr" / "fantasy_points_ppr_predictions.csv"
    fantasy = pd.read_csv(fantasy_path)
    fantasy = fantasy.loc[fantasy["method"].eq("quantile_engine")].copy()
    fantasy = fantasy.rename(columns={"actual": "actual_fantasy_points_ppr"})
    keep = [
        *KEYS,
        "fantasy_points_ppr_q10",
        "fantasy_points_ppr_q50",
        "fantasy_points_ppr_q90",
        "actual_fantasy_points_ppr",
    ]
    panel = fantasy[keep].copy()

    for target in VOLUME_TARGETS:
        path = root / target / f"{target}_predictions.csv"
        frame = pd.read_csv(path)
        frame = frame.loc[frame["method"].eq("quantile_engine"), [*KEYS, "actual"]]
        frame = frame.rename(columns={"actual": f"actual_{target}"})
        panel = panel.merge(frame, on=KEYS, how="left", validate="one_to_one")

    panel["week_index"] = panel["season"].astype(int) * 25 + panel["week"].astype(int)
    panel = panel.sort_values(["player_id", "week_index", "game_id"]).reset_index(drop=True)
    return panel


def _rolling_features(
    panel: pd.DataFrame, columns: Iterable[str], windows: tuple[int, ...] = (3, 5, 8)
) -> pd.DataFrame:
    data = panel.copy()
    generated: dict[str, pd.Series] = {}
    for column in columns:
        values = pd.to_numeric(data[column], errors="coerce")
        shifted = values.groupby(data["player_id"], sort=False).shift(1)
        generated[f"history_{column}_lag1"] = shifted
        shifted_group = shifted.groupby(data["player_id"], sort=False)
        for window in windows:
            roll = shifted_group.rolling(window, min_periods=1)
            generated[f"history_{column}_roll{window}_mean"] = (
                roll.mean().reset_index(level=0, drop=True).reindex(data.index)
            )
            generated[f"history_{column}_roll{window}_std"] = (
                roll.std(ddof=0).reset_index(level=0, drop=True).reindex(data.index)
            )
        generated[f"history_{column}_ewm5"] = shifted_group.transform(
            lambda s: s.ewm(span=5, adjust=False, min_periods=1).mean()
        )
    return pd.concat([data, pd.DataFrame(generated, index=data.index)], axis=1)


def build_frozen_opportunity_features(panel: pd.DataFrame) -> pd.DataFrame:
    """Build strictly lagged opportunity and participation-history features.

    This is an objective historical-opportunity experiment. It does not claim to
    contain official injury designations, practice reports, or inactive lists.
    """
    data = panel.copy()
    if "week_index" not in data:
        data["week_index"] = data["season"].astype(int) * 25 + data["week"].astype(int)
    volume = [f"actual_{name}" for name in VOLUME_TARGETS]
    for column in volume + ["actual_fantasy_points_ppr"]:
        data[column] = pd.to_numeric(data[column], errors="coerce").fillna(0.0)

    data["observed_active"] = (
        data[["actual_carries", "actual_targets", "actual_receptions", "actual_passing_yards"]]
        .abs()
        .sum(axis=1)
        .gt(0)
    ).astype(float)

    team_keys = ["season", "week", "recent_team"]
    data["team_carries"] = data.groupby(team_keys)["actual_carries"].transform("sum")
    data["team_targets"] = data.groupby(team_keys)["actual_targets"].transform("sum")
    data["team_fantasy"] = data.groupby(team_keys)["actual_fantasy_points_ppr"].transform("sum")
    data["actual_carry_share"] = np.where(
        data["team_carries"] > 0, data["actual_carries"] / data["team_carries"], 0.0
    )
    data["actual_target_share"] = np.where(
        data["team_targets"] > 0, data["actual_targets"] / data["team_targets"], 0.0
    )
    data["actual_fantasy_share"] = np.where(
        data["team_fantasy"].abs() > 0,
        data["actual_fantasy_points_ppr"] / data["team_fantasy"],
        0.0,
    )

    history_columns = [
        *volume,
        "actual_fantasy_points_ppr",
        "observed_active",
        "actual_carry_share",
        "actual_target_share",
        "actual_fantasy_share",
        "team_carries",
        "team_targets",
    ]
    data = _rolling_features(data, history_columns)

    data["opportunity_target_trend"] = (
        data["history_actual_targets_roll3_mean"] - data["history_actual_targets_roll8_mean"]
    )
    data["opportunity_carry_trend"] = (
        data["history_actual_carries_roll3_mean"] - data["history_actual_carries_roll8_mean"]
    )
    data["opportunity_fantasy_trend"] = (
        data["history_actual_fantasy_points_ppr_roll3_mean"]
        - data["history_actual_fantasy_points_ppr_roll8_mean"]
    )
    data["availability_recent_active_rate"] = data["history_observed_active_roll5_mean"]
    data["availability_previous_active"] = data["history_observed_active_lag1"]

    previous_week = data.groupby("player_id", sort=False)["week_index"].shift(1)
    data["availability_gap_weeks"] = (data["week_index"] - previous_week - 1).clip(lower=0)
    data["availability_history_missing"] = (
        data["availability_recent_active_rate"].isna().astype(int)
    )
    data["role_high_chance_score"] = (
        0.40 * data["history_actual_target_share_roll3_mean"].fillna(0)
        + 0.35 * data["history_actual_carry_share_roll3_mean"].fillna(0)
        + 0.15 * data["availability_recent_active_rate"].fillna(0)
        + 0.10 * np.tanh(data["opportunity_fantasy_trend"].fillna(0) / 5.0)
    )
    return data


def _pipeline(frame: pd.DataFrame, features: list[str]) -> Pipeline:
    numeric = [c for c in features if pd.api.types.is_numeric_dtype(frame[c])]
    categorical = [c for c in features if c not in numeric]
    transformers = []
    if numeric:
        transformers.append(("num", SimpleImputer(strategy="median", add_indicator=True), numeric))
    if categorical:
        transformers.append(
            (
                "cat",
                Pipeline(
                    [
                        ("impute", SimpleImputer(strategy="most_frequent")),
                        (
                            "encode",
                            OrdinalEncoder(handle_unknown="use_encoded_value", unknown_value=-1),
                        ),
                    ]
                ),
                categorical,
            )
        )
    return Pipeline(
        [
            ("pre", ColumnTransformer(transformers, remainder="drop")),
            (
                "model",
                HistGradientBoostingRegressor(
                    loss="squared_error",
                    max_iter=150,
                    learning_rate=0.035,
                    max_leaf_nodes=15,
                    min_samples_leaf=45,
                    l2_regularization=5.0,
                    random_state=42,
                ),
            ),
        ]
    )


def _pinball(y: np.ndarray, pred: np.ndarray, q: float) -> float:
    err = y - pred
    return float(np.mean(np.maximum(q * err, (q - 1.0) * err)))


def _evaluate(frame: pd.DataFrame, method: str) -> dict[str, float | str | int]:
    y = frame["actual_fantasy_points_ppr"].to_numpy(float)
    q10 = frame["adjusted_q10"].to_numpy(float)
    q50 = frame["adjusted_q50"].to_numpy(float)
    q90 = frame["adjusted_q90"].to_numpy(float)
    return {
        "method": method,
        "rows": len(frame),
        "mae": float(np.mean(np.abs(y - q50))),
        "rmse": float(np.sqrt(np.mean((y - q50) ** 2))),
        "mean_pinball": float(
            np.mean([_pinball(y, q10, 0.1), _pinball(y, q50, 0.5), _pinball(y, q90, 0.9)])
        ),
        "interval_coverage": float(np.mean((y >= q10) & (y <= q90))),
        "interval_width": float(np.mean(q90 - q10)),
    }


def run_frozen_opportunity_ablation(panel: pd.DataFrame) -> FrozenAblationResult:
    data = build_frozen_opportunity_features(panel)
    base = [
        "position",
        "fantasy_points_ppr_q10",
        "fantasy_points_ppr_q50",
        "fantasy_points_ppr_q90",
    ]
    availability = [c for c in data if c.startswith("availability_")]
    objective = [
        c
        for c in data
        if c.startswith("history_actual_")
        or c.startswith("opportunity_")
        or c == "role_high_chance_score"
    ]
    combined = [*objective, *availability]
    variants = {
        "numerical_baseline": (data, []),
        "participation_history_proxy": (data, availability),
        "objective_opportunity": (data, objective),
        "objective_plus_participation": (data, combined),
    }
    shuffled = data.copy()
    rng = np.random.default_rng(42)
    for _, index in shuffled.groupby(["season", "week", "position"], dropna=False).groups.items():
        index = np.asarray(list(index))
        if len(index) > 1:
            permutation = rng.permutation(index)
            shuffled.loc[index, combined] = shuffled.loc[permutation, combined].to_numpy()
    shifted = data.sort_values(["player_id", "season", "week"]).copy()
    shifted[combined] = shifted.groupby("player_id", sort=False)[combined].shift(-1)
    variants["shuffled_player_control"] = (shuffled, combined)
    variants["shifted_time_leakage_control"] = (shifted, combined)

    predictions: list[pd.DataFrame] = []
    seasons = sorted(data["season"].unique())
    for test_season in seasons[1:]:
        for method, (working_data, extra) in variants.items():
            train = working_data.loc[working_data["season"] < test_season].copy()
            test = working_data.loc[working_data["season"] == test_season].copy()
            out = test[
                KEYS
                + [
                    "actual_fantasy_points_ppr",
                    "fantasy_points_ppr_q10",
                    "fantasy_points_ppr_q50",
                    "fantasy_points_ppr_q90",
                ]
            ].copy()
            out["method"] = method
            out["test_season"] = test_season
            if not extra:
                shift = np.zeros(len(test))
            else:
                features = list(dict.fromkeys([*base, *extra]))
                model = _pipeline(train, features)
                residual = train["actual_fantasy_points_ppr"] - train["fantasy_points_ppr_q50"]
                model.fit(train[features], residual)
                raw_shift = model.predict(test[features])
                half_width = (
                    (test["fantasy_points_ppr_q90"] - test["fantasy_points_ppr_q10"]) / 2.0
                ).clip(lower=1.0)
                shift = np.clip(raw_shift, -0.30 * half_width, 0.30 * half_width)
            out["center_shift"] = shift
            out["adjusted_q10"] = np.maximum(
                test["fantasy_points_ppr_q10"].to_numpy() + np.asarray(shift), 0.0
            )
            out["adjusted_q50"] = np.maximum(
                test["fantasy_points_ppr_q50"].to_numpy() + np.asarray(shift), 0.0
            )
            out["adjusted_q90"] = np.maximum(
                test["fantasy_points_ppr_q90"].to_numpy() + np.asarray(shift), 0.0
            )
            predictions.append(out)

    pred = pd.concat(predictions, ignore_index=True)
    summary = pd.DataFrame([_evaluate(group, method) for method, group in pred.groupby("method")])
    baseline = float(
        summary.loc[summary["method"].eq("numerical_baseline"), "mean_pinball"].iloc[0]
    )
    summary["pinball_improvement_vs_baseline_pct"] = (
        100.0 * (baseline - summary["mean_pinball"]) / baseline
    )
    summary = summary.sort_values("mean_pinball").reset_index(drop=True)

    season_rows = []
    for (method, season), group in pred.groupby(["method", "test_season"]):
        row = _evaluate(group, method)
        row["season"] = season
        season_rows.append(row)
    season_metrics = pd.DataFrame(season_rows)

    manifest_rows = []
    for name, (_, cols) in variants.items():
        for column in cols:
            manifest_rows.append({"ablation": name, "feature": column})
    manifest = pd.DataFrame(manifest_rows)
    return FrozenAblationResult(pred, summary, season_metrics, manifest)


def persist_frozen_ablation(
    result: FrozenAblationResult, output_dir: str | Path
) -> dict[str, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "predictions": output_dir / "frozen_opportunity_predictions.csv",
        "summary": output_dir / "frozen_opportunity_summary.csv",
        "season_metrics": output_dir / "frozen_opportunity_season_metrics.csv",
        "feature_manifest": output_dir / "frozen_opportunity_feature_manifest.csv",
    }
    result.predictions.to_csv(paths["predictions"], index=False)
    result.summary.to_csv(paths["summary"], index=False)
    result.season_metrics.to_csv(paths["season_metrics"], index=False)
    result.feature_manifest.to_csv(paths["feature_manifest"], index=False)
    return paths
