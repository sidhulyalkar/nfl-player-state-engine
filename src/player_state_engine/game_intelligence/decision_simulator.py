from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.scoring import score_simulation_draws
from player_state_engine.game_intelligence.decision import (
    DriveTerminationHazardModel,
    FourthDownDecisionModel,
)
from player_state_engine.game_intelligence.drive import DriveVolumeModel
from player_state_engine.game_intelligence.models import EmpiricalPlayOutcomeModel, PlayCallModel
from player_state_engine.game_intelligence.opportunity import StateConditionedOpportunityModel
from player_state_engine.game_intelligence.schema import MatchupSpec, SimulationConfig
from player_state_engine.game_intelligence.simulator import (
    PlayByPlaySimulationResult,
    _bucket_distance,
    _complete_player_draw_matrix,
    _field_goal_success,
    _field_zone,
    _fourth_down_action,
    _pass_probability,
    _record,
    _select_player,
    _select_state_conditioned_player,
    _summarize,
)
from player_state_engine.game_intelligence.tendencies import build_matchup_profile
from player_state_engine.game_intelligence.transition import PossessionTransitionModel
from player_state_engine.game_intelligence.transition_simulator import (
    _make_transition_helpers,
    _other_team,
)


def _component_rngs(
    seed: int,
    simulation: int,
) -> tuple[
    np.random.Generator,
    np.random.Generator,
    np.random.Generator,
    np.random.Generator,
    np.random.Generator,
    np.random.Generator,
    np.random.Generator,
]:
    """Preserve v0.14's first six streams and add one decision-only stream."""
    sequence = np.random.SeedSequence([int(seed), int(simulation), 13])
    children = sequence.spawn(7)
    return tuple(np.random.default_rng(child) for child in children)


def _binary_log_loss(actual: list[float], probability: list[float]) -> float | None:
    if not actual:
        return None
    y = np.asarray(actual, dtype=float)
    p = np.clip(np.asarray(probability, dtype=float), 1e-8, 1.0 - 1e-8)
    return float(np.mean(-(y * np.log(p) + (1.0 - y) * np.log(1.0 - p))))


def _binary_brier(actual: list[float], probability: list[float]) -> float | None:
    if not actual:
        return None
    return float(
        np.mean(
            (np.asarray(probability, dtype=float) - np.asarray(actual, dtype=float)) ** 2
        )
    )


