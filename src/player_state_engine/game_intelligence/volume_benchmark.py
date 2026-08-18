from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.drive import (
    DriveVolumeModel,
    evaluate_drive_volume_draws,
    evaluate_pace_event_scores,
    observed_drive_volume,
    permute_pace_targets_within_team_season,
)
from player_state_engine.game_intelligence.drive_simulator import (
    simulate_matchup_volume_probe,
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
from player_state_engine.game_intelligence.usage import build_player_usage_profiles

_VARIANTS = {
    "profile_static_legacy": (False, False, False),
    "learned_static_legacy": (True, False, False),
    "profile_state_legacy": (False, True, False),
    "learned_state_legacy": (True, True, False),
    "profile_static_drive": (False, False, True),
    "learned_static_drive": (True, False, True),
    "profile_state_drive": (False, True, True),
    "learned_state_drive": (True, True, True),
}
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
    "team_drives_mae",
    "team_plays_per_drive_mae",
    "team_seconds_per_play_mae",
    "team_start_yardline_mae",
}


@dataclass(slots=True)
class DriveVolumeBenchmarkResult:
    weekly_metrics: pd.DataFrame
    aggregate_metrics: dict[str, dict[str, float]]
    weekly_pace_metrics: pd.DataFrame
    aggregate_pace_metrics: dict[str, float]
    diagnostics: dict[str, object]


