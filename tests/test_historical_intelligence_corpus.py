from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from player_state_engine.evaluation.historical_intelligence_corpus import (
    HISTORICAL_NFLVERSE_INJURY_MAX_SEASON,
    build_historical_intelligence_corpus,
    verify_source_archive_manifest,
)
from player_state_engine.state_graph.experiments import EvidenceTier


def _panel() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "season": 2023,
                "week": 3,
                "game_id": "2023_03_BBB_AAA",
                "player_id": "P1",
                "recent_team": "AAA",
            },
            {
                "season": 2023,
                "week": 3,
                "game_id": "2023_03_BBB_AAA",
                "player_id": "P2",
                "recent_team": "AAA",
            },
            {
                "season": 2024,
                "week": 3,
                "game_id": "2024_03_DDD_CCC",
                "player_id": "P3",
                "recent_team": "CCC",
            },
            {
                "season": 2024,
                "week": 3,
                "game_id": "2024_03_FFF_EEE",
                "player_id": "P4",
                "recent_team": "EEE",
            },
        ]
    )


def _schedules() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "game_id": ["2023_03_BBB_AAA", "2024_03_DDD_CCC", "2024_03_FFF_EEE"],
            "gameday": ["2023-09-24", "2024-09-22", "2024-09-22"],
            "gametime": ["13:00", "13:00", "16:25"],
        }
    )


def _injuries() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "season": [2023, 2023, 2024, 2024],
            "week": [3, 3, 3, 3],
            "gsis_id": ["P1", "P1", "P3", "P3"],
            "full_name": ["Player One", "Player One", "Player Three", "Player Three"],
            "team": ["AAA", "AAA", "CCC", "CCC"],
            "report_status": ["Questionable", "Out", "Questionable", "Out"],
            "practice_status": ["Limited Participation", "DNP", "Limited", "DNP"],
            # 13:00 ET cutoff at 1.5h is 15:30Z. The second row in each season is late.
            "date_modified": [
                "2023-09-24T15:00:00Z",
                "2023-09-24T16:00:00Z",
                "2024-09-22T15:00:00Z",
                "2024-09-22T16:00:00Z",
            ],
            "report_primary_injury": ["Knee", "Knee", "Ankle", "Ankle"],
        }
    )


def test_injury_corpus_separates_source_coverage_from_claim_prevalence() -> None:
    corpus = build_historical_intelligence_corpus(
        _panel(),
        _schedules(),
        injuries=_injuries(),
        include_injuries=True,
        include_depth_charts=False,
        source_archive_verified=True,
        archive_identity_sha256="archive-verified-123",
    )

    coverage = corpus.source_coverage.set_index("player_id")
    assert bool(coverage.loc["P1", "official_availability_source_covered"])
    assert bool(coverage.loc["P2", "official_availability_source_covered"])
    assert not bool(coverage.loc["P2", "official_availability_evidence_found"])
    assert bool(coverage.loc["P3", "official_availability_source_covered"])
    assert not bool(coverage.loc["P4", "official_availability_source_covered"])
    assert not bool(coverage.loc["P4", "official_availability_evidence_found"])

    evidence = corpus.official_evidence
    assert len(evidence) == 4
    assert set(evidence["player_id"]) == {"P1", "P3"}
    assert set(evidence["practice_status"]) >= {"limited", "unknown"}
    assert set(evidence["game_status"]) >= {"questionable", "unknown"}
    assert "out" not in set(evidence["game_status"])

    assert corpus.provenance.tier == EvidenceTier.MULTI_SEASON_ISOLATED
    assert corpus.provenance.point_in_time_verified is True
    assert corpus.provenance.source_coverage_point_in_time_verified is True
    assert corpus.audit["automatic_promotion"] is False
    assert corpus.audit["production_projection_changed"] is False


