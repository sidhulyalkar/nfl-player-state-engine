from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.drive import (
    DriveVolumeModel,
    evaluate_drive_volume_draws,
    observed_drive_volume,
)
from player_state_engine.game_intelligence.evaluation import (
    evaluate_play_call_probabilities,
    evaluate_player_opportunity,
    evaluate_team_simulation_draws,
)
from player_state_engine.game_intelligence.models import EmpiricalPlayOutcomeModel, PlayCallModel
from player_state_engine.game_intelligence.opportunity import StateConditionedOpportunityModel
from player_state_engine.game_intelligence.play_features import build_play_intelligence_frame
from player_state_engine.game_intelligence.replay import (
    _combine_metrics,
    _fantasy_metrics,
    matchup_from_schedule,
    observed_player_opportunity,
    observed_team_games,
    predicted_player_opportunity_from_draws,
)
from player_state_engine.game_intelligence.schema import (
    SimulationConfig,
    SimulationPromotionDecision,
)
from player_state_engine.game_intelligence.tendencies import (
    attach_point_in_time_matchup_features,
    build_team_tendency_snapshots,
)
from player_state_engine.game_intelligence.transition import (
    PossessionTransitionModel,
    build_possession_transition_frame,
    evaluate_field_goal_scores,
    evaluate_transition_event_scores,
    evaluate_transition_team_draws,
    extract_field_goal_attempts,
    observed_transition_team_games,
    permute_field_goal_results_within_distance_season,
    permute_transition_targets_within_type_season,
)
from player_state_engine.game_intelligence.transition_simulator import (
    simulate_matchup_transition_probe,
)
from player_state_engine.game_intelligence.usage import build_player_usage_profiles

_VARIANTS = {
    "legacy_drive_legacy_transition": (False, False),
    "drive_legacy_transition": (True, False),
    "legacy_drive_transition": (False, True),
    "drive_transition": (True, True),
}
_LOWER_IS_BETTER = {
    "team_plays_mae",
    "team_pass_rate_mae",
    "team_points_mae",
    "player_carries_mae",
    "player_targets_mae",
    "player_opportunity_mae",
    "fantasy_median_mae",
    "fantasy_pinball_loss",
    "team_drives_mae",
    "team_plays_per_drive_mae",
    "team_seconds_per_play_mae",
    "team_start_yardline_mae",
    "team_punts_mae",
    "team_field_goal_attempts_mae",
    "team_field_goals_made_mae",
    "team_turnovers_mae",
    "team_turnovers_on_downs_mae",
}


@dataclass(slots=True)
class TransitionBenchmarkResult:
    weekly_metrics: pd.DataFrame
    aggregate_metrics: dict[str, dict[str, float]]
    weekly_isolated_metrics: pd.DataFrame
    aggregate_isolated_metrics: dict[str, float]
    diagnostics: dict[str, object]


