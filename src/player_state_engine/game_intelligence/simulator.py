from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.scoring import score_simulation_draws
from player_state_engine.game_intelligence.models import EmpiricalPlayOutcomeModel, PlayCallModel
from player_state_engine.game_intelligence.schema import MatchupSpec, SimulationConfig
from player_state_engine.game_intelligence.tendencies import build_matchup_profile


_RAW_STATS = (
    "passing_yards",
    "passing_tds",
    "interceptions",
    "rushing_yards",
    "rushing_tds",
    "receptions",
    "receiving_yards",
    "receiving_tds",
    "fumbles_lost",
)


@dataclass(slots=True)
class PlayByPlaySimulationResult:
    game_summary: pd.DataFrame
    team_summary: pd.DataFrame
    player_summary: pd.DataFrame
    player_draws: pd.DataFrame
    diagnostics: dict[str, object]


def _bucket_distance(ydstogo: float) -> int:
    if ydstogo <= 2:
        return 0
    if ydstogo <= 6:
        return 1
    if ydstogo <= 10:
        return 2
    return 3


def _field_zone(yardline_100: float) -> int:
    if yardline_100 <= 20:
        return 0
    if yardline_100 <= 40:
        return 1
    if yardline_100 <= 60:
        return 2
    if yardline_100 <= 80:
        return 3
    return 4


def _quarter(clock: float) -> int:
    if clock > 2700:
        return 1
    if clock > 1800:
        return 2
    if clock > 900:
        return 3
    return 4


def _select_player(
    usage: pd.DataFrame,
    team: str,
    column: str,
    rng: np.random.Generator,
    *,
    red_zone_column: str | None = None,
    red_zone: bool = False,
    position: str | None = None,
) -> str | None:
    pool = usage.loc[usage["team"].astype(str).eq(str(team))].copy()
    if position is not None and "position" in pool:
        positioned = pool.loc[pool["position"].astype(str).str.upper().eq(position.upper())]
        if not positioned.empty:
            pool = positioned
    if pool.empty:
        return None
    weight_column = red_zone_column if red_zone and red_zone_column in pool else column
    weights = pd.to_numeric(pool.get(weight_column), errors="coerce").fillna(0.0).clip(lower=0.0)
    if float(weights.sum()) <= 0:
        weights = pd.to_numeric(pool.get("usage_evidence_weight"), errors="coerce").fillna(0.0)
    if float(weights.sum()) <= 0:
        weights = pd.Series(1.0, index=pool.index)
    probabilities = (weights / weights.sum()).to_numpy(dtype=float)
    index = int(rng.choice(np.arange(len(pool)), p=probabilities))
    return str(pool.iloc[index]["player_id"])


def _player_position(usage: pd.DataFrame, player_id: str | None) -> str:
    if player_id is None:
        return "UNK"
    rows = usage.loc[usage["player_id"].astype(str).eq(str(player_id))]
    if rows.empty or "position" not in rows:
        return "UNK"
    return str(rows.iloc[0]["position"]).upper()


def _pass_probability(
    state: dict[str, float],
    profile: dict[str, float | str],
    model: PlayCallModel | None,
    *,
    home_spread: float,
    game_total: float,
) -> float:
    base = float(profile.get("pregame_pass_rate", 0.58))
    row = {
        **profile,
        **state,
        "qtr": _quarter(state["game_seconds_remaining"]),
        "neutral_score_state": float(abs(state["score_differential"]) <= 7),
        "late_game": float(state["game_seconds_remaining"] <= 900),
        "red_zone": float(state["yardline_100"] <= 20),
        "goal_to_go_state": float(state["yardline_100"] <= state["ydstogo"]),
        "distance_bucket": _bucket_distance(state["ydstogo"]),
        "field_zone": _field_zone(state["yardline_100"]),
        "home_spread": home_spread,
        "game_total": game_total,
    }
    if model is not None and model.fitted:
        base = float(model.predict_pass_probability(pd.DataFrame([row]))[0])
    score = state["score_differential"]
    clock = state["game_seconds_remaining"]
    if clock <= 900 and score <= -7:
        base += 0.15
    elif clock <= 900 and score >= 7:
        base -= 0.12
    if state["down"] == 3 and state["ydstogo"] >= 7:
        base += 0.18
    if state["down"] == 1 and state["ydstogo"] <= 2:
        base -= 0.07
    return float(np.clip(base, 0.20, 0.90))


