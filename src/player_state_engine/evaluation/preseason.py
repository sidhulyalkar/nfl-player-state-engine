from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from math import ceil

import numpy as np
import pandas as pd
from sklearn.metrics import mean_pinball_loss

from player_state_engine.config import ModelConfig
from player_state_engine.evaluation.metrics import evaluate_quantiles
from player_state_engine.fantasy.preseason import PRESEASON_TARGETS, preseason_feature_columns
from player_state_engine.models.quantile import TARGET_POSITIONS, QuantileModelBundle


@dataclass(frozen=True, slots=True)
class PreseasonPromotionGate:
    primary_target: str = "fantasy_points_ppr"
    min_primary_pinball_improvement_pct: float = 1.0
    max_component_pinball_regression_pct: float = 2.0
    min_primary_season_win_rate: float = 0.60
    max_primary_position_regression_pct: float = 3.0
    max_primary_rookie_regression_pct: float = 5.0
    min_rookie_rows: int = 75
    bootstrap_samples: int = 5000
    random_state: int = 42
    require_positive_season_bootstrap_ci: bool = True


@dataclass(frozen=True, slots=True)
class PreseasonGateDecision:
    approved: bool
    blockers: tuple[str, ...]
    metrics: dict[str, float]
    policy: dict[str, object]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(slots=True)
class PreseasonBenchmarkResult:
    predictions: pd.DataFrame
    summary_metrics: pd.DataFrame
    season_metrics: pd.DataFrame
    position_metrics: pd.DataFrame
    rookie_metrics: pd.DataFrame
    comparisons: pd.DataFrame
    gate: PreseasonGateDecision


_METHOD_ENGINE = "preseason_quantile_engine"
_METHOD_PRIOR = "prior_season_shrunk"
_METHOD_POSITION = "position_rookie_prior"


def _clip_monotonic(values: np.ndarray) -> np.ndarray:
    return np.sort(np.clip(values.astype(float), 0.0, None))


def _eligible(frame: pd.DataFrame, target: str) -> pd.DataFrame:
    positions = TARGET_POSITIONS.get(target)
    if not positions or "position" not in frame:
        return frame
    return frame.loc[frame["position"].isin(positions)].copy()


def _cohort_quantiles(
    train: pd.DataFrame,
    test: pd.DataFrame,
    target: str,
    quantiles: tuple[float, ...],
) -> pd.DataFrame:
    """Training-only position x rookie prior with hierarchical fallback."""

    output = test[["season", "player_id", "position", "rookie"]].copy().reset_index(drop=True)
    global_values = pd.to_numeric(train[target], errors="coerce").dropna().to_numpy(dtype=float)
    if not len(global_values):
        raise ValueError(f"No training outcomes for {target}.")

    by_position = {
        str(position): pd.to_numeric(group[target], errors="coerce").dropna().to_numpy(dtype=float)
        for position, group in train.groupby("position", sort=False)
    }
    by_cohort = {
        (str(position), int(rookie)): pd.to_numeric(group[target], errors="coerce")
        .dropna()
        .to_numpy(dtype=float)
        for (position, rookie), group in train.groupby(["position", "rookie"], sort=False)
    }
    predictions = np.zeros((len(output), len(quantiles)), dtype=float)
    for row_index, row in output.iterrows():
        cohort = by_cohort.get((str(row["position"]), int(row["rookie"])), np.array([]))
        position_values = by_position.get(str(row["position"]), np.array([]))
        values = cohort if len(cohort) >= 25 else position_values if len(position_values) >= 25 else global_values
        predictions[row_index] = _clip_monotonic(np.quantile(values, quantiles))
    for index, quantile in enumerate(quantiles):
        output[f"{target}_q{int(round(quantile * 100)):02d}"] = predictions[:, index]
    return output


