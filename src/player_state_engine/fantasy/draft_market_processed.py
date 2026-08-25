from __future__ import annotations

import pandas as pd


def resolve_processed_player_identity(frame: pd.DataFrame) -> pd.DataFrame:
    """Resolve the downstream draft player ID without discarding raw platform identity."""

    if frame.empty:
        output = frame.copy()
        if "player_id" not in output:
            output["player_id"] = pd.Series(dtype=str)
        return output

    required = {"canonical_player_id", "platform_player_id"}
    missing = sorted(required - set(frame.columns))
    if missing:
        raise ValueError(f"Normalized draft archive is missing identity columns: {missing}")

    output = frame.copy()
    canonical = output["canonical_player_id"].where(output["canonical_player_id"].notna(), None)
    platform = output["platform_player_id"].where(output["platform_player_id"].notna(), None)
    output["player_id"] = canonical.combine_first(platform)
    if output["player_id"].isna().any():
        raise ValueError("Normalized Sleeper draft archive contains picks without player identity")
    output["player_id"] = output["player_id"].astype(str)
    return output
