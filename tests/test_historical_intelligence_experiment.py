from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from player_state_engine.evaluation.historical_intelligence_experiment import (
    build_historical_feature_replay,
    verify_frozen_benchmark_sources,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_frozen_benchmark_source_verification_requires_exact_bytes_and_prior_history(
    tmp_path: Path,
) -> None:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    records = []
    for name, filename, content in (
        ("player_stats_2021", "stats_player_week_2021.csv", b"season,week\n2021,1\n"),
        ("player_stats_2022", "stats_player_week_2022.csv", b"season,week\n2022,1\n"),
        ("player_stats_2023", "stats_player_week_2023.csv", b"season,week\n2023,1\n"),
        ("schedules", "games.csv", b"season,week\n2022,1\n"),
    ):
        path = source_dir / filename
        path.write_bytes(content)
        records.append(
            {
                "name": name,
                "url": f"https://example.com/{filename}",
                "bytes": len(content),
                "sha256": _sha256(path),
            }
        )
    manifest = tmp_path / "DATA_MANIFEST.json"
    manifest.write_text(json.dumps({"sources": records}), encoding="utf-8")

    verified = verify_frozen_benchmark_sources(
        manifest,
        source_dir,
        seasons=(2022, 2023),
    )

    assert verified.verified is True
    assert verified.source_identity_sha256
    assert {name for name, _ in verified.paths} == {
        "player_stats_2021",
        "player_stats_2022",
        "player_stats_2023",
        "schedules",
    }

    (source_dir / "games.csv").write_text("drifted\n", encoding="utf-8")
    drifted = verify_frozen_benchmark_sources(
        manifest,
        source_dir,
        seasons=(2022, 2023),
    )
    assert drifted.verified is False
    assert drifted.source_identity_sha256 is None
    assert "source_sha256_mismatch:schedules" in drifted.failures
    assert "source_bytes_mismatch:schedules" in drifted.failures


def _player_stats() -> pd.DataFrame:
    rows = []
    for week, aaa_points, bbb_points in ((1, 8.0, 6.0), (2, 12.0, 7.0), (3, 10.0, 9.0)):
        rows.extend(
            [
                {
                    "season": 2022,
                    "week": week,
                    "player_id": "P1",
                    "player_name": "Player One",
                    "recent_team": "AAA",
                    "position": "WR",
                    "fantasy_points_ppr": aaa_points,
                    "targets": 5 + week,
                    "receptions": 3 + week,
                    "receiving_yards": 40 + 10 * week,
                },
                {
                    "season": 2022,
                    "week": week,
                    "player_id": "P2",
                    "player_name": "Player Two",
                    "recent_team": "BBB",
                    "position": "WR",
                    "fantasy_points_ppr": bbb_points,
                    "targets": 4 + week,
                    "receptions": 2 + week,
                    "receiving_yards": 30 + 8 * week,
                },
            ]
        )
    return pd.DataFrame(rows)


def _schedules() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "game_id": ["2022_01_AAA_BBB", "2022_02_AAA_BBB", "2022_03_AAA_BBB"],
            "season": [2022, 2022, 2022],
            "week": [1, 2, 3],
            "gameday": ["2022-09-11", "2022-09-18", "2022-09-25"],
            "away_team": ["AAA", "AAA", "AAA"],
            "home_team": ["BBB", "BBB", "BBB"],
            "away_rest": [7, 7, 7],
            "home_rest": [7, 7, 7],
            "spread_line": [1.0, 1.5, 2.0],
            "total_line": [45.0, 46.0, 47.0],
            "roof": ["outdoors", "outdoors", "outdoors"],
            "surface": ["grass", "grass", "grass"],
            "temp": [70.0, 68.0, 65.0],
            "wind": [5.0, 6.0, 4.0],
        }
    )


def _frozen_panel() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "season": 2022,
                "week": 2,
                "game_id": "2022_02_AAA_BBB",
                "player_id": "P1",
                "position": "WR",
                "actual_fantasy_points_ppr": 12.0,
                "fantasy_points_ppr_q10": 5.0,
                "fantasy_points_ppr_q50": 10.0,
                "fantasy_points_ppr_q90": 16.0,
            },
            {
                "season": 2022,
                "week": 2,
                "game_id": "2022_02_AAA_BBB",
                "player_id": "P2",
                "position": "WR",
                "actual_fantasy_points_ppr": 7.0,
                "fantasy_points_ppr_q10": 2.0,
                "fantasy_points_ppr_q50": 6.0,
                "fantasy_points_ppr_q90": 12.0,
            },
            {
                "season": 2022,
                "week": 3,
                "game_id": "2022_03_AAA_BBB",
                "player_id": "P1",
                "position": "WR",
                "actual_fantasy_points_ppr": 10.0,
                "fantasy_points_ppr_q10": 4.0,
                "fantasy_points_ppr_q50": 11.0,
                "fantasy_points_ppr_q90": 17.0,
            },
            {
                "season": 2022,
                "week": 3,
                "game_id": "2022_03_AAA_BBB",
                "player_id": "P2",
                "position": "WR",
                "actual_fantasy_points_ppr": 9.0,
                "fantasy_points_ppr_q10": 3.0,
                "fantasy_points_ppr_q50": 7.0,
                "fantasy_points_ppr_q90": 13.0,
            },
        ]
    )


def _coverage() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "season": [2022, 2022, 2022, 2022],
            "week": [2, 2, 3, 3],
            "player_id": ["P1", "P2", "P1", "P2"],
            "prediction_cutoff": [
                "2022-09-18T15:30:00Z",
                "2022-09-18T15:30:00Z",
                "2022-09-25T15:30:00Z",
                "2022-09-25T15:30:00Z",
            ],
            "official_availability_source_covered": [True, True, True, True],
        }
    )


def test_feature_replay_uses_exact_frozen_universe_and_schedule_cutoffs(monkeypatch) -> None:
    monkeypatch.setattr(
        "player_state_engine.evaluation.historical_intelligence_experiment.load_frozen_prediction_panel",
        lambda _root: _frozen_panel(),
    )

    replay = build_historical_feature_replay(
        _player_stats(),
        _schedules(),
        _coverage(),
        benchmark_root="unused",
        seasons=(2022,),
    )

    assert len(replay.frame) == 4
    assert replay.frame["prediction_cutoff"].notna().all()
    assert "official_availability_source_covered" not in replay.frame.columns
    assert "fantasy_points_ppr_lag1" in replay.frame.columns
    assert replay.audit["frozen_outcome_agreement_verified"] is True
    assert replay.audit["frozen_outcome_max_abs_difference"] == 0.0
    assert replay.audit["baseline_authority"] == "current_feature_builder_frozen_source_replay"
    assert replay.audit["historical_production_parity_verified"] is False
    assert replay.audit["base_feature_count"] > 0


def test_feature_replay_fails_when_rebuilt_outcomes_disagree_with_frozen_benchmark(
    monkeypatch,
) -> None:
    frozen = _frozen_panel()
    frozen.loc[frozen["player_id"].eq("P1") & frozen["week"].eq(2), "actual_fantasy_points_ppr"] = 99.0
    monkeypatch.setattr(
        "player_state_engine.evaluation.historical_intelligence_experiment.load_frozen_prediction_panel",
        lambda _root: frozen,
    )

    with pytest.raises(ValueError, match="Rebuilt target outcomes disagree"):
        build_historical_feature_replay(
            _player_stats(),
            _schedules(),
            _coverage(),
            benchmark_root="unused",
            seasons=(2022,),
        )
