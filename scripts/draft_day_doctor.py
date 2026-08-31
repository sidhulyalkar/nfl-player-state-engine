from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from player_state_engine.api.market_draft_routes import MarketAwareDraftBoardService
from player_state_engine.product.draft_day_doctor import DraftDayDoctorService
from player_state_engine.product.draft_day_doctor_adapter import DoctorDraftServiceAdapter
from player_state_engine.product.draft_portfolio_doctor import PortfolioAwareDraftDayDoctor
from player_state_engine.product.league_connections import LeaguePortfolioExpectationStore
from player_state_engine.product.projection_artifact_source import (
    DEFAULT_PROJECTION_PATH,
    ProjectionArtifactSource,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Diagnose whether the verified champion, intended real-league portfolio, NFL Hub, "
            "K/DST market, and live ADP are operationally safe for the Draft War Room. "
            "This command is read-only."
        )
    )
    parser.add_argument("--league-id", default=None, help="Optionally diagnose one league only.")
    parser.add_argument("--json", action="store_true", help="Emit the complete machine-readable report.")
    args = parser.parse_args()

    source = ProjectionArtifactSource.from_environment()
    try:
        projection_path = source.resolved_path()
    except (OSError, KeyError, ValueError, PermissionError, RuntimeError):
        # Preserve diagnosis even when champion resolution itself is broken. The doctor will report
        # that failure authoritatively; this fallback is only a constructor path for draft_service.
        projection_path = Path(os.getenv("PSE_PROJECTIONS_PATH", str(DEFAULT_PROJECTION_PATH)))

    draft_service = DoctorDraftServiceAdapter(
        MarketAwareDraftBoardService(projections_path=projection_path)
    )
    base_doctor = DraftDayDoctorService(
        projection_source=source,
        draft_service=draft_service,
    )
    doctor = PortfolioAwareDraftDayDoctor(
        base_doctor,
        draft_service=draft_service,
        expectation_store=LeaguePortfolioExpectationStore(),
    )
    report = doctor.report(league_id=args.league_id)
    payload = report.as_dict()

    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True, default=str))
    else:
        print(f"Draft-Day Doctor: {report.status}")
        print(f"War Room usable: {'YES' if report.can_open_war_room else 'NO'}")
        for check in report.checks:
            print(f"[{check.status:11}] {check.code}: {check.detail}")
            if check.remediation and check.status != "READY":
                print(f"              -> {check.remediation}")
        for league in report.leagues:
            print(f"\n{league.league_name} ({league.platform}:{league.league_id}): {league.status}")
            for check in league.checks:
                print(f"  [{check.status:11}] {check.code}: {check.detail}")
                if check.remediation and check.status != "READY":
                    print(f"                -> {check.remediation}")

    if report.status == "BLOCKED":
        raise SystemExit(3)


if __name__ == "__main__":
    main()
