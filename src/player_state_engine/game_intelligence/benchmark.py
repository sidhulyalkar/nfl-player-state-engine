from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.opportunity import (
    StateConditionedOpportunityModel,
    evaluate_expected_opportunity,
    evaluate_opportunity_event_scores,
    observed_opportunity_from_events,
)
from player_state_engine.game_intelligence.play_features import build_play_intelligence_frame
from player_state_engine.game_intelligence.replay import GameReplayResult, frozen_game_replay
from player_state_engine.game_intelligence.schema import SimulationPromotionDecision

_LOWER_IS_BETTER = {
    "play_call_log_loss",
    "play_call_brier",
    "team_plays_mae",
    "team_pass_rate_mae",
    "team_points_mae",
    "player_carries_mae",
    "player_targets_mae",
    "player_opportunity_mae",
    "fantasy_median_mae",
    "fantasy_pinball_loss",
}


@dataclass(slots=True)
class ExpandingGameBenchmarkResult:
    weekly_game_metrics: pd.DataFrame
    weekly_opportunity_metrics: pd.DataFrame
    candidate_metrics: dict[str, float]
    baseline_metrics: dict[str, float]
    opportunity_candidate_metrics: dict[str, float]
    opportunity_baseline_metrics: dict[str, float]
    diagnostics: dict[str, object]