def simulate_matchup_decision_probe(
    matchup: MatchupSpec,
    *,
    tendencies: pd.DataFrame,
    usage: pd.DataFrame,
    outcome_model: EmpiricalPlayOutcomeModel,
    play_call_model: PlayCallModel | None = None,
    opportunity_model: StateConditionedOpportunityModel | None = None,
    drive_volume_model: DriveVolumeModel | None = None,
    transition_model: PossessionTransitionModel | None = None,
    decision_model: FourthDownDecisionModel | None = None,
    termination_hazard_model: DriveTerminationHazardModel | None = None,
    league_config: LeagueConfig | None = None,
    config: SimulationConfig | None = None,
) -> PlayByPlaySimulationResult:
    """Research-only v0.15 probe with learned fourth-down action authority.

    The v0.14 transition simulator remains the frozen comparator. When decision_model is
    disabled, this probe preserves the v0.14 first six RNG streams and core trajectory.
    When enabled, the frozen fourth-down heuristic is still evaluated to consume its exact
    special-teams RNG draws; the challenger uses a seventh independent stream. The binary
    termination hazard is diagnostic-only in v0.15 because a calibrated hazard alone does not
    identify which terminal family should be generated.
    """
    config = config or SimulationConfig()
    game_id = matchup.resolved_game_id
    game_usage = usage.loc[
        usage["team"].astype(str).isin([str(matchup.home_team), str(matchup.away_team)])
    ].copy()
    if game_usage.empty:
        raise ValueError("Decision probe requires point-in-time usage for a matchup team")

    profiles = {
        matchup.home_team: build_matchup_profile(
            tendencies,
            season=matchup.season,
            week=matchup.week,
            offense_team=matchup.home_team,
            defense_team=matchup.away_team,
        ),
        matchup.away_team: build_matchup_profile(
            tendencies,
            season=matchup.season,
            week=matchup.week,
            offense_team=matchup.away_team,
            defense_team=matchup.home_team,
        ),
    }

    player_stats: defaultdict[tuple[int, str], dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    team_rows: list[dict[str, object]] = []
    game_rows: list[dict[str, object]] = []
    diagnostic_counts = {
        "modeled_transition_events": 0,
        "aligned_discarded_drive_start_draws": 0,
        "modeled_fourth_down_decisions": 0,
        "aligned_legacy_fourth_down_decisions": 0,
        "aligned_discarded_legacy_fg_draws": 0,
    }
    modeled_pace_plays = 0
    state_allocation_attempts = 0
    state_allocation_fallbacks = 0
    termination_actuals: list[float] = []
    termination_probabilities: list[float] = []

    for simulation in range(config.simulations):
        (
            rng_special,
            rng_play_call,
            rng_outcome,
            rng_allocation,
            rng_tempo,
            rng_transition,
            rng_decision,
        ) = _component_rngs(config.seed, simulation)
        scores = {matchup.home_team: 0.0, matchup.away_team: 0.0}
        plays = {matchup.home_team: 0, matchup.away_team: 0}
        dropbacks = {matchup.home_team: 0, matchup.away_team: 0}
        drives = {matchup.home_team: 0, matchup.away_team: 0}
        start_yardline_sum = {matchup.home_team: 0.0, matchup.away_team: 0.0}
        continuing_runoff_sum = {matchup.home_team: 0.0, matchup.away_team: 0.0}
        continuing_runoff_count = {matchup.home_team: 0, matchup.away_team: 0}
        punts = {matchup.home_team: 0.0, matchup.away_team: 0.0}
        field_goal_attempts = {matchup.home_team: 0.0, matchup.away_team: 0.0}
        field_goals_made = {matchup.home_team: 0.0, matchup.away_team: 0.0}
        turnovers = {matchup.home_team: 0.0, matchup.away_team: 0.0}
        turnovers_on_downs = {matchup.home_team: 0.0, matchup.away_team: 0.0}
        fourth_down_decisions = {matchup.home_team: 0.0, matchup.away_team: 0.0}
        fourth_down_go_attempts = {matchup.home_team: 0.0, matchup.away_team: 0.0}
        pending_drive: dict[str, object] = {}
        start_possession, terminal_transition = _make_transition_helpers(
            matchup=matchup,
            drive_volume_model=drive_volume_model,
            transition_model=transition_model,
            rng_tempo=rng_tempo,
            rng_transition=rng_transition,
            pending_drive=pending_drive,
            diagnostic_counts=diagnostic_counts,
        )

        initial_offense = (
            matchup.home_team if rng_special.random() < 0.5 else matchup.away_team
        )
        offense, defense, yardline, down, distance = start_possession(initial_offense, 75.0)
        clock = 3600.0
        play_index = 0

        while clock > 0 and play_index < config.max_plays:
            play_index += 1
            before_clock = clock

            if down == 4:
                fourth_down_decisions[offense] += 1.0
                state_for_decision = {
                    "down": float(down),
                    "ydstogo": float(distance),
                    "yardline_100": float(yardline),
                    "game_seconds_remaining": float(clock),
                    "score_differential": float(scores[offense] - scores[defense]),
                }
                legacy_action = _fourth_down_action(
                    yardline,
                    distance,
                    rng_special,
                    config.fourth_down_aggression_scale,
                )
                diagnostic_counts["aligned_legacy_fourth_down_decisions"] += 1
                legacy_fg_uniform: float | None = None
                if legacy_action == "FIELD_GOAL":
                    legacy_fg_uniform = float(rng_special.random())
                if decision_model is None:
                    action = legacy_action
                else:
                    diagnostic_counts["modeled_fourth_down_decisions"] += 1
                    action = decision_model.sample_action(
                        team=offense,
                        state=state_for_decision,
                        rng=rng_decision,
                    )
                    if legacy_fg_uniform is not None and action != "FIELD_GOAL":
                        diagnostic_counts["aligned_discarded_legacy_fg_draws"] += 1

                if action == "FIELD_GOAL":
                    play_offense = offense
                    source_yardline = float(yardline)
                    field_goal_attempts[play_offense] += 1.0
                    probability = (
                        transition_model.field_goal_make_probability(
                            team=play_offense,
                            yardline_100=source_yardline,
                        )
                        if transition_model is not None
                        else _field_goal_success(source_yardline)
                    )
                    if decision_model is None:
                        if legacy_fg_uniform is None:
                            legacy_fg_uniform = float(rng_special.random())
                        made = bool(legacy_fg_uniform < probability)
                    else:
                        made = bool(rng_decision.random() < probability)
                    transition_type = "FIELD_GOAL_GOOD" if made else "FIELD_GOAL_MISSED"
                    if made:
                        scores[play_offense] += 3.0
                        field_goals_made[play_offense] += 1.0
                    if transition_model is None:
                        clock = max(0.0, clock - min(6.0, clock))
                        offense, defense, yardline, down, distance = start_possession(
                            _other_team(play_offense, matchup),
                            75.0,
                        )
                    else:
                        (
                            offense,
                            defense,
                            yardline,
                            down,
                            distance,
                            clock,
                        ) = terminal_transition(
                            previous_offense=play_offense,
                            transition_type=transition_type,
                            source_yardline_100=source_yardline,
                            fallback_yardline_100=75.0,
                            fallback_seconds=6.0,
                            clock_value=clock,
                        )
                    continue
                if action == "PUNT":
                    play_offense = offense
                    source_yardline = float(yardline)
                    punts[play_offense] += 1.0
                    if transition_model is None:
                        clock = max(0.0, clock - min(8.0, clock))
                        offense, defense, yardline, down, distance = start_possession(
                            _other_team(play_offense, matchup),
                            80.0,
                        )
                    else:
                        (
                            offense,
                            defense,
                            yardline,
                            down,
                            distance,
                            clock,
                        ) = terminal_transition(
                            previous_offense=play_offense,
                            transition_type="PUNT",
                            source_yardline_100=source_yardline,
                            fallback_yardline_100=80.0,
                            fallback_seconds=8.0,
                            clock_value=clock,
                        )
                    continue
                fourth_down_go_attempts[play_offense] += 1.0

            play_offense = offense
            if pending_drive and str(pending_drive.get("team")) == str(play_offense):
                drives[play_offense] += 1
                start_yardline_sum[play_offense] += float(
                    pending_drive.get("start_yardline_100", yardline)
                )
                pending_drive.clear()

            state = {
                "down": float(down),
                "ydstogo": float(distance),
                "yardline_100": float(yardline),
                "game_seconds_remaining": float(clock),
                "score_differential": float(scores[offense] - scores[defense]),
            }
            offense_spread = (
                matchup.home_spread if offense == matchup.home_team else -matchup.home_spread
            )
            pass_probability = _pass_probability(
                state,
                profiles[offense],
                play_call_model,
                offense_spread=offense_spread,
                game_total=matchup.game_total,
            )
            family = "DROPBACK" if rng_play_call.random() < pass_probability else "RUSH"
            plays[play_offense] += 1
            dropbacks[play_offense] += int(family == "DROPBACK")

            hazard_probability: float | None = None
            if termination_hazard_model is not None:
                hazard_probability = termination_hazard_model.probability(
                    team=play_offense,
                    state=state,
                    play_family=family,
                )

            outcome = outcome_model.sample(
                play_family=family,
                down=down,
                distance_bucket=_bucket_distance(distance),
                field_zone=_field_zone(yardline),
                rng=rng_outcome,
            )
            yards = float(np.clip(outcome.get("yards_gained", 0.0), -25.0, 99.0))
            red_zone = yardline <= 20
            passer = target = rusher = None

            if family == "DROPBACK":
                passer = _select_player(
                    game_usage,
                    play_offense,
                    "dropback_share",
                    rng_allocation,
                    position="QB",
                )
                if opportunity_model is not None:
                    state_allocation_attempts += 1
                    target = _select_state_conditioned_player(
                        opportunity_model,
                        game_usage,
                        play_offense,
                        "target",
                        state,
                        rng_allocation,
                    )
                    if target is None:
                        state_allocation_fallbacks += 1
                if target is None:
                    target = _select_player(
                        game_usage,
                        play_offense,
                        "target_share",
                        rng_allocation,
                        red_zone_column="red_zone_target_share",
                        red_zone=red_zone,
                    )
                _record(player_stats, simulation, target, "targets", 1.0)
                if outcome.get("interception", 0.0) >= 0.5:
                    _record(player_stats, simulation, passer, "interceptions", 1.0)
                if outcome.get("complete_pass", 0.0) >= 0.5 and target is not None:
                    receiving_yards = max(0.0, yards)
                    _record(player_stats, simulation, target, "receptions", 1.0)
                    _record(player_stats, simulation, target, "receiving_yards", receiving_yards)
                    _record(player_stats, simulation, passer, "passing_yards", receiving_yards)
            else:
                if opportunity_model is not None:
                    state_allocation_attempts += 1
                    rusher = _select_state_conditioned_player(
                        opportunity_model,
                        game_usage,
                        play_offense,
                        "carry",
                        state,
                        rng_allocation,
                    )
                    if rusher is None:
                        state_allocation_fallbacks += 1
                if rusher is None:
                    rusher = _select_player(
                        game_usage,
                        play_offense,
                        "carry_share",
                        rng_allocation,
                        red_zone_column="red_zone_carry_share",
                        red_zone=red_zone,
                    )
                _record(player_stats, simulation, rusher, "carries", 1.0)
                _record(player_stats, simulation, rusher, "rushing_yards", yards)

            touchdown = bool(outcome.get("touchdown", 0.0) >= 0.5 or yards >= yardline)
            turnover = bool(outcome.get("turnover", 0.0) >= 0.5)
            drive_continues = True
            terminal_type: str | None = None

            if touchdown:
                drive_continues = False
                terminal_type = "TOUCHDOWN"
                scores[play_offense] += 7.0
                if family == "DROPBACK":
                    _record(player_stats, simulation, passer, "passing_tds", 1.0)
                    _record(player_stats, simulation, target, "receiving_tds", 1.0)
                else:
                    _record(player_stats, simulation, rusher, "rushing_tds", 1.0)
            elif turnover:
                drive_continues = False
                terminal_type = "TURNOVER"
                turnovers[play_offense] += 1.0
                if outcome.get("fumble_lost", 0.0) >= 0.5:
                    _record(
                        player_stats,
                        simulation,
                        rusher if family == "RUSH" else target,
                        "fumbles_lost",
                        1.0,
                    )
            else:
                yardline = float(np.clip(yardline - yards, 0.5, 99.5))
                first_down = bool(outcome.get("first_down", 0.0) >= 0.5 or yards >= distance)
                if first_down:
                    down, distance = 1, min(10.0, yardline)
                else:
                    down += 1
                    distance = float(np.clip(distance - yards, 0.5, 30.0))
                    if down > 4:
                        drive_continues = False
                        terminal_type = "DOWNS"
                        turnovers_on_downs[play_offense] += 1.0

            if hazard_probability is not None:
                termination_probabilities.append(float(hazard_probability))
                termination_actuals.append(float(not drive_continues))

            legacy_runoff = outcome.get("seconds_between_plays", np.nan)
            if not np.isfinite(legacy_runoff) or legacy_runoff <= 0:
                legacy_runoff = 30.0 if family == "RUSH" else 24.0

            if drive_continues:
                runoff = float(legacy_runoff)
                if drive_volume_model is not None:
                    modeled_pace_plays += 1
                    runoff = drive_volume_model.sample_seconds(
                        team=play_offense,
                        state=state,
                        play_family=family,
                        rng=rng_tempo,
                        use_context=True,
                        fallback_seconds=float(legacy_runoff),
                    )
                runoff = float(
                    np.clip(
                        runoff,
                        config.minimum_seconds_per_play,
                        config.maximum_seconds_per_play,
                    )
                )
                continuing_runoff_sum[play_offense] += runoff
                continuing_runoff_count[play_offense] += 1
                clock = max(0.0, clock - runoff)
            elif transition_model is None:
                clock = max(
                    0.0,
                    clock
                    - float(
                        np.clip(
                            legacy_runoff,
                            config.minimum_seconds_per_play,
                            config.maximum_seconds_per_play,
                        )
                    ),
                )
                offense, defense, yardline, down, distance = start_possession(
                    _other_team(play_offense, matchup),
                    75.0,
                )
            else:
                (
                    offense,
                    defense,
                    yardline,
                    down,
                    distance,
                    clock,
                ) = terminal_transition(
                    previous_offense=play_offense,
                    transition_type=str(terminal_type or "OTHER"),
                    source_yardline_100=float(state["yardline_100"]),
                    fallback_yardline_100=75.0,
                    fallback_seconds=float(legacy_runoff),
                    clock_value=clock,
                )

            if before_clock > 1800 >= clock:
                halftime_offense = (
                    matchup.away_team if rng_special.random() < 0.5 else matchup.home_team
                )
                offense, defense, yardline, down, distance = start_possession(
                    halftime_offense,
                    75.0,
                    transition_type="HALFTIME" if transition_model is not None else None,
                )

        for team in (matchup.home_team, matchup.away_team):
            seconds_per_play = (
                continuing_runoff_sum[team] / continuing_runoff_count[team]
                if continuing_runoff_count[team] > 0
                else float("nan")
            )
            team_rows.append(
                {
                    "game_id": game_id,
                    "simulation": simulation,
                    "team": team,
                    "opponent": _other_team(team, matchup),
                    "points": scores[team],
                    "plays": plays[team],
                    "dropbacks": dropbacks[team],
                    "pass_rate": dropbacks[team] / max(plays[team], 1),
                    "drives": float(drives[team]),
                    "plays_per_drive": plays[team] / max(drives[team], 1),
                    "seconds_per_play": seconds_per_play,
                    "mean_start_yardline_100": start_yardline_sum[team] / max(drives[team], 1),
                    "punts": punts[team],
                    "field_goal_attempts": field_goal_attempts[team],
                    "field_goals_made": field_goals_made[team],
                    "turnovers": turnovers[team],
                    "turnovers_on_downs": turnovers_on_downs[team],
                    "fourth_down_decisions": fourth_down_decisions[team],
                    "fourth_down_go_attempts": fourth_down_go_attempts[team],
                }
            )
        game_rows.append(
            {
                "game_id": game_id,
                "simulation": simulation,
                "home_team": matchup.home_team,
                "away_team": matchup.away_team,
                "home_points": scores[matchup.home_team],
                "away_points": scores[matchup.away_team],
                "total_points": scores[matchup.home_team] + scores[matchup.away_team],
                "home_margin": scores[matchup.home_team] - scores[matchup.away_team],
            }
        )

    player_draws = _complete_player_draw_matrix(
        player_stats,
        game_usage,
        simulations=config.simulations,
        game_id=game_id,
    )
    scoring_config = league_config or LeagueConfig(scoring="ppr")
    player_value = "league_fantasy_points"
    if not player_draws.empty:
        player_draws = score_simulation_draws(player_draws, scoring_config)
        if league_config is None:
            player_draws = player_draws.rename(
                columns={"league_fantasy_points": "fantasy_points_ppr_proxy"}
            )
            player_value = "fantasy_points_ppr_proxy"

    team_draws = pd.DataFrame(team_rows)
    game_draws = pd.DataFrame(game_rows)
    team_summary = _summarize(team_draws, ["game_id", "team", "opponent"], "points")
    game_summary = pd.DataFrame(
        {
            "game_id": [game_id],
            "home_team": [matchup.home_team],
            "away_team": [matchup.away_team],
            "home_points_mean": [float(game_draws["home_points"].mean())],
            "away_points_mean": [float(game_draws["away_points"].mean())],
            "total_q10": [float(game_draws["total_points"].quantile(0.10))],
            "total_q50": [float(game_draws["total_points"].quantile(0.50))],
            "total_q90": [float(game_draws["total_points"].quantile(0.90))],
            "home_win_probability": [float((game_draws["home_margin"] > 0).mean())],
        }
    )
    player_summary = _summarize(
        player_draws,
        [
            column
            for column in ("game_id", "player_id", "team", "position")
            if column in player_draws
        ],
        player_value,
    )
    termination_log_loss = _binary_log_loss(
        termination_actuals, termination_probabilities
    )
    termination_brier = _binary_brier(termination_actuals, termination_probabilities)
    diagnostics = {
        "game_id": game_id,
        "model_source": "fourth_down_decision_probe_v015",
        "promoted": False,
        "simulations": config.simulations,
        "home_profile": profiles[matchup.home_team],
        "away_profile": profiles[matchup.away_team],
        "play_call_model": (
            play_call_model.model_source if play_call_model is not None else "profile_baseline"
        ),
        "outcome_model": outcome_model.model_source,
        "opportunity_allocation_model": (
            opportunity_model.model_source if opportunity_model is not None else "static_usage_share"
        ),
        "drive_volume_model": (
            drive_volume_model.model_source if drive_volume_model is not None else "legacy_drive_mechanics"
        ),
        "transition_model": (
            transition_model.model_source if transition_model is not None else "v013_transition_heuristics"
        ),
        "fourth_down_decision_model": (
            decision_model.model_source if decision_model is not None else "v014_fourth_down_heuristic"
        ),
        "termination_hazard_model": (
            termination_hazard_model.model_source
            if termination_hazard_model is not None
            else "not_evaluated_in_simulation"
        ),
        "termination_hazard_authority": False,
        "termination_probe_log_loss": termination_log_loss,
        "termination_probe_brier": termination_brier,
        "component_rng_streams": True,
        "component_rng_base_version": 13,
        "transition_rng_stream_added": True,
        "decision_rng_stream_added": True,
        "aligned_discarded_drive_start_draws": int(
            diagnostic_counts["aligned_discarded_drive_start_draws"]
        ),
        "modeled_transition_events": int(diagnostic_counts["modeled_transition_events"]),
        "modeled_fourth_down_decisions": int(
            diagnostic_counts["modeled_fourth_down_decisions"]
        ),
        "aligned_legacy_fourth_down_decisions": int(
            diagnostic_counts["aligned_legacy_fourth_down_decisions"]
        ),
        "aligned_discarded_legacy_fg_draws": int(
            diagnostic_counts["aligned_discarded_legacy_fg_draws"]
        ),
        "modeled_pace_plays": int(modeled_pace_plays),
        "state_allocation_attempts": int(state_allocation_attempts),
        "state_allocation_fallbacks": int(state_allocation_fallbacks),
        "research_only": True,
        "automatic_promotion": False,
        "production_projection_changed": False,
        "limitations": [
            "v0.15 is a parallel research probe; the v0.14 transition simulator remains frozen",
            "drive-termination hazard is diagnostic-only until terminal-family generation is separately identified",
            "fourth-down decisions use team/context empirical shrinkage without timeout or explicit coach identity state",
            "field-goal outcome calibration remains the v0.14 distance/team model",
            "no player-level return model, overtime state machine, PAT model, or two-point strategy model",
        ],
    }
    return PlayByPlaySimulationResult(
        game_summary=game_summary,
        team_summary=team_summary,
        player_summary=player_summary,
        game_draws=game_draws,
        team_draws=team_draws,
        player_draws=player_draws,
        diagnostics=diagnostics,
    )
