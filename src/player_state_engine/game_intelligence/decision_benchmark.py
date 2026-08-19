from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.decision import (
    DriveTerminationHazardModel,
    FourthDownDecisionModel,
    evaluate_fourth_down_scores,
    evaluate_fourth_down_team_draws,
    evaluate_termination_scores,
    extract_drive_termination_events,
    extract_fourth_down_decisions,
    observed_fourth_down_team_games,
    permute_fourth_down_actions_within_context_season,
    permute_termination_targets_within_context_season,
)
from player_state_engine.game_intelligence.decision_simulator import (
    simulate_matchup_decision_probe,
)
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
    evaluate_transition_team_draws,
    observed_transition_team_games,
)
from player_state_engine.game_intelligence.usage import build_player_usage_profiles

_VARIANTS = {
    "legacy_transition_legacy_decision": (False, False),
    "legacy_transition_decision": (False, True),
    "transition_legacy_decision": (True, False),
    "transition_decision": (True, True),
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
    "team_fourth_down_decisions_mae",
    "team_fourth_down_go_attempts_mae",
}


@dataclass(slots=True)
class DecisionBenchmarkResult:
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
        "decision_team_rows",
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
            elif key in {
                "team_drives_mae",
                "team_plays_per_drive_mae",
                "team_seconds_per_play_mae",
                "team_start_yardline_mae",
            }:
                weight = max(float(record.get("drive_team_rows", 0.0)), 1.0)
            elif key in {
                "team_punts_mae",
                "team_field_goal_attempts_mae",
                "team_field_goals_made_mae",
                "team_turnovers_mae",
                "team_turnovers_on_downs_mae",
            }:
                weight = max(float(record.get("transition_team_rows", 0.0)), 1.0)
            elif key in {
                "team_fourth_down_decisions_mae",
                "team_fourth_down_go_attempts_mae",
            }:
                weight = max(float(record.get("decision_team_rows", 0.0)), 1.0)
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


def _isolated_weight_column(column: str) -> str:
    if "termination" in column:
        return "termination_rows"
    return "fourth_down_rows"


