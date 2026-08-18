from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.evaluation import (
    evaluate_play_call_probabilities,
    evaluate_player_opportunity,
    evaluate_team_simulation_draws,
    interval_coverage,
)
from player_state_engine.game_intelligence.models import EmpiricalPlayOutcomeModel, PlayCallModel
from player_state_engine.game_intelligence.play_features import build_play_intelligence_frame
from player_state_engine.game_intelligence.schema import MatchupSpec, SimulationConfig
from player_state_engine.game_intelligence.simulator import (
    PlayByPlaySimulationResult,
    simulate_matchup,
)
from player_state_engine.game_intelligence.tendencies import (
    attach_point_in_time_matchup_features,
    build_team_tendency_snapshots,
)
from player_state_engine.game_intelligence.usage import build_player_usage_profiles


@dataclass(slots=True)
class GameReplayResult:
    candidate_metrics: dict[str, float]
    baseline_metrics: dict[str, float]
    candidate_team_draws: pd.DataFrame
    baseline_team_draws: pd.DataFrame
    candidate_player_predictions: pd.DataFrame
    baseline_player_predictions: pd.DataFrame
    observed_teams: pd.DataFrame
    observed_opportunity: pd.DataFrame
    diagnostics: dict[str, object]


def _chronology(frame: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(frame["season"], errors="coerce") * 25 + pd.to_numeric(
        frame["week"], errors="coerce"
    )


def _schedule_number(row: pd.Series, columns: tuple[str, ...], default: float) -> float:
    for column in columns:
        if column in row and pd.notna(row[column]):
            value = pd.to_numeric(row[column], errors="coerce")
            if pd.notna(value):
                return float(value)
    return float(default)


def _schedule_game_id(row: pd.Series) -> str:
    for column in ("game_id", "nflverse_game_id"):
        if column in row and pd.notna(row[column]):
            return str(row[column])
    return (
        f"{int(row['season'])}_{int(row['week']):02d}_"
        f"{str(row['away_team'])}_{str(row['home_team'])}"
    )


def matchup_from_schedule(row: pd.Series) -> MatchupSpec:
    return MatchupSpec(
        season=int(row["season"]),
        week=int(row["week"]),
        home_team=str(row["home_team"]),
        away_team=str(row["away_team"]),
        game_id=_schedule_game_id(row),
        home_spread=_schedule_number(row, ("spread_line", "home_spread"), 0.0),
        game_total=_schedule_number(row, ("total_line", "game_total"), 44.0),
        roof=str(row["roof"]) if "roof" in row and pd.notna(row["roof"]) else None,
        surface=(
            str(row["surface"]) if "surface" in row and pd.notna(row["surface"]) else None
        ),
        temperature=_schedule_number(row, ("temp", "temperature"), np.nan),
        wind=_schedule_number(row, ("wind",), np.nan),
    )


def observed_team_games(play_frame: pd.DataFrame, schedules: pd.DataFrame) -> pd.DataFrame:
    play = (
        play_frame.groupby(["game_id", "posteam"], dropna=False)
        .agg(plays=("play_id", "size"), pass_rate=("is_dropback", "mean"))
        .reset_index()
        .rename(columns={"posteam": "team"})
    )
    score_rows: list[dict[str, object]] = []
    for _, row in schedules.iterrows():
        game_id = _schedule_game_id(row)
        home_score = _schedule_number(row, ("home_score", "total_home_score"), np.nan)
        away_score = _schedule_number(row, ("away_score", "total_away_score"), np.nan)
        if np.isfinite(home_score):
            score_rows.append(
                {"game_id": game_id, "team": str(row["home_team"]), "points": home_score}
            )
        if np.isfinite(away_score):
            score_rows.append(
                {"game_id": game_id, "team": str(row["away_team"]), "points": away_score}
            )
    scores = pd.DataFrame(score_rows)
    if scores.empty:
        scores = pd.DataFrame(columns=["game_id", "team", "points"])
    return play.merge(scores, on=["game_id", "team"], how="left")


def observed_player_opportunity(play_frame: pd.DataFrame) -> pd.DataFrame:
    carries = (
        play_frame.loc[
            play_frame["play_family"].eq("RUSH") & play_frame["rusher_player_id"].notna()
        ]
        .groupby(["game_id", "rusher_player_id"], dropna=False)
        .size()
        .rename("carries")
        .reset_index()
        .rename(columns={"rusher_player_id": "player_id"})
    )
    targets = (
        play_frame.loc[
            play_frame["play_family"].eq("DROPBACK") & play_frame["receiver_player_id"].notna()
        ]
        .groupby(["game_id", "receiver_player_id"], dropna=False)
        .size()
        .rename("targets")
        .reset_index()
        .rename(columns={"receiver_player_id": "player_id"})
    )
    merged = carries.merge(targets, on=["game_id", "player_id"], how="outer").fillna(0.0)
    if not merged.empty:
        merged["player_id"] = merged["player_id"].astype(str)
    return merged


def predicted_player_opportunity(
    team_draws: pd.DataFrame,
    usage_by_game: pd.DataFrame,
) -> pd.DataFrame:
    teams = (
        team_draws.groupby(["game_id", "team"], dropna=False)
        .agg(plays=("plays", "median"), pass_rate=("pass_rate", "median"))
        .reset_index()
    )
    joined = usage_by_game.merge(teams, on=["game_id", "team"], how="inner")
    if joined.empty:
        return pd.DataFrame(columns=["game_id", "player_id", "carries", "targets"])
    dropbacks = joined["plays"] * joined["pass_rate"]
    rushes = (joined["plays"] - dropbacks).clip(lower=0.0)
    joined["targets"] = dropbacks * pd.to_numeric(
        joined["target_share"], errors="coerce"
    ).fillna(0)
    joined["carries"] = rushes * pd.to_numeric(joined["carry_share"], errors="coerce").fillna(0)
    return joined[["game_id", "player_id", "carries", "targets"]].copy()


def _fantasy_metrics(
    predictions: pd.DataFrame,
    actual: pd.DataFrame | None,
) -> dict[str, float]:
    if actual is None or actual.empty or predictions.empty:
        return {}
    value_column = next(
        (
            column
            for column in ("fantasy_points_ppr", "fantasy_points", "points")
            if column in actual
        ),
        None,
    )
    if value_column is None or "player_id" not in actual:
        return {}
    keys = [
        column
        for column in ("season", "week", "player_id")
        if column in predictions and column in actual
    ]
    if "player_id" not in keys:
        return {}
    observed = actual[keys + [value_column]].copy()
    observed["player_id"] = observed["player_id"].astype(str)
    predicted = predictions.copy()
    predicted["player_id"] = predicted["player_id"].astype(str)
    joined = observed.merge(predicted, on=keys, how="inner")
    if joined.empty:
        return {}
    y = pd.to_numeric(joined[value_column], errors="coerce")
    q10 = pd.to_numeric(joined["q10"], errors="coerce")
    q50 = pd.to_numeric(joined["q50"], errors="coerce")
    q90 = pd.to_numeric(joined["q90"], errors="coerce")
    valid = y.notna() & q10.notna() & q50.notna() & q90.notna()
    if not valid.any():
        return {}
    y = y.loc[valid].to_numpy(dtype=float)
    q10 = q10.loc[valid].to_numpy(dtype=float)
    q50 = q50.loc[valid].to_numpy(dtype=float)
    q90 = q90.loc[valid].to_numpy(dtype=float)

    def pinball(target: np.ndarray, prediction: np.ndarray, quantile: float) -> float:
        error = target - prediction
        return float(np.mean(np.maximum(quantile * error, (quantile - 1.0) * error)))

    return {
        "fantasy_rows": float(len(y)),
        "fantasy_median_mae": float(np.mean(np.abs(y - q50))),
        "fantasy_pinball_loss": float(
            np.mean(
                [
                    pinball(y, q10, 0.10),
                    pinball(y, q50, 0.50),
                    pinball(y, q90, 0.90),
                ]
            )
        ),
        "fantasy_q10_q90_coverage": interval_coverage(y, q10, q90),
    }


def _combine_metrics(
    play_call: dict[str, float],
    team: dict[str, float],
    opportunity: dict[str, float],
    fantasy: dict[str, float],
) -> dict[str, float]:
    metrics = {
        "play_call_log_loss": play_call["log_loss"],
        "play_call_brier": play_call["brier"],
        **team,
        **opportunity,
        **fantasy,
    }
    return {key: float(value) for key, value in metrics.items()}


def frozen_game_replay(
    pbp: pd.DataFrame,
    schedules: pd.DataFrame,
    *,
    test_season: int,
    test_week_start: int = 1,
    test_week_end: int = 18,
    players: pd.DataFrame | None = None,
    player_actuals: pd.DataFrame | None = None,
    league_config: LeagueConfig | None = None,
    simulations_per_game: int = 250,
    max_games: int | None = None,
    seed: int = 42,
) -> GameReplayResult:
    """Run a frozen, point-in-time game replay against a transparent profile baseline.

    Models are trained only on plays before ``test_week_start``. Each test game's player usage
    is reconstructed from earlier weeks. Team tendency rows are pre-shifted, so test-game outcomes
    never enter their own prediction-time feature vector.
    """
    play_frame = build_play_intelligence_frame(pbp)
    tendencies = build_team_tendency_snapshots(play_frame)
    enriched = attach_point_in_time_matchup_features(play_frame, tendencies)
    split = int(test_season) * 25 + int(test_week_start)
    train_mask = _chronology(enriched) < split
    train = enriched.loc[train_mask].copy()
    if len(train) < 50:
        raise ValueError("Frozen game replay needs at least 50 pre-cutoff training plays")
    play_call_model = PlayCallModel().fit(train)
    outcome_model = EmpiricalPlayOutcomeModel().fit(train)

    test_schedule = schedules.loc[
        (pd.to_numeric(schedules["season"], errors="coerce") == int(test_season))
        & pd.to_numeric(schedules["week"], errors="coerce").between(
            int(test_week_start), int(test_week_end)
        )
    ].copy()
    test_schedule = test_schedule.dropna(subset=["home_team", "away_team"])
    if max_games is not None:
        test_schedule = test_schedule.head(int(max_games))
    if test_schedule.empty:
        raise ValueError("Frozen game replay has no test games")

    candidate_team_draws: list[pd.DataFrame] = []
    baseline_team_draws: list[pd.DataFrame] = []
    candidate_players: list[pd.DataFrame] = []
    baseline_players: list[pd.DataFrame] = []
    usage_rows: list[pd.DataFrame] = []

    for game_index, (_, schedule_row) in enumerate(test_schedule.iterrows()):
        matchup = matchup_from_schedule(schedule_row)
        usage = build_player_usage_profiles(
            play_frame,
            season=matchup.season,
            week=matchup.week,
            players=players,
        )
        if usage.empty:
            continue
        usage_game = usage.copy()
        usage_game["game_id"] = matchup.resolved_game_id
        usage_rows.append(usage_game)
        config = SimulationConfig(
            simulations=int(simulations_per_game),
            seed=int(seed + game_index * 1009),
        )
        candidate: PlayByPlaySimulationResult = simulate_matchup(
            matchup,
            tendencies=tendencies,
            usage=usage,
            outcome_model=outcome_model,
            play_call_model=play_call_model,
            league_config=league_config,
            config=config,
        )
        baseline = simulate_matchup(
            matchup,
            tendencies=tendencies,
            usage=usage,
            outcome_model=outcome_model,
            play_call_model=None,
            league_config=league_config,
            config=config,
        )
        candidate_team_draws.append(candidate.team_draws)
        baseline_team_draws.append(baseline.team_draws)
        for result, destination in (
            (candidate, candidate_players),
            (baseline, baseline_players),
        ):
            summary = result.player_summary.copy()
            summary["season"] = matchup.season
            summary["week"] = matchup.week
            destination.append(summary)

    if not candidate_team_draws:
        raise ValueError("No replay games had sufficient point-in-time player usage")
    candidate_team = pd.concat(candidate_team_draws, ignore_index=True)
    baseline_team = pd.concat(baseline_team_draws, ignore_index=True)
    candidate_player = pd.concat(candidate_players, ignore_index=True)
    baseline_player = pd.concat(baseline_players, ignore_index=True)
    usage_by_game = pd.concat(usage_rows, ignore_index=True)

    test_game_ids = set(candidate_team["game_id"].astype(str))
    observed_teams = observed_team_games(play_frame, test_schedule)
    observed_teams = observed_teams.loc[
        observed_teams["game_id"].astype(str).isin(test_game_ids)
    ]
    observed_opportunity = observed_player_opportunity(play_frame)
    observed_opportunity = observed_opportunity.loc[
        observed_opportunity["game_id"].astype(str).isin(test_game_ids)
    ]

    candidate_team_metrics = evaluate_team_simulation_draws(candidate_team, observed_teams)
    baseline_team_metrics = evaluate_team_simulation_draws(baseline_team, observed_teams)
    candidate_opportunity = evaluate_player_opportunity(
        predicted_player_opportunity(candidate_team, usage_by_game), observed_opportunity
    )
    baseline_opportunity = evaluate_player_opportunity(
        predicted_player_opportunity(baseline_team, usage_by_game), observed_opportunity
    )

    test_plays = enriched.loc[
        (pd.to_numeric(enriched["season"], errors="coerce") == int(test_season))
        & pd.to_numeric(enriched["week"], errors="coerce").between(
            int(test_week_start), int(test_week_end)
        )
        & enriched["game_id"].astype(str).isin(test_game_ids)
    ].copy()
    candidate_probability = play_call_model.predict_pass_probability(test_plays)
    baseline_probability = pd.to_numeric(
        test_plays["pregame_pass_rate"], errors="coerce"
    ).fillna(float(train["is_dropback"].mean()))
    candidate_play_call = evaluate_play_call_probabilities(
        test_plays["is_dropback"], candidate_probability
    )
    baseline_play_call = evaluate_play_call_probabilities(
        test_plays["is_dropback"], baseline_probability
    )

    candidate_fantasy = _fantasy_metrics(candidate_player, player_actuals)
    baseline_fantasy = _fantasy_metrics(baseline_player, player_actuals)
    candidate_metrics = _combine_metrics(
        candidate_play_call, candidate_team_metrics, candidate_opportunity, candidate_fantasy
    )
    baseline_metrics = _combine_metrics(
        baseline_play_call, baseline_team_metrics, baseline_opportunity, baseline_fantasy
    )
    diagnostics = {
        "test_season": int(test_season),
        "test_week_start": int(test_week_start),
        "test_week_end": int(test_week_end),
        "games_replayed": int(candidate_team["game_id"].nunique()),
        "training_plays": int(len(train)),
        "simulations_per_game": int(simulations_per_game),
        "candidate_model": play_call_model.model_source,
        "baseline_model": "point_in_time_matchup_profile",
        "outcome_model": outcome_model.model_source,
        "research_only": True,
    }
    return GameReplayResult(
        candidate_metrics=candidate_metrics,
        baseline_metrics=baseline_metrics,
        candidate_team_draws=candidate_team,
        baseline_team_draws=baseline_team,
        candidate_player_predictions=candidate_player,
        baseline_player_predictions=baseline_player,
        observed_teams=observed_teams,
        observed_opportunity=observed_opportunity,
        diagnostics=diagnostics,
    )
