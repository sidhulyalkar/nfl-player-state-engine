from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.evaluation import (
    evaluate_play_call_probabilities,
    evaluate_player_opportunity,
    evaluate_team_simulation_draws,
)
from player_state_engine.game_intelligence.models import EmpiricalPlayOutcomeModel, PlayCallModel
from player_state_engine.game_intelligence.opportunity import (
    StateConditionedOpportunityModel,
    evaluate_opportunity_event_scores,
    permute_context_within_team_season,
)
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
from player_state_engine.game_intelligence.simulator import simulate_matchup
from player_state_engine.game_intelligence.tendencies import (
    attach_point_in_time_matchup_features,
    build_team_tendency_snapshots,
)
from player_state_engine.game_intelligence.usage import build_player_usage_profiles

_VARIANTS = {
    "profile_static": (False, False),
    "learned_static": (True, False),
    "profile_state": (False, True),
    "learned_state": (True, True),
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
}
_CONTEXTS = (
    "red_zone",
    "third_down",
    "early_down",
    "late_game",
    "score_state",
    "distance_bucket",
    "field_zone",
)


@dataclass(slots=True)
class FactorialBenchmarkResult:
    weekly_metrics: pd.DataFrame
    aggregate_metrics: dict[str, dict[str, float]]
    weekly_ablation_metrics: pd.DataFrame
    aggregate_ablation_metrics: dict[str, float]
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
    return max(float(record.get("games", 0.0)), 1.0)


def _aggregate(records: list[dict[str, float]]) -> dict[str, float]:
    if not records:
        return {}
    keys = sorted({key for record in records for key in record})
    totals = {"games", "player_rows", "predicted_player_rows", "observed_player_rows", "fantasy_rows"}
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
            result[key] = float(
                sum(value * weight for value, weight in values) / sum(weight for _, weight in values)
            )
    return result


def _safe_ratio(candidate: float | None, baseline: float | None) -> float | None:
    if candidate is None or baseline is None or not np.isfinite(candidate) or not np.isfinite(baseline):
        return None
    if abs(float(baseline)) < 1e-12:
        return None
    return float(candidate) / float(baseline)


def _add_pairwise_deltas(
    row: dict[str, float | int], variant_metrics: dict[str, dict[str, float]]
) -> None:
    comparisons = {
        "play_call": ("learned_static", "profile_static"),
        "allocation_profile": ("profile_state", "profile_static"),
        "allocation_learned": ("learned_state", "learned_static"),
        "combined": ("learned_state", "profile_static"),
    }
    for effect, (candidate_name, baseline_name) in comparisons.items():
        candidate = variant_metrics[candidate_name]
        baseline = variant_metrics[baseline_name]
        for metric in sorted(set(candidate) & set(baseline)):
            c = candidate[metric]
            b = baseline[metric]
            if not np.isfinite(c) or not np.isfinite(b):
                continue
            row[f"delta_{effect}__{metric}"] = float(c - b)
            if metric in _LOWER_IS_BETTER:
                row[f"win_{effect}__{metric}"] = float(c < b)


def _opportunity_ablation_fold(
    train: pd.DataFrame,
    test: pd.DataFrame,
    *,
    prior_strength: float,
    half_life_weeks: float,
    seed: int,
) -> dict[str, float]:
    variants: dict[str, tuple[pd.DataFrame, tuple[str, ...], bool]] = {
        "static": (train, (), False),
        "red_zone_only": (train, ("red_zone",), True),
        "full": (train, _CONTEXTS, True),
    }
    for context in _CONTEXTS:
        variants[f"without_{context}"] = (
            train,
            tuple(value for value in _CONTEXTS if value != context),
            True,
        )
    variants["permuted_full"] = (
        permute_context_within_team_season(train, seed=seed, context_columns=_CONTEXTS),
        _CONTEXTS,
        True,
    )
    result: dict[str, float] = {}
    for name, (training_frame, contexts, use_context) in variants.items():
        model = StateConditionedOpportunityModel(
            prior_strength=prior_strength,
            half_life_weeks=half_life_weeks,
            context_columns=contexts,
        ).fit(training_frame)
        scores = model.score_events(test, use_context=use_context)
        if scores.empty:
            continue
        metrics = evaluate_opportunity_event_scores(scores)
        result[f"{name}__log_loss"] = float(
            metrics["state_conditioned_log_loss"] if use_context else metrics["static_share_log_loss"]
        )
        result[f"{name}__rows"] = float(metrics["event_rows"])
    return result


