from __future__ import annotations

import pytest

from player_state_engine.integrations.fantasypros import FantasyProsClient


def test_fantasypros_generic_api_pull_does_not_claim_2qb_or_team_count(monkeypatch) -> None:
    client = FantasyProsClient(api_key="test-key")

    def fake_get(path, params):
        assert path == "nfl/2026/consensus-rankings"
        assert params["scoring"] == "HALF"
        return {
            "type": "DRAFT",
            "count": 2,
            "total_experts": 5,
            "last_updated_ts": 1787011200,
            "players": [
                {
                    "player_id": "fp1",
                    "player_name": "Quarterback One",
                    "player_position_id": "QB",
                    "player_team_id": "BUF",
                    "rank_ecr": 18,
                    "pos_rank": "QB5",
                    "rank_min": 12,
                    "rank_max": 27,
                    "rank_std": 4.2,
                },
                {
                    "player_id": "fp2",
                    "player_name": "Running Back One",
                    "player_position_id": "RB",
                    "player_team_id": "ATL",
                    "rank_ecr": 3,
                    "pos_rank": "RB1",
                    "rank_min": 1,
                    "rank_max": 6,
                    "rank_std": 1.3,
                },
            ],
        }

    monkeypatch.setattr(client, "_get", fake_get)
    frame, metadata = client.fetch_consensus_rankings(2026, scoring="HALF")

    assert set(frame["teams"].isna()) == {True}
    assert set(frame["qb_format"]) == {"unknown"}
    assert metadata["teams"] is None
    assert metadata["qb_format"] == "unknown"
    assert metadata["rank_semantics"] == "consensus_ordinal_rank"
    assert frame.loc[frame["player_name"].eq("Quarterback One"), "position_rank"].iloc[0] == 5


def test_fantasypros_adp_prefers_scoring_specific_position_over_ecr(monkeypatch) -> None:
    client = FantasyProsClient(api_key="test-key")

    def fake_get(path, params):
        assert path == "nfl/2026/consensus-rankings"
        assert params["type"] == "ADP"
        assert params["position"] == "OP"
        assert params["scoring"] == "PPR"
        assert params["experts"] is None
        return {
            "type": "ADP",
            "count": 1,
            "total_experts": 0,
            "last_updated_ts": 1788199200,
            "players": [
                {
                    "player_id": "fp1",
                    "player_name": "Quarterback One",
                    "player_position_id": "QB",
                    "player_team_id": "BUF",
                    "rank_ecr": 3,
                    "rank_adp": 6.25,
                    "rank_adp_ppr": 4.75,
                    "rank_ave": 5.5,
                    "pos_rank": "QB1",
                    "rank_std": 1.1,
                }
            ],
        }

    monkeypatch.setattr(client, "_get", fake_get)
    frame, metadata = client.fetch_consensus_rankings(
        2026,
        scoring="PPR",
        position="OP",
        ranking_type="ADP",
        experts=False,
    )

    assert frame.loc[0, "rank"] == pytest.approx(4.75)
    assert frame.loc[0, "source"] == "fantasypros_adp"
    assert frame.loc[0, "source_kind"] == "market"
    assert frame.loc[0, "ranking_type"] == "adp"
    assert metadata["rank_semantics"] == "average_draft_position"


def test_fantasypros_adp_accepts_average_position_alias(monkeypatch) -> None:
    client = FantasyProsClient(api_key="test-key")
    monkeypatch.setattr(
        client,
        "_get",
        lambda _path, _params: {
            "type": "ADP",
            "count": 1,
            "players": [
                {
                    "player_id": "fp1",
                    "player_name": "Running Back One",
                    "player_position_id": "RB",
                    "player_team_id": "ATL",
                    "rank_ecr": 2,
                    "rank_ave": 7.4,
                }
            ],
        },
    )

    frame, _metadata = client.fetch_consensus_rankings(
        2026,
        scoring="HALF",
        position="ALL",
        ranking_type="ADP",
        experts=False,
    )

    assert frame.loc[0, "rank"] == pytest.approx(7.4)


def test_fantasypros_adp_refuses_to_disguise_ordinal_rank_as_adp(monkeypatch) -> None:
    client = FantasyProsClient(api_key="test-key")

    monkeypatch.setattr(
        client,
        "_get",
        lambda _path, _params: {
            "type": "ADP",
            "count": 1,
            "players": [
                {
                    "player_id": "fp1",
                    "player_name": "Quarterback One",
                    "player_position_id": "QB",
                    "player_team_id": "BUF",
                    "rank_ecr": 3,
                }
            ],
        },
    )

    with pytest.raises(ValueError, match="refusing to substitute rank_ecr as ADP"):
        client.fetch_consensus_rankings(
            2026,
            scoring="PPR",
            position="OP",
            ranking_type="ADP",
            experts=False,
        )
