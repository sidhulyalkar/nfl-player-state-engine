from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.decision import (
    FourthDownDecisionModel,
    evaluate_fourth_down_team_draws,
    extract_fourth_down_decisions,
    observed_fourth_down_team_games,
)
from player_state_engine.game_intelligence.decision_benchmark import (
    _chronology,
    _safe_ratio,
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
from player_state_engine.game_intelligence.terminal import (
    TerminalFamilyModel,
    attach_terminal_family_labels,
    evaluate_terminal_family_scores,
    extract_terminal_family_events,
    permute_conditional_terminal_families_within_context_season,
    permute_terminal_families_within_context_season,
)
from player_state_engine.game_intelligence.terminal_simulator import (
    simulate_matchup_terminal_probe,
)
from player_state_engine.game_intelligence.transition import (
    PossessionTransitionModel,
    evaluate_transition_team_draws,
    observed_transition_team_games,
)
from player_state_engine.game_intelligence.usage import build_player_usage_profiles

_VARIANTS = {
    "legacy_transition_legacy_decision_legacy_terminal": (False, False, False),
    "legacy_transition_legacy_decision_terminal": (False, False, True),
    "legacy_transition_decision_legacy_terminal": (False, True, False),
    "legacy_transition_decision_terminal": (False, True, True),
    "transition_legacy_decision_legacy_terminal": (True, False, False),
    "transition_legacy_decision_terminal": (True, False, True),
    "transition_decision_legacy_terminal": (True, True, False),
    "transition_decision_terminal": (True, True, True),
}
_PARENT_PAIRS = {
    "legacy_transition_legacy_decision": (
        "legacy_transition_legacy_decision_terminal",
        "legacy_transition_legacy_decision_legacy_terminal",
    ),
    "legacy_transition_decision": (
        "legacy_transition_decision_terminal",
        "legacy_transition_decision_legacy_terminal",
    ),
    "transition_legacy_decision": (
        "transition_legacy_decision_terminal",
        "transition_legacy_decision_legacy_terminal",
    ),
    "transition_decision": (
        "transition_decision_terminal",
        "transition_decision_legacy_terminal",
    ),
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
    "team_terminal_non_clock_events_mae",
    "team_terminal_score_events_mae",
    "team_terminal_turnover_events_mae",
    "team_terminal_downs_events_mae",
    "terminal_conditioning_fallback_rate",
}


@dataclass(slots=True)
class TerminalBenchmarkResult:
    weekly_metrics: pd.DataFrame
    aggregate_metrics: dict[str, dict[str, float]]
    weekly_isolated_metrics: pd.DataFrame
    aggregate_isolated_metrics: dict[str, float]
    diagnostics: dict[str, object]


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
        "terminal_team_rows",
    }
    keys = sorted({key for record in records for key in record})
    result: dict[str, float] = {}
    for key in keys:
        weighted: list[tuple[float, float]] = []
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
            elif key.startswith("team_terminal_"):
                weight = max(float(record.get("terminal_team_rows", 0.0)), 1.0)
            else:
                weight = max(float(record.get("games", 0.0)), 1.0)
            weighted.append((float(value), weight))
        if not weighted:
            continue
        if key in totals:
            result[key] = float(sum(value for value, _ in weighted))
        else:
            denominator = sum(weight for _, weight in weighted)
            result[key] = float(
                sum(value * weight for value, weight in weighted) / max(denominator, 1e-12)
            )
    return result


def _aggregate_isolated(frame: pd.DataFrame) -> dict[str, float]:
    if frame.empty:
        return {}
    result: dict[str, float] = {}
    totals = {"terminal_family_rows", "conditional_terminal_rows"}
    for column in frame.columns:
        if column in {"season", "week"}:
            continue
        values = pd.to_numeric(frame[column], errors="coerce")
        valid = values.notna()
        if not valid.any():
            continue
        if column in totals or column.endswith("_rows"):
            result[column] = float(values[valid].sum())
            continue
        weights = pd.to_numeric(
            frame.loc[valid, "terminal_family_rows"], errors="coerce"
        ).fillna(0.0)
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


