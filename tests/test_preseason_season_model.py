from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd

from player_state_engine.config import ModelConfig
from player_state_engine.evaluation.preseason import run_preseason_season_benchmark
from player_state_engine.fantasy.preseason import (
    PRESEASON_TARGETS,
    build_current_preseason_features,
    build_preseason_season_dataset,
    preseason_feature_columns,
)


def _weekly_rosters() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for season in (2022, 2023, 2024, 2025):
        rows.extend(
            [
                {"season": season, "week": 1, "team": "AAA", "position": "QB", "status": "ACT", "full_name": "Quarterback", "gsis_id": "QB1"},
                {"season": season, "week": 1, "team": "AAA", "position": "WR", "status": "ACT", "full_name": "Receiver", "gsis_id": "WR1"},
                {"season": season, "week": 1, "team": "AAA", "position": "RB", "status": "ACT", "full_name": "Backup", "gsis_id": "RB-ZERO"},
            ]
        )
    # A player is rostered in 2022 and 2024 but not 2023. Exact prior-year joins must not use 2022
    # as the 2024 prior season.
    rows.extend(
        [
            {"season": 2022, "week": 1, "team": "BBB", "position": "WR", "status": "ACT", "full_name": "Gap Player", "gsis_id": "WR-GAP"},
            {"season": 2024, "week": 1, "team": "BBB", "position": "WR", "status": "ACT", "full_name": "Gap Player", "gsis_id": "WR-GAP"},
            # Released row with a missing ID is not part of the candidate universe and must not
            # be misreported as an unresolved rostered fantasy asset.
            {"season": 2025, "week": 1, "team": "AAA", "position": "WR", "status": "UFA", "full_name": "Released", "gsis_id": None},
        ]
    )
    return pd.DataFrame(rows)


def _stats() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for season in (2022, 2023, 2024, 2025):
        for week in (1, 2):
            rows.extend(
                [
                    {
                        "season": season,
                        "week": week,
                        "season_type": "REG",
                        "game_id": f"{season}_{week}_AAA",
                        "player_id": "QB1",
                        "player_name": "Quarterback",
                        "team": "AAA",
                        "position": "QB",
                        "passing_yards": 250 + 2 * (season - 2022),
                        "passing_tds": 2,
                        "interceptions": 1,
                        "rushing_yards": 15,
                        "rushing_tds": 0,
                        "fantasy_points_ppr": 20 + season - 2022,
                    },
                    {
                        "season": season,
                        "week": week,
                        "season_type": "REG",
                        "game_id": f"{season}_{week}_AAA",
                        "player_id": "WR1",
                        "player_name": "Receiver",
                        "team": "AAA",
                        "position": "WR",
                        "targets": 8,
                        "receptions": 6,
                        "receiving_yards": 80 + season - 2022,
                        "receiving_tds": 1,
                        "fantasy_points_ppr": 20 + season - 2022,
                    },
                ]
            )
    # Gap player's only box-score season is 2022. RB-ZERO never gets a stat row.
    rows.append(
        {
            "season": 2022,
            "week": 1,
            "season_type": "REG",
            "game_id": "2022_1_BBB",
            "player_id": "WR-GAP",
            "player_name": "Gap Player",
            "team": "BBB",
            "position": "WR",
            "targets": 5,
            "receptions": 3,
            "receiving_yards": 44,
            "receiving_tds": 0,
            "fantasy_points_ppr": 7.4,
        }
    )
    return pd.DataFrame(rows)


def _players() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"gsis_id": "QB1", "birth_date": "1998-01-01", "draft_year": 2020, "draft_round": 1, "draft_pick": 5},
            {"gsis_id": "WR1", "birth_date": "1999-01-01", "draft_year": 2021, "draft_round": 2, "draft_pick": 40},
            {"gsis_id": "RB-ZERO", "birth_date": "2001-01-01", "draft_year": 2024, "draft_round": 5, "draft_pick": 150},
            {"gsis_id": "WR-GAP", "birth_date": "1997-01-01", "draft_year": 2019, "draft_round": 3, "draft_pick": 80},
        ]
    )