def _prior_season_baseline(
    train: pd.DataFrame,
    test: pd.DataFrame,
    target: str,
    quantiles: tuple[float, ...],
) -> pd.DataFrame:
    """Prior-season total with training-only residual uncertainty and rookie fallback."""

    fallback = _cohort_quantiles(train, test, target, quantiles)
    output = fallback.copy()
    prior_column = f"prior1_{target}"
    rostered = pd.to_numeric(test.get("prior1_rostered", 0), errors="coerce").fillna(0).gt(0)
    prior_test = pd.to_numeric(test.get(prior_column), errors="coerce")

    train_rostered = pd.to_numeric(train.get("prior1_rostered", 0), errors="coerce").fillna(0).gt(0)
    train_prior = pd.to_numeric(train.get(prior_column), errors="coerce")
    train_actual = pd.to_numeric(train[target], errors="coerce")
    residual_frame = train.loc[train_rostered & train_prior.notna() & train_actual.notna(), ["position"]].copy()
    residual_frame["residual"] = (
        train_actual.loc[residual_frame.index] - train_prior.loc[residual_frame.index]
    )

    for row_index, row in test.reset_index(drop=True).iterrows():
        if not bool(rostered.reset_index(drop=True).iloc[row_index]) or pd.isna(
            prior_test.reset_index(drop=True).iloc[row_index]
        ):
            continue
        base = float(prior_test.reset_index(drop=True).iloc[row_index])
        position_residuals = residual_frame.loc[
            residual_frame["position"].eq(row["position"]), "residual"
        ].to_numpy(dtype=float)
        residuals = (
            position_residuals
            if len(position_residuals) >= 25
            else residual_frame["residual"].to_numpy(dtype=float)
        )
        if not len(residuals):
            continue
        values = _clip_monotonic(base + np.quantile(residuals, quantiles))
        for q_index, quantile in enumerate(quantiles):
            output.loc[row_index, f"{target}_q{int(round(quantile * 100)):02d}"] = values[q_index]
    return output