def _chronology(frame: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(frame["season"], errors="coerce") * 25 + pd.to_numeric(
        frame["week"], errors="coerce"
    )


def _metric_weight(metric: str, values: dict[str, float]) -> float:
    if metric.startswith("fantasy_"):
        return max(float(values.get("fantasy_rows", 0.0)), 1.0)
    if metric.startswith("player_"):
        return max(float(values.get("player_rows", 0.0)), 1.0)
    if metric.startswith("play_call_") or metric.startswith("team_"):
        return max(float(values.get("games", 0.0)), 1.0)
    return max(float(values.get("games", 0.0)), 1.0)


def _aggregate_metric_dicts(records: list[dict[str, float]]) -> dict[str, float]:
    if not records:
        return {}
    keys = sorted({key for record in records for key in record})
    totals = {"games", "player_rows", "fantasy_rows"}
    result: dict[str, float] = {}
    for key in keys:
        values: list[tuple[float, float]] = []
        for record in records:
            value = record.get(key)
            if value is None or not np.isfinite(value):
                continue
            values.append((float(value), _metric_weight(key, record)))
        if not values:
            continue
        if key in totals:
            result[key] = float(sum(value for value, _ in values))
        else:
            numerator = sum(value * weight for value, weight in values)
            denominator = sum(weight for _, weight in values)
            result[key] = float(numerator / denominator)
    return result


def _aggregate_opportunity_metrics(records: list[dict[str, float]]) -> dict[str, float]:
    if not records:
        return {}
    keys = sorted({key for record in records for key in record})
    totals = {"event_rows", "carry_rows", "target_rows", "player_rows"}
    result: dict[str, float] = {}
    for key in keys:
        observations: list[tuple[float, float]] = []
        for record in records:
            value = record.get(key)
            if value is None or not np.isfinite(value):
                continue
            if key.startswith("carry_"):
                weight = max(float(record.get("carry_rows", 0.0)), 1.0)
            elif key.startswith("target_"):
                weight = max(float(record.get("target_rows", 0.0)), 1.0)
            elif key in {"carries_mae", "targets_mae", "opportunity_mae"}:
                weight = max(float(record.get("player_rows", 0.0)), 1.0)
            else:
                weight = max(float(record.get("event_rows", 0.0)), 1.0)
            observations.append((float(value), weight))
        if not observations:
            continue
        if key in totals:
            result[key] = float(sum(value for value, _ in observations))
        else:
            result[key] = float(
                sum(value * weight for value, weight in observations)
                / sum(weight for _, weight in observations)
            )
    return result


def _fold_delta_rows(
    *,
    season: int,
    week: int,
    candidate: dict[str, float],
    baseline: dict[str, float],
) -> dict[str, float | int]:
    row: dict[str, float | int] = {"season": int(season), "week": int(week)}
    for key in sorted(set(candidate) & set(baseline)):
        c = candidate[key]
        b = baseline[key]
        if not np.isfinite(c) or not np.isfinite(b):
            continue
        row[f"candidate_{key}"] = float(c)
        row[f"baseline_{key}"] = float(b)
        row[f"delta_{key}"] = float(c - b)
        if key in _LOWER_IS_BETTER:
            row[f"win_{key}"] = float(c < b)
    return row


def _opportunity_fold(
    play_frame: pd.DataFrame,
    *,
    season: int,
    week: int,
    prior_strength: float,
    half_life_weeks: float,
) -> tuple[dict[str, float], dict[str, float]] | None:
    split = int(season) * 25 + int(week)
    chronology = _chronology(play_frame)
    train = play_frame.loc[chronology < split].copy()
    test = play_frame.loc[
        (pd.to_numeric(play_frame["season"], errors="coerce") == int(season))
        & (pd.to_numeric(play_frame["week"], errors="coerce") == int(week))
    ].copy()
    if len(train) < 30 or test.empty:
        return None
    model = StateConditionedOpportunityModel(
        prior_strength=float(prior_strength),
        half_life_weeks=float(half_life_weeks),
    ).fit(train)
    scores = model.score_events(test, use_context=True)
    if scores.empty:
        return None
    event_metrics = evaluate_opportunity_event_scores(scores)
    observed = observed_opportunity_from_events(test)
    candidate_expected = model.expected_opportunity_from_realized_states(test, use_context=True)
    baseline_expected = model.expected_opportunity_from_realized_states(test, use_context=False)
    candidate_allocation = evaluate_expected_opportunity(candidate_expected, observed)
    baseline_allocation = evaluate_expected_opportunity(baseline_expected, observed)

    candidate = {
        "event_rows": event_metrics["event_rows"],
        "carry_rows": event_metrics.get("carry_rows", 0.0),
        "target_rows": event_metrics.get("target_rows", 0.0),
        "allocation_log_loss": event_metrics["state_conditioned_log_loss"],
        "mean_actual_probability": event_metrics["state_conditioned_mean_actual_probability"],
        "top1_hit_rate": event_metrics["top1_hit_rate"],
        "top3_hit_rate": event_metrics["top3_hit_rate"],
        "mean_context_evidence": event_metrics["mean_context_evidence"],
        **candidate_allocation,
    }
    baseline = {
        "event_rows": event_metrics["event_rows"],
        "carry_rows": event_metrics.get("carry_rows", 0.0),
        "target_rows": event_metrics.get("target_rows", 0.0),
        "allocation_log_loss": event_metrics["static_share_log_loss"],
        "mean_actual_probability": event_metrics["static_share_mean_actual_probability"],
        **baseline_allocation,
    }
    for opportunity_type in ("carry", "target"):
        state_key = f"{opportunity_type}_state_log_loss"
        static_key = f"{opportunity_type}_static_log_loss"
        if state_key in event_metrics:
            candidate[f"{opportunity_type}_allocation_log_loss"] = event_metrics[state_key]
        if static_key in event_metrics:
            baseline[f"{opportunity_type}_allocation_log_loss"] = event_metrics[static_key]
    return candidate, baseline


def run_expanding_game_benchmark(
    pbp: pd.DataFrame,
    schedules: pd.DataFrame,
    *,
    test_seasons: tuple[int, ...] | list[int],
    week_start: int = 1,
    week_end: int = 18,
    players: pd.DataFrame | None = None,
    player_actuals: pd.DataFrame | None = None,
    league_config: LeagueConfig | None = None,
    simulations_per_game: int = 100,
    max_games_per_week: int | None = None,
    seed: int = 42,
    opportunity_prior_strength: float = 12.0,
    opportunity_half_life_weeks: float = 4.0,
) -> ExpandingGameBenchmarkResult:
    """Replay every week with an expanding point-in-time training cutoff.

    Each fold trains on information available strictly before that week. This is materially
    different from fitting once before an entire season and is the canonical v0.11 continual-
    learning evaluation protocol.
    """
    play_frame = build_play_intelligence_frame(pbp)
    weekly_game_rows: list[dict[str, float | int]] = []
    weekly_opportunity_rows: list[dict[str, float | int]] = []
    candidate_records: list[dict[str, float]] = []
    baseline_records: list[dict[str, float]] = []
    opportunity_candidate_records: list[dict[str, float]] = []
    opportunity_baseline_records: list[dict[str, float]] = []
    skipped: list[dict[str, object]] = []

    for season in sorted({int(value) for value in test_seasons}):
        for week in range(int(week_start), int(week_end) + 1):
            schedule_fold = schedules.loc[
                (pd.to_numeric(schedules["season"], errors="coerce") == int(season))
                & (pd.to_numeric(schedules["week"], errors="coerce") == int(week))
            ]
            if schedule_fold.empty:
                continue
            try:
                replay: GameReplayResult = frozen_game_replay(
                    pbp,
                    schedules,
                    test_season=season,
                    test_week_start=week,
                    test_week_end=week,
                    players=players,
                    player_actuals=player_actuals,
                    league_config=league_config,
                    simulations_per_game=int(simulations_per_game),
                    max_games=max_games_per_week,
                    seed=int(seed + season * 101 + week * 1009),
                )
            except ValueError as exc:
                skipped.append({"season": season, "week": week, "layer": "game", "reason": str(exc)})
            else:
                candidate_records.append(replay.candidate_metrics)
                baseline_records.append(replay.baseline_metrics)
                weekly_game_rows.append(
                    _fold_delta_rows(
                        season=season,
                        week=week,
                        candidate=replay.candidate_metrics,
                        baseline=replay.baseline_metrics,
                    )
                )

            try:
                opportunity_fold = _opportunity_fold(
                    play_frame,
                    season=season,
                    week=week,
                    prior_strength=float(opportunity_prior_strength),
                    half_life_weeks=float(opportunity_half_life_weeks),
                )
            except ValueError as exc:
                skipped.append(
                    {"season": season, "week": week, "layer": "opportunity", "reason": str(exc)}
                )
                opportunity_fold = None
            if opportunity_fold is not None:
                candidate_opportunity, baseline_opportunity = opportunity_fold
                opportunity_candidate_records.append(candidate_opportunity)
                opportunity_baseline_records.append(baseline_opportunity)
                row: dict[str, float | int] = {"season": season, "week": week}
                for key in sorted(set(candidate_opportunity) & set(baseline_opportunity)):
                    c = float(candidate_opportunity[key])
                    b = float(baseline_opportunity[key])
                    row[f"candidate_{key}"] = c
                    row[f"baseline_{key}"] = b
                    row[f"delta_{key}"] = c - b
                    if key.endswith("_mae") or key.endswith("log_loss"):
                        row[f"win_{key}"] = float(c < b)
                weekly_opportunity_rows.append(row)

    if not candidate_records:
        raise ValueError("Expanding benchmark produced no valid game replay folds")

    weekly_game = pd.DataFrame(weekly_game_rows).sort_values(
        ["season", "week"], kind="mergesort"
    ).reset_index(drop=True)
    weekly_opportunity = pd.DataFrame(weekly_opportunity_rows)
    if not weekly_opportunity.empty:
        weekly_opportunity = weekly_opportunity.sort_values(
            ["season", "week"], kind="mergesort"
        ).reset_index(drop=True)

    candidate_metrics = _aggregate_metric_dicts(candidate_records)
    baseline_metrics = _aggregate_metric_dicts(baseline_records)
    opportunity_candidate = _aggregate_opportunity_metrics(opportunity_candidate_records)
    opportunity_baseline = _aggregate_opportunity_metrics(opportunity_baseline_records)

    diagnostics: dict[str, object] = {
        "protocol": "expanding_weekly_point_in_time_v011",
        "test_seasons": sorted({int(value) for value in test_seasons}),
        "week_start": int(week_start),
        "week_end": int(week_end),
        "game_folds": int(len(weekly_game)),
        "opportunity_folds": int(len(weekly_opportunity)),
        "simulations_per_game": int(simulations_per_game),
        "opportunity_challenger": "hierarchical_state_conditioned_allocator_v011",
        "opportunity_evaluation_boundary": (
            "allocation benchmark conditions on realized play states and is diagnostic, not a deployable pregame forecast"
        ),
        "skipped_folds": skipped,
    }
    return ExpandingGameBenchmarkResult(
        weekly_game_metrics=weekly_game,
        weekly_opportunity_metrics=weekly_opportunity,
        candidate_metrics=candidate_metrics,
        baseline_metrics=baseline_metrics,
        opportunity_candidate_metrics=opportunity_candidate,
        opportunity_baseline_metrics=opportunity_baseline,
        diagnostics=diagnostics,
    )


def _win_rate(frame: pd.DataFrame, metric: str) -> float | None:
    column = f"win_{metric}"
    if column not in frame or frame.empty:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.mean()) if not values.empty else None