def _chronology(frame: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(frame["season"], errors="coerce") * 25 + pd.to_numeric(
        frame["week"], errors="coerce"
    )


def _metric_weight(metric: str, record: dict[str, float]) -> float:
    if metric.startswith("fantasy_"):
        return max(float(record.get("fantasy_rows", 0.0)), 1.0)
    if metric.startswith("player_"):
        return max(float(record.get("player_rows", 0.0)), 1.0)
    if metric.startswith("team_") and metric in {
        "team_drives_mae",
        "team_plays_per_drive_mae",
        "team_seconds_per_play_mae",
        "team_start_yardline_mae",
    }:
        return max(float(record.get("drive_team_rows", 0.0)), 1.0)
    return max(float(record.get("games", 0.0)), 1.0)


def _aggregate(records: list[dict[str, float]]) -> dict[str, float]:
    if not records:
        return {}
    keys = sorted({key for record in records for key in record})
    totals = {
        "games",
        "player_rows",
        "predicted_player_rows",
        "observed_player_rows",
        "fantasy_rows",
        "drive_team_rows",
    }
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
            denominator = sum(weight for _, weight in values)
            result[key] = float(
                sum(value * weight for value, weight in values) / max(denominator, 1e-12)
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


def _add_effect_deltas(
    row: dict[str, float | int],
    metrics: dict[str, dict[str, float]],
) -> None:
    comparisons = {
        "drive_learned_static": ("learned_static_drive", "learned_static_legacy"),
        "drive_learned_state": ("learned_state_drive", "learned_state_legacy"),
        "allocation_drive": ("learned_state_drive", "learned_static_drive"),
        "play_call_drive": ("learned_static_drive", "profile_static_drive"),
        "combined_drive": ("learned_state_drive", "profile_static_legacy"),
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


def run_v013_drive_volume_benchmark(
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
) -> DriveVolumeBenchmarkResult:
    """Run an eight-cell weekly expanding replay with isolated drive/pace mechanics."""
    play_frame = build_play_intelligence_frame(pbp)
    tendencies = build_team_tendency_snapshots(play_frame)
    enriched = attach_point_in_time_matchup_features(play_frame, tendencies)
    chronology = _chronology(enriched)
    records: dict[str, list[dict[str, float]]] = {name: [] for name in _VARIANTS}
    weekly_rows: list[dict[str, float | int]] = []
    weekly_pace_rows: list[dict[str, float | int]] = []
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
            train = enriched.loc[chronology < split].copy()
            test_plays = enriched.loc[
                (pd.to_numeric(enriched["season"], errors="coerce") == season)
                & (pd.to_numeric(enriched["week"], errors="coerce") == week)
            ].copy()
            if len(train) < 50 or test_plays.empty:
                skipped.append(
                    {"season": season, "week": week, "reason": "insufficient pre-cutoff plays"}
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
                permuted_drive_model = DriveVolumeModel(
                    prior_strength=drive_prior_strength,
                    half_life_weeks=drive_half_life_weeks,
                ).fit(
                    permute_pace_targets_within_team_season(
                        train,
                        seed=int(seed + season * 97 + week * 997),
                    )
                )
            except ValueError as exc:
                skipped.append({"season": season, "week": week, "reason": str(exc)})
                continue

            pace_scores = drive_model.score_pace_events(test_plays, use_context=True)
            permuted_scores = permuted_drive_model.score_pace_events(
                test_plays, use_context=True
            )
            if not pace_scores.empty and not permuted_scores.empty:
                pace_metrics = evaluate_pace_event_scores(pace_scores)
                permuted_metrics = evaluate_pace_event_scores(permuted_scores)
                weekly_pace_rows.append(
                    {
                        "season": season,
                        "week": week,
                        **pace_metrics,
                        "permuted_state_pace_mae": float(
                            permuted_metrics["state_pace_mae"]
                        ),
                        "real_beats_team_base": float(
                            pace_metrics["state_pace_mae"]
                            < pace_metrics["team_base_pace_mae"]
                        ),
                        "real_beats_permuted": float(
                            pace_metrics["state_pace_mae"]
                            < permuted_metrics["state_pace_mae"]
                        ),
                    }
                )

            usage = build_player_usage_profiles(
                play_frame,
                season=season,
                week=week,
                players=players,
            )
            if usage.empty:
                skipped.append(
                    {"season": season, "week": week, "reason": "empty point-in-time usage"}
                )
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
                for variant, (use_play_call, use_state, use_drive) in _VARIANTS.items():
                    simulation = simulate_matchup_volume_probe(
                        matchup,
                        tendencies=tendencies,
                        usage=usage,
                        outcome_model=outcome_model,
                        play_call_model=play_call_model if use_play_call else None,
                        opportunity_model=opportunity_model if use_state else None,
                        drive_volume_model=drive_model if use_drive else None,
                        league_config=league_config,
                        config=config,
                    )
                    variant_team_draws[variant].append(simulation.team_draws)
                    variant_player_draws[variant].append(simulation.player_draws)
                    summary = simulation.player_summary.copy()
                    summary["season"] = season
                    summary["week"] = week
                    variant_player_summaries[variant].append(summary)

            if not variant_team_draws["profile_static_legacy"]:
                skipped.append(
                    {"season": season, "week": week, "reason": "no usable game simulations"}
                )
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
            game_ids = set(
                team_frames["profile_static_legacy"]["game_id"].astype(str)
            )

            observed_teams = observed_team_games(play_frame, schedule_fold)
            observed_teams = observed_teams.loc[
                observed_teams["game_id"].astype(str).isin(game_ids)
            ]
            observed_opportunity = observed_player_opportunity(play_frame)
            observed_opportunity = observed_opportunity.loc[
                observed_opportunity["game_id"].astype(str).isin(game_ids)
            ]
            observed_drive = observed_drive_volume(test_plays)
            observed_drive = observed_drive.loc[
                observed_drive["game_id"].astype(str).isin(game_ids)
            ]
            fold_test_plays = test_plays.loc[
                test_plays["game_id"].astype(str).isin(game_ids)
            ]

            profile_probability = pd.to_numeric(
                fold_test_plays["pregame_pass_rate"], errors="coerce"
            ).fillna(float(train["is_dropback"].mean()))
            learned_probability = play_call_model.predict_pass_probability(
                fold_test_plays
            )
            play_metrics = {
                False: evaluate_play_call_probabilities(
                    fold_test_plays["is_dropback"], profile_probability
                ),
                True: evaluate_play_call_probabilities(
                    fold_test_plays["is_dropback"], learned_probability
                ),
            }

            fold_metrics: dict[str, dict[str, float]] = {}
            for variant, (use_play_call, _, _) in _VARIANTS.items():
                team_metrics = evaluate_team_simulation_draws(
                    team_frames[variant], observed_teams
                )
                drive_metrics = evaluate_drive_volume_draws(
                    team_frames[variant], observed_drive
                )
                predicted_opportunity = predicted_player_opportunity_from_draws(
                    player_draw_frames[variant]
                )
                opportunity_metrics = evaluate_player_opportunity(
                    predicted_opportunity,
                    observed_opportunity,
                )
                fantasy_metrics = _fantasy_metrics(
                    player_summaries[variant], player_actuals
                )
                metrics = _combine_metrics(
                    play_metrics[use_play_call],
                    team_metrics,
                    opportunity_metrics,
                    fantasy_metrics,
                )
                metrics.update(drive_metrics)
                fold_metrics[variant] = metrics
                records[variant].append(metrics)

            row: dict[str, float | int] = {"season": season, "week": week}
            for variant, metrics in fold_metrics.items():
                for metric, value in metrics.items():
                    row[f"{variant}__{metric}"] = float(value)
            _add_effect_deltas(row, fold_metrics)
            weekly_rows.append(row)

    if not weekly_rows:
        raise ValueError("v0.13 drive-volume benchmark produced no valid folds")

    weekly = pd.DataFrame(weekly_rows).sort_values(
        ["season", "week"], kind="mergesort"
    )
    weekly_pace = pd.DataFrame(weekly_pace_rows)
    if not weekly_pace.empty:
        weekly_pace = weekly_pace.sort_values(
            ["season", "week"], kind="mergesort"
        )
    aggregate = {
        variant: _aggregate(variant_records)
        for variant, variant_records in records.items()
    }

    aggregate_pace: dict[str, float] = {}
    if not weekly_pace.empty:
        for column in weekly_pace.columns:
            if column in {"season", "week"}:
                continue
            values = pd.to_numeric(weekly_pace[column], errors="coerce").dropna()
            if not values.empty:
                if column == "pace_rows":
                    aggregate_pace[column] = float(values.sum())
                else:
                    weights = pd.to_numeric(
                        weekly_pace.loc[values.index, "pace_rows"], errors="coerce"
                    ).fillna(1.0)
                    aggregate_pace[column] = float(
                        np.average(
                            values.to_numpy(dtype=float),
                            weights=weights.to_numpy(dtype=float),
                        )
                    )

    diagnostics = {
        "protocol": "v013_drive_volume_eight_cell_expanding_weekly",
        "test_seasons": sorted({int(value) for value in test_seasons}),
        "week_start": int(week_start),
        "week_end": int(week_end),
        "folds": int(len(weekly)),
        "simulations_per_game": int(simulations_per_game),
        "variants": {
            name: {
                "learned_play_call": play_call,
                "state_conditioned_opportunity": state,
                "drive_volume_model": drive,
            }
            for name, (play_call, state, drive) in _VARIANTS.items()
        },
        "component_rng_streams": True,
        "pace_negative_control": "seconds_between_plays permuted within team-season",
        "drive_start_source": "scrimmage-play drive starts with offense/defense/league mixture",
        "skipped_folds": skipped,
        "research_only": True,
        "automatic_promotion": False,
        "production_projection_changed": False,
    }
    return DriveVolumeBenchmarkResult(
        weekly_metrics=weekly.reset_index(drop=True),
        aggregate_metrics=aggregate,
        weekly_pace_metrics=weekly_pace.reset_index(drop=True),
        aggregate_pace_metrics=aggregate_pace,
        diagnostics=diagnostics,
    )


def _weekly_win_rate(
    frame: pd.DataFrame,
    effect: str,
    metric: str,
) -> float | None:
    column = f"win_{effect}__{metric}"
    if column not in frame:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.mean()) if not values.empty else None


def v013_drive_volume_promotion_gate(
    benchmark: DriveVolumeBenchmarkResult,
    *,
    min_seasons: int = 3,
    min_games: int = 200,
    min_team_plays_improvement_fraction: float = 0.005,
    max_regression_ratio: float = 1.01,
    min_weekly_volume_win_rate: float = 0.55,
) -> SimulationPromotionDecision:
    """Gate drive-volume mechanics into the research simulator champion only."""
    reasons: list[str] = []
    baseline = benchmark.aggregate_metrics.get("learned_state_legacy", {})
    candidate = benchmark.aggregate_metrics.get("learned_state_drive", {})
    seasons = benchmark.weekly_metrics["season"].nunique()
    if seasons < int(min_seasons):
        reasons.append(f"insufficient held-out seasons: {seasons} < {min_seasons}")
    games = int(candidate.get("games", 0.0))
    if games < int(min_games):
        reasons.append(f"insufficient replay games: {games} < {min_games}")

    plays_ratio = _safe_ratio(
        candidate.get("team_plays_mae"), baseline.get("team_plays_mae")
    )
    if plays_ratio is None:
        reasons.append("missing team plays comparison")
    elif plays_ratio > 1.0 - float(min_team_plays_improvement_fraction):
        reasons.append("drive-volume challenger did not improve team plays enough")

    pace_ratio = _safe_ratio(
        candidate.get("team_seconds_per_play_mae"),
        baseline.get("team_seconds_per_play_mae"),
    )
    if pace_ratio is None:
        reasons.append("missing team pace comparison")
    elif pace_ratio >= 1.0:
        reasons.append("drive-volume challenger did not improve team pace")

    for metric in (
        "team_drives_mae",
        "team_plays_per_drive_mae",
        "team_start_yardline_mae",
        "team_points_mae",
        "player_opportunity_mae",
        "fantasy_pinball_loss",
    ):
        ratio = _safe_ratio(candidate.get(metric), baseline.get(metric))
        if ratio is None:
            reasons.append(f"missing required comparison: {metric}")
        elif ratio > float(max_regression_ratio):
            reasons.append(f"{metric} materially regressed")

    win_rate = _weekly_win_rate(
        benchmark.weekly_metrics,
        "drive_learned_state",
        "team_plays_mae",
    )
    if win_rate is None:
        reasons.append("missing weekly team-play win-rate evidence")
    elif win_rate < float(min_weekly_volume_win_rate):
        reasons.append(
            f"weekly team-play win rate below floor: "
            f"{win_rate:.3f} < {min_weekly_volume_win_rate:.3f}"
        )

    pace = benchmark.aggregate_pace_metrics
    real_pace = pace.get("state_pace_mae")
    team_base_pace = pace.get("team_base_pace_mae")
    permuted_pace = pace.get("permuted_state_pace_mae")
    if real_pace is None or team_base_pace is None or permuted_pace is None:
        reasons.append("missing real/base/permuted pace evidence")
    else:
        if real_pace >= team_base_pace:
            reasons.append("state-conditioned pace did not beat team-only pace")
        if real_pace >= permuted_pace:
            reasons.append("state-conditioned pace did not beat permuted negative control")

    metrics: dict[str, float] = {}
    for prefix, values in benchmark.aggregate_metrics.items():
        for key, value in values.items():
            if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value):
                metrics[f"{prefix}__{key}"] = float(value)
    for key, value in benchmark.aggregate_pace_metrics.items():
        if np.isfinite(value):
            metrics[f"pace__{key}"] = float(value)
    if win_rate is not None:
        metrics["drive_learned_state__weekly_team_plays_win_rate"] = float(win_rate)

    return SimulationPromotionDecision(
        promoted=not reasons,
        reasons=reasons,
        metrics=metrics,
        model_source="drive_volume_promotion_gate_v013",
    )


def recommend_v014_development(
    benchmark: DriveVolumeBenchmarkResult,
) -> dict[str, object]:
    """Route v0.14 based on drive-volume evidence instead of architectural novelty."""
    baseline = benchmark.aggregate_metrics.get("learned_state_legacy", {})
    candidate = benchmark.aggregate_metrics.get("learned_state_drive", {})
    pace = benchmark.aggregate_pace_metrics
    plays_ratio = _safe_ratio(
        candidate.get("team_plays_mae"), baseline.get("team_plays_mae")
    )
    drives_ratio = _safe_ratio(
        candidate.get("team_drives_mae"), baseline.get("team_drives_mae")
    )
    fantasy_ratio = _safe_ratio(
        candidate.get("fantasy_pinball_loss"), baseline.get("fantasy_pinball_loss")
    )
    points_ratio = _safe_ratio(
        candidate.get("team_points_mae"), baseline.get("team_points_mae")
    )
    pace_real = pace.get("state_pace_mae")
    pace_base = pace.get("team_base_pace_mae")
    pace_permuted = pace.get("permuted_state_pace_mae")
    pace_signal = (
        pace_real is not None
        and pace_base is not None
        and pace_permuted is not None
        and pace_real < pace_base
        and pace_real < pace_permuted
    )

    signals: list[str] = []
    if pace_signal:
        signals.append("state-conditioned pace beats team-only and permuted controls")
    if plays_ratio is not None and plays_ratio < 1.0:
        signals.append("drive-volume model improves team play volume")
    if drives_ratio is not None and drives_ratio < 1.0:
        signals.append("drive-volume model improves drive-count accuracy")
    if fantasy_ratio is not None and fantasy_ratio < 1.0:
        signals.append("drive-volume model improves fantasy distribution loss")

    if (
        plays_ratio is not None
        and plays_ratio < 1.0
        and drives_ratio is not None
        and drives_ratio < 1.0
        and fantasy_ratio is not None
        and fantasy_ratio <= 1.0
    ):
        next_experiment = "latent_drive_strategy_state"
        rationale = (
            "Volume mechanics survive full replay, so the next interpretable layer is persistent "
            "drive strategy: scripted, normal, hurry-up, comeback, clock-control, and red-zone states."
        )
    elif pace_signal and (plays_ratio is None or plays_ratio >= 1.0):
        next_experiment = "drive_transition_and_possession_model"
        rationale = (
            "Pace context is real, but full-game volume does not improve. Model drive continuation, "
            "possession termination, field-position transitions, and special-teams starts next."
        )
    elif plays_ratio is not None and plays_ratio < 1.0 and (
        fantasy_ratio is None or fantasy_ratio >= 1.0
    ):
        next_experiment = "decomposed_play_outcomes"
        rationale = (
            "Volume is improving without downstream fantasy gains. Opportunity quantity is less "
            "likely to be the bottleneck than completion, yardage, turnover, or touchdown conversion."
        )
    elif not pace_signal:
        next_experiment = "reject_or_redesign_drive_context"
        rationale = (
            "State-conditioned pace does not survive the negative control. Do not deepen the drive "
            "model until context definitions, data quality, and regime segmentation are audited."
        )
    elif points_ratio is not None and points_ratio > 1.0:
        next_experiment = "field_position_and_scoring_transition_model"
        rationale = (
            "Drive volume is plausible but scoring calibration worsens. Improve possession starts, "
            "fourth-down, field-goal, turnover-return, and red-zone transition mechanics."
        )
    else:
        next_experiment = "collect_more_drive_replay_evidence"
        rationale = (
            "The evidence does not isolate a stable bottleneck. Expand held-out replay or segment "
            "coaching, QB, and role-change regimes before increasing model complexity."
        )

    return {
        "next_experiment": next_experiment,
        "rationale": rationale,
        "signals": signals,
        "ratios": {
            "team_plays": plays_ratio,
            "team_drives": drives_ratio,
            "fantasy_pinball": fantasy_ratio,
            "team_points": points_ratio,
        },
        "pace_negative_control_passed": bool(pace_signal),
        "research_only": True,
        "production_projection_changed": False,
    }
