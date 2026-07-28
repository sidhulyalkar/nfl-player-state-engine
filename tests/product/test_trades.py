import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.product.schemas import (
    FantasyRoster,
    LeagueIdentity,
    LeagueSettings,
    LeagueSnapshot,
    RosterEntry,
    TradeAnalysisRequest,
    TradeAsset,
    TradeSide,
)
from player_state_engine.product.trades import analyze_trade, suggest_trades


def make_snapshot():
    return LeagueSnapshot(
        identity=LeagueIdentity(league_id="L", platform="demo", name="Demo", season=2026),
        settings=LeagueSettings(
            teams=2, season=2026, roster_positions=["QB", "RB", "WR", "TE", "FLEX"]
        ),
        rosters=[
            FantasyRoster(
                roster_id="1",
                team_name="A",
                players=[
                    RosterEntry(platform_player_id="q1", canonical_player_id="q1"),
                    RosterEntry(platform_player_id="r1", canonical_player_id="r1"),
                    RosterEntry(platform_player_id="w1", canonical_player_id="w1"),
                    RosterEntry(platform_player_id="w2", canonical_player_id="w2"),
                    RosterEntry(platform_player_id="t1", canonical_player_id="t1"),
                ],
            ),
            FantasyRoster(
                roster_id="2",
                team_name="B",
                players=[
                    RosterEntry(platform_player_id="q2", canonical_player_id="q2"),
                    RosterEntry(platform_player_id="r2", canonical_player_id="r2"),
                    RosterEntry(platform_player_id="r3", canonical_player_id="r3"),
                    RosterEntry(platform_player_id="w3", canonical_player_id="w3"),
                    RosterEntry(platform_player_id="t2", canonical_player_id="t2"),
                ],
            ),
        ],
    )


def projections():
    rows = []
    specs = {
        "q1": ("QB", 20),
        "r1": ("RB", 8),
        "w1": ("WR", 20),
        "w2": ("WR", 18),
        "t1": ("TE", 12),
        "q2": ("QB", 18),
        "r2": ("RB", 20),
        "r3": ("RB", 17),
        "w3": ("WR", 8),
        "t2": ("TE", 11),
    }
    for pid, (pos, val) in specs.items():
        rows.append(
            {
                "player_id": pid,
                "player_name": pid,
                "position": pos,
                "decision_value": val,
                "vorp": val,
                "floor_vorp": val - 4,
                "upside_vorp": val + 5,
                "uncertainty": 9,
                "season_points_q50": val,
            }
        )
    return pd.DataFrame(rows)


def test_trade_analysis_is_two_sided():
    request = TradeAnalysisRequest(
        league_id="L",
        side_a=TradeSide(roster_id="1", assets=[TradeAsset(player_id="w2")]),
        side_b=TradeSide(roster_id="2", assets=[TradeAsset(player_id="r3")]),
    )
    result = analyze_trade(
        make_snapshot(),
        projections(),
        request,
        LeagueConfig(
            teams=2, roster_slots={"QB": 1, "RB": 1, "WR": 1, "TE": 1, "FLEX": 1, "BENCH": 2}
        ),
    )
    assert result.side_a.roster_id == "1"
    assert result.side_b.roster_id == "2"
    assert 0 <= result.fairness_score <= 100


def test_suggest_trades_returns_valid_candidates():
    suggestions = suggest_trades(
        make_snapshot(),
        projections(),
        LeagueConfig(
            teams=2, roster_slots={"QB": 1, "RB": 1, "WR": 1, "TE": 1, "FLEX": 1, "BENCH": 2}
        ),
        roster_id="1",
        max_suggestions=3,
    )
    assert len(suggestions) <= 3
    assert all(item.trade.league_id == "L" for item in suggestions)
