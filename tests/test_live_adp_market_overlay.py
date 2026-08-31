from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.product.live_adp import attach_live_adp


def _projections() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "player_id": "00-0034857",
                "player_name": "Josh Allen",
                "position": "QB",
                "recent_team": "BUF",
                "season_points_q50": 350.0,
                "market_adp": np.nan,
            },
            {
                "player_id": "00-0036322",
                "player_name": "Justin Jefferson",
                "position": "WR",
                "recent_team": "MIN",
                "season_points_q50": 300.0,
                "market_adp": np.nan,
            },
        ]
    )


def _market_row(
    *, scoring: str, scope: str, name: str, position: str, team: str, rank: float
) -> dict:
    return {
        "source": "fantasypros_adp",
        "source_kind": "market",
        "source_player_id": f"fp-{name}",
        "canonical_player_id": None,
        "player_name": name,
        "position": position,
        "nfl_team": team,
        "ranking_type": "adp",
        "scoring": scoring.lower(),
        "teams": np.nan,
        "qb_format": "unknown",
        "rank": rank,
        "position_rank": np.nan,
        "rank_min": np.nan,
        "rank_max": np.nan,
        "rank_std": 1.0,
        "expert_count": 0,
        "source_weight": 1.0,
        "captured_at_utc": datetime(2026, 8, 31, 18, 0, tzinfo=UTC),
        "source_url": "https://api.fantasypros.com/public/v2/json/nfl/2026/consensus-rankings",
        "market_scope": scope,
        "market_scoring": scoring,
    }


def _market() -> pd.DataFrame:
    rows = []
    for scoring in ("PPR", "HALF"):
        for scope in ("ALL", "OP"):
            qb_rank = (22.0 if scope == "ALL" else 3.0) + (2.0 if scoring == "HALF" else 0.0)
            wr_rank = (4.0 if scope == "ALL" else 6.0) + (1.0 if scoring == "HALF" else 0.0)
            rows.extend(
                [
                    _market_row(
                        scoring=scoring,
                        scope=scope,
                        name="Josh Allen",
                        position="QB",
                        team="BUF",
                        rank=qb_rank,
                    ),
                    _market_row(
                        scoring=scoring,
                        scope=scope,
                        name="Justin Jefferson",
                        position="WR",
                        team="MIN",
                        rank=wr_rank,
                    ),
                ]
            )
    return pd.DataFrame(rows)


def test_half_ppr_one_qb_uses_half_all_market() -> None:
    config = LeagueConfig(
        teams=12,
        scoring="half_ppr",
        roster_slots={"QB": 1, "RB": 2, "WR": 2, "TE": 1, "FLEX": 1, "BENCH": 6},
    )
    out, status = attach_live_adp(_projections(), config, _market())

    by_name = out.set_index("player_name")
    assert by_name.loc["Josh Allen", "market_adp"] == 24.0
    assert by_name.loc["Justin Jefferson", "market_adp"] == 5.0
    assert status["requested_scoring"] == "HALF"
    assert status["requested_scope"] == "ALL"
    assert status["format_authority"] == "scoring_matched_1qb_market"
    assert status["format_confidence"] == 0.82
    assert status["coverage_rate"] == 1.0


def test_eight_team_two_qb_uses_ppr_op_proxy_and_expands_uncertainty() -> None:
    config = LeagueConfig(
        teams=8,
        scoring="ppr",
        roster_slots={
            "QB": 2,
            "RB": 3,
            "WR": 3,
            "TE": 1,
            "FLEX": 3,
            "K": 1,
            "DST": 1,
            "BENCH": 6,
        },
    )
    out, status = attach_live_adp(_projections(), config, _market())

    by_name = out.set_index("player_name")
    assert by_name.loc["Josh Allen", "market_adp"] == 3.0
    assert by_name.loc["Justin Jefferson", "market_adp"] == 6.0
    assert status["requested_scoring"] == "PPR"
    assert status["requested_scope"] == "OP"
    assert status["format_authority"] == "superflex_proxy_for_multi_qb"
    assert 0.45 < float(status["format_confidence"]) < 0.55
    assert by_name.loc["Josh Allen", "market_adp_sd"] > 10.0
    assert by_name.loc["Josh Allen", "market_adp_sd_authority"] == (
        "conservative_format_freshness_proxy_not_observed_pick_sd"
    )


def test_multicontract_projection_rows_share_one_market_identity() -> None:
    base = _projections()
    ppr = base.assign(scoring_contract_id="ppr-contract")
    half = base.assign(scoring_contract_id="half-contract")
    projections = pd.concat([ppr, half], ignore_index=True)
    config = LeagueConfig(teams=12, scoring="ppr")

    out, status = attach_live_adp(projections, config, _market())

    allen = out.loc[out["player_id"].eq("00-0034857")]
    jefferson = out.loc[out["player_id"].eq("00-0036322")]
    assert len(allen) == 2
    assert len(jefferson) == 2
    assert set(allen["market_adp"]) == {22.0}
    assert set(jefferson["market_adp"]) == {4.0}
    assert status["matched_players"] == 2
    assert status["eligible_players"] == 2
    assert status["coverage_rate"] == 1.0


def test_fantasypros_rank_std_is_not_used_as_pick_position_sd() -> None:
    config = LeagueConfig(teams=12, scoring="ppr")
    market = _market()
    market.loc[:, "rank_std"] = 0.01
    out, _status = attach_live_adp(_projections(), config, market)

    assert float(out.loc[out["player_name"].eq("Josh Allen"), "market_adp_sd"].iloc[0]) >= 6.0


def test_market_older_than_24_hours_expires_to_neutral_timing() -> None:
    config = LeagueConfig(teams=12, scoring="ppr")
    metadata = {
        "generated_at_utc": (datetime.now(UTC) - timedelta(hours=25)).isoformat(),
    }

    out, status = attach_live_adp(_projections(), config, _market(), metadata)

    assert out["market_adp"].isna().all()
    assert status["available"] is False
    assert status["expired"] is True
    assert status["freshness_confidence"] == 0.0
    assert status["reason"] == "market_snapshot_expired"


def test_missing_market_keeps_projection_adp_unavailable() -> None:
    config = LeagueConfig(teams=12, scoring="ppr")
    out, status = attach_live_adp(_projections(), config, pd.DataFrame())

    assert out["market_adp"].isna().all()
    assert status["available"] is False
    assert status["reason"] == "compatible_market_snapshot_unavailable"