def run_v012_factorial_benchmark(
    pbp: pd.DataFrame,
    schedules: pd.DataFrame,
    *,
    test_seasons: tuple[int, ...] | list[int],
    week_start: int = 1,
    week_end: int = 18,
    players: pd.DataFrame | None = None,
    player_actuals: pd.DataFrame | None = None,
    league_config: LeagueConfig | None = None,
    simulations_per_game: int = 50,
    max_games_per_week: int | None = None,
    seed: int = 42,
    opportunity_prior_strength: float = 12.0,
    opportunity_half_life_weeks: float = 4.0,
    run_context_ablations: bool = True,
) -> FactorialBenchmarkResult:
    """Run four simulator variants with common random numbers at each frozen weekly cutoff."""
    play_frame = build_play_intelligence_frame(pbp)
    tendencies = build_team_tendency_snapshots(play_frame)
    enriched = attach_point_in_time_matchup_features(play_frame, tendencies)
    chronology = _chronology(enriched)
    weekly_rows: list[dict[str, float | int]] = []
    weekly_ablation_rows: list[dict[str, float | int]] = []
    records: dict[str, list[dict[str, float]]] = {name: [] for name in _VARIANTS}
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
                skipped.append({"season": season, "week": week, "reason": "insufficient pre-cutoff plays"})
                continue

            try:
                play_call_model = PlayCallModel().fit(train)
                outcome_model = EmpiricalPlayOutcomeModel().fit(train)
                opportunity_model = StateConditionedOpportunityModel(
                    prior_strength=opportunity_prior_strength,
                    half_life_weeks=opportunity_half_life_weeks,
                ).fit(train)
            except ValueError as exc:
                skipped.append({"season": season, "week": week, "reason": str(exc)})
                continue

            variant_team_draws: dict[str, list[pd.DataFrame]] = {name: [] for name in _VARIANTS}
            variant_player_draws: dict[str, list[pd.DataFrame]] = {name: [] for name in _VARIANTS}
            variant_player_summaries: dict[str, list[pd.DataFrame]] = {name: [] for name in _VARIANTS}

            for game_index, (_, schedule_row) in enumerate(schedule_fold.iterrows()):
                matchup = matchup_from_schedule(schedule_row)
                usage = build_player_usage_profiles(
                    play_frame, season=season, week=week, players=players
                )
                if usage.empty:
                    continue
                config = SimulationConfig(
                    simulations=int(simulations_per_game),
                    seed=int(seed + season * 101 + week * 1009 + game_index * 7919),
                )
                for variant, (use_play_call, use_state_opportunity) in _VARIANTS.items():
                    result = simulate_matchup(
                        matchup,
                        tendencies=tendencies,
                        usage=usage,
                        outcome_model=outcome_model,
                        play_call_model=play_call_model if use_play_call else None,
                        opportunity_model=opportunity_model if use_state_opportunity else None,
                        league_config=league_config,
                        config=config,
                    )
                    variant_team_draws[variant].append(result.team_draws)
                    variant_player_draws[variant].append(result.player_draws)
                    summary = result.player_summary.copy()
                    summary["season"] = season
                    summary["week"] = week
                    variant_player_summaries[variant].append(summary)

            if not variant_team_draws["profile_static"]:
                skipped.append({"season": season, "week": week, "reason": "no games had usable player state"})
                continue

            team_frames = {
                name: pd.concat(frames, ignore_index=True) for name, frames in variant_team_draws.items()
            }
            player_draw_frames = {
                name: pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
                for name, frames in variant_player_draws.items()
            }
            player_summaries = {
                name: pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
                for name, frames in variant_player_summaries.items()
            }
            game_ids = set(team_frames["profile_static"]["game_id"].astype(str))
            observed_teams = observed_team_games(play_frame, schedule_fold)
            observed_teams = observed_teams.loc[observed_teams["game_id"].astype(str).isin(game_ids)]
            observed_opportunity = observed_player_opportunity(play_frame)
            observed_opportunity = observed_opportunity.loc[
                observed_opportunity["game_id"].astype(str).isin(game_ids)
            ]
            fold_test_plays = test_plays.loc[test_plays["game_id"].astype(str).isin(game_ids)]
            profile_probability = pd.to_numeric(
                fold_test_plays["pregame_pass_rate"], errors="coerce"
            ).fillna(float(train["is_dropback"].mean()))
            learned_probability = play_call_model.predict_pass_probability(fold_test_plays)
            play_metrics = {
                False: evaluate_play_call_probabilities(fold_test_plays["is_dropback"], profile_probability),
                True: evaluate_play_call_probabilities(fold_test_plays["is_dropback"], learned_probability),
            }

            fold_metrics: dict[str, dict[str, float]] = {}
            for variant, (use_play_call, _) in _VARIANTS.items():
                team_metrics = evaluate_team_simulation_draws(team_frames[variant], observed_teams)
                predicted_opportunity = predicted_player_opportunity_from_draws(
                    player_draw_frames[variant]
                )
                opportunity_metrics = evaluate_player_opportunity(
                    predicted_opportunity, observed_opportunity
                )
                fantasy_metrics = _fantasy_metrics(player_summaries[variant], player_actuals)
                metrics = _combine_metrics(
                    play_metrics[use_play_call], team_metrics, opportunity_metrics, fantasy_metrics
                )
                fold_metrics[variant] = metrics
                records[variant].append(metrics)

            row: dict[str, float | int] = {"season": season, "week": week}
            for variant, metrics in fold_metrics.items():
                for metric, value in metrics.items():
                    row[f"{variant}__{metric}"] = float(value)
            _add_pairwise_deltas(row, fold_metrics)
            weekly_rows.append(row)

            if run_context_ablations:
                try:
                    ablation = _opportunity_ablation_fold(
                        train,
                        fold_test_plays,
                        prior_strength=opportunity_prior_strength,
                        half_life_weeks=opportunity_half_life_weeks,
                        seed=int(seed + season * 101 + week * 1009),
                    )
                except ValueError as exc:
                    skipped.append({"season": season, "week": week, "reason": f"opportunity ablation: {exc}"})
                else:
                    weekly_ablation_rows.append({"season": season, "week": week, **ablation})

    if not weekly_rows:
        raise ValueError("v0.12 factorial benchmark produced no valid folds")

    weekly = pd.DataFrame(weekly_rows).sort_values(["season", "week"], kind="mergesort")
    weekly_ablation = pd.DataFrame(weekly_ablation_rows)
    if not weekly_ablation.empty:
        weekly_ablation = weekly_ablation.sort_values(["season", "week"], kind="mergesort")
    aggregate = {variant: _aggregate(values) for variant, values in records.items()}

    aggregate_ablation: dict[str, float] = {}
    if not weekly_ablation.empty:
        for column in weekly_ablation.columns:
            if column in {"season", "week"} or not column.endswith("__log_loss"):
                continue
            values = pd.to_numeric(weekly_ablation[column], errors="coerce").dropna()
            if not values.empty:
                aggregate_ablation[column] = float(values.mean())

    diagnostics = {
        "protocol": "v012_factorial_expanding_weekly_point_in_time",
        "test_seasons": sorted({int(value) for value in test_seasons}),
        "week_start": int(week_start),
        "week_end": int(week_end),
        "folds": int(len(weekly)),
        "simulations_per_game": int(simulations_per_game),
        "variants": {
            name: {"learned_play_call": use_play_call, "state_conditioned_opportunity": use_state}
            for name, (use_play_call, use_state) in _VARIANTS.items()
        },
        "common_random_numbers": True,
        "opportunity_metric_source": "simulated_player_draws_union_scoring",
        "context_ablations": bool(run_context_ablations),
        "skipped_folds": skipped,
        "research_only": True,
        "production_projection_changed": False,
    }
    return FactorialBenchmarkResult(
        weekly_metrics=weekly.reset_index(drop=True),
        aggregate_metrics=aggregate,
        weekly_ablation_metrics=weekly_ablation.reset_index(drop=True),
        aggregate_ablation_metrics=aggregate_ablation,
        diagnostics=diagnostics,
    )