def _observed_terminal_non_clock_team_games(pbp: pd.DataFrame) -> pd.DataFrame:
    events = extract_terminal_family_events(pbp)
    columns = [
        "game_id",
        "team",
        "terminal_non_clock_events",
        "terminal_score_events",
        "terminal_turnover_events",
        "terminal_downs_events",
    ]
    if events.empty:
        return pd.DataFrame(columns=columns)
    data = events.assign(
        score=events["terminal_family"].eq("SCORE").astype(float),
        turnover=events["terminal_family"].eq("TURNOVER").astype(float),
        downs=events["terminal_family"].eq("DOWNS").astype(float),
    )
    data["non_clock"] = data[["score", "turnover", "downs"]].sum(axis=1)
    return (
        data.groupby(["game_id", "team"], dropna=False)
        .agg(
            terminal_non_clock_events=("non_clock", "sum"),
            terminal_score_events=("score", "sum"),
            terminal_turnover_events=("turnover", "sum"),
            terminal_downs_events=("downs", "sum"),
        )
        .reset_index()[columns]
    )


def _evaluate_terminal_non_clock_team_draws(
    team_draws: pd.DataFrame,
    observed: pd.DataFrame,
) -> dict[str, float]:
    if team_draws.empty or observed.empty:
        return {}
    metrics = (
        "terminal_non_clock_events",
        "terminal_score_events",
        "terminal_turnover_events",
        "terminal_downs_events",
    )
    missing = {"game_id", "team", *metrics} - set(team_draws)
    if missing:
        raise ValueError(f"Terminal-family team draws missing columns: {sorted(missing)}")
    predicted = (
        team_draws.groupby(["game_id", "team"], dropna=False)[list(metrics)]
        .mean()
        .reset_index()
    )
    merged = predicted.merge(
        observed,
        on=["game_id", "team"],
        how="outer",
        suffixes=("_pred", "_actual"),
    )
    if merged.empty:
        return {}
    result = {"terminal_team_rows": float(len(merged))}
    for metric in metrics:
        predicted_values = pd.to_numeric(
            merged[f"{metric}_pred"], errors="coerce"
        ).fillna(0.0)
        actual_values = pd.to_numeric(
            merged[f"{metric}_actual"], errors="coerce"
        ).fillna(0.0)
        result[f"team_{metric}_mae"] = float(
            np.mean(np.abs(predicted_values - actual_values))
        )
    return result


def _effect_columns(
    row: dict[str, float | int],
    metrics: dict[str, dict[str, float]],
) -> None:
    for parent, (candidate_name, baseline_name) in _PARENT_PAIRS.items():
        candidate = metrics[candidate_name]
        baseline = metrics[baseline_name]
        for metric in sorted(set(candidate) & set(baseline)):
            candidate_value = candidate[metric]
            baseline_value = baseline[metric]
            if not np.isfinite(candidate_value) or not np.isfinite(baseline_value):
                continue
            effect = f"terminal_on_{parent}"
            row[f"delta_{effect}__{metric}"] = float(candidate_value - baseline_value)
            if metric in _LOWER_IS_BETTER:
                row[f"win_{effect}__{metric}"] = float(candidate_value < baseline_value)


def _weekly_win_rate(frame: pd.DataFrame, parent: str, metric: str) -> float | None:
    column = f"win_terminal_on_{parent}__{metric}"
    if column not in frame:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.mean()) if not values.empty else None


