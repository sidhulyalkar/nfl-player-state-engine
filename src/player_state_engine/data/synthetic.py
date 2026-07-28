from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from player_state_engine.data.io import write_table

POSITIONS = ("QB", "RB", "WR", "WR", "TE", "K", "DST")
TEAMS = ("ARI", "ATL", "BAL", "BUF", "CAR", "CHI", "CIN", "CLE")


@dataclass(slots=True)
class SyntheticDataset:
    player_stats: pd.DataFrame
    schedules: pd.DataFrame
    rosters: pd.DataFrame


def _round_robin_pairs(teams: tuple[str, ...], week: int) -> list[tuple[str, str]]:
    rotation = list(teams)
    steps = (week - 1) % (len(teams) - 1)
    for _ in range(steps):
        rotation = [rotation[0], rotation[-1], *rotation[1:-1]]
    pairs: list[tuple[str, str]] = []
    half = len(rotation) // 2
    for i in range(half):
        away = rotation[i]
        home = rotation[-(i + 1)]
        if week % 2 == 0:
            away, home = home, away
        pairs.append((away, home))
    return pairs


def _fantasy_points(row: dict[str, float]) -> float:
    return float(
        row.get("passing_yards", 0.0) / 25.0
        + 4.0 * row.get("passing_tds", 0.0)
        - 2.0 * row.get("interceptions", 0.0)
        + row.get("rushing_yards", 0.0) / 10.0
        + 6.0 * row.get("rushing_tds", 0.0)
        + row.get("receiving_yards", 0.0) / 10.0
        + 6.0 * row.get("receiving_tds", 0.0)
        + row.get("receptions", 0.0)
    )


