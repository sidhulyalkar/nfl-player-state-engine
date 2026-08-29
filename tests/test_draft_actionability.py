from __future__ import annotations

import pandas as pd

from player_state_engine.fantasy.draft_actionability import assess_candidate_scope_actionability
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.readiness import assess_league_readiness


def _projection(player_id: str, position: str, adp: float) -> dict[str, object]:
    row: dict[str, object] = {
        "player_id": player_id,
        "player_name": player_id,
        "position": position,
        "market_adp": adp,
    }
    stats = (
        "passing_yards",
        "passing_tds",
        "interceptions",
        "rushing_yards",
        "rushing_tds",
        "receptions",
        "receiving_yards",
        "receiving_tds",
    )
    for index, stat in enumerate(stats, start=1):
        row[f"{stat}_q10"] = float(index)
        row[f"{stat}_q50"] = float(index * 2)
        row[f"{stat}_q90"] = float(index * 3)
    return row


def test_skill_candidate_scope_can_be_actionable_while_global_k_dst_remain_blocked() -> None:
    projections = pd.DataFrame(
        [
            _projection("qb1", "QB", 8.0),
            _projection("rb1", "RB", 4.0),
            _projection("wr1", "WR", 5.0),
            _projection("te1", "TE", 30.0),
        ]
    )
    config = LeagueConfig(
        teams=8,
        scoring="ppr",
        roster_slots={
            "QB": 2,
            "RB": 2,
            "WR": 2,
            "TE": 1,
            "FLEX": 1,
            "DST": 1,
            "K": 1,
            "BENCH": 4,
        },
    )
    readiness = assess_league_readiness(projections, config)
    assert readiness.ready is False
    assert set(readiness.missing_positions) == {"DST", "K"}

    candidates = pd.DataFrame(
        [
            {"player_id": "rb1", "position": "RB"},
            {"player_id": "wr1", "position": "WR"},
        ]
    )
    scoped = assess_candidate_scope_actionability(
        projections,
        candidates,
        config,
        global_readiness=readiness,
    )

    assert scoped.actionable is True
    assert scoped.status == "CAUTION"
    assert scoped.blocking_reasons == ()
    assert set(scoped.unsupported_required_positions) == {"DST", "K"}
    assert "UNSUPPORTED_REQUIRED_POSITIONS_OUTSIDE_SCOPE" in scoped.caution_reasons
    assert "GLOBAL_LEAGUE_READINESS_BLOCKED" in scoped.caution_reasons
    assert scoped.exact_scoring_coverage == 1.0
    assert scoped.valuation_coverage == 1.0


def test_candidate_missing_from_projection_pool_blocks_scope() -> None:
    projections = pd.DataFrame([_projection("wr1", "WR", 5.0)])
    config = LeagueConfig(roster_slots={"WR": 1, "BENCH": 1})
    candidates = pd.DataFrame(
        [
            {"player_id": "wr1", "position": "WR"},
            {"player_id": "ghost", "position": "WR"},
        ]
    )

    scoped = assess_candidate_scope_actionability(projections, candidates, config)

    assert scoped.actionable is False
    assert scoped.status == "BLOCKED"
    assert "MISSING_CANDIDATE_PROJECTIONS" in scoped.blocking_reasons
    assert scoped.missing_candidate_player_ids == ("ghost",)


def test_generic_scoring_fallback_blocks_candidate_scope() -> None:
    projections = pd.DataFrame(
        [
            {
                "player_id": "wr1",
                "position": "WR",
                "market_adp": 5.0,
                "season_points_q10": 100.0,
                "season_points_q50": 180.0,
                "season_points_q90": 250.0,
            }
        ]
    )
    config = LeagueConfig(roster_slots={"WR": 1, "BENCH": 1})
    candidates = pd.DataFrame([{"player_id": "wr1", "position": "WR"}])

    scoped = assess_candidate_scope_actionability(projections, candidates, config)

    assert scoped.actionable is False
    assert "CANDIDATE_GENERIC_SCORING_FALLBACK" in scoped.blocking_reasons
    assert scoped.exact_scoring_coverage == 0.0


def test_complete_candidate_scope_is_ready_when_global_contract_is_complete() -> None:
    projections = pd.DataFrame([_projection("wr1", "WR", 5.0)])
    config = LeagueConfig(roster_slots={"WR": 1, "BENCH": 1})
    readiness = assess_league_readiness(projections, config)
    assert readiness.ready is True

    candidates = pd.DataFrame([{"player_id": "wr1", "position": "WR"}])
    scoped = assess_candidate_scope_actionability(
        projections,
        candidates,
        config,
        global_readiness=readiness,
    )

    assert scoped.actionable is True
    assert scoped.status == "READY"
    assert scoped.blocking_reasons == ()
    assert scoped.caution_reasons == ()