def run_v016_terminal_benchmark(
    pbp: pd.DataFrame,
    schedules: pd.DataFrame,
    *,
    test_seasons: tuple[int, ...] | list[int],
    week_start: int = 1,
    week_end: int = 18,
    players: pd.DataFrame | None = None,
    player_actuals: pd.DataFrame | None = None,
    league_config: LeagueConfig | None = None,
    simulations_per_game: int = 8,
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
    terminal_prior_strength: float = 30.0,
    terminal_half_life_weeks: float = 8.0,
) -> TerminalBenchmarkResult:
    """Run expanding weekly 2x2x2 terminal-family authority attribution."""
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
                train_terminal = extract_terminal_family_events(train_raw)
                test_terminal = extract_terminal_family_events(test_raw)
                train_with_terminal = attach_terminal_family_labels(train, train_raw)
                play_call_model = PlayCallModel().fit(train)
                outcome_model = EmpiricalPlayOutcomeModel().fit(train_with_terminal)
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
                decision_model = FourthDownDecisionModel(
                    prior_strength=decision_prior_strength,
                    half_life_weeks=decision_half_life_weeks,
                ).fit_frame(extract_fourth_down_decisions(train_raw))
                terminal_model = TerminalFamilyModel(
                    prior_strength=terminal_prior_strength,
                    half_life_weeks=terminal_half_life_weeks,
                ).fit_frame(train_terminal)
                full_permuted_model = TerminalFamilyModel(
                    prior_strength=terminal_prior_strength,
                    half_life_weeks=terminal_half_life_weeks,
                ).fit_frame(
                    permute_terminal_families_within_context_season(
                        train_terminal,
                        seed=int(seed + season * 809 + week * 2027),
                    )
                )
                conditional_permuted_model = TerminalFamilyModel(
                    prior_strength=terminal_prior_strength,
                    half_life_weeks=terminal_half_life_weeks,
                ).fit_frame(
                    permute_conditional_terminal_families_within_context_season(
                        train_terminal,
                        seed=int(seed + season * 1151 + week * 4093),
                    )
                )
            except ValueError as exc:
                skipped.append({"season": season, "week": week, "reason": str(exc)})
                continue

            isolated: dict[str, float | int] = {"season": season, "week": week}
            if not test_terminal.empty:
                real = evaluate_terminal_family_scores(terminal_model.score_events(test_terminal))
                full_permuted = evaluate_terminal_family_scores(
                    full_permuted_model.score_events(test_terminal)
                )
                conditional_permuted = evaluate_terminal_family_scores(
                    conditional_permuted_model.score_events(test_terminal)
                )
                isolated.update(real)
                isolated["permuted_terminal_family_log_loss"] = float(
                    full_permuted["terminal_family_log_loss"]
                )
                isolated["permuted_terminal_family_brier"] = float(
                    full_permuted["terminal_family_brier"]
                )
                if "conditional_terminal_log_loss" in conditional_permuted:
                    isolated["permuted_conditional_terminal_log_loss"] = float(
                        conditional_permuted["conditional_terminal_log_loss"]
                    )
                isolated["real_terminal_beats_context_base"] = float(
                    real["terminal_family_log_loss"]
                    < real["context_base_terminal_family_log_loss"]
                )
                isolated["real_terminal_beats_permuted"] = float(
                    real["terminal_family_log_loss"]
                    < full_permuted["terminal_family_log_loss"]
                )
                if (
                    "conditional_terminal_log_loss" in real
                    and "conditional_terminal_log_loss" in conditional_permuted
                ):
                    isolated["real_conditional_beats_permuted"] = float(
                        real["conditional_terminal_log_loss"]
                        < conditional_permuted["conditional_terminal_log_loss"]
                    )
                isolated["real_hazard_beats_context_base"] = float(
                    real["canonical_termination_brier"]
                    < real["context_base_canonical_termination_brier"]
                )
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

            variant_team_draws = {name: [] for name in _VARIANTS}
            variant_player_draws = {name: [] for name in _VARIANTS}
            variant_player_summaries = {name: [] for name in _VARIANTS}
            variant_fallbacks: dict[str, list[float]] = {name: [] for name in _VARIANTS}

            for game_index, (_, schedule_row) in enumerate(schedule_fold.iterrows()):
                matchup = matchup_from_schedule(schedule_row)
                config = SimulationConfig(
                    simulations=int(simulations_per_game),
                    seed=int(seed + season * 101 + week * 1009 + game_index * 7919),
                )
                for variant, (use_transition, use_decision, use_terminal) in _VARIANTS.items():
                    simulation = simulate_matchup_terminal_probe(
                        matchup,
                        tendencies=tendencies,
                        usage=usage,
                        outcome_model=outcome_model,
                        play_call_model=play_call_model,
                        opportunity_model=opportunity_model,
                        drive_volume_model=drive_model,
                        transition_model=transition_model if use_transition else None,
                        decision_model=decision_model if use_decision else None,
                        terminal_family_model=terminal_model if use_terminal else None,
                        termination_hazard_model=terminal_model.hazard_model,
                        league_config=league_config,
                        config=config,
                    )
                    variant_team_draws[variant].append(simulation.team_draws)
                    variant_player_draws[variant].append(simulation.player_draws)
                    summary = simulation.player_summary.copy()
                    summary["season"] = season
                    summary["week"] = week
                    variant_player_summaries[variant].append(summary)
                    fallback = simulation.diagnostics.get("terminal_conditioning_fallback_rate")
                    if fallback is not None and np.isfinite(float(fallback)):
                        variant_fallbacks[variant].append(float(fallback))

            reference = "legacy_transition_legacy_decision_legacy_terminal"
            if not variant_team_draws[reference]:
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
            game_ids = set(team_frames[reference]["game_id"].astype(str))

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
            observed_decisions = observed_fourth_down_team_games(test_raw)
            observed_decisions = observed_decisions.loc[
                observed_decisions["game_id"].astype(str).isin(game_ids)
            ]
            observed_terminal = _observed_terminal_non_clock_team_games(test_raw)
            observed_terminal = observed_terminal.loc[
                observed_terminal["game_id"].astype(str).isin(game_ids)
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
                decision_metrics = evaluate_fourth_down_team_draws(
                    team_frames[variant], observed_decisions
                )
                terminal_metrics = _evaluate_terminal_non_clock_team_draws(
                    team_frames[variant], observed_terminal
                )
                predicted_opportunity = predicted_player_opportunity_from_draws(
                    player_draw_frames[variant]
                )
                opportunity_metrics = evaluate_player_opportunity(
                    predicted_opportunity, observed_opportunity
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
                metrics.update(decision_metrics)
                metrics.update(terminal_metrics)
                if variant_fallbacks[variant]:
                    metrics["terminal_conditioning_fallback_rate"] = float(
                        np.mean(variant_fallbacks[variant])
                    )
                fold_metrics[variant] = metrics
                records[variant].append(metrics)

            row: dict[str, float | int] = {"season": season, "week": week}
            for variant, metrics in fold_metrics.items():
                for metric, value in metrics.items():
                    row[f"{variant}__{metric}"] = float(value)
            _effect_columns(row, fold_metrics)
            weekly_rows.append(row)

    if not weekly_rows:
        raise ValueError("v0.16 terminal benchmark produced no valid full-simulation folds")
    weekly = pd.DataFrame(weekly_rows).sort_values(["season", "week"], kind="mergesort")
    isolated_weekly = pd.DataFrame(isolated_rows)
    if not isolated_weekly.empty:
        isolated_weekly = isolated_weekly.sort_values(["season", "week"], kind="mergesort")
    aggregate = {variant: _aggregate(values) for variant, values in records.items()}
    aggregate_isolated = _aggregate_isolated(isolated_weekly)
    diagnostics = {
        "protocol": "v016_terminal_family_eight_cell_expanding_weekly",
        "test_seasons": sorted({int(value) for value in test_seasons}),
        "week_start": int(week_start),
        "week_end": int(week_end),
        "folds": int(len(weekly)),
        "simulations_per_game": int(simulations_per_game),
        "variants": {
            name: {
                "possession_transition_model": transition,
                "fourth_down_decision_model": decision,
                "terminal_family_authority": terminal,
            }
            for name, (transition, decision, terminal) in _VARIANTS.items()
        },
        "play_call_model_fixed": "learned",
        "opportunity_model_fixed": "state_conditioned",
        "drive_volume_model_fixed": "hierarchical_v013",
        "outcome_model": "same empirical evidence; terminal cells condition on canonical family",
        "terminal_negative_controls": (
            "full family labels shuffled within season/down/field-zone; conditional terminal type "
            "shuffled while exact termination labels remain fixed"
        ),
        "legacy_outcome_rng_alignment": True,
        "terminal_shadow_rng_advances_legacy_stream": False,
        "v015_parity_contract": "terminal-off cells delegate to the v0.15 decision simulator",
        "skipped_folds": skipped,
        "research_only": True,
        "automatic_promotion": False,
        "production_projection_changed": False,
    }
    return TerminalBenchmarkResult(
        weekly_metrics=weekly.reset_index(drop=True),
        aggregate_metrics=aggregate,
        weekly_isolated_metrics=isolated_weekly.reset_index(drop=True),
        aggregate_isolated_metrics=aggregate_isolated,
        diagnostics=diagnostics,
    )


def v016_terminal_promotion_gate(
    benchmark: TerminalBenchmarkResult,
    *,
    min_seasons: int = 3,
    min_games: int = 200,
    min_terminal_rows: int = 5000,
    min_conditional_terminal_rows: int = 500,
    min_direct_improvement_fraction: float = 0.005,
    max_regression_ratio: float = 1.02,
    max_family_regression_ratio: float = 1.05,
    max_ece: float = 0.10,
    max_fallback_rate: float = 0.01,
    min_parent_context_wins: int = 3,
    min_weekly_win_rate: float = 0.52,
) -> SimulationPromotionDecision:
    """Gate terminal authority into manual research-champion review only."""
    reasons: list[str] = []
    isolated = benchmark.aggregate_isolated_metrics
    seasons = benchmark.weekly_metrics["season"].nunique()
    if seasons < int(min_seasons):
        reasons.append(f"insufficient held-out seasons: {seasons} < {min_seasons}")
    games = max(
        (int(values.get("games", 0.0)) for values in benchmark.aggregate_metrics.values()),
        default=0,
    )
    if games < int(min_games):
        reasons.append(f"insufficient replay games: {games} < {min_games}")
    terminal_rows = int(isolated.get("terminal_family_rows", 0.0))
    if terminal_rows < int(min_terminal_rows):
        reasons.append(f"insufficient terminal-family rows: {terminal_rows} < {min_terminal_rows}")
    conditional_rows = int(isolated.get("conditional_terminal_rows", 0.0))
    if conditional_rows < int(min_conditional_terminal_rows):
        reasons.append(
            f"insufficient conditional terminal rows: {conditional_rows} < {min_conditional_terminal_rows}"
        )

    model_loss = isolated.get("terminal_family_log_loss")
    context_loss = isolated.get("context_base_terminal_family_log_loss")
    permuted_loss = isolated.get("permuted_terminal_family_log_loss")
    if model_loss is None or context_loss is None:
        reasons.append("missing terminal-family model/context baseline evidence")
    elif model_loss >= context_loss * (1.0 - float(min_direct_improvement_fraction)):
        reasons.append("terminal-family log loss does not beat context baseline by required margin")
    if model_loss is None or permuted_loss is None:
        reasons.append("missing terminal-family permutation control evidence")
    elif model_loss >= permuted_loss:
        reasons.append("terminal-family model does not beat full permutation control")

    conditional_loss = isolated.get("conditional_terminal_log_loss")
    permuted_conditional = isolated.get("permuted_conditional_terminal_log_loss")
    if conditional_loss is None or permuted_conditional is None:
        reasons.append("missing conditional terminal-family permutation evidence")
    elif conditional_loss >= permuted_conditional:
        reasons.append("conditional terminal-family head does not beat its permutation control")

    ece = isolated.get("terminal_family_ece")
    if ece is None:
        reasons.append("missing terminal-family calibration evidence")
    elif ece > float(max_ece):
        reasons.append(f"terminal-family calibration ECE too high: {ece:.3f} > {max_ece:.3f}")

    parent_wins = 0
    weekly_rates: list[float] = []
    for parent, (candidate_name, baseline_name) in _PARENT_PAIRS.items():
        candidate = benchmark.aggregate_metrics.get(candidate_name, {})
        baseline = benchmark.aggregate_metrics.get(baseline_name, {})
        ratio = _safe_ratio(
            candidate.get("team_terminal_non_clock_events_mae"),
            baseline.get("team_terminal_non_clock_events_mae"),
        )
        if ratio is not None and ratio < 1.0:
            parent_wins += 1
        rate = _weekly_win_rate(
            benchmark.weekly_metrics,
            parent,
            "team_terminal_non_clock_events_mae",
        )
        if rate is not None:
            weekly_rates.append(rate)
        fallback = candidate.get("terminal_conditioning_fallback_rate")
        if fallback is None:
            reasons.append(f"missing terminal conditioning fallback evidence in {candidate_name}")
        elif fallback > float(max_fallback_rate):
            reasons.append(
                f"terminal conditioning fallback rate too high in {candidate_name}: "
                f"{fallback:.3f} > {max_fallback_rate:.3f}"
            )

        for metric in (
            "team_plays_mae",
            "team_drives_mae",
            "team_plays_per_drive_mae",
            "team_seconds_per_play_mae",
            "team_points_mae",
            "player_opportunity_mae",
            "fantasy_pinball_loss",
            "team_punts_mae",
            "team_field_goal_attempts_mae",
            "team_fourth_down_go_attempts_mae",
        ):
            metric_ratio = _safe_ratio(candidate.get(metric), baseline.get(metric))
            if metric_ratio is None:
                reasons.append(f"missing downstream comparison {parent}: {metric}")
            elif metric_ratio > float(max_regression_ratio):
                reasons.append(f"{parent} materially regressed {metric}")

        for metric in (
            "team_terminal_score_events_mae",
            "team_terminal_turnover_events_mae",
            "team_terminal_downs_events_mae",
        ):
            metric_ratio = _safe_ratio(candidate.get(metric), baseline.get(metric))
            if metric_ratio is not None and metric_ratio > float(max_family_regression_ratio):
                reasons.append(f"{parent} materially regressed {metric}")

    if parent_wins < int(min_parent_context_wins):
        reasons.append(
            f"terminal authority improves only {parent_wins}/4 parent contexts; "
            f"requires {min_parent_context_wins}"
        )
    if not weekly_rates:
        reasons.append("missing weekly terminal-family win-rate evidence")
    elif float(np.mean(weekly_rates)) < float(min_weekly_win_rate):
        reasons.append(
            "mean weekly terminal-family win rate below floor: "
            f"{float(np.mean(weekly_rates)):.3f} < {min_weekly_win_rate:.3f}"
        )

    metrics: dict[str, float] = {}
    for variant, values in benchmark.aggregate_metrics.items():
        for key, value in values.items():
            if np.isfinite(value):
                metrics[f"{variant}__{key}"] = float(value)
    for key, value in isolated.items():
        if np.isfinite(value):
            metrics[f"isolated__{key}"] = float(value)
    metrics["terminal_parent_context_wins"] = float(parent_wins)
    if weekly_rates:
        metrics["terminal_mean_weekly_win_rate"] = float(np.mean(weekly_rates))
    return SimulationPromotionDecision(
        promoted=not reasons,
        reasons=reasons,
        metrics=metrics,
        model_source="terminal_family_promotion_gate_v016",
    )


def recommend_v017_development(benchmark: TerminalBenchmarkResult) -> dict[str, object]:
    """Route v0.17 from isolated family signal and downstream intervention behavior."""
    isolated = benchmark.aggregate_isolated_metrics
    full_signal = (
        isolated.get("terminal_family_log_loss") is not None
        and isolated.get("context_base_terminal_family_log_loss") is not None
        and isolated.get("permuted_terminal_family_log_loss") is not None
        and isolated["terminal_family_log_loss"]
        < isolated["context_base_terminal_family_log_loss"]
        and isolated["terminal_family_log_loss"]
        < isolated["permuted_terminal_family_log_loss"]
    )
    conditional_signal = (
        isolated.get("conditional_terminal_log_loss") is not None
        and isolated.get("permuted_conditional_terminal_log_loss") is not None
        and isolated["conditional_terminal_log_loss"]
        < isolated["permuted_conditional_terminal_log_loss"]
    )
    hazard_signal = (
        isolated.get("canonical_termination_brier") is not None
        and isolated.get("context_base_canonical_termination_brier") is not None
        and isolated["canonical_termination_brier"]
        < isolated["context_base_canonical_termination_brier"]
    )

    primary_candidate = benchmark.aggregate_metrics.get("transition_decision_terminal", {})
    primary_baseline = benchmark.aggregate_metrics.get(
        "transition_decision_legacy_terminal", {}
    )
    terminal_ratio = _safe_ratio(
        primary_candidate.get("team_terminal_non_clock_events_mae"),
        primary_baseline.get("team_terminal_non_clock_events_mae"),
    )
    points_ratio = _safe_ratio(
        primary_candidate.get("team_points_mae"), primary_baseline.get("team_points_mae")
    )
    fantasy_ratio = _safe_ratio(
        primary_candidate.get("fantasy_pinball_loss"),
        primary_baseline.get("fantasy_pinball_loss"),
    )
    play_ratio = _safe_ratio(
        primary_candidate.get("team_plays_mae"), primary_baseline.get("team_plays_mae")
    )

    signals: list[str] = []
    if hazard_signal:
        signals.append("canonical possession-termination hazard beats observable-state baseline")
    if conditional_signal:
        signals.append("conditional terminal type beats permutation control")
    if full_signal:
        signals.append("five-family terminal distribution beats context and permutation controls")
    if terminal_ratio is not None and terminal_ratio < 1.0:
        signals.append("terminal authority improves non-clock terminal event frequency")
    if play_ratio is not None and play_ratio < 1.0:
        signals.append("terminal authority improves team play volume")
    if points_ratio is not None and points_ratio < 1.0:
        signals.append("terminal authority improves scoring error")
    if fantasy_ratio is not None and fantasy_ratio < 1.0:
        signals.append("terminal authority improves fantasy distribution loss")

    if full_signal and conditional_signal and terminal_ratio is not None and terminal_ratio < 1.0:
        if (points_ratio is None or points_ratio <= 1.0) and (
            fantasy_ratio is None or fantasy_ratio <= 1.0
        ):
            next_experiment = "latent_drive_strategy_state"
            rationale = (
                "Terminal family is now predictive and transfers safely into the world model. "
                "The next interpretable missing variable is persistent possession strategy state."
            )
        else:
            next_experiment = "decomposed_scoring_execution"
            rationale = (
                "Terminal timing/family improves but scoring or fantasy conversion regresses. "
                "Separate completion, rush efficiency, turnover and touchdown execution heads next."
            )
    elif hazard_signal and not conditional_signal:
        next_experiment = "richer_terminal_family_context"
        rationale = (
            "We can predict that a possession ends but not how it ends. Add coach/QB, exact score-clock, "
            "timeouts and red-zone execution context before granting richer family authority."
        )
    elif conditional_signal and terminal_ratio is not None and terminal_ratio >= 1.0:
        next_experiment = "terminal_authority_mechanics_audit"
        rationale = (
            "Terminal type is learnable in isolation but does not transfer to simulation frequency. "
            "Audit conditioned outcome support, END_HALF clock coupling and interaction with fourth-down policy."
        )
    elif full_signal and play_ratio is not None and play_ratio >= 1.0:
        next_experiment = "drive_strategy_and_continuation_state"
        rationale = (
            "Terminal labels are learnable but total play volume remains weak. Model persistent drive strategy "
            "and continuation state rather than adding a larger terminal classifier."
        )
    else:
        next_experiment = "collect_more_terminal_replay_evidence"
        rationale = (
            "The current evidence does not isolate a stable next causal layer. Expand replay and segment "
            "terminal residuals by family, down, field zone, team and coaching regime."
        )

    return {
        "next_experiment": next_experiment,
        "rationale": rationale,
        "signals": signals,
        "ratios": {
            "terminal_non_clock_events": terminal_ratio,
            "team_plays": play_ratio,
            "team_points": points_ratio,
            "fantasy_pinball": fantasy_ratio,
        },
        "hazard_signal": bool(hazard_signal),
        "conditional_family_signal": bool(conditional_signal),
        "full_family_signal": bool(full_signal),
        "research_only": True,
        "production_projection_changed": False,
    }
