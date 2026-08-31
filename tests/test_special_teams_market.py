from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from player_state_engine.product.release_readiness import _special_teams_support
from player_state_engine.product.special_teams_market import build_special_teams_market


def _rankings() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "page_type": "redraft-k",
                "ecr_type": "rp",
                "player": "Brandon Aubrey",
                "id": 26068,
                "pos": "K",
                "team": "DAL",
                "ecr": 1.19,
                "sd": 0.53,
                "best": 1,
                "worst": 4,
                "scrape_date": "2026-08-28",
            },
            {
                "page_type": "redraft-k",
                "ecr_type": "rp",
                "player": "Free Agent Kicker",
                "id": 99999,
                "pos": "K",
                "team": "FA",
                "ecr": 2.0,
                "scrape_date": "2026-08-28",
            },
            {
                "page_type": "redraft-dst",
                "ecr_type": "rp",
                "player": "Houston Texans",
                "id": 8120,
                "pos": "DST",
                "team": "HOU",
                "ecr": 1.76,
                "sd": 3.02,
                "best": 1,
                "worst": 24,
                "scrape_date": "2026-08-28",
            },
            {
                "page_type": "redraft-dst",
                "ecr_type": "rp",
                "player": "Los Angeles Rams",
                "id": 8280,
                "pos": "DST",
                "team": "LAR",
                "ecr": 3.79,
                "scrape_date": "2026-08-28",
            },
            {
                "page_type": "best-dst",
                "ecr_type": "bp",
                "player": "Denver Broncos",
                "id": 8090,
                "pos": "DST",
                "team": "DEN",
                "ecr": 1.0,
                "scrape_date": "2026-08-28",
            },
        ]
    )


def _playerids() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"gsis_id": "00-0039999", "fantasypros_id": 26068.0},
            {"gsis_id": "00-0099999", "fantasypros_id": 99999.0},
        ]
    )


def _rosters() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "season": 2026,
                "gsis_id": "00-0039999",
                "full_name": "Brandon Aubrey",
                "team": "DAL",
                "position": "K",
                "status": "ACT",
            },
            {
                "season": 2026,
                "gsis_id": "00-0099999",
                "full_name": "Free Agent Kicker",
                "team": None,
                "position": "K",
                "status": "FA",
            },
        ]
    )


def test_special_teams_board_keeps_market_authority_separate_from_model_fields() -> None:
    snapshot = build_special_teams_market(
        _rankings(),
        _playerids(),
        _rosters(),
        season=2026,
        generated_at=datetime(2026, 8, 29, tzinfo=UTC),
    )

    assert snapshot["authority"] == "external_market_only"
    assert snapshot["model_fields_present"] is False
    assert snapshot["source_date"] == "2026-08-28"
    assert snapshot["kicker_count"] == 1
    assert snapshot["kicker_identity_scheme"] == "gsis_id"
    assert snapshot["kicker_ids"] == ["00-0039999"]
    assert snapshot["dst_count"] == 2
    assert snapshot["dst_identity_scheme"] == "team_abbr"
    assert snapshot["dst_ids"] == ["HOU", "LA"]
    for row in snapshot["kickers"] + snapshot["defenses"]:
        assert row["authority"] == "external_market_only"
        assert "projection_q50" not in row
        assert "vorp" not in row
        assert "season_points_q50" not in row


def test_real_special_teams_snapshot_satisfies_release_identity_contract() -> None:
    now = datetime(2026, 8, 29, 12, tzinfo=UTC)
    snapshot = build_special_teams_market(
        _rankings(),
        _playerids(),
        _rosters(),
        season=2026,
        generated_at=now,
    )

    supported = _special_teams_support(snapshot, now=now, max_age_hours=36.0)

    assert supported == ("K", "DST")


def test_kicker_board_uses_exact_identity_and_current_roster_truth() -> None:
    snapshot = build_special_teams_market(_rankings(), _playerids(), _rosters(), season=2026)

    assert snapshot["kickers"] == [
        {
            "entity_id": "K:00-0039999",
            "entity_type": "player",
            "position": "K",
            "player_id": "00-0039999",
            "player_name": "Brandon Aubrey",
            "team": "DAL",
            "roster_status": "ACT",
            "market_team": "DAL",
            "market_order": 1,
            "positional_ecr": 1.19,
            "rank_sd": 0.53,
            "best_rank": 1.0,
            "worst_rank": 4.0,
            "source_date": "2026-08-28",
            "identity_source": "fantasypros_id",
            "market_source": "fantasypros_redraft_positional_ecr",
            "authority": "external_market_only",
        }
    ]


def test_current_roster_team_wins_when_market_team_is_stale() -> None:
    rankings = _rankings().copy()
    rankings.loc[rankings["id"].eq(26068), "team"] = "HOU"

    snapshot = build_special_teams_market(rankings, _playerids(), _rosters(), season=2026)

    kicker = snapshot["kickers"][0]
    assert kicker["team"] == "DAL"
    assert kicker["market_team"] == "HOU"


def test_dst_board_uses_team_entity_and_canonical_nflverse_code() -> None:
    snapshot = build_special_teams_market(_rankings(), _playerids(), _rosters(), season=2026)
    defenses = snapshot["defenses"]

    assert [row["market_order"] for row in defenses] == [1, 2]
    assert defenses[0]["entity_id"] == "DST:HOU"
    assert defenses[0]["entity_type"] == "team_defense"
    assert defenses[0]["positional_ecr"] == 1.76
    assert defenses[1]["entity_id"] == "DST:LA"
    assert defenses[1]["team"] == "LA"
    assert all(row["position"] == "DST" for row in defenses)


def test_best_ball_defense_rows_never_enter_redraft_board() -> None:
    snapshot = build_special_teams_market(_rankings(), _playerids(), _rosters(), season=2026)

    assert all(row["team"] != "DEN" for row in snapshot["defenses"])