def _fourth_down_action(
    yardline_100: float,
    ydstogo: float,
    rng: np.random.Generator,
    aggression_scale: float,
) -> str:
    if ydstogo <= 1:
        go_probability = 0.62
    elif ydstogo <= 3:
        go_probability = 0.34
    else:
        go_probability = 0.08
    if yardline_100 <= 10:
        go_probability += 0.12
    elif yardline_100 >= 60:
        go_probability *= 0.45
    go_probability = float(np.clip(go_probability * aggression_scale, 0.01, 0.90))
    if rng.random() < go_probability:
        return "GO"
    if yardline_100 <= 35:
        return "FIELD_GOAL"
    return "PUNT"


def _field_goal_success(yardline_100: float) -> float:
    distance = float(yardline_100) + 17.0
    if distance <= 35:
        return 0.96
    if distance <= 45:
        return 0.88
    if distance <= 52:
        return 0.76
    return float(np.clip(0.72 - 0.035 * (distance - 52), 0.25, 0.72))


def _reset_possession(
    offense: str,
    home_team: str,
    away_team: str,
) -> tuple[str, str, float, int, float]:
    new_offense = away_team if offense == home_team else home_team
    new_defense = home_team if new_offense == away_team else away_team
    return new_offense, new_defense, 75.0, 1, 10.0


def _record_stat(
    stats: defaultdict[tuple[int, str], dict[str, float]],
    simulation: int,
    player_id: str | None,
    column: str,
    value: float,
) -> None:
    if player_id is None:
        return
    stats[(simulation, player_id)][column] += float(value)