def generate_synthetic_dataset(
    seasons: tuple[int, ...] = (2023, 2024),
    weeks_per_season: int = 12,
    seed: int = 42,
) -> SyntheticDataset:
    rng = np.random.default_rng(seed)
    team_attack = {team: rng.normal(0.0, 0.45) for team in TEAMS}
    team_defense = {team: rng.normal(0.0, 0.35) for team in TEAMS}
    player_talent: dict[str, float] = {}
    rosters: list[dict[str, object]] = []

    for team in TEAMS:
        counts: dict[str, int] = {}
        for position in POSITIONS:
            counts[position] = counts.get(position, 0) + 1
            suffix = counts[position]
            player_id = f"{team}_{position}{suffix}"
            player_talent[player_id] = rng.normal(0.0, 0.55)
            rosters.append(
                {
                    "player_id": player_id,
                    "gsis_id": player_id,
                    "player_name": player_id.replace("_", " "),
                    "full_name": player_id.replace("_", " "),
                    "recent_team": team,
                    "team": team,
                    "position": position,
                    "status": "ACT",
                }
            )

    schedule_rows: list[dict[str, object]] = []
    stat_rows: list[dict[str, object]] = []

    for season in seasons:
        seasonal_shift = rng.normal(0.0, 0.12, len(TEAMS))
        season_attack = {
            team: team_attack[team] + seasonal_shift[i] for i, team in enumerate(TEAMS)
        }
        for week in range(1, weeks_per_season + 1):
            for away, home in _round_robin_pairs(TEAMS, week):
                home_edge = 0.15
                matchup = season_attack[home] - season_attack[away]
                spread_line = float(np.clip(-3.0 - 4.0 * matchup + rng.normal(0, 1.5), -14, 14))
                total_line = float(
                    np.clip(
                        45 + 3 * (season_attack[home] + season_attack[away]) + rng.normal(0, 2),
                        34,
                        58,
                    )
                )
                game_id = f"{season}_{week:02d}_{away}_{home}"
                schedule_rows.append(
                    {
                        "game_id": game_id,
                        "season": season,
                        "week": week,
                        "game_type": "REG",
                        "gameday": pd.Timestamp(season, 9, 1) + pd.Timedelta(days=(week - 1) * 7),
                        "away_team": away,
                        "home_team": home,
                        "spread_line": spread_line,
                        "total_line": total_line,
                        "away_rest": 7,
                        "home_rest": 7,
                        "roof": rng.choice(["outdoors", "dome", "closed"], p=[0.65, 0.2, 0.15]),
                        "surface": rng.choice(["grass", "fieldturf"], p=[0.55, 0.45]),
                        "temp": float(rng.normal(61, 14)),
                        "wind": float(abs(rng.normal(8, 5))),
                    }
                )

                for team, opponent, is_home in ((away, home, 0), (home, away, 1)):
                    game_environment = (
                        season_attack[team]
                        - 0.6 * team_defense[opponent]
                        + home_edge * is_home
                        + rng.normal(0, 0.22)
                    )
                    team_roster = [r for r in rosters if r["team"] == team]
                    for player in team_roster:
                        pid = str(player["player_id"])
                        pos = str(player["position"])
                        talent = player_talent[pid]
                        row: dict[str, float | int | str] = {
                            "season": season,
                            "week": week,
                            "season_type": "REG",
                            "game_id": game_id,
                            "player_id": pid,
                            "player_name": str(player["player_name"]),
                            "recent_team": team,
                            "opponent_team": opponent,
                            "position": pos,
                            "passing_attempts": 0.0,
                            "attempts": 0.0,
                            "completions": 0.0,
                            "passing_yards": 0.0,
                            "passing_tds": 0.0,
                            "interceptions": 0.0,
                            "carries": 0.0,
                            "rushing_yards": 0.0,
                            "rushing_tds": 0.0,
                            "targets": 0.0,
                            "receptions": 0.0,
                            "receiving_yards": 0.0,
                            "receiving_tds": 0.0,
                            "receiving_air_yards": 0.0,
                            "receiving_yards_after_catch": 0.0,
                            "target_share": 0.0,
                            "air_yards_share": 0.0,
                            "snap_count": 0.0,
                            "route_count": 0.0,
                        }
                        availability = rng.random() > 0.035
                        if not availability:
                            row["fantasy_points_ppr"] = 0.0
                            stat_rows.append(row)
                            continue

                        if pos == "QB":
                            attempts = max(12, rng.normal(32 + 3 * game_environment, 5))
                            completion_rate = np.clip(
                                0.64 + 0.035 * talent + 0.02 * game_environment, 0.48, 0.78
                            )
                            completions = rng.binomial(round(attempts), completion_rate)
                            pass_yards = max(
                                40, completions * max(7.0, rng.normal(10.5 + talent, 1.2))
                            )
                            row.update(
                                {
                                    "passing_attempts": attempts,
                                    "attempts": attempts,
                                    "completions": completions,
                                    "passing_yards": pass_yards,
                                    "passing_tds": rng.poisson(
                                        max(0.3, 1.5 + 0.35 * game_environment + 0.2 * talent)
                                    ),
                                    "interceptions": rng.poisson(max(0.1, 0.65 - 0.08 * talent)),
                                    "carries": max(0, rng.normal(4 + talent, 2)),
                                    "rushing_yards": max(0, rng.normal(17 + 8 * talent, 12)),
                                    "rushing_tds": rng.binomial(
                                        1, np.clip(0.06 + 0.025 * talent, 0.01, 0.2)
                                    ),
                                    "snap_count": max(40, rng.normal(65, 5)),
                                }
                            )
                        elif pos == "RB":
                            carries = max(1, rng.normal(13 + 3 * talent + 2 * game_environment, 4))
                            targets = max(0, rng.normal(3.3 + talent, 1.8))
                            receptions = rng.binomial(
                                round(targets), np.clip(0.72 + 0.03 * talent, 0.5, 0.9)
                            )
                            row.update(
                                {
                                    "carries": carries,
                                    "rushing_yards": max(
                                        0,
                                        carries * max(2.2, rng.normal(4.25 + 0.35 * talent, 0.65)),
                                    ),
                                    "rushing_tds": rng.poisson(
                                        max(0.04, 0.35 + 0.12 * game_environment + 0.08 * talent)
                                    ),
                                    "targets": targets,
                                    "receptions": receptions,
                                    "receiving_yards": max(
                                        0, receptions * max(3.0, rng.normal(7.2 + talent, 1.5))
                                    ),
                                    "receiving_tds": rng.binomial(
                                        1, np.clip(0.04 + 0.02 * talent, 0.01, 0.15)
                                    ),
                                    "receiving_air_yards": max(
                                        0, targets * max(1.0, rng.normal(3.8, 1.5))
                                    ),
                                    "receiving_yards_after_catch": max(
                                        0, receptions * max(2.0, rng.normal(6.2, 1.1))
                                    ),
                                    "snap_count": max(15, rng.normal(42 + 7 * talent, 8)),
                                    "route_count": max(5, rng.normal(20 + 4 * talent, 5)),
                                }
                            )
                        elif pos in {"WR", "TE"}:
                            role = 1.0 if pos == "WR" else 0.72
                            targets = max(
                                0, rng.normal((6.5 + 2.1 * talent + game_environment) * role, 2.4)
                            )
                            catch_rate = np.clip(
                                0.64 + 0.04 * talent + (0.05 if pos == "TE" else 0), 0.42, 0.86
                            )
                            receptions = rng.binomial(round(targets), catch_rate)
                            adot = max(
                                4.0, rng.normal((11.5 + 1.4 * talent) if pos == "WR" else 8.0, 2.0)
                            )
                            row.update(
                                {
                                    "targets": targets,
                                    "receptions": receptions,
                                    "receiving_yards": max(
                                        0, receptions * max(4.0, rng.normal(adot * 0.95, 2.0))
                                    ),
                                    "receiving_tds": rng.poisson(
                                        max(0.02, 0.24 + 0.08 * game_environment + 0.05 * talent)
                                    ),
                                    "receiving_air_yards": max(0, targets * adot),
                                    "receiving_yards_after_catch": max(
                                        0, receptions * max(1.5, rng.normal(4.8, 1.2))
                                    ),
                                    "carries": rng.binomial(2, 0.07 if pos == "WR" else 0.02),
                                    "rushing_yards": max(0, rng.normal(3, 6)),
                                    "snap_count": max(15, rng.normal(48 + 6 * talent, 8)),
                                    "route_count": max(5, rng.normal(31 + 5 * talent, 6)),
                                }
                            )
                        elif pos == "K":
                            row.update({"snap_count": rng.normal(9, 2)})
                        else:
                            row.update({"snap_count": rng.normal(62, 5)})

                        row["target_share"] = float(row["targets"]) / max(
                            1.0, 33 + 3 * game_environment
                        )
                        row["air_yards_share"] = float(row["receiving_air_yards"]) / max(
                            1.0, 320 + 25 * game_environment
                        )
                        row["fantasy_points_ppr"] = _fantasy_points(row) + rng.normal(0, 0.25)
                        row["fantasy_points"] = float(row["fantasy_points_ppr"]) - float(
                            row["receptions"]
                        )
                        stat_rows.append(row)

    stats = pd.DataFrame(stat_rows)
    schedules = pd.DataFrame(schedule_rows)
    roster_frame = pd.DataFrame(rosters)
    return SyntheticDataset(stats, schedules, roster_frame)


def write_synthetic_dataset(output_dir: str | Path, **kwargs: object) -> SyntheticDataset:
    output_dir = Path(output_dir)
    dataset = generate_synthetic_dataset(**kwargs)
    write_table(dataset.player_stats, output_dir / "player_stats.csv")
    write_table(dataset.schedules, output_dir / "schedules.csv")
    write_table(dataset.rosters, output_dir / "rosters.csv")
    return dataset