def v011_research_promotion_gate(
    benchmark: ExpandingGameBenchmarkResult,
    *,
    min_seasons: int = 3,
    min_games: int = 200,
    min_weekly_core_win_rate: float = 0.55,
    max_core_regression_ratio: float = 1.02,
    min_allocation_log_loss_improvement: float = 0.002,
) -> SimulationPromotionDecision:
    """Fail closed until game and opportunity challengers win across time, not one aggregate."""
    reasons: list[str] = []
    candidate = benchmark.candidate_metrics
    baseline = benchmark.baseline_metrics
    opportunity = benchmark.opportunity_candidate_metrics
    opportunity_baseline = benchmark.opportunity_baseline_metrics

    seasons = benchmark.weekly_game_metrics["season"].nunique() if not benchmark.weekly_game_metrics.empty else 0
    if seasons < int(min_seasons):
        reasons.append(f"insufficient held-out seasons: {seasons} < {min_seasons}")
    games = int(candidate.get("games", 0.0))
    if games < int(min_games):
        reasons.append(f"insufficient replay games: {games} < {min_games}")

    candidate_log_loss = candidate.get("play_call_log_loss")
    baseline_log_loss = baseline.get("play_call_log_loss")
    if candidate_log_loss is None or baseline_log_loss is None:
        reasons.append("missing play-call log-loss comparison")
    elif candidate_log_loss >= baseline_log_loss:
        reasons.append("play-call challenger did not beat the profile baseline")

    core_metrics = (
        "team_plays_mae",
        "team_pass_rate_mae",
        "team_points_mae",
        "player_opportunity_mae",
    )
    for metric in core_metrics:
        c = candidate.get(metric)
        b = baseline.get(metric)
        if c is None or b is None:
            reasons.append(f"missing core replay metric: {metric}")
            continue
        if b > 0 and c > b * float(max_core_regression_ratio):
            reasons.append(f"{metric} regressed more than allowed")
        win_rate = _win_rate(benchmark.weekly_game_metrics, metric)
        if win_rate is not None and win_rate < float(min_weekly_core_win_rate):
            reasons.append(
                f"{metric} weekly win rate too low: {win_rate:.3f} < {min_weekly_core_win_rate:.3f}"
            )

    allocation = opportunity.get("allocation_log_loss")
    allocation_baseline = opportunity_baseline.get("allocation_log_loss")
    if allocation is None or allocation_baseline is None:
        reasons.append("missing state-conditioned opportunity log-loss comparison")
    elif allocation > allocation_baseline - float(min_allocation_log_loss_improvement):
        reasons.append("state-conditioned opportunity head did not clear log-loss improvement gate")

    candidate_fantasy = candidate.get("fantasy_pinball_loss")
    baseline_fantasy = baseline.get("fantasy_pinball_loss")
    if candidate_fantasy is None or baseline_fantasy is None:
        reasons.append("missing downstream fantasy pinball evidence")
    elif candidate_fantasy > baseline_fantasy:
        reasons.append("downstream fantasy pinball loss regressed")

    coverage = candidate.get("fantasy_q10_q90_coverage")
    if coverage is None:
        reasons.append("missing fantasy interval coverage")
    elif not 0.74 <= coverage <= 0.92:
        reasons.append(f"fantasy interval coverage outside research band: {coverage:.3f}")

    metrics = {
        **{f"game_{key}": float(value) for key, value in candidate.items() if np.isfinite(value)},
        **{
            f"opportunity_{key}": float(value)
            for key, value in opportunity.items()
            if np.isfinite(value)
        },
    }
    return SimulationPromotionDecision(promoted=not reasons, reasons=reasons, metrics=metrics)
