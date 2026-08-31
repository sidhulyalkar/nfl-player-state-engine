from __future__ import annotations

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig


def select_projection_scoring_contract(
    projections: pd.DataFrame,
    config: LeagueConfig,
    *,
    require_explicit_contract: bool = False,
) -> pd.DataFrame:
    """Select exactly one league-scoring slice from a shared projection artifact.

    A production artifact may contain one row per ``(scoring_contract_id, player_id)`` so the
    application can keep a single configured file while serving several fantasy scoring systems.
    Contract selection must happen before readiness, identity coverage, VORP, scarcity, room
    simulation, or candidate comparison. Otherwise the same player legitimately appears more than
    once in the shared artifact and can be mistaken for a duplicate projection.

    Legacy single-contract development artifacts without ``scoring_contract_id`` remain readable
    unless the caller explicitly requires a contract-bearing production artifact. Once the column
    exists, however, there is no fallback: the requested scoring fingerprint must be present and
    unique by player identity.
    """

    data = projections.copy()
    expected = config.scoring_contract_id
    if data.empty:
        return data

    if "scoring_contract_id" not in data:
        if require_explicit_contract:
            raise ValueError(
                "Projection artifact does not declare scoring_contract_id; exact multicontract "
                f"serving requires {expected}."
            )
        return data.reset_index(drop=True)

    contract_ids = data["scoring_contract_id"].astype("string").str.strip()
    selected = data.loc[contract_ids.eq(expected)].copy()
    if selected.empty:
        available = tuple(
            sorted(
                set(
                    contract_ids.loc[contract_ids.notna() & contract_ids.ne("")].astype(str)
                )
            )
        )
        raise ValueError(
            "Projection artifact does not contain the requested scoring contract "
            f"{expected}; available={list(available)}"
        )

    selected["scoring_contract_id"] = expected
    if "player_id" in selected:
        player_ids = selected["player_id"].astype("string").str.strip()
        invalid = player_ids.isna() | player_ids.eq("")
        if invalid.any():
            raise ValueError("Selected scoring contract contains missing player_id values.")
        duplicated = player_ids.duplicated(keep=False)
        if duplicated.any():
            examples = tuple(sorted(set(player_ids.loc[duplicated].astype(str))))[:5]
            raise ValueError(
                "Selected scoring contract contains duplicate player_id rows: "
                f"{list(examples)}"
            )

    return selected.reset_index(drop=True)
