from __future__ import annotations

from player_state_engine.fantasy.league import LeagueConfig


def test_roster_and_strategy_settings_do_not_change_scoring_contract_identity() -> None:
    shallow = LeagueConfig(
        teams=8,
        scoring="ppr",
        roster_slots={"QB": 2, "RB": 3, "WR": 3, "TE": 1, "FLEX": 3, "BENCH": 6},
        risk_preference=0.9,
        median_scoring=False,
    )
    deep = LeagueConfig(
        teams=14,
        scoring="ppr",
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 10},
        risk_preference=0.1,
        median_scoring=True,
        median_game_weight=2.0,
    )

    assert shallow.scoring_contract_payload() == deep.scoring_contract_payload()
    assert shallow.scoring_contract_id == deep.scoring_contract_id


def test_half_ppr_and_ppr_have_distinct_scoring_contracts() -> None:
    ppr = LeagueConfig(scoring="ppr")
    half = LeagueConfig(scoring="half_ppr")

    assert ppr.scoring_contract_id != half.scoring_contract_id
    assert ppr.scoring_contract_payload()["scoring_weights"]["receptions"] == 1.0
    assert half.scoring_contract_payload()["scoring_weights"]["receptions"] == 0.5


def test_custom_scoring_weight_changes_contract_identity() -> None:
    base = LeagueConfig(scoring="ppr")
    return_tds = LeagueConfig(scoring="ppr", scoring_weights={"special_teams_tds": 6.0})

    assert base.scoring_contract_id != return_tds.scoring_contract_id
    assert return_tds.scoring_contract_payload()["scoring_weights"]["special_teams_tds"] == 6.0


def test_tight_end_premium_changes_contract_identity() -> None:
    base = LeagueConfig(scoring="ppr", tight_end_premium=0.0)
    premium = LeagueConfig(scoring="ppr", tight_end_premium=0.5)

    assert base.scoring_contract_id != premium.scoring_contract_id


def test_contract_id_is_deterministic_and_full_length_sha256() -> None:
    config = LeagueConfig(scoring="ppr")

    assert config.scoring_contract_id == LeagueConfig(scoring="ppr").scoring_contract_id
    prefix, version, digest = config.scoring_contract_id.split("-", maxsplit=2)
    assert prefix == "scoring"
    assert version == "v1"
    assert len(digest) == 64
    int(digest, 16)
