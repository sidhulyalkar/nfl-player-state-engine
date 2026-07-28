from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from player_state_engine.data.io import write_table
from player_state_engine.product.schemas import (
    FantasyManager,
    FantasyRoster,
    LeagueIdentity,
    LeagueSettings,
    LeagueSnapshot,
    RosterEntry,
)
from player_state_engine.product.store import LeagueSnapshotStore

POSITIONS = ["QB", "RB", "RB", "WR", "WR", "WR", "TE"]
TEAM_NAMES = ["Neural Blitz", "Shasta Snowdogs", "Fourth & Chaos", "Bayesian Ballers"]
NFL_TEAMS = ["SF", "DET", "MIN", "DAL", "ATL", "BAL", "ARI", "TB"]


def seed_product_demo(root: str | Path = ".", seed: int = 42) -> dict[str, Path]:
    root = Path(root)
    rng = np.random.default_rng(seed)
    managers: list[FantasyManager] = []
    rosters: list[FantasyRoster] = []
    rows: list[dict[str, object]] = []
    player_index = 0
    for roster_index, team_name in enumerate(TEAM_NAMES, start=1):
        manager_id = f"manager-{roster_index}"
        managers.append(
            FantasyManager(
                manager_id=manager_id, display_name=f"Manager {roster_index}", team_name=team_name
            )
        )
        entries: list[RosterEntry] = []
        for slot_index, position in enumerate(POSITIONS):
            player_index += 1
            player_id = f"demo-{player_index:03d}"
            median = float(
                {"QB": 290, "RB": 205, "WR": 190, "TE": 145}[position] + rng.normal(0, 28)
            )
            width = float(rng.uniform(55, 95))
            entries.append(
                RosterEntry(
                    platform_player_id=player_id,
                    canonical_player_id=player_id,
                    player_name=f"Demo {position} {player_index}",
                    position=position,
                    nfl_team=NFL_TEAMS[player_index % len(NFL_TEAMS)],
                    is_starter=slot_index < 6,
                )
            )
            rows.append(_projection_row(player_id, position, median, width, rng, owner=team_name))
        rosters.append(
            FantasyRoster(
                roster_id=str(roster_index),
                manager_id=manager_id,
                team_name=team_name,
                players=entries,
                wins=7 - roster_index,
                losses=roster_index + 1,
                points_for=980 - roster_index * 35,
                points_against=870 + roster_index * 22,
                faab_remaining=100 - roster_index * 9,
            )
        )

    free_agents: list[RosterEntry] = []
    for position in ("QB", "RB", "RB", "WR", "WR", "TE", "TE", "WR"):
        player_index += 1
        player_id = f"demo-{player_index:03d}"
        median = float({"QB": 235, "RB": 145, "WR": 135, "TE": 105}[position] + rng.normal(0, 20))
        width = float(rng.uniform(60, 110))
        free_agents.append(
            RosterEntry(
                platform_player_id=player_id,
                canonical_player_id=player_id,
                player_name=f"Free {position} {player_index}",
                position=position,
                nfl_team=NFL_TEAMS[player_index % len(NFL_TEAMS)],
            )
        )
        rows.append(_projection_row(player_id, position, median, width, rng, owner=None))

    snapshot = LeagueSnapshot(
        identity=LeagueIdentity(
            league_id="demo-league", platform="demo", name="Fourth Down Demo", season=2026
        ),
        settings=LeagueSettings(
            teams=len(rosters),
            season=2026,
            current_week=8,
            scoring={"rec": 1.0, "pass_yd": 0.04, "pass_td": 4.0},
            roster_positions=["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "BN", "BN"],
            playoff_week_start=15,
            faab_budget=100,
        ),
        managers=managers,
        rosters=rosters,
        free_agents=free_agents,
    )
    store_path = LeagueSnapshotStore(root / "data/product/leagues").save(snapshot)
    values = pd.DataFrame(rows)
    values_path = write_table(values, root / "artifacts/predictions/product_player_values.csv")
    schedules = pd.DataFrame(_demo_schedule_rows(rng))
    schedules_path = write_table(schedules, root / "data/raw/nflverse/schedules.csv")
    return {"league": store_path, "player_values": values_path, "schedules": schedules_path}


def _projection_row(
    player_id: str,
    position: str,
    season_median: float,
    width: float,
    rng: np.random.Generator,
    *,
    owner: str | None,
) -> dict[str, object]:
    week_median = season_median / 15.5
    return {
        "player_id": player_id,
        "platform_player_id": player_id,
        "player_name": f"{position} {player_id}",
        "position": position,
        "recent_team": NFL_TEAMS[int(player_id[-3:]) % len(NFL_TEAMS)],
        "season_points_q10": max(0.0, season_median - width),
        "season_points_q50": season_median,
        "season_points_q90": season_median + width,
        "fantasy_points_ppr_q10": max(0.0, week_median - width / 18),
        "fantasy_points_ppr_q50": week_median,
        "fantasy_points_ppr_q90": week_median + width / 16,
        "availability_probability": float(rng.uniform(0.82, 0.99)),
        "opportunity_confidence": float(rng.uniform(0.45, 0.92)),
        "role_growth_score": float(rng.normal(0.1 if owner is None else 0.0, 0.25)),
        "schedule_score": float(rng.normal(0, 0.35)),
        "scheme_fit_score": float(rng.uniform(0.25, 0.9)),
        "breakout_probability": float(rng.uniform(0.08, 0.65 if owner is None else 0.35)),
        "age": int(rng.integers(21, 31)),
        "prospect_prior_score": float(rng.uniform(0, 0.75)),
        "market_cost": float(rng.uniform(0, 45)),
    }


def _demo_schedule_rows(rng: np.random.Generator) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    teams = NFL_TEAMS
    for week in range(1, 9):
        rotated = teams[week % len(teams) :] + teams[: week % len(teams)]
        for index in range(0, len(rotated), 2):
            home, away = rotated[index], rotated[index + 1]
            rows.append(
                {
                    "season": 2026,
                    "week": week,
                    "game_type": "REG",
                    "home_team": home,
                    "away_team": away,
                    "home_score": int(rng.integers(14, 38)),
                    "away_score": int(rng.integers(10, 35)),
                }
            )
    return rows