def _weekly_win_rate(frame: pd.DataFrame, effect: str, metric: str) -> float | None:
    column = f"win_{effect}__{metric}"
    if column not in frame:
        return None
    values = pd.to_numeric(frame[column], errors="coerce").dropna()
    return float(values.mean()) if not values.empty else None


def v012_state_opportunity_promotion_gate(
    benchmark: FactorialBenchmarkResult,
    *,
    min_seasons: int = 3,
    min_games: int = 200,
    min_opportunity_improvement_fraction: float = 0.005,
    max_component_regression_ratio: float = 1.02,
    max_fantasy_pinball_ratio: float = 1.00,
    min_weekly_opportunity_win_rate: float = 0.55,
) -> SimulationPromotionDecision:
    """Gate state-conditioned allocation into the research generative champion only."""
    reasons: list[str] = []
    learned_static = benchmark.aggregate_metrics.get("learned_static", {})
    learned_state = benchmark.aggregate_metrics.get("learned_state", {})
    seasons = benchmark.weekly_metrics["season"].nunique()
    if seasons < int(min_seasons):
        reasons.append(f"insufficient held-out seasons: {seasons} < {min_seasons}")
    games = int(learned_state.get("games", 0.0))
    if games < int(min_games):
        reasons.append(f"insufficient replay games: {games} < {min_games}")

    candidate_opportunity = learned_state.get("player_opportunity_mae")
    baseline_opportunity = learned_static.get("player_opportunity_mae")
    ratio = _safe_ratio(candidate_opportunity, baseline_opportunity)
    if ratio is None:
        reasons.append("missing full-pregame player opportunity comparison")
    elif ratio > 1.0 - float(min_opportunity_improvement_fraction):
        reasons.append("state-conditioned allocation did not improve full-pregame opportunity enough")

    for metric in ("player_carries_mae", "player_targets_mae"):
        component_ratio = _safe_ratio(learned_state.get(metric), learned_static.get(metric))
        if component_ratio is None:
            reasons.append(f"missing {metric} comparison")
        elif component_ratio > float(max_component_regression_ratio):
            reasons.append(f"{metric} materially regressed")

    fantasy_ratio = _safe_ratio(
        learned_state.get("fantasy_pinball_loss"), learned_static.get("fantasy_pinball_loss")
    )
    if fantasy_ratio is None:
        reasons.append("missing fantasy pinball comparison")
    elif fantasy_ratio > float(max_fantasy_pinball_ratio):
        reasons.append("fantasy pinball loss regressed with state-conditioned allocation")

    win_rate = _weekly_win_rate(benchmark.weekly_metrics, "allocation_learned", "player_opportunity_mae")
    if win_rate is None:
        reasons.append("missing weekly opportunity win-rate evidence")
    elif win_rate < float(min_weekly_opportunity_win_rate):
        reasons.append(
            f"weekly opportunity win rate below floor: {win_rate:.3f} < {min_weekly_opportunity_win_rate:.3f}"
        )

    full_log_loss = benchmark.aggregate_ablation_metrics.get("full__log_loss")
    static_log_loss = benchmark.aggregate_ablation_metrics.get("static__log_loss")
    permuted_log_loss = benchmark.aggregate_ablation_metrics.get("permuted_full__log_loss")
    if full_log_loss is None or static_log_loss is None or permuted_log_loss is None:
        reasons.append("missing full/static/permuted opportunity ablation evidence")
    else:
        if full_log_loss >= static_log_loss:
            reasons.append("full context allocator did not beat static share in oracle-state ablation")
        if full_log_loss >= permuted_log_loss:
            reasons.append("full context allocator did not beat the permuted-context negative control")

    metrics: dict[str, float] = {}
    for prefix, values in benchmark.aggregate_metrics.items():
        for key, value in values.items():
            if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(value):
                metrics[f"{prefix}__{key}"] = float(value)
    if win_rate is not None:
        metrics["allocation_learned__weekly_opportunity_win_rate"] = float(win_rate)
    return SimulationPromotionDecision(
        promoted=not reasons,
        reasons=reasons,
        metrics=metrics,
        model_source="state_opportunity_promotion_gate_v012",
    )


