from __future__ import annotations

import numpy as np
import pandas as pd

from player_state_engine.product.schemas import LeagueSnapshot


def attach_ownership(projections: pd.DataFrame, snapshot: LeagueSnapshot) -> pd.DataFrame:
    data = projections.copy()
    owner_by_external: dict[str, tuple[str, str]] = {}
    owner_by_canonical: dict[str, tuple[str, str]] = {}
    for roster in snapshot.rosters:
        for player in roster.players:
            owner_by_external[player.platform_player_id] = (roster.roster_id, roster.team_name)
            if player.canonical_player_id:
                owner_by_canonical[player.canonical_player_id] = (
                    roster.roster_id,
                    roster.team_name,
                )

    platform_id = data.get("platform_player_id", pd.Series("", index=data.index)).astype(str)
    canonical_id = data.get("player_id", pd.Series("", index=data.index)).astype(str)
    owners: list[tuple[str | None, str | None]] = []
    for external, canonical in zip(platform_id, canonical_id, strict=True):
        owners.append(
            owner_by_external.get(external) or owner_by_canonical.get(canonical) or (None, None)
        )
    data["owner_roster_id"] = [owner[0] for owner in owners]
    data["owner_team_name"] = [owner[1] for owner in owners]
    data["is_free_agent"] = data["owner_roster_id"].isna()
    return data


def league_power_rankings(snapshot: LeagueSnapshot, player_values: pd.DataFrame) -> pd.DataFrame:
    """Build an interpretable league-wide roster strength table.

    The function expects player_values to contain player_id, decision_value, floor_vorp,
    upside_vorp and position. It falls back conservatively when optional columns are absent.
    """
    values = player_values.copy()
    if "player_id" not in values:
        raise ValueError("player_values requires player_id")
    values["player_id"] = values["player_id"].astype(str)
    lookup = values.set_index("player_id")
    rows: list[dict[str, object]] = []
    for roster in snapshot.rosters:
        ids = [
            str(entry.canonical_player_id or entry.platform_player_id) for entry in roster.players
        ]
        matched = lookup.reindex(ids).dropna(how="all")
        decision = pd.to_numeric(
            matched.get("decision_value", pd.Series(dtype=float)), errors="coerce"
        ).fillna(0.0)
        floor = pd.to_numeric(
            matched.get("floor_vorp", pd.Series(dtype=float)), errors="coerce"
        ).fillna(0.0)
        ceiling = pd.to_numeric(
            matched.get("upside_vorp", pd.Series(dtype=float)), errors="coerce"
        ).fillna(0.0)
        uncertainty = pd.to_numeric(
            matched.get("uncertainty", pd.Series(dtype=float)), errors="coerce"
        ).fillna(0.0)
        positions = matched.get("position", pd.Series(dtype=str)).astype(str)
        position_depth = {
            position: float(decision.loc[positions.eq(position)].nlargest(3).sum())
            for position in ("QB", "RB", "WR", "TE")
        }
        rows.append(
            {
                "roster_id": roster.roster_id,
                "team_name": roster.team_name,
                "record": f"{roster.wins}-{roster.losses}-{roster.ties}",
                "points_for": roster.points_for,
                "points_against": roster.points_against,
                "roster_value": float(decision.sum()),
                "floor_value": float(floor.sum()),
                "ceiling_value": float(ceiling.sum()),
                "uncertainty": float(uncertainty.sum()),
                "qb_depth": position_depth["QB"],
                "rb_depth": position_depth["RB"],
                "wr_depth": position_depth["WR"],
                "te_depth": position_depth["TE"],
            }
        )
    output = pd.DataFrame(rows)
    if output.empty:
        return output
    output["power_score"] = (
        0.45 * output["roster_value"].rank(pct=True)
        + 0.20 * output["floor_value"].rank(pct=True)
        + 0.20 * output["ceiling_value"].rank(pct=True)
        + 0.15 * output["points_for"].rank(pct=True)
    ) * 100
    output["risk_score"] = output["uncertainty"].rank(pct=True) * 100
    return output.sort_values("power_score", ascending=False).reset_index(drop=True)


def roster_needs(snapshot: LeagueSnapshot, player_values: pd.DataFrame) -> pd.DataFrame:
    values = attach_ownership(player_values, snapshot)
    if "decision_value" not in values:
        raise ValueError("player_values requires decision_value")
    position_reference = values.groupby("position")["decision_value"].quantile(0.60).to_dict()
    rows: list[dict[str, object]] = []
    for roster in snapshot.rosters:
        owned = values.loc[values["owner_roster_id"].eq(roster.roster_id)]
        for position in ("QB", "RB", "WR", "TE"):
            position_values = owned.loc[owned["position"].eq(position), "decision_value"].nlargest(
                3
            )
            strength = float(position_values.mean()) if len(position_values) else 0.0
            reference = float(position_reference.get(position, 0.0))
            need = reference - strength
            rows.append(
                {
                    "roster_id": roster.roster_id,
                    "team_name": roster.team_name,
                    "position": position,
                    "position_strength": strength,
                    "league_reference": reference,
                    "need_score": float(np.clip(need, -100, 100)),
                    "need_percentile": 0.0,
                }
            )
    output = pd.DataFrame(rows)
    if not output.empty:
        output["need_percentile"] = output.groupby("position")["need_score"].rank(pct=True)
        output["strength_rank"] = (
            output.groupby("position")["position_strength"]
            .rank(method="first", ascending=False)
            .astype(int)
        )
        output["need_rank"] = (
            output.groupby("position")["need_score"]
            .rank(method="first", ascending=False)
            .astype(int)
        )
    return output.sort_values(["roster_id", "need_score"], ascending=[True, False]).reset_index(
        drop=True
    )
