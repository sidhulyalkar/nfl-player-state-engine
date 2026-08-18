from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.scoring import score_simulation_draws
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


def _component_rngs(
    seed: int,
    simulation: int,
) -> tuple[
    np.random.Generator,
    np.random.Generator,
    np.random.Generator,
    np.random.Generator,
    np.random.Generator,
]:
    """Independent streams keep A/B components from perturbing unrelated random draws."""
    sequence = np.random.SeedSequence([int(seed), int(simulation), 13])
    special, play_call, outcome, allocation, tempo = sequence.spawn(5)
    return tuple(
        np.random.default_rng(child)
        for child in (special, play_call, outcome, allocation, tempo)
    )


def simulate_matchup_volume_probe(
    matchup: MatchupSpec,
    *,
    tendencies: pd.DataFrame,
    usage: pd.DataFrame,
    outcome_model: EmpiricalPlayOutcomeModel,
    play_call_model: PlayCallModel | None = None,
    opportunity_model: StateConditionedOpportunityModel | None = None,
    drive_volume_model: DriveVolumeModel | None = None,
    league_config: LeagueConfig | None = None,
    config: SimulationConfig | None = None,
) -> PlayByPlaySimulationResult:
    """Research simulator that isolates drive/pace mechanics from play outcomes.

    With ``drive_volume_model=None`` this mirrors the v0.12 clock/start-field heuristics while
    tracking drive diagnostics. Supplying a fitted model changes only drive starts and clock
    runoff, leaving play calling, outcomes, and player allocation on independent RNG streams.
    """
    config = config or SimulationConfig()
    game_id = matchup.resolved_game_id
    game_usage = usage.loc[
        usage["team"].astype(str).isin([str(matchup.home_team), str(matchup.away_team)])
    ].copy()
    if game_usage.empty:
        raise ValueError("Volume probe requires point-in-time usage for at least one matchup team")

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
    state_allocation_attempts = 0
    state_allocation_fallbacks = 0

    for simulation in range(config.simulations):
        rng_special, rng_play_call, rng_outcome, rng_allocation, rng_tempo = _component_rngs(
            config.seed, simulation
        )
        scores = {matchup.home_team: 0.0, matchup.away_team: 0.0}
        plays = {matchup.home_team: 0, matchup.away_team: 0}
        dropbacks = {matchup.home_team: 0, matchup.away_team: 0}
        drives = {matchup.home_team: 0, matchup.away_team: 0}
        start_yardline_sum = {matchup.home_team: 0.0, matchup.away_team: 0.0}
        runoff_sum = {matchup.home_team: 0.0, matchup.away_team: 0.0}
        runoff_count = {matchup.home_team: 0, matchup.away_team: 0}

        def start_possession(
            new_offense: str,
            *,
            fallback_yardline: float,
        ) -> tuple[str, str, float, int, float]:
            new_defense = (
                matchup.away_team if new_offense == matchup.home_team else matchup.home_team
            )
            start_yardline = float(fallback_yardline)
            if drive_volume_model is not None:
                start_yardline = drive_volume_model.sample_start_yardline(
                    team=new_offense,
                    opponent=new_defense,
                    rng=rng_tempo,
                    fallback_yardline_100=float(fallback_yardline),
                )
            drives[new_offense] += 1
            start_yardline_sum[new_offense] += start_yardline
            return new_offense, new_defense, start_yardline, 1, min(10.0, start_yardline)

        def flip_possession(
            current_offense: str,
            *,
            fallback_yardline: float = 75.0,
        ) -> tuple[str, str, float, int, float]:
            new_offense = (
                matchup.away_team
                if current_offense == matchup.home_team
                else matchup.home_team
            )
            return start_possession(new_offense, fallback_yardline=fallback_yardline)

        initial_offense = (
            matchup.home_team if rng_special.random() < 0.5 else matchup.away_team
        )
        offense, defense, yardline, down, distance = start_possession(
            initial_offense, fallback_yardline=75.0
        )
        clock = 3600.0
        play_index = 0

        while clock > 0 and play_index < config.max_plays:
            play_index += 1
            before_clock = clock

            if down == 4:
                action = _fourth_down_action(
                    yardline,
                    distance,
                    rng_special,
                    config.fourth_down_aggression_scale,
                )
                if action == "FIELD_GOAL":
                    scores[offense] += (
                        3.0 if rng_special.random() < _field_goal_success(yardline) else 0.0
                    )
                    clock -= min(6.0, clock)
                    offense, defense, yardline, down, distance = flip_possession(
                        offense, fallback_yardline=75.0
                    )
                    continue
                if action == "PUNT":
                    clock -= min(8.0, clock)
                    offense, defense, yardline, down, distance = flip_possession(
                        offense, fallback_yardline=80.0
                    )
                    continue

            play_offense = offense
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
            if touchdown:
                scores[play_offense] += 7.0
                if family == "DROPBACK":
                    _record(player_stats, simulation, passer, "passing_tds", 1.0)
                    _record(player_stats, simulation, target, "receiving_tds", 1.0)
                else:
                    _record(player_stats, simulation, rusher, "rushing_tds", 1.0)
                offense, defense, yardline, down, distance = flip_possession(
                    play_offense, fallback_yardline=75.0
                )
            elif turnover:
                if outcome.get("fumble_lost", 0.0) >= 0.5:
                    _record(
                        player_stats,
                        simulation,
                        rusher if family == "RUSH" else target,
                        "fumbles_lost",
                        1.0,
                    )
                offense, defense, yardline, down, distance = flip_possession(
                    play_offense, fallback_yardline=75.0
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
                        offense, defense, yardline, down, distance = flip_possession(
                            play_offense, fallback_yardline=75.0
                        )

            legacy_runoff = outcome.get("seconds_between_plays", np.nan)
            if not np.isfinite(legacy_runoff) or legacy_runoff <= 0:
                legacy_runoff = 30.0 if family == "RUSH" else 24.0
            runoff = float(legacy_runoff)
            if drive_volume_model is not None:
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
            runoff_sum[play_offense] += runoff
            runoff_count[play_offense] += 1
            clock = max(0.0, clock - runoff)

            if before_clock > 1800 >= clock:
                halftime_offense = (
                    matchup.away_team if rng_special.random() < 0.5 else matchup.home_team
                )
                offense, defense, yardline, down, distance = start_possession(
                    halftime_offense, fallback_yardline=75.0
                )

        for team in (matchup.home_team, matchup.away_team):
            team_rows.append(
                {
                    "game_id": game_id,
                    "simulation": simulation,
                    "team": team,
                    "opponent": (
                        matchup.away_team if team == matchup.home_team else matchup.home_team
                    ),
                    "points": scores[team],
                    "plays": plays[team],
                    "dropbacks": dropbacks[team],
                    "pass_rate": dropbacks[team] / max(plays[team], 1),
                    "drives": float(drives[team]),
                    "plays_per_drive": plays[team] / max(drives[team], 1),
                    "seconds_per_play": runoff_sum[team] / max(runoff_count[team], 1),
                    "mean_start_yardline_100": (
                        start_yardline_sum[team] / max(drives[team], 1)
                    ),
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
    diagnostics = {
        "game_id": game_id,
        "model_source": "drive_volume_probe_v013",
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
            drive_volume_model.model_source
            if drive_volume_model is not None
            else "v012_legacy_clock_and_fixed_drive_start"
        ),
        "component_rng_streams": True,
        "state_allocation_attempts": int(state_allocation_attempts),
        "state_allocation_fallbacks": int(state_allocation_fallbacks),
        "complete_player_draw_matrix": True,
        "matchup_player_rows": int(game_usage["player_id"].astype(str).nunique()),
        "player_value_column": player_value,
        "simulation_scoring_source": (
            "exact_league" if league_config is not None else "ppr_proxy"
        ),
        "research_only": True,
        "production_projection_changed": False,
        "limitations": [
            "no overtime state machine",
            "touchdowns use seven points instead of a separate PAT/two-point model",
            "fourth-down decisions remain transparent heuristics pending calibration",
            "drive starts are learned from scrimmage-play drive starts, not special-teams tracking",
            "drive-volume challenger changes pace and field-position starts only",
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