def _chronology(frame: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(frame["season"], errors="coerce") * 25 + pd.to_numeric(
        frame["week"], errors="coerce"
    )


def _aggregate(records: list[dict[str, float]]) -> dict[str, float]:
    if not records:
        return {}
    totals = {
        "games",
        "player_rows",
        "predicted_player_rows",
        "observed_player_rows",
        "fantasy_rows",
        "drive_team_rows",
        "transition_team_rows",
    }
    keys = sorted({key for record in records for key in record})
    result: dict[str, float] = {}
    for key in keys:
        values: list[tuple[float, float]] = []
        for record in records:
            value = record.get(key)
            if value is None or not np.isfinite(value):
                continue
            if key.startswith("fantasy_"):
                weight = max(float(record.get("fantasy_rows", 0.0)), 1.0)
            elif key.startswith("player_"):
                weight = max(float(record.get("player_rows", 0.0)), 1.0)
            elif key.startswith("team_") and key in {
                "team_drives_mae",
                "team_plays_per_drive_mae",
                "team_seconds_per_play_mae",
                "team_start_yardline_mae",
            }:
                weight = max(float(record.get("drive_team_rows", 0.0)), 1.0)
            elif key.startswith("team_") and key in {
                "team_punts_mae",
                "team_field_goal_attempts_mae",
                "team_field_goals_made_mae",
                "team_turnovers_mae",
                "team_turnovers_on_downs_mae",
            }:
                weight = max(float(record.get("transition_team_rows", 0.0)), 1.0)
            else:
                weight = max(float(record.get("games", 0.0)), 1.0)
            values.append((float(value), weight))
        if not values:
            continue
        if key in totals:
            result[key] = float(sum(value for value, _ in values))
        else:
            denominator = sum(weight for _, weight in values)
            result[key] = float(
                sum(value * weight for value, weight in values) / max(denominator, 1e-12)
            )
    return result


def _aggregate_isolated(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty:
        return {}
    result: dict[str, float] = {}
    weight_columns = {
        "transition": "transition_rows",
        "field_goal": "field_goal_rows",
    }
    for column in frame.columns:
        if column in {"season", "week"}:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        valid = values.notna()
        if not valid.any():
            continue
        prefix = "field_goal" if column.startswith("field_goal") else "transition"
        weight_column = weight_columns[prefix]
        weights = pd.to_numeric(frame.loc[valid, weight_column], errors="coerce").fillna(1.0)
        if column in {"transition_rows", "transition_start_rows", "transition_seconds_rows", "field_goal_rows"}:
            result[column] = float(values[valid].sum())
        else:
            result[column] = float(
                np.average(values[valid].to_numpy(dtype=float), weights=weights.to_numpy(dtype=float))
            )
    return result


def _safe_ratio(candidate: float | None, baseline: float | None) -> float | None:
    if (
        candidate is None
        or baseline is None
        or not np.isfinite(candidate)
        or not np.isfinite(baseline)
        or abs(float(baseline)) < 1e-12
    ):
        return None
    return float(candidate) / float(baseline)


def _effect_columns(
    row: dict[str, float | int],
    metrics: dict[str, dict[str, float]],
) -> None:
    comparisons = {
        "transition_on_drive": ("drive_transition", "drive_legacy_transition"),
        "transition_without_drive": ("legacy_drive_transition", "legacy_drive_legacy_transition"),
        "drive_with_transition": ("drive_transition", "legacy_drive_transition"),
        "combined": ("drive_transition", "legacy_drive_legacy_transition"),
    }
    for effect, (candidate_name, baseline_name) in comparisons.items():
        candidate = metrics[candidate_name]
        baseline = metrics[baseline_name]
        for metric in sorted(set(candidate) & set(baseline)):
            c = candidate[metric]
            b = baseline[metric]
            if not np.isfinite(c) or not np.isfinite(b):
                continue
            row[f"delta_{effect}__{metric}"] = float(c - b)
            if metric in _LOWER_IS_BETTER:
                row[f"win_{effect}__{metric}"] = float(c < b)


def run_v014_transition_benchmark(
    pbp: pd.DataFrame,
    schedules: pd.DataFrame,
    *,
    test_seasons: tuple[int, ...] | list[int],
    week_start: int = 1,
    week_end: int = 18,
    players: pd.DataFrame | None = None,
    player_actuals: pd.DataFrame | None = None,
    league_config: LeagueConfig | None = None,
    simulations_per_game: int = 15,
    max_games_per_week: int | None = None,
    seed: int = 42,
    opportunity_prior_strength: float = 12.0,
    opportunity_half_life_weeks: float = 4.0,
    drive_prior_strength: float = 24.0,
    drive_half_life_weeks: float = 6.0,
    transition_prior_strength: float = 18.0,
    transition_half_life_weeks: float = 8.0,
) -> TransitionBenchmarkResult:
    """Run weekly expanding four-cell transition attribution on point-in-time history."""
    play_frame = build_play_intelligence_frame(pbp)
    tendencies = build_team_tendency_snapshots(play_frame)
    enriched = attach_point_in_time_matchup_features(play_frame, tendencies)
    play_chronology = _chronology(enriched)
    raw = pbp.copy()
    if "game_id" not in raw and "nflverse_game_id" in raw:
        raw["game_id"] = raw["nflverse_game_id"]
    raw_chronology = _chronology(raw)

    records: dict[str, list[dict[str, float]]] = {name: [] for name in _VARIANTS}
    weekly_rows: list[dict[str, float | int]] = []
    isolated_rows: list[dict[str, float | int]] = []
    skipped: list[dict[str, object]] = []

    for season in sorted({int(value) for value in test_seasons}):
        for week in range(int(week_start), int(week_end) + 1):
            schedule_fold = schedules.loc[
                (pd.to_numeric(schedules["season"], errors="coerce") == season)
                & (pd.to_numeric(schedules["week"], errors="coerce") == week)
            ].dropna(subset=["home_team", "away_team"])
            if max_games_per_week is not None:
                schedule_fold = schedule_fold.head(int(max_games_per_week))
            if schedule_fold.empty:
                continue

            split = season * 25 + week
            train = enriched.loc[play_chronology < split].copy()
            test_plays = enriched.loc[
                (pd.to_numeric(enriched["season"], errors="coerce") == season)
                & (pd.to_numeric(enriched["week"], errors="coerce") == week)
            ].copy()
            train_raw = raw.loc[raw_chronology < split].copy()
            test_raw = raw.loc[
                (pd.to_numeric(raw["season"], errors="coerce") == season)
                & (pd.to_numeric(raw["week"], errors="coerce") == week)
            ].copy()
            if len(train) < 50 or test_plays.empty or train_raw.empty or test_raw.empty:
                skipped.append(
                    {"season": season, "week": week, "reason": "insufficient pre-cutoff evidence"}
                )
                continue

            try:
                play_call_model = PlayCallModel().fit(train)
                outcome_model = EmpiricalPlayOutcomeModel().fit(train)
                opportunity_model = StateConditionedOpportunityModel(
                    prior_strength=opportunity_prior_strength,
                    half_life_weeks=opportunity_half_life_weeks,
                ).fit(train)
                drive_model = DriveVolumeModel(
                    prior_strength=drive_prior_strength,
                    half_life_weeks=drive_half_life_weeks,
                ).fit(train)
                transition_model = PossessionTransitionModel(
                    prior_strength=transition_prior_strength,
                    half_life_weeks=transition_half_life_weeks,
                ).fit(train_raw)
                transition_frame = build_possession_transition_frame(train_raw)
                field_goals = extract_field_goal_attempts(train_raw)
                permuted_transition_model = PossessionTransitionModel(
                    prior_strength=transition_prior_strength,
                    half_life_weeks=transition_half_life_weeks,
                ).fit_frames(
                    permute_transition_targets_within_type_season(
                        transition_frame,
                        seed=int(seed + season * 193 + week * 1009),
                    ),
                    permute_field_goal_results_within_distance_season(
                        field_goals,
                        seed=int(seed + season * 389 + week * 2027),
                    ),
                )
            except ValueError as exc:
                skipped.append({"season": season, "week": week, "reason": str(exc)})
                continue

            isolated: dict[str, float | int] = {"season": season, "week": week}
            try:
                real_transition = evaluate_transition_event_scores(
                    transition_model.score_transition_events(test_raw)
                )
                permuted_transition = evaluate_transition_event_scores(
                    permuted_transition_model.score_transition_events(test_raw)
                )
                isolated.update(real_transition)
                isolated["permuted_transition_start_yardline_mae"] = float(
                    permuted_transition["transition_start_yardline_mae"]
                )
                isolated["permuted_transition_seconds_mae"] = float(
                    permuted_transition["transition_seconds_mae"]
                )
                isolated["real_start_beats_type_base"] = float(
                    real_transition["transition_start_yardline_mae"]
                    < real_transition["type_base_start_yardline_mae"]
                )
                isolated["real_start_beats_permuted"] = float(
                    real_transition["transition_start_yardline_mae"]
                    < permuted_transition["transition_start_yardline_mae"]
                )
                isolated["real_seconds_beats_type_base"] = float(
                    real_transition["transition_seconds_mae"]
                    < real_transition["type_base_transition_seconds_mae"]
                )
                isolated["real_seconds_beats_permuted"] = float(
                    real_transition["transition_seconds_mae"]
                    < permuted_transition["transition_seconds_mae"]
                )
            except ValueError:
                pass
            try:
                real_field_goal = evaluate_field_goal_scores(
                    transition_model.score_field_goals(test_raw)
                )
                permuted_field_goal = evaluate_field_goal_scores(
                    permuted_transition_model.score_field_goals(test_raw)
                )
                isolated.update(real_field_goal)
                isolated["permuted_field_goal_log_loss"] = float(
                    permuted_field_goal["field_goal_log_loss"]
                )
                isolated["permuted_field_goal_brier"] = float(
                    permuted_field_goal["field_goal_brier"]
                )
                isolated["real_fg_beats_distance_base"] = float(
                    real_field_goal["field_goal_log_loss"]
                    < real_field_goal["field_goal_base_log_loss"]
                )
                isolated["real_fg_beats_permuted"] = float(
                    real_field_goal["field_goal_log_loss"]
                    < permuted_field_goal["field_goal_log_loss"]
                )
            except ValueError:
                pass
            if len(isolated) > 2:
                isolated_rows.append(isolated)

            usage = build_player_usage_profiles(
                play_frame,
                season=season,
                week=week,
                players=players,
            )
            if usage.empty:
                skipped.append({"season": season, "week": week, "reason": "empty point-in-time usage"})
                continue

            variant_team_draws: dict[str, list[pd.DataFrame]] = {
                name: [] for name in _VARIANTS
            }
            variant_player_draws: dict[str, list[pd.DataFrame]] = {
                name: [] for name in _VARIANTS
            }
            variant_player_summaries: dict[str, list[pd.DataFrame]] = {
                name: [] for name in _VARIANTS
            }

            for game_index, (_, schedule_row) in enumerate(schedule_fold.iterrows()):
                matchup = matchup_from_schedule(schedule_row)
                config = SimulationConfig(
                    simulations=int(simulations_per_game),
                    seed=int(seed + season * 101 + week * 1009 + game_index * 7919),
                )
                for variant, (use_drive, use_transition) in _VARIANTS.items():
                    simulation = simulate_matchup_transition_probe(
                        matchup,
                        tendencies=tendencies,
                        usage=usage,
                        outcome_model=outcome_model,
                        play_call_model=play_call_model,
                        opportunity_model=opportunity_model,
                        drive_volume_model=drive_model if use_drive else None,
                        transition_model=transition_model if use_transition else None,
                        league_config=league_config,
                        config=config,
                    )
                    variant_team_draws[variant].append(simulation.team_draws)
                    variant_player_draws[variant].append(simulation.player_draws)
                    summary = simulation.player_summary.copy()
                    summary["season"] = season
                    summary["week"] = week
                    variant_player_summaries[variant].append(summary)

            if not variant_team_draws["legacy_drive_legacy_transition"]:
                continue
            team_frames = {
                name: pd.concat(frames, ignore_index=True)
                for name, frames in variant_team_draws.items()
            }
            player_draw_frames = {
                name: pd.concat(frames, ignore_index=True)
                for name, frames in variant_player_draws.items()
            }
            player_summaries = {
                name: pd.concat(frames, ignore_index=True)
                for name, frames in variant_player_summaries.items()
            }
            game_ids = set(team_frames["legacy_drive_legacy_transition"]["game_id"].astype(str))

            observed_teams = observed_team_games(play_frame, schedule_fold)
            observed_teams = observed_teams.loc[observed_teams["game_id"].astype(str).isin(game_ids)]
            observed_opportunity = observed_player_opportunity(play_frame)
            observed_opportunity = observed_opportunity.loc[
                observed_opportunity["game_id"].astype(str).isin(game_ids)
            ]
            observed_drive = observed_drive_volume(test_plays)
            observed_drive = observed_drive.loc[observed_drive["game_id"].astype(str).isin(game_ids)]
            observed_transitions = observed_transition_team_games(test_raw)
            observed_transitions = observed_transitions.loc[
                observed_transitions["game_id"].astype(str).isin(game_ids)
            ]
            fold_test_plays = test_plays.loc[test_plays["game_id"].astype(str).isin(game_ids)]
            learned_probability = play_call_model.predict_pass_probability(fold_test_plays)
            play_metrics = evaluate_play_call_probabilities(
                fold_test_plays["is_dropback"], learned_probability
            )

            fold_metrics: dict[str, dict[str, float]] = {}
            for variant in _VARIANTS:
                team_metrics = evaluate_team_simulation_draws(team_frames[variant], observed_teams)
                drive_metrics = evaluate_drive_volume_draws(team_frames[variant], observed_drive)
                transition_metrics = evaluate_transition_team_draws(
                    team_frames[variant], observed_transitions
                )
                predicted_opportunity = predicted_player_opportunity_from_draws(
                    player_draw_frames[variant]
                )
                opportunity_metrics = evaluate_player_opportunity(
                    predicted_opportunity,
                    observed_opportunity,
                )
                fantasy_metrics = _fantasy_metrics(player_summaries[variant], player_actuals)
                metrics = _combine_metrics(
                    play_metrics,
                    team_metrics,
                    opportunity_metrics,
                    fantasy_metrics,
                )
                metrics.update(drive_metrics)
                metrics.update(transition_metrics)
                fold_metrics[variant] = metrics
                records[variant].append(metrics)

            row: dict[str, float | int] = {"season": season, "week": week}
            for variant, metrics in fold_metrics.items():
                for metric, value in metrics.items():
                    row[f"{variant}__{metric}"] = float(value)
            _effect_columns(row, fold_metrics)
            weekly_rows.append(row)

    if not weekly_rows:
        raise ValueError("v0.14 transition benchmark produced no valid full-simulation folds")
    weekly = pd.DataFrame(weekly_rows).sort_values(["season", "week"], kind="mergesort")
    isolated_weekly = pd.DataFrame(isolated_rows)
    if not isolated_weekly.empty:
        isolated_weekly = isolated_weekly.sort_values(["season", "week"], kind="mergesort")
    aggregate = {variant: _aggregate(values) for variant, values in records.items()}
    aggregate_isolated = _aggregate_isolated(isolated_weekly)
    diagnostics = {
        "protocol": "v014_possession_transition_four_cell_expanding_weekly",
        "test_seasons": sorted({int(value) for value in test_seasons}),
        "week_start": int(week_start),
        "week_end": int(week_end),
        "folds": int(len(weekly)),
        "simulations_per_game": int(simulations_per_game),
        "variants": {
            name: {"drive_volume_model": drive, "possession_transition_model": transition}
            for name, (drive, transition) in _VARIANTS.items()
        },
        "play_call_model_fixed": "learned",
        "opportunity_model_fixed": "state_conditioned",
        "transition_negative_control": (
            "next-start yardline and transition seconds permuted within transition-type/season; "
            "field-goal outcomes permuted within distance-bucket/season"
        ),
        "component_rng_streams": True,
        "raw_special_teams_evidence": True,
        "skipped_folds": skipped,
        "research_only": True,
        "automatic_promotion": False,
        "production_projection_changed": False,
    }
    return TransitionBenchmarkResult(
        weekly_metrics=weekly.reset_index(drop=True),
        aggregate_metrics=aggregate,
        weekly_isolated_metrics=isolated_weekly.reset_index(drop=True),
        aggregate_isolated_metrics=aggregate_isolated,
        diagnostics=diagnostics,
    )


def _weekly_win_rate(frame: pd.DataFrame, effect: str, metric: str) -> float | None:
    column = f"win_{effect}__{metric}"
    if column not in frame:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.mean()) if not values.empty else None


def v014_transition_promotion_gate(
    benchmark: TransitionBenchmarkResult,
    *,
    min_seasons: int = 3,
    min_games: int = 200,
    min_transition_rows: int = 500,
    min_field_goal_rows: int = 100,
    min_start_improvement_fraction: float = 0.005,
    max_regression_ratio: float = 1.01,
    min_weekly_start_win_rate: float = 0.55,
) -> SimulationPromotionDecision:
    """Gate possession transitions into the research simulator champion only."""
    reasons: list[str] = []
    baseline = benchmark.aggregate_metrics.get("drive_legacy_transition", {})
    candidate = benchmark.aggregate_metrics.get("drive_transition", {})
    isolated = benchmark.aggregate_isolated_metrics
    seasons = benchmark.weekly_metrics["season"].nunique()
    if seasons < int(min_seasons):
        reasons.append(f"insufficient held-out seasons: {seasons} < {min_seasons}")
    games = int(candidate.get("games", 0.0))
    if games < int(min_games):
        reasons.append(f"insufficient replay games: {games} < {min_games}")

    transition_rows = int(isolated.get("transition_rows", 0.0))
    if transition_rows < int(min_transition_rows):
        reasons.append(
            f"insufficient isolated transition rows: {transition_rows} < {min_transition_rows}"
        )
    field_goal_rows = int(isolated.get("field_goal_rows", 0.0))
    if field_goal_rows < int(min_field_goal_rows):
        reasons.append(f"insufficient field-goal rows: {field_goal_rows} < {min_field_goal_rows}")

    real_start = isolated.get("transition_start_yardline_mae")
    type_start = isolated.get("type_base_start_yardline_mae")
    permuted_start = isolated.get("permuted_transition_start_yardline_mae")
    if real_start is None or type_start is None or permuted_start is None:
        reasons.append("missing real/type-base/permuted start-field evidence")
    else:
        if real_start >= type_start:
            reasons.append("contextual transition start field did not beat type-only baseline")
        if real_start >= permuted_start:
            reasons.append("contextual transition start field did not beat permuted control")

    real_seconds = isolated.get("transition_seconds_mae")
    type_seconds = isolated.get("type_base_transition_seconds_mae")
    permuted_seconds = isolated.get("permuted_transition_seconds_mae")
    if real_seconds is None or type_seconds is None or permuted_seconds is None:
        reasons.append("missing real/type-base/permuted transition-time evidence")
    else:
        if real_seconds >= type_seconds:
            reasons.append("contextual transition time did not beat type-only baseline")
        if real_seconds >= permuted_seconds:
            reasons.append("contextual transition time did not beat permuted control")

    fg = isolated.get("field_goal_log_loss")
    fg_base = isolated.get("field_goal_base_log_loss")
    fg_permuted = isolated.get("permuted_field_goal_log_loss")
    if fg is None or fg_base is None or fg_permuted is None:
        reasons.append("missing field-goal calibration evidence")
    else:
        if fg > fg_base:
            reasons.append("field-goal calibrator regressed versus distance baseline")
        if fg > fg_permuted:
            reasons.append("field-goal calibrator failed permuted control")

    start_ratio = _safe_ratio(
        candidate.get("team_start_yardline_mae"), baseline.get("team_start_yardline_mae")
    )
    if start_ratio is None:
        reasons.append("missing full-simulation starting-field comparison")
    elif start_ratio > 1.0 - float(min_start_improvement_fraction):
        reasons.append("transition challenger did not improve starting-field MAE enough")

    for metric in (
        "team_plays_mae",
        "team_drives_mae",
        "team_plays_per_drive_mae",
        "team_seconds_per_play_mae",
        "team_points_mae",
        "team_punts_mae",
        "team_field_goal_attempts_mae",
        "team_field_goals_made_mae",
        "team_turnovers_mae",
        "player_opportunity_mae",
        "fantasy_pinball_loss",
    ):
        ratio = _safe_ratio(candidate.get(metric), baseline.get(metric))
        if ratio is None:
            reasons.append(f"missing required downstream comparison: {metric}")
        elif ratio > float(max_regression_ratio):
            reasons.append(f"{metric} materially regressed")

    win_rate = _weekly_win_rate(
        benchmark.weekly_metrics,
        "transition_on_drive",
        "team_start_yardline_mae",
    )
    if win_rate is None:
        reasons.append("missing weekly starting-field win-rate evidence")
    elif win_rate < float(min_weekly_start_win_rate):
        reasons.append(
            f"weekly starting-field win rate below floor: {win_rate:.3f} < {min_weekly_start_win_rate:.3f}"
        )

    metrics: dict[str, float] = {}
    for variant, values in benchmark.aggregate_metrics.items():
        for key, value in values.items():
            if np.isfinite(value):
                metrics[f"{variant}__{key}"] = float(value)
    for key, value in benchmark.aggregate_isolated_metrics.items():
        if np.isfinite(value):
            metrics[f"isolated__{key}"] = float(value)
    if win_rate is not None:
        metrics["transition_on_drive__weekly_start_yardline_win_rate"] = float(win_rate)
    return SimulationPromotionDecision(
        promoted=not reasons,
        reasons=reasons,
        metrics=metrics,
        model_source="possession_transition_promotion_gate_v014",
    )


def recommend_v015_development(benchmark: TransitionBenchmarkResult) -> dict[str, object]:
    """Route v0.15 according to observed transition bottlenecks."""
    baseline = benchmark.aggregate_metrics.get("drive_legacy_transition", {})
    candidate = benchmark.aggregate_metrics.get("drive_transition", {})
    isolated = benchmark.aggregate_isolated_metrics
    start_ratio = _safe_ratio(
        candidate.get("team_start_yardline_mae"), baseline.get("team_start_yardline_mae")
    )
    points_ratio = _safe_ratio(candidate.get("team_points_mae"), baseline.get("team_points_mae"))
    fantasy_ratio = _safe_ratio(
        candidate.get("fantasy_pinball_loss"), baseline.get("fantasy_pinball_loss")
    )
    play_ratio = _safe_ratio(candidate.get("team_plays_mae"), baseline.get("team_plays_mae"))
    isolated_start_signal = (
        isolated.get("transition_start_yardline_mae") is not None
        and isolated.get("type_base_start_yardline_mae") is not None
        and isolated.get("permuted_transition_start_yardline_mae") is not None
        and isolated["transition_start_yardline_mae"] < isolated["type_base_start_yardline_mae"]
        and isolated["transition_start_yardline_mae"]
        < isolated["permuted_transition_start_yardline_mae"]
    )
    fg_signal = (
        isolated.get("field_goal_log_loss") is not None
        and isolated.get("field_goal_base_log_loss") is not None
        and isolated["field_goal_log_loss"] <= isolated["field_goal_base_log_loss"]
    )
    signals: list[str] = []
    if isolated_start_signal:
        signals.append("transition context improves isolated next-possession field position")
    if fg_signal:
        signals.append("field-goal calibration survives the distance-only baseline")
    if start_ratio is not None and start_ratio < 1.0:
        signals.append("transition model improves simulated starting field position")
    if points_ratio is not None and points_ratio < 1.0:
        signals.append("transition model improves team scoring error")
    if fantasy_ratio is not None and fantasy_ratio < 1.0:
        signals.append("transition model improves fantasy distribution loss")

    if (
        isolated_start_signal
        and start_ratio is not None
        and start_ratio < 1.0
        and points_ratio is not None
        and points_ratio <= 1.0
        and fantasy_ratio is not None
        and fantasy_ratio <= 1.0
    ):
        next_experiment = "latent_drive_strategy_state"
        rationale = (
            "Possession transitions now survive both isolated and downstream replay. The next "
            "interpretable missing layer is persistent within-drive strategy state."
        )
    elif isolated_start_signal and (start_ratio is None or start_ratio >= 1.0):
        next_experiment = "transition_action_generation"
        rationale = (
            "Transition outcomes are predictable given event type, but full simulation does not "
            "benefit. Calibrate punt/field-goal/turnover-on-downs event generation before adding depth."
        )
    elif not fg_signal:
        next_experiment = "kicker_weather_field_goal_model"
        rationale = (
            "Field-goal calibration remains weak. Add point-in-time kicker identity, stadium/roof, "
            "weather, kick distance, and block environment before deeper possession models."
        )
    elif start_ratio is not None and start_ratio < 1.0 and (
        points_ratio is None or points_ratio >= 1.0
    ):
        next_experiment = "decomposed_scoring_transitions"
        rationale = (
            "Field position improves without scoring accuracy. The likely bottleneck is red-zone, "
            "touchdown, turnover, or fourth-down conversion rather than possession starts."
        )
    elif play_ratio is not None and play_ratio >= 1.0:
        next_experiment = "drive_termination_and_duration_model"
        rationale = (
            "Transition mechanics are not resolving team play volume. Model possession termination, "
            "drive continuation, and duration directly before adding latent sequence state."
        )
    else:
        next_experiment = "collect_more_transition_replay_evidence"
        rationale = (
            "The current evidence does not isolate a stable downstream bottleneck. Expand held-out "
            "history and segment by transition family before increasing model complexity."
        )

    return {
        "next_experiment": next_experiment,
        "rationale": rationale,
        "signals": signals,
        "ratios": {
            "team_start_yardline": start_ratio,
            "team_points": points_ratio,
            "fantasy_pinball": fantasy_ratio,
            "team_plays": play_ratio,
        },
        "isolated_start_negative_control_passed": bool(isolated_start_signal),
        "field_goal_distance_baseline_passed": bool(fg_signal),
        "research_only": True,
        "production_projection_changed": False,
    }
