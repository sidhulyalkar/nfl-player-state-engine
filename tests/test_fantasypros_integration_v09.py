from __future__ import annotations

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
    assert frame.loc[frame["player_name"].eq("Quarterback One"), "position_rank"].iloc[0] == 5