def _metric_rows(
    predictions: pd.DataFrame,
    *,
    group_columns: tuple[str, ...],
    quantiles: tuple[float, ...],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    grouped = predictions.groupby(["target", "method", *group_columns], dropna=False, sort=False)
    for key, group in grouped:
        if not isinstance(key, tuple):
            key = (key,)
        target = str(key[0])
        pred = pd.DataFrame(index=group.index)
        for quantile in quantiles:
            column = f"prediction_q{int(round(quantile * 100)):02d}"
            pred[f"{target}_q{int(round(quantile * 100)):02d}"] = group[column]
        row: dict[str, object] = {
            "target": target,
            "method": str(key[1]),
            "rows": int(len(group)),
        }
        for index, column in enumerate(group_columns, start=2):
            row[column] = key[index]
        row.update(evaluate_quantiles(group["actual"], pred, target, quantiles))
        rows.append(row)
    return pd.DataFrame(rows)


def _long_predictions(
    test: pd.DataFrame,
    predicted: pd.DataFrame,
    *,
    target: str,
    method: str,
    quantiles: tuple[float, ...],
) -> pd.DataFrame:
    context = test[["season", "player_id", "player_name", "position", "recent_team", "rookie"]].copy().reset_index(drop=True)
    context["target"] = target
    context["method"] = method
    context["actual"] = pd.to_numeric(test[target], errors="coerce").to_numpy(dtype=float)
    for quantile in quantiles:
        label = int(round(quantile * 100))
        context[f"prediction_q{label:02d}"] = pd.to_numeric(
            predicted[f"{target}_q{label:02d}"], errors="coerce"
        ).to_numpy(dtype=float)
    return context


def _mean_row_pinball(frame: pd.DataFrame, quantiles: tuple[float, ...]) -> float:
    losses = []
    actual = frame["actual"].to_numpy(dtype=float)
    for quantile in quantiles:
        prediction = frame[f"prediction_q{int(round(quantile * 100)):02d}"].to_numpy(dtype=float)
        losses.append(mean_pinball_loss(actual, prediction, alpha=quantile))
    return float(np.mean(losses))


def _season_bootstrap(
    predictions: pd.DataFrame,
    *,
    target: str,
    baseline: str,
    quantiles: tuple[float, ...],
    samples: int,
    seed: int,
) -> dict[str, float]:
    subset = predictions.loc[
        predictions["target"].eq(target)
        & predictions["method"].isin([_METHOD_ENGINE, baseline])
    ].copy()
    effects: list[float] = []
    for season, group in subset.groupby("season", sort=True):
        engine = group.loc[group["method"].eq(_METHOD_ENGINE)]
        base = group.loc[group["method"].eq(baseline)]
        if engine.empty or base.empty:
            continue
        effects.append(_mean_row_pinball(base, quantiles) - _mean_row_pinball(engine, quantiles))
    if not effects:
        return {"effect": float("nan"), "ci_low": float("nan"), "ci_high": float("nan"), "p_value": float("nan")}
    values = np.asarray(effects, dtype=float)
    rng = np.random.default_rng(seed)
    draws = np.empty(max(1, int(samples)), dtype=float)
    for index in range(len(draws)):
        draws[index] = float(rng.choice(values, size=len(values), replace=True).mean())
    return {
        "effect": float(values.mean()),
        "ci_low": float(np.quantile(draws, 0.025)),
        "ci_high": float(np.quantile(draws, 0.975)),
        "p_value": float((1 + np.sum(draws <= 0.0)) / (len(draws) + 1)),
    }


def _evaluate_gate(
    result_predictions: pd.DataFrame,
    summary: pd.DataFrame,
    season_metrics: pd.DataFrame,
    position_metrics: pd.DataFrame,
    rookie_metrics: pd.DataFrame,
    comparisons: pd.DataFrame,
    *,
    quantiles: tuple[float, ...],
    policy: PreseasonPromotionGate,
) -> PreseasonGateDecision:
    blockers: list[str] = []
    metrics: dict[str, float] = {}
    primary = policy.primary_target
    primary_comparison = comparisons.loc[comparisons["target"].eq(primary)]
    if primary_comparison.empty:
        blockers.append("PRIMARY_TARGET_UNAVAILABLE")
        return PreseasonGateDecision(False, tuple(blockers), metrics, asdict(policy))

    primary_row = primary_comparison.iloc[0]
    improvement = float(primary_row["pinball_improvement_pct"])
    metrics["primary_pinball_improvement_pct"] = improvement
    if improvement < policy.min_primary_pinball_improvement_pct:
        blockers.append("PRIMARY_PINBALL_IMPROVEMENT_BELOW_THRESHOLD")

    baseline = str(primary_row["best_baseline"])
    season = season_metrics.loc[season_metrics["target"].eq(primary)].copy()
    engine_season = season.loc[season["method"].eq(_METHOD_ENGINE), ["season", "mean_pinball"]]
    base_season = season.loc[season["method"].eq(baseline), ["season", "mean_pinball"]]
    paired = engine_season.merge(base_season, on="season", suffixes=("_engine", "_baseline"))
    win_rate = float((paired["mean_pinball_engine"] < paired["mean_pinball_baseline"]).mean()) if len(paired) else 0.0
    metrics["primary_season_win_rate"] = win_rate
    if win_rate < policy.min_primary_season_win_rate:
        blockers.append("PRIMARY_SEASON_WIN_RATE_BELOW_THRESHOLD")

    bootstrap = _season_bootstrap(
        result_predictions,
        target=primary,
        baseline=baseline,
        quantiles=quantiles,
        samples=policy.bootstrap_samples,
        seed=policy.random_state,
    )
    metrics.update({f"primary_season_bootstrap_{key}": value for key, value in bootstrap.items()})
    if policy.require_positive_season_bootstrap_ci and not bootstrap["ci_low"] > 0.0:
        blockers.append("PRIMARY_SEASON_BOOTSTRAP_CI_NOT_POSITIVE")

    for _, row in comparisons.iterrows():
        if row["target"] == primary:
            continue
        regression = -float(row["pinball_improvement_pct"])
        if regression > policy.max_component_pinball_regression_pct:
            blockers.append(f"COMPONENT_REGRESSION:{row['target']}")

    primary_positions = position_metrics.loc[position_metrics["target"].eq(primary)]
    for position, group in primary_positions.groupby("position", sort=False):
        engine = group.loc[group["method"].eq(_METHOD_ENGINE)]
        base = group.loc[group["method"].eq(baseline)]
        if engine.empty or base.empty or float(base.iloc[0]["mean_pinball"]) <= 0:
            continue
        regression_pct = 100.0 * (
            float(engine.iloc[0]["mean_pinball"]) - float(base.iloc[0]["mean_pinball"])
        ) / float(base.iloc[0]["mean_pinball"])
        if regression_pct > policy.max_primary_position_regression_pct:
            blockers.append(f"PRIMARY_POSITION_REGRESSION:{position}")

    rookies = rookie_metrics.loc[
        rookie_metrics["target"].eq(primary) & rookie_metrics["rookie"].eq(1)
    ]
    engine_rookie = rookies.loc[rookies["method"].eq(_METHOD_ENGINE)]
    base_rookie = rookies.loc[rookies["method"].eq(baseline)]
    if (
        not engine_rookie.empty
        and not base_rookie.empty
        and int(engine_rookie.iloc[0]["rows"]) >= policy.min_rookie_rows
        and float(base_rookie.iloc[0]["mean_pinball"]) > 0
    ):
        regression_pct = 100.0 * (
            float(engine_rookie.iloc[0]["mean_pinball"])
            - float(base_rookie.iloc[0]["mean_pinball"])
        ) / float(base_rookie.iloc[0]["mean_pinball"])
        metrics["primary_rookie_regression_pct"] = regression_pct
        if regression_pct > policy.max_primary_rookie_regression_pct:
            blockers.append("PRIMARY_ROOKIE_REGRESSION")

    return PreseasonGateDecision(
        approved=not blockers,
        blockers=tuple(dict.fromkeys(blockers)),
        metrics=metrics,
        policy=asdict(policy),
    )


def run_preseason_season_benchmark(
    dataset: pd.DataFrame,
    *,
    model_config: ModelConfig | None = None,
    targets: tuple[str, ...] = PRESEASON_TARGETS,
    min_train_seasons: int = 4,
    gate_policy: PreseasonPromotionGate | None = None,
) -> PreseasonBenchmarkResult:
    """Run expanding-season preseason evaluation with baselines fitted only on earlier years."""

    config = model_config or ModelConfig(targets=targets)
    config = replace(config, targets=tuple(targets))
    quantiles = tuple(sorted(float(value) for value in config.quantiles))
    seasons = sorted(int(value) for value in dataset["season"].dropna().unique())
    if len(seasons) <= min_train_seasons:
        raise ValueError("Not enough seasons for expanding preseason holdouts.")

    parts: list[pd.DataFrame] = []
    for index in range(min_train_seasons, len(seasons)):
        test_season = seasons[index]
        train = dataset.loc[dataset["season"].isin(seasons[:index])].copy()
        test = dataset.loc[dataset["season"].eq(test_season)].copy()
        features = preseason_feature_columns(train)
        if not features:
            raise ValueError("Preseason benchmark has no season-start feature columns.")
        bundle = QuantileModelBundle(config).fit(train, features, targets)
        engine = bundle.predict(test)

        for target in targets:
            eligible_test = _eligible(test, target).reset_index(drop=True)
            if eligible_test.empty:
                continue
            eligible_index = test.reset_index(drop=True)["position"].isin(
                TARGET_POSITIONS.get(target, set(test["position"].unique()))
            )
            engine_target = engine.loc[eligible_index].reset_index(drop=True)
            prior = _prior_season_baseline(train, eligible_test, target, quantiles)
            position = _cohort_quantiles(train, eligible_test, target, quantiles)
            parts.extend(
                [
                    _long_predictions(
                        eligible_test,
                        engine_target,
                        target=target,
                        method=_METHOD_ENGINE,
                        quantiles=quantiles,
                    ),
                    _long_predictions(
                        eligible_test,
                        prior,
                        target=target,
                        method=_METHOD_PRIOR,
                        quantiles=quantiles,
                    ),
                    _long_predictions(
                        eligible_test,
                        position,
                        target=target,
                        method=_METHOD_POSITION,
                        quantiles=quantiles,
                    ),
                ]
            )

    predictions = pd.concat(parts, ignore_index=True)
    summary = _metric_rows(predictions, group_columns=(), quantiles=quantiles)
    season_metrics = _metric_rows(predictions, group_columns=("season",), quantiles=quantiles)
    position_metrics = _metric_rows(predictions, group_columns=("position",), quantiles=quantiles)
    rookie_metrics = _metric_rows(predictions, group_columns=("rookie",), quantiles=quantiles)

    comparison_rows: list[dict[str, object]] = []
    for target, group in summary.groupby("target", sort=False):
        engine = group.loc[group["method"].eq(_METHOD_ENGINE)].iloc[0]
        baselines = group.loc[group["method"].ne(_METHOD_ENGINE)].sort_values("mean_pinball")
        baseline = baselines.iloc[0]
        baseline_pinball = float(baseline["mean_pinball"])
        improvement = (
            100.0 * (baseline_pinball - float(engine["mean_pinball"])) / baseline_pinball
            if baseline_pinball > 0
            else 0.0
        )
        comparison_rows.append(
            {
                "target": target,
                "best_baseline": baseline["method"],
                "engine_mean_pinball": float(engine["mean_pinball"]),
                "baseline_mean_pinball": baseline_pinball,
                "pinball_improvement_pct": float(improvement),
                "engine_mae": float(engine.get("mae", np.nan)),
                "baseline_mae": float(baseline.get("mae", np.nan)),
                "engine_interval_coverage": float(engine.get("interval_coverage", np.nan)),
                "baseline_interval_coverage": float(baseline.get("interval_coverage", np.nan)),
            }
        )
    comparisons = pd.DataFrame(comparison_rows)
    gate = _evaluate_gate(
        predictions,
        summary,
        season_metrics,
        position_metrics,
        rookie_metrics,
        comparisons,
        quantiles=quantiles,
        policy=gate_policy or PreseasonPromotionGate(),
    )
    return PreseasonBenchmarkResult(
        predictions=predictions,
        summary_metrics=summary,
        season_metrics=season_metrics,
        position_metrics=position_metrics,
        rookie_metrics=rookie_metrics,
        comparisons=comparisons,
        gate=gate,
    )
