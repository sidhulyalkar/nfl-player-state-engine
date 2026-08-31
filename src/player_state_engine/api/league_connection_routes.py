from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from player_state_engine.product.draft_day_doctor_adapter import is_real_league_summary
from player_state_engine.product.league_connections import (
    LeagueConnectionService,
    LeaguePortfolioExpectationStore,
)

try:
    from fastapi import FastAPI, HTTPException
except ImportError as exc:  # pragma: no cover
    raise RuntimeError("Install the API extras: python -m pip install -e '.[api]'") from exc


class LeagueConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    platform: Literal["sleeper", "espn"]
    league_id: str = Field(min_length=1, max_length=64)
    season: int = Field(default=2026, ge=2000, le=2100)
    external_user_id: str | None = Field(default=None, max_length=128)
    include_free_agents: bool = True


class LeaguePortfolioExpectationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_league_count: int = Field(ge=1, le=20)


def install_league_connection_routes(
    app: FastAPI,
    *,
    draft_service: object,
    portfolio_path: str | Path | None = None,
) -> LeagueConnectionService:
    """Install the local-only real-league onboarding boundary.

    ESPN cookies are intentionally absent from the request schema. Private ESPN authentication is
    resolved only from PSE_ESPN_S2/PSE_ESPN_SWID in the API process environment.
    """

    store = getattr(draft_service, "store", None)
    service = LeagueConnectionService(store=store)
    expectations = LeaguePortfolioExpectationStore(portfolio_path)

    def portfolio_payload() -> dict[str, object]:
        try:
            all_connections = [dict(item) for item in getattr(draft_service, "list_leagues")()]
        except Exception as exc:  # noqa: BLE001 - operator endpoint should surface store failure.
            raise HTTPException(
                status_code=503,
                detail=f"League snapshot store could not be enumerated: {exc}",
            ) from exc
        connections = [item for item in all_connections if is_real_league_summary(item)]
        connected_ids = {
            str(item.get("league_id"))
            for item in connections
            if item.get("league_id") not in {None, ""}
        }
        expected = expectations.expected_count()
        connected = len(connected_ids)
        missing = max(0, expected - connected) if expected is not None else None
        return {
            "expected_league_count": expected,
            "connected_league_count": connected,
            "missing_league_count": missing,
            "complete": bool(expected is not None and connected >= expected),
            "connections": connections,
            "ignored_non_real_snapshot_count": len(all_connections) - len(connections),
            "supported_platforms": ["sleeper", "espn"],
            "espn_private_auth_configured": bool(
                os.getenv("PSE_ESPN_S2") and os.getenv("PSE_ESPN_SWID")
            ),
            "credential_contract": (
                "ESPN credentials are server-side environment variables only; "
                "the browser never sends or receives cookie values."
            ),
        }

    @app.get("/v1/draft/connections")
    def list_connections() -> dict[str, object]:
        return portfolio_payload()

    @app.put("/v1/draft/connections/expectation")
    def set_portfolio_expectation(
        request: LeaguePortfolioExpectationRequest,
    ) -> dict[str, object]:
        try:
            expectations.save_expected_count(request.expected_league_count)
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return portfolio_payload()

    @app.post("/v1/draft/connections")
    def connect_league(payload: dict[str, object]) -> dict[str, object]:
        allowed = set(LeagueConnectionRequest.model_fields)
        if set(payload) - allowed:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Unsupported league connection fields. Platform credentials must remain "
                    "server-side environment variables."
                ),
            )
        try:
            request = LeagueConnectionRequest.model_validate(payload)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail="Invalid league connection request.") from exc

        try:
            result = service.connect(
                platform=request.platform,
                league_id=request.league_id,
                season=request.season,
                external_user_id=request.external_user_id,
                include_free_agents=request.include_free_agents,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except RuntimeError as exc:
            message = str(exc)
            status = 503 if "ESPN support requires" in message else 502
            raise HTTPException(status_code=status, detail=message) from exc
        except Exception as exc:  # noqa: BLE001 - third-party platform adapters vary by failure type.
            raise HTTPException(
                status_code=502,
                detail=(
                    "League import failed; no new snapshot was persisted and any prior valid "
                    f"snapshot was preserved: {exc}"
                ),
            ) from exc
        return {
            "connection": result.as_dict(),
            "portfolio": portfolio_payload(),
        }

    return service