def _aggregate_isolated(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty:
        return {}
    totals = {"fourth_down_rows", "termination_rows"}
    result: dict[str, float] = {}
    for column in frame.columns:
        if column in {"season", "week"}:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        valid = values.notna()
        if not valid.any():
            continue
        if column in totals:
            result[column] = float(values[valid].sum())
            continue
        weight_column = _isolated_weight_column(column)
        if weight_column not in frame:
            continue
        weights = pd.to_numeric(frame.loc[valid, weight_column], errors="coerce").fillna(0.0)
        positive = weights.gt(0)
        if not positive.any():
            continue
        selected = values.loc[valid]
        result[column] = float(
            np.average(
                selected.loc[positive.index][positive].to_numpy(dtype=float),
                weights=weights[positive].to_numpy(dtype=float),
            )
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
        "decision_on_transition": ("transition_decision", "transition_legacy_decision"),
        "decision_without_transition": (
            "legacy_transition_decision",
            "legacy_transition_legacy_decision",
        ),
        "transition_with_decision": (
            "transition_decision",
            "legacy_transition_decision",
        ),
        "combined": ("transition_decision", "legacy_transition_legacy_decision"),
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


def run_v015_decision_benchmark(
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
    decision_prior_strength: float = 24.0,
    decision_half_life_weeks: float = 8.0,
    termination_prior_strength: float = 36.0,
    termination_half_life_weeks: float = 8.0,
) -> DecisionBenchmarkResult:
    """Run expanding weekly v0.15 fourth-down policy attribution."""
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
                    {
                        "season": season,
                        "week": week,
                        "reason": "insufficient pre-cutoff evidence",
                    }
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
                decision_events = extract_fourth_down_decisions(train_raw)
                termination_events = extract_drive_termination_events(train_raw)
                decision_model = FourthDownDecisionModel(
                    prior_strength=decision_prior_strength,
                    half_life_weeks=decision_half_life_weeks,
                ).fit_frame(decision_events)
                termination_model = DriveTerminationHazardModel(
                    prior_strength=termination_prior_strength,
                    half_life_weeks=termination_half_life_weeks,
                ).fit_frame(termination_events)
                permuted_decision_model = FourthDownDecisionModel(
                    prior_strength=decision_prior_strength,
                    half_life_weeks=decision_half_life_weeks,
                ).fit_frame(
                    permute_fourth_down_actions_within_context_season(
                        decision_events,
                        seed=int(seed + season * 353 + week * 1009),
                    )
                )
                permuted_termination_model = DriveTerminationHazardModel(
                    prior_strength=termination_prior_strength,
                    half_life_weeks=termination_half_life_weeks,
                ).fit_frame(
                    permute_termination_targets_within_context_season(
                        termination_events,
                        seed=int(seed + season * 557 + week * 2027),
                    )
                )
            except ValueError as exc:
                skipped.append({"season": season, "week": week, "reason": str(exc)})
                continue

            isolated: dict[str, float | int] = {"season": season, "week": week}
            try:
                real_decision = evaluate_fourth_down_scores(decision_model.score_events(test_raw))
                permuted_decision = evaluate_fourth_down_scores(
                    permuted_decision_model.score_events(test_raw)
                )
                isolated.update(real_decision)
                isolated["permuted_fourth_down_log_loss"] = float(
                    permuted_decision["fourth_down_log_loss"]
                )
                isolated["permuted_fourth_down_brier"] = float(
                    permuted_decision["fourth_down_brier"]
                )
                isolated["real_decision_beats_heuristic"] = float(
                    real_decision["fourth_down_log_loss"]
                    < real_decision["heuristic_fourth_down_log_loss"]
                )
                isolated["real_decision_beats_permuted"] = float(
                    real_decision["fourth_down_log_loss"]
                    < permuted_decision["fourth_down_log_loss"]
                )
            except ValueError:
                pass
            try:
                real_termination = evaluate_termination_scores(
                    termination_model.score_events(test_raw)
                )
                permuted_termination = evaluate_termination_scores(
                    permuted_termination_model.score_events(test_raw)
                )
                isolated.update(real_termination)
                isolated["permuted_termination_log_loss"] = float(
                    permuted_termination["termination_log_loss"]
                )
                isolated["permuted_termination_brier"] = float(
                    permuted_termination["termination_brier"]
                )
                isolated["real_termination_beats_team_base"] = float(
                    real_termination["termination_log_loss"]
                    < real_termination["team_base_termination_log_loss"]
                )
                isolated["real_termination_beats_permuted"] = float(
                    real_termination["termination_log_loss"]
                    < permuted_termination["termination_log_loss"]
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
                for variant, (use_transition, use_decision) in _VARIANTS.items():
                    simulation = simulate_matchup_decision_probe(
                        matchup,
                        tendencies=tendencies,
                        usage=usage,
                        outcome_model=outcome_model,
                        play_call_model=play_call_model,
                        opportunity_model=opportunity_model,
                        drive_volume_model=drive_model,
                        transition_model=transition_model if use_transition else None,
                        decision_model=decision_model if use_decision else None,
                        termination_hazard_model=termination_model,
                        league_config=league_config,
                        config=config,
                    )
                    variant_team_draws[variant].append(simulation.team_draws)
                    variant_player_draws[variant].append(simulation.player_draws)
                    summary = simulation.player_summary.copy()
                    summary["season"] = season
                    summary["week"] = week
                    variant_player_summaries[variant].append(summary)

            if not variant_team_draws["legacy_transition_legacy_decision"]:
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
                team_frames["legacy_transition_legacy_decision"]["game_id"].astype(str)
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
            observed_transitions = observed_transition_team_games(test_raw)
            observed_transitions = observed_transitions.loc[
                observed_transitions["game_id"].astype(str).isin(game_ids)
            ]
            observed_decisions = observed_fourth_down_team_games(test_raw)
            observed_decisions = observed_decisions.loc[
                observed_decisions["game_id"].astype(str).isin(game_ids)
            ]
            fold_test_plays = test_plays.loc[
                test_plays["game_id"].astype(str).isin(game_ids)
            ]
            learned_probability = play_call_model.predict_pass_probability(fold_test_plays)
            play_metrics = evaluate_play_call_probabilities(
                fold_test_plays["is_dropback"], learned_probability
            )

            fold_metrics: dict[str, dict[str, float]] = {}
            for variant in _VARIANTS:
                team_metrics = evaluate_team_simulation_draws(
                    team_frames[variant], observed_teams
                )
                drive_metrics = evaluate_drive_volume_draws(
                    team_frames[variant], observed_drive
                )
                transition_metrics = evaluate_transition_team_draws(
                    team_frames[variant], observed_transitions
                )
                decision_metrics = evaluate_fourth_down_team_draws(
                    team_frames[variant], observed_decisions
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
                    play_metrics,
                    team_metrics,
                    opportunity_metrics,
                    fantasy_metrics,
                )
                metrics.update(drive_metrics)
                metrics.update(transition_metrics)
                metrics.update(decision_metrics)
                fold_metrics[variant] = metrics
                records[variant].append(metrics)

            row: dict[str, float | int] = {"season": season, "week": week}
            for variant, metrics in fold_metrics.items():
                for metric, value in metrics.items():
                    row[f"{variant}__{metric}"] = float(value)
            _effect_columns(row, fold_metrics)
            weekly_rows.append(row)

    if not weekly_rows:
        raise ValueError("v0.15 decision benchmark produced no valid full-simulation folds")
    weekly = pd.DataFrame(weekly_rows).sort_values(["season", "week"], kind="mergesort")
    isolated_weekly = pd.DataFrame(isolated_rows)
    if not isolated_weekly.empty:
        isolated_weekly = isolated_weekly.sort_values(["season", "week"], kind="mergesort")
    aggregate = {variant: _aggregate(values) for variant, values in records.items()}
    aggregate_isolated = _aggregate_isolated(isolated_weekly)
    diagnostics = {
        "protocol": "v015_fourth_down_decision_four_cell_expanding_weekly",
        "test_seasons": sorted({int(value) for value in test_seasons}),
        "week_start": int(week_start),
        "week_end": int(week_end),
        "folds": int(len(weekly)),
        "simulations_per_game": int(simulations_per_game),
        "variants": {
            name: {
                "drive_volume_model": True,
                "possession_transition_model": transition,
                "fourth_down_decision_model": decision,
            }
            for name, (transition, decision) in _VARIANTS.items()
        },
        "play_call_model_fixed": "learned",
        "opportunity_model_fixed": "state_conditioned",
        "drive_volume_model_fixed": "hierarchical_v013",
        "termination_hazard": "evaluated in isolation and diagnostic-only in simulation",
        "decision_negative_control": (
            "actions permuted within season/field-zone/distance; termination targets permuted "
            "within season/down/field-zone"
        ),
        "component_rng_streams": True,
        "component_rng_base_version": 13,
        "v014_parity_contract": (
            "decision-off probe must match frozen v0.14 transition simulator core draws"
        ),
        "skipped_folds": skipped,
        "research_only": True,
        "automatic_promotion": False,
        "production_projection_changed": False,
    }
    return DecisionBenchmarkResult(
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


def _isolated_rate(frame: pd.DataFrame, column: str) -> float | None:
    if column not in frame:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.mean()) if not values.empty else None


def v015_decision_promotion_gate(
    benchmark: DecisionBenchmarkResult,
    *,
    min_seasons: int = 3,
    min_games: int = 200,
    min_fourth_down_rows: int = 300,
    min_termination_rows: int = 5000,
    min_go_improvement_fraction: float = 0.005,
    max_regression_ratio: float = 1.01,
    min_weekly_action_win_rate: float = 0.55,
    min_weekly_go_win_rate: float = 0.52,
) -> SimulationPromotionDecision:
    """Gate fourth-down policy into manual research-champion review only."""
    reasons: list[str] = []
    baseline = benchmark.aggregate_metrics.get("transition_legacy_decision", {})
    candidate = benchmark.aggregate_metrics.get("transition_decision", {})
    isolated = benchmark.aggregate_isolated_metrics
    seasons = benchmark.weekly_metrics["season"].nunique()
    if seasons < int(min_seasons):
        reasons.append(f"insufficient held-out seasons: {seasons} < {min_seasons}")
    games = int(candidate.get("games", 0.0))
    if games < int(min_games):
        reasons.append(f"insufficient replay games: {games} < {min_games}")

    decision_rows = int(isolated.get("fourth_down_rows", 0.0))
    if decision_rows < int(min_fourth_down_rows):
        reasons.append(
            f"insufficient fourth-down decisions: {decision_rows} < {min_fourth_down_rows}"
        )
    termination_rows = int(isolated.get("termination_rows", 0.0))
    if termination_rows < int(min_termination_rows):
        reasons.append(
            f"insufficient drive-termination observations: {termination_rows} < {min_termination_rows}"
        )

    action_loss = isolated.get("fourth_down_log_loss")
    heuristic_loss = isolated.get("heuristic_fourth_down_log_loss")
    permuted_loss = isolated.get("permuted_fourth_down_log_loss")
    if action_loss is None or heuristic_loss is None or permuted_loss is None:
        reasons.append("missing fourth-down real/heuristic/permuted log-loss evidence")
    else:
        if action_loss >= heuristic_loss:
            reasons.append("learned fourth-down policy did not beat frozen heuristic log loss")
        if action_loss >= permuted_loss:
            reasons.append("learned fourth-down policy did not beat permuted control")

    action_brier = isolated.get("fourth_down_brier")
    heuristic_brier = isolated.get("heuristic_fourth_down_brier")
    permuted_brier = isolated.get("permuted_fourth_down_brier")
    if action_brier is None or heuristic_brier is None or permuted_brier is None:
        reasons.append("missing fourth-down Brier evidence")
    else:
        if action_brier > heuristic_brier:
            reasons.append("learned fourth-down policy regressed heuristic Brier score")
        if action_brier > permuted_brier:
            reasons.append("learned fourth-down policy failed permuted Brier control")

    go_ratio = _safe_ratio(
        candidate.get("team_fourth_down_go_attempts_mae"),
        baseline.get("team_fourth_down_go_attempts_mae"),
    )
    if go_ratio is None:
        reasons.append("missing simulated fourth-down go-attempt comparison")
    elif go_ratio > 1.0 - float(min_go_improvement_fraction):
        reasons.append("decision challenger did not improve go-attempt MAE enough")

    for metric in (
        "team_fourth_down_decisions_mae",
        "team_punts_mae",
        "team_field_goal_attempts_mae",
        "team_field_goals_made_mae",
        "team_turnovers_on_downs_mae",
        "team_plays_mae",
        "team_drives_mae",
        "team_plays_per_drive_mae",
        "team_seconds_per_play_mae",
        "team_start_yardline_mae",
        "team_points_mae",
        "player_opportunity_mae",
        "fantasy_pinball_loss",
    ):
        ratio = _safe_ratio(candidate.get(metric), baseline.get(metric))
        if ratio is None:
            reasons.append(f"missing required downstream comparison: {metric}")
        elif ratio > float(max_regression_ratio):
            reasons.append(f"{metric} materially regressed")

    isolated_action_rate = _isolated_rate(
        benchmark.weekly_isolated_metrics, "real_decision_beats_heuristic"
    )
    if isolated_action_rate is None:
        reasons.append("missing weekly isolated fourth-down win-rate evidence")
    elif isolated_action_rate < float(min_weekly_action_win_rate):
        reasons.append(
            "weekly isolated fourth-down win rate below floor: "
            f"{isolated_action_rate:.3f} < {min_weekly_action_win_rate:.3f}"
        )
    weekly_go_rate = _weekly_win_rate(
        benchmark.weekly_metrics,
        "decision_on_transition",
        "team_fourth_down_go_attempts_mae",
    )
    if weekly_go_rate is None:
        reasons.append("missing weekly go-attempt win-rate evidence")
    elif weekly_go_rate < float(min_weekly_go_win_rate):
        reasons.append(
            f"weekly go-attempt win rate below floor: {weekly_go_rate:.3f} < {min_weekly_go_win_rate:.3f}"
        )

    metrics: dict[str, float] = {}
    for variant, values in benchmark.aggregate_metrics.items():
        for key, value in values.items():
            if np.isfinite(value):
                metrics[f"{variant}__{key}"] = float(value)
    for key, value in benchmark.aggregate_isolated_metrics.items():
        if np.isfinite(value):
            metrics[f"isolated__{key}"] = float(value)
    if isolated_action_rate is not None:
        metrics["isolated__weekly_decision_beats_heuristic_rate"] = float(
            isolated_action_rate
        )
    if weekly_go_rate is not None:
        metrics["decision_on_transition__weekly_go_attempt_win_rate"] = float(
            weekly_go_rate
        )
    return SimulationPromotionDecision(
        promoted=not reasons,
        reasons=reasons,
        metrics=metrics,
        model_source="fourth_down_decision_promotion_gate_v015",
    )


def recommend_v016_development(benchmark: DecisionBenchmarkResult) -> dict[str, object]:
    """Route v0.16 according to decision and termination replay evidence."""
    baseline = benchmark.aggregate_metrics.get("transition_legacy_decision", {})
    candidate = benchmark.aggregate_metrics.get("transition_decision", {})
    isolated = benchmark.aggregate_isolated_metrics
    go_ratio = _safe_ratio(
        candidate.get("team_fourth_down_go_attempts_mae"),
        baseline.get("team_fourth_down_go_attempts_mae"),
    )
    play_ratio = _safe_ratio(candidate.get("team_plays_mae"), baseline.get("team_plays_mae"))
    points_ratio = _safe_ratio(
        candidate.get("team_points_mae"), baseline.get("team_points_mae")
    )
    fantasy_ratio = _safe_ratio(
        candidate.get("fantasy_pinball_loss"), baseline.get("fantasy_pinball_loss")
    )
    action_signal = (
        isolated.get("fourth_down_log_loss") is not None
        and isolated.get("heuristic_fourth_down_log_loss") is not None
        and isolated.get("permuted_fourth_down_log_loss") is not None
        and isolated["fourth_down_log_loss"] < isolated["heuristic_fourth_down_log_loss"]
        and isolated["fourth_down_log_loss"] < isolated["permuted_fourth_down_log_loss"]
    )
    termination_signal = (
        isolated.get("termination_log_loss") is not None
        and isolated.get("team_base_termination_log_loss") is not None
        and isolated.get("permuted_termination_log_loss") is not None
        and isolated["termination_log_loss"] < isolated["team_base_termination_log_loss"]
        and isolated["termination_log_loss"] < isolated["permuted_termination_log_loss"]
    )
    signals: list[str] = []
    if action_signal:
        signals.append("fourth-down policy beats frozen heuristic and permutation control")
    if termination_signal:
        signals.append("drive-termination hazard beats team base and permutation control")
    if go_ratio is not None and go_ratio < 1.0:
        signals.append("learned policy improves simulated fourth-down go frequency")
    if play_ratio is not None and play_ratio < 1.0:
        signals.append("learned policy improves team play volume")
    if points_ratio is not None and points_ratio < 1.0:
        signals.append("learned policy improves team scoring error")
    if fantasy_ratio is not None and fantasy_ratio < 1.0:
        signals.append("learned policy improves fantasy distribution loss")

    downstream_safe = (
        go_ratio is not None
        and go_ratio < 1.0
        and (points_ratio is None or points_ratio <= 1.0)
        and (fantasy_ratio is None or fantasy_ratio <= 1.0)
    )
    if action_signal and downstream_safe and termination_signal:
        next_experiment = "latent_drive_strategy_state"
        rationale = (
            "Observed fourth-down choices and drive-end hazard both carry stable state information. "
            "The next interpretable missing layer is persistent strategy state across a possession."
        )
    elif action_signal and (go_ratio is None or go_ratio >= 1.0):
        next_experiment = "fourth_down_execution_outcomes"
        rationale = (
            "The model predicts decisions but does not improve simulated action frequencies. "
            "Audit fourth-down conversion, punt/field-goal eligibility, and execution outcomes before depth."
        )
    elif not action_signal:
        next_experiment = "richer_fourth_down_context"
        rationale = (
            "The transparent policy does not beat the frozen heuristic. Add point-in-time coach, timeout, "
            "QB, score/clock, market, roof, and weather context before considering a larger model."
        )
    elif termination_signal and play_ratio is not None and play_ratio >= 1.0:
        next_experiment = "terminal_family_generation"
        rationale = (
            "Drive-end hazard is predictable but play volume remains weak. Learn terminal-family generation "
            "separately so termination authority can be tested without inventing event types."
        )
    elif go_ratio is not None and go_ratio < 1.0 and points_ratio is not None and points_ratio >= 1.0:
        next_experiment = "decomposed_scoring_transitions"
        rationale = (
            "Fourth-down frequencies improve without scoring accuracy. The next bottleneck is execution and "
            "red-zone/turnover conversion rather than action policy."
        )
    else:
        next_experiment = "collect_more_decision_replay_evidence"
        rationale = (
            "The current evidence does not isolate a stable next causal layer. Expand held-out replay and "
            "segment by team, field zone, distance, and coaching regime before adding complexity."
        )

    return {
        "next_experiment": next_experiment,
        "rationale": rationale,
        "signals": signals,
        "ratios": {
            "fourth_down_go_attempts": go_ratio,
            "team_plays": play_ratio,
            "team_points": points_ratio,
            "fantasy_pinball": fantasy_ratio,
        },
        "fourth_down_negative_control_passed": bool(action_signal),
        "termination_negative_control_passed": bool(termination_signal),
        "research_only": True,
        "production_projection_changed": False,
    }