def test_preseason_dataset_keeps_zero_output_rostered_players_and_exact_lags() -> None:
    dataset, diagnostics = build_preseason_season_dataset(
        _stats(),
        _weekly_rosters(),
        players=_players(),
        seasons=(2022, 2023, 2024, 2025),
    )

    zero = dataset.loc[
        dataset["player_id"].eq("RB-ZERO") & dataset["season"].eq(2025)
    ].iloc[0]
    gap = dataset.loc[
        dataset["player_id"].eq("WR-GAP") & dataset["season"].eq(2024)
    ].iloc[0]

    assert zero["fantasy_points_ppr"] == 0.0
    assert zero["games_with_stat_row"] == 0
    assert diagnostics.zero_outcome_rows >= 4
    assert diagnostics.unresolved_identity_rows == 0
    assert diagnostics.excluded_status_rows == 1

    assert gap["prior1_rostered"] == 0
    assert pd.isna(gap["prior1_fantasy_points_ppr"])
    assert gap["prior2_rostered"] == 1
    assert gap["prior2_fantasy_points_ppr"] > 0

    features = preseason_feature_columns(dataset)
    assert "fantasy_points_ppr" not in features
    assert "prior1_fantasy_points_ppr" in features
    assert "position" in features


def test_current_preseason_features_do_not_manufacture_target_outcomes() -> None:
    dataset, _ = build_preseason_season_dataset(
        _stats(), _weekly_rosters(), players=_players(), seasons=(2022, 2023, 2024, 2025)
    )
    current = pd.DataFrame(
        [
            {"season": 2026, "team": "CCC", "position": "WR", "status": "ACT", "full_name": "Receiver", "gsis_id": "WR1"},
            {"season": 2026, "team": "CCC", "position": "RB", "status": "ACT", "full_name": "New Rookie", "gsis_id": "NEW-RB"},
        ]
    )
    players = pd.concat(
        [
            _players(),
            pd.DataFrame(
                [{"gsis_id": "NEW-RB", "birth_date": "2004-03-01", "draft_year": 2026, "draft_round": 2, "draft_pick": 50}]
            ),
        ],
        ignore_index=True,
    )
    features = build_current_preseason_features(dataset, current, season=2026, players=players)
    receiver = features.loc[features["player_id"].eq("WR1")].iloc[0]
    rookie = features.loc[features["player_id"].eq("NEW-RB")].iloc[0]

    assert receiver["team_changed_from_prior"] == 1
    assert receiver["prior1_rostered"] == 1
    assert receiver["prior1_fantasy_points_ppr"] > 0
    assert rookie["rookie"] == 1
    assert rookie["prior1_rostered"] == 0
    assert all(pd.isna(receiver[target]) for target in PRESEASON_TARGETS)


def _benchmark_dataset() -> pd.DataFrame:
    rng = np.random.default_rng(7)
    rows: list[dict[str, object]] = []
    for season in (2021, 2022, 2023, 2024, 2025):
        for index in range(36):
            position = ("QB", "RB", "WR", "TE")[index % 4]
            prior = 90 + index * 2.5 + 6 * (season - 2021)
            actual = prior + rng.normal(0, 8)
            rows.append(
                {
                    "season": season,
                    "player_id": f"P{index:02d}",
                    "player_name": f"Player {index}",
                    "position": position,
                    "recent_team": f"T{index % 8}",
                    "roster_status": "ACT",
                    "rookie": 0,
                    "age_at_season_start": 24 + index % 8,
                    "draft_year": 2018 + index % 4,
                    "draft_round": 1 + index % 6,
                    "draft_pick": 10 + index * 3,
                    "experience_seasons_prior": max(0, season - 2021),
                    "team_changed_from_prior": int((index + season) % 7 == 0),
                    "team_position_roster_count": 4,
                    "team_skill_roster_count": 16,
                    "prior1_rostered": int(season > 2021),
                    "prior2_rostered": int(season > 2022),
                    "prior1_games": 17 if season > 2021 else np.nan,
                    "prior2_games": 17 if season > 2022 else np.nan,
                    "prior1_fantasy_points_ppr": prior if season > 2021 else np.nan,
                    "prior2_fantasy_points_ppr": prior - 5 if season > 2022 else np.nan,
                    "fantasy_points_ppr": max(0.0, actual),
                }
            )
    return pd.DataFrame(rows)


def test_preseason_benchmark_is_expanding_season_and_reports_frozen_gate() -> None:
    config = replace(
        ModelConfig(),
        targets=("fantasy_points_ppr",),
        max_iter=10,
        min_samples_leaf=5,
    )
    result = run_preseason_season_benchmark(
        _benchmark_dataset(),
        model_config=config,
        targets=("fantasy_points_ppr",),
        min_train_seasons=3,
    )

    assert set(result.predictions["season"]) == {2024, 2025}
    assert set(result.predictions["method"]) == {
        "preseason_quantile_engine",
        "prior_season_shrunk",
        "position_rookie_prior",
    }
    assert set(result.comparisons["target"]) == {"fantasy_points_ppr"}
    assert isinstance(result.gate.approved, bool)
    assert result.gate.policy["min_primary_pinball_improvement_pct"] == 1.0