def test_unverified_archive_cannot_self_promote_to_tier_two() -> None:
    corpus = build_historical_intelligence_corpus(
        _panel(),
        _schedules(),
        injuries=_injuries(),
        source_archive_verified=False,
    )

    assert corpus.provenance.tier == EvidenceTier.SINGLE_HISTORICAL_SLICE
    assert corpus.provenance.point_in_time_verified is True
    assert corpus.provenance.source_coverage_point_in_time_verified is False


def test_post_2024_nflverse_injury_rows_fail_closed() -> None:
    injuries = _injuries().iloc[[0]].copy()
    injuries["season"] = HISTORICAL_NFLVERSE_INJURY_MAX_SEASON + 1
    panel = _panel().iloc[[0]].copy()
    panel["season"] = HISTORICAL_NFLVERSE_INJURY_MAX_SEASON + 1
    panel["game_id"] = "2025_03_BBB_AAA"
    schedules = pd.DataFrame(
        {"game_id": ["2025_03_BBB_AAA"], "gameday": ["2025-09-21"], "gametime": ["13:00"]}
    )

    with pytest.raises(ValueError, match="not certified after 2024"):
        build_historical_intelligence_corpus(panel, schedules, injuries=injuries)


def test_timestamped_depth_coverage_requires_recent_pre_cutoff_snapshot() -> None:
    panel = pd.DataFrame(
        [
            {
                "season": 2025,
                "week": 1,
                "game_id": "2025_01_BBB_AAA",
                "player_id": "D1",
                "recent_team": "AAA",
            },
            {
                "season": 2025,
                "week": 1,
                "game_id": "2025_01_DDD_CCC",
                "player_id": "D2",
                "recent_team": "CCC",
            },
        ]
    )
    schedules = pd.DataFrame(
        {
            "game_id": ["2025_01_BBB_AAA", "2025_01_DDD_CCC"],
            "gameday": ["2025-09-07", "2025-09-07"],
            "gametime": ["13:00", "13:00"],
        }
    )
    depth = pd.DataFrame(
        {
            "dt": [
                "2025-09-07T14:00:00Z",
                "2025-09-07T16:00:00Z",
                "2025-08-01T14:00:00Z",
            ],
            "team": ["AAA", "AAA", "CCC"],
            "player_name": ["Depth One", "Depth One", "Depth Two"],
            "gsis_id": ["D1", "D1", "D2"],
            "pos_rank": [1, 3, 1],
        }
    )

    corpus = build_historical_intelligence_corpus(
        panel,
        schedules,
        depth_charts=depth,
        include_injuries=False,
        include_depth_charts=True,
        depth_maximum_age_days=14.0,
    )
    coverage = corpus.source_coverage.set_index("player_id")
    assert bool(coverage.loc["D1", "official_depth_chart_source_covered"])
    assert not bool(coverage.loc["D2", "official_depth_chart_source_covered"])
    assert len(corpus.official_evidence) == 1
    row = corpus.official_evidence.iloc[0]
    assert row["player_id"] == "D1"
    assert row["depth_rank"] == 1
    assert row["depth_role"] == "starter"


def test_source_archive_manifest_verifies_hashes_and_fails_on_tamper(tmp_path: Path) -> None:
    source = tmp_path / "injuries_2024.csv"
    source.write_text("season,week\n2024,1\n", encoding="utf-8")
    import hashlib

    expected = hashlib.sha256(source.read_bytes()).hexdigest()
    manifest = pd.DataFrame(
        [
            {
                "name": "injuries_2024",
                "path": f"some/other/root/{source.name}",
                "sha256": expected,
                "status": "available",
            }
        ]
    )

    verified = verify_source_archive_manifest([source], manifest)
    assert verified.verified is True
    assert verified.archive_identity_sha256
    assert verified.failures == ()

    source.write_text("tampered\n", encoding="utf-8")
    tampered = verify_source_archive_manifest([source], manifest)
    assert tampered.verified is False
    assert any("sha256_mismatch" in failure for failure in tampered.failures)
