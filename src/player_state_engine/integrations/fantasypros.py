from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from player_state_engine.fantasy.rankings import normalize_ranking_frame

_BASE_URL = "https://api.fantasypros.com/public/v2/json"


def _httpx():
    try:
        import httpx
    except ImportError as exc:
        raise RuntimeError(
            'FantasyPros API support requires the intelligence extras: pip install -e ".[intelligence]"'
        ) from exc
    return httpx


def _position_rank_number(value: object) -> float | None:
    if value is None:
        return None
    match = re.search(r"(\d+)", str(value))
    return float(match.group(1)) if match else None


class FantasyProsClient:
    """Thin client for FantasyPros' documented public v2 API.

    Raw responses are never treated as model truth. Ranking calls normalize into the repository's
    timestamped external-ranking schema so they can be used for consensus audits, format-delta
    validation and market-survival features without contaminating football projections.
    """

    def __init__(
        self,
        api_key: str | None = None,
        *,
        api_key_env: str = "PSE_FANTASYPROS_API_KEY",
        timeout_seconds: float = 20.0,
    ) -> None:
        self.api_key = api_key or os.getenv(api_key_env)
        self.timeout_seconds = float(timeout_seconds)
        if not self.api_key:
            raise RuntimeError(
                f"FantasyPros API key not configured. Set {api_key_env} or pass api_key explicitly."
            )

    def _get(self, path: str, params: dict[str, object | None]) -> dict[str, Any]:
        httpx = _httpx()
        clean_params = {key: value for key, value in params.items() if value is not None}
        response = httpx.get(
            f"{_BASE_URL}/{path.lstrip('/')}",
            params=clean_params,
            headers={"x-api-key": self.api_key, "accept": "application/json"},
            timeout=self.timeout_seconds,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("FantasyPros returned a non-object JSON response.")
        return payload

    def fetch_consensus_rankings(
        self,
        season: int,
        *,
        position: str = "ALL",
        scoring: str = "HALF",
        ranking_type: str | None = None,
        week: int = 0,
        experts: bool = True,
        filters: str | None = None,
        teams: int | None = None,
        qb_format_name: str = "unknown",
        source_weight: float = 1.0,
    ) -> tuple[pd.DataFrame, dict[str, object]]:
        params: dict[str, object | None] = {
            "position": position.upper(),
            "scoring": scoring.upper(),
            "week": int(week),
            "experts": "show" if experts else None,
            "filters": filters,
        }
        if ranking_type:
            params["type"] = ranking_type.upper()
        payload = self._get(f"nfl/{int(season)}/consensus-rankings", params)
        players = payload.get("players") or []
        if not isinstance(players, list):
            raise ValueError("FantasyPros consensus response did not contain a players list.")
        raw = pd.DataFrame(players)
        if raw.empty:
            normalized = normalize_ranking_frame(
                raw,
                source="fantasypros_ecr",
                source_kind="expert",
                ranking_type=(ranking_type or str(payload.get("type") or "draft")),
                scoring=scoring.lower(),
                teams=teams,
                qb_format_name=qb_format_name,
                captured_at_utc=datetime.now(UTC),
                source_url=f"{_BASE_URL}/nfl/{int(season)}/consensus-rankings",
            )
            return normalized, {"count": 0, "total_experts": 0}

        prepared = pd.DataFrame(index=raw.index)
        prepared["source_player_id"] = raw.get("player_id")
        prepared["player_name"] = raw.get("player_name")
        prepared["position"] = raw.get("player_position_id", raw.get("player_positions"))
        prepared["nfl_team"] = raw.get("player_team_id")
        prepared["rank"] = raw.get("rank_ecr")
        prepared["position_rank"] = (
            raw.get("pos_rank", pd.Series(index=raw.index, dtype=object)).map(_position_rank_number)
        )
        prepared["rank_min"] = raw.get("rank_min")
        prepared["rank_max"] = raw.get("rank_max")
        prepared["rank_std"] = raw.get("rank_std")
        prepared["expert_count"] = payload.get("total_experts")
        resolved_type = str(ranking_type or payload.get("type") or "draft").lower()
        source = "fantasypros_adp" if resolved_type == "adp" else "fantasypros_ecr"
        source_kind = "market" if resolved_type == "adp" else "expert"
        captured = datetime.now(UTC)
        if payload.get("last_updated_ts"):
            try:
                captured = datetime.fromtimestamp(float(payload["last_updated_ts"]), tz=UTC)
            except (TypeError, ValueError, OSError):
                pass
        normalized = normalize_ranking_frame(
            prepared,
            source=source,
            source_kind=source_kind,
            ranking_type=resolved_type,
            scoring=scoring.lower(),
            teams=teams,
            qb_format_name=qb_format_name,
            source_weight=source_weight,
            captured_at_utc=captured,
            source_url=f"{_BASE_URL}/nfl/{int(season)}/consensus-rankings",
        )
        metadata = {
            "count": int(payload.get("count") or len(normalized)),
            "total_experts": int(payload.get("total_experts") or 0),
            "last_updated": payload.get("last_updated"),
            "last_updated_ts": payload.get("last_updated_ts"),
            "filters": payload.get("filters"),
            "position": position.upper(),
            "scoring": scoring.upper(),
            "ranking_type": resolved_type,
            "expert_publication_times": payload.get("expert_pub") or {},
        }
        return normalized, metadata

    def fetch_expert_accuracy(
        self,
        season: int,
        *,
        position: str | None = None,
        scoring: str | None = None,
        ranking_type: str | None = None,
        include_overall: bool = True,
    ) -> tuple[pd.DataFrame, dict[str, object]]:
        payload = self._get(
            f"nfl/{int(season)}/rankings/experts",
            {
                "position": position.upper() if position else None,
                "scoring": scoring.upper() if scoring else None,
                "type": ranking_type.upper() if ranking_type else None,
                "include_overall": "true" if include_overall else None,
            },
        )
        experts = payload.get("experts") or []
        if isinstance(experts, dict):
            experts = list(experts.values())
        frame = pd.DataFrame(experts) if isinstance(experts, list) else pd.DataFrame()
        metadata = {
            "count": int(payload.get("count") or len(frame)),
            "accuracy_weekly_season": payload.get("accuracy_weekly_season"),
            "accuracy_draft_season": payload.get("accuracy_draft_season"),
            "position": position,
            "scoring": scoring,
            "ranking_type": ranking_type,
        }
        return frame, metadata
