from __future__ import annotations

import pandas as pd

from player_state_engine.features.weekly import build_weekly_features, merge_schedule_context


def test_nonempty_schedule_without_optional_context_gets_safe_defaults() -> None:
    stats = pd.DataFrame(
        [
            {
                "season": 2026,
                "week": 1,
                "game_id": "2026_01_AAA_BBB",
                "player_id": "p1",
                "player_name": "Player One",
                "team": "AAA",
                "position": "WR",
                "targets": 5,
                "receptions": 3,
                "receiving_yards": 40,
                "fantasy_points_ppr": 10.0,
            }
        ]
    )
    schedules = pd.DataFrame(
        [
            {
                "season": 2026,
                "week": 1,
                "game_id": "2026_01_AAA_BBB",
                "away_team": "AAA",
                "home_team": "BBB",
            }
        ]
    )

    canonical = stats.rename(columns={"team": "recent_team"})
    merged = merge_schedule_context(canonical, schedules)
    assert merged.loc[0, "roof"] == "unknown"
    assert merged.loc[0, "surface"] == "unknown"
    assert pd.isna(merged.loc[0, "spread_line"])
    assert pd.isna(merged.loc[0, "total_line"])

    featured = build_weekly_features(stats, schedules)
    assert featured.loc[0, "is_dome"] == 0
    assert featured.loc[0, "is_grass"] == 0