def recommend_next_development(benchmark: FactorialBenchmarkResult) -> dict[str, object]:
    """Translate comparative replay evidence into a conservative next experiment recommendation."""
    profile_static = benchmark.aggregate_metrics.get("profile_static", {})
    learned_static = benchmark.aggregate_metrics.get("learned_static", {})
    learned_state = benchmark.aggregate_metrics.get("learned_state", {})
    signals: list[str] = []

    allocation_ratio = _safe_ratio(
        learned_state.get("player_opportunity_mae"), learned_static.get("player_opportunity_mae")
    )
    fantasy_ratio = _safe_ratio(
        learned_state.get("fantasy_pinball_loss"), learned_static.get("fantasy_pinball_loss")
    )
    play_call_ratio = _safe_ratio(
        learned_static.get("play_call_log_loss"), profile_static.get("play_call_log_loss")
    )
    team_plays_ratio = _safe_ratio(
        learned_static.get("team_plays_mae"), profile_static.get("team_plays_mae")
    )
    points_ratio = _safe_ratio(
        learned_state.get("team_points_mae"), learned_static.get("team_points_mae")
    )
    full_log_loss = benchmark.aggregate_ablation_metrics.get("full__log_loss")
    static_log_loss = benchmark.aggregate_ablation_metrics.get("static__log_loss")

    if allocation_ratio is not None and allocation_ratio < 1.0:
        signals.append("state-conditioned allocation improves full-pregame player opportunity")
    if fantasy_ratio is not None and fantasy_ratio < 1.0:
        signals.append("state-conditioned allocation improves fantasy distribution loss")
    if play_call_ratio is not None and play_call_ratio < 1.0:
        signals.append("learned play calling improves play-family probability loss")
    if full_log_loss is not None and static_log_loss is not None and full_log_loss < static_log_loss:
        signals.append("real play-state context carries oracle-state allocation information")

    if allocation_ratio is not None and allocation_ratio < 1.0 and fantasy_ratio is not None and fantasy_ratio <= 1.0:
        next_experiment = "role_route_alignment_conditioning"
        rationale = (
            "The allocator survives simulated-state replay, so the next information gain is richer "
            "role evidence: route participation, alignment, personnel package, goal-line and third-down role."
        )
    elif full_log_loss is not None and static_log_loss is not None and full_log_loss < static_log_loss and (allocation_ratio is None or allocation_ratio >= 1.0):
        next_experiment = "pace_and_drive_state"
        rationale = (
            "Context is useful when the real play-state path is known but does not survive full pregame "
            "simulation. Improve the simulated state distribution and team volume before adding allocator complexity."
        )
    elif play_call_ratio is not None and play_call_ratio < 1.0 and team_plays_ratio is not None and team_plays_ratio >= 0.995:
        next_experiment = "pace_and_drive_volume"
        rationale = (
            "Play-family probabilities improve without a corresponding team-volume gain, pointing to pace, "
            "drive continuation, field position and possession length rather than another play-call formula."
        )
    elif allocation_ratio is not None and allocation_ratio < 1.0 and points_ratio is not None and points_ratio >= 1.0:
        next_experiment = "decomposed_play_outcomes"
        rationale = (
            "Opportunity is improving while scoring is not. Decompose completion, yards, sacks, turnovers and "
            "touchdown conversion before adding sequence representations."
        )
    else:
        next_experiment = "collect_more_factorial_replay_evidence"
        rationale = (
            "The comparative evidence does not isolate one stable bottleneck. Expand held-out seasons/weeks or "
            "improve point-in-time evidence coverage before choosing a larger architecture."
        )

    return {
        "next_experiment": next_experiment,
        "rationale": rationale,
        "signals": signals,
        "ratios": {
            "allocation_opportunity": allocation_ratio,
            "allocation_fantasy": fantasy_ratio,
            "play_call_log_loss": play_call_ratio,
            "team_plays": team_plays_ratio,
            "team_points": points_ratio,
        },
        "research_only": True,
    }