def simulate_matchup(
    matchup: MatchupSpec,
    *,
    tendencies: pd.DataFrame,
    usage: pd.DataFrame,
    outcome_model: EmpiricalPlayOutcomeModel,
    play_call_model: PlayCallModel | None = None,
    league_config: LeagueConfig | None = None,
    config: SimulationConfig = SimulationConfig(),
) -> PlayByPlaySimulationResult:
    """Simulate a matchup play-by-play and preserve correlated raw football outcomes."""
    home_profile = build_matchup_profile(
        tendencies,
        season=matchup.season,
        week=matchup.week,
        offense_team=matchup.home_team,
        defense_team=matchup.away_team,
    )
    away_profile = build_matchup_profile(
        tendencies,
        season=matchup.season,
        week=matchup.week,
        offense_team=matchup.away_team,
        defense_team=matchup.home_team,
    )
    profiles = {matchup.home_team: home_profile, matchup.away_team: away_profile}
    rng = np.random.default_rng(config.seed)
    player_stats: defaultdict[tuple[int, str], dict[str, float]] = defaultdict(
        lambda: defaultdict(float)
    )
    team_rows: list[dict[str, object]] = []
    game_rows: list[dict[str, object]] = []

    for simulation in range(config.simulations):
        scores = {matchup.home_team: 0.0, matchup.away_team: 0.0}
        team_plays = {matchup.home_team: 0, matchup.away_team: 0}
        team_passes = {matchup.home_team: 0, matchup.away_team: 0}
        offense = matchup.home_team if rng.random() < 0.5 else matchup.away_team
        defense = matchup.away_team if offense == matchup.home_team else matchup.home_team
        yardline_100 = 75.0
        down = 1
        ydstogo = 10.0
        clock = 3600.0
        play_index = 0

        while clock > 0 and play_index < config.max_plays:
            play_index += 1
            before_clock = clock
            score_diff = scores[offense] - scores[defense]
            if down == 4:
                action = _fourth_down_action(
                    yardline_100,
                    ydstogo,
                    rng,
                    config.fourth_down_aggression_scale,
                )
                if action == "FIELD_GOAL":
                    if rng.random() < _field_goal_success(yardline_100):
                        scores[offense] += 3.0
                    clock -= min(6.0, clock)
                    offense, defense, yardline_100, down, ydstogo = _reset_possession(
                        offense, matchup.home_team, matchup.away_team
                    )
                    continue
                if action == "PUNT":
                    clock -= min(8.0, clock)
                    offense, defense, yardline_100, down, ydstogo = _reset_possession(
                        offense, matchup.home_team, matchup.away_team
                    )
                    yardline_100 = 80.0
                    continue

            state = {
                "down": float(down),
                "ydstogo": float(ydstogo),
                "yardline_100": float(yardline_100),
                "game_seconds_remaining": float(clock),
                "score_differential": float(score_diff),
            }
            home_spread = matchup.home_spread if offense == matchup.home_team else -matchup.home_spread
            p_pass = _pass_probability(
                state,
                profiles[offense],
                play_call_model,
                home_spread=home_spread,
                game_total=matchup.game_total,
            )
            play_family = "DROPBACK" if rng.random() < p_pass else "RUSH"
            team_plays[offense] += 1
            team_passes[offense] += int(play_family == "DROPBACK")
            outcome = outcome_model.sample(
                play_family=play_family,
                down=down,
                distance_bucket=_bucket_distance(ydstogo),
                field_zone=_field_zone(yardline_100),
                rng=rng,
            )
            yards = float(np.clip(outcome.get("yards_gained", 0.0), -25.0, 99.0))
            red_zone = yardline_100 <= 20
            passer: str | None = None
            target: str | None = None
            rusher: str | None = None

            if play_family == "DROPBACK":
                passer = _select_player(
                    usage, offense, "dropback_share", rng, position="QB"
                )
                target = _select_player(
                    usage,
                    offense,
                    "target_share",
                    rng,
                    red_zone_column="red_zone_target_share",
                    red_zone=red_zone,
                )
                if outcome.get("interception", 0.0) >= 0.5:
                    _record_stat(player_stats, simulation, passer, "interceptions", 1.0)
                if outcome.get("complete_pass", 0.0) >= 0.5 and target is not None:
                    receiving_yards = max(0.0, yards)
                    _record_stat(player_stats, simulation, target, "receptions", 1.0)
                    _record_stat(
                        player_stats, simulation, target, "receiving_yards", receiving_yards
                    )
                    _record_stat(
                        player_stats, simulation, passer, "passing_yards", receiving_yards
                    )
            else:
                rusher = _select_player(
                    usage,
                    offense,
                    "carry_share",
                    rng,
                    red_zone_column="red_zone_carry_share",
                    red_zone=red_zone,
                )
                _record_stat(player_stats, simulation, rusher, "rushing_yards", yards)

            touchdown = bool(outcome.get("touchdown", 0.0) >= 0.5 or yards >= yardline_100)
            turnover = bool(outcome.get("turnover", 0.0) >= 0.5)
            if touchdown:
                scores[offense] += 7.0
                if play_family == "DROPBACK":
                    _record_stat(player_stats, simulation, passer, "passing_tds", 1.0)
                    _record_stat(player_stats, simulation, target, "receiving_tds", 1.0)
                else:
                    _record_stat(player_stats, simulation, rusher, "rushing_tds", 1.0)
                offense, defense, yardline_100, down, ydstogo = _reset_possession(
                    offense, matchup.home_team, matchup.away_team
                )
            elif turnover:
                if outcome.get("fumble_lost", 0.0) >= 0.5:
                    turnover_player = rusher if play_family == "RUSH" else target
                    _record_stat(player_stats, simulation, turnover_player, "fumbles_lost", 1.0)
                offense, defense, yardline_100, down, ydstogo = _reset_possession(
                    offense, matchup.home_team, matchup.away_team
                )
            else:
                yardline_100 = float(np.clip(yardline_100 - yards, 0.5, 99.5))
                gained_first = bool(outcome.get("first_down", 0.0) >= 0.5 or yards >= ydstogo)
                if gained_first:
                    down = 1
                    ydstogo = min(10.0, yardline_100)
                else:
                    down += 1
                    ydstogo = float(np.clip(ydstogo - yards, 0.5, 30.0))
                    if down > 4:
                        offense, defense, yardline_100, down, ydstogo = _reset_possession(
                            offense, matchup.home_team, matchup.away_team
                        )

            runoff = outcome.get("seconds_between_plays", np.nan)
            if not np.isfinite(runoff) or runoff <= 0:
                runoff = 30.0 if play_family == "RUSH" else 24.0
            runoff = float(
                np.clip(runoff, config.minimum_seconds_per_play, config.maximum_seconds_per_play)
            )
            clock = max(0.0, clock - runoff)
            if before_clock > 1800 >= clock:
                offense = matchup.away_team if rng.random() < 0.5 else matchup.home_team
                defense = matchup.home_team if offense == matchup.away_team else matchup.away_team
                yardline_100, down, ydstogo = 75.0, 1, 10.0

        for team in (matchup.home_team, matchup.away_team):
            team_rows.append(
                {
                    "simulation": simulation,
                    "team": team,
                    "opponent": matchup.away_team if team == matchup.home_team else matchup.home_team,
                    "points": scores[team],
                    "plays": team_plays[team],
                    "dropbacks": team_passes[team],
                    "pass_rate": team_passes[team] / max(team_plays[team], 1),
                }
            )
        game_rows.append(
            {
                "simulation": simulation,
                "home_team": matchup.home_team,
                "away_team": matchup.away_team,
                "home_points": scores[matchup.home_team],
                "away_points": scores[matchup.away_team],
                "total_points": scores[matchup.home_team] + scores[matchup.away_team],
                "home_margin": scores[matchup.home_team] - scores[matchup.away_team],
            }
        )

    usage_lookup = usage.drop_duplicates("player_id").set_index("player_id") if not usage.empty else None
    draw_rows: list[dict[str, object]] = []
    for (simulation, player_id), values in player_stats.items():
        row: dict[str, object] = {"simulation": simulation, "player_id": player_id}
        row.update({stat: float(values.get(stat, 0.0)) for stat in _RAW_STATS})
        row["position"] = _player_position(usage, player_id)
        if usage_lookup is not None and player_id in usage_lookup.index:
            row["team"] = str(usage_lookup.loc[player_id, "team"])
        draw_rows.append(row)
    player_draws = pd.DataFrame(draw_rows)
    if not player_draws.empty and league_config is not None:
        player_draws = score_simulation_draws(player_draws, league_config)

    def summary(frame: pd.DataFrame, group: list[str], value: str) -> pd.DataFrame:
        if frame.empty:
            return pd.DataFrame(columns=[*group, "mean", "q10", "q50", "q90"])
        grouped = frame.groupby(group, dropna=False)[value]
        return pd.concat(
            [
                grouped.mean().rename("mean"),
                grouped.quantile(0.10).rename("q10"),
                grouped.quantile(0.50).rename("q50"),
                grouped.quantile(0.90).rename("q90"),
            ],
            axis=1,
        ).reset_index()

    team_draws = pd.DataFrame(team_rows)
    game_draws = pd.DataFrame(game_rows)
    team_summary = summary(team_draws, ["team", "opponent"], "points")
    game_summary = pd.DataFrame(
        {
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
    player_value = "league_fantasy_points" if "league_fantasy_points" in player_draws else "rushing_yards"
    player_summary = summary(
        player_draws,
        [column for column in ("player_id", "team", "position") if column in player_draws],
        player_value,
    )
    diagnostics = {
        "model_source": config.model_source,
        "promoted": config.promoted,
        "simulations": config.simulations,
        "home_profile": home_profile,
        "away_profile": away_profile,
        "play_call_model": play_call_model.model_source if play_call_model is not None else "profile_baseline",
        "outcome_model": outcome_model.model_source,
        "player_value_column": player_value,
    }
    return PlayByPlaySimulationResult(
        game_summary=game_summary,
        team_summary=team_summary,
        player_summary=player_summary,
        player_draws=player_draws,
        diagnostics=diagnostics,
    )
