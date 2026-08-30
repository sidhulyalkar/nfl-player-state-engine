from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.product.release_readiness import assess_draft_release_readiness

NOW = datetime(2026, 9, 1, 16, 0, tzinfo=UTC)


def _config(*, scoring: str = "ppr", median: bool = False, special: bool = False) -> LeagueConfig:
    slots = {"QB": 1, "RB": 1, "WR": 1, "TE": 1}
    if special:
        slots.update({"DST": 1, "K": 1})
    return LeagueConfig(teams=1, scoring=scoring, median_scoring=median, roster_slots=slots)


def _players(config: LeagueConfig, policy: str) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for index, position in enumerate(("QB", "RB", "WR", "TE"), start=1):
        rows.append(
            {
                "player_id": f"{position}{index}",
                "player_name": f"{position} {index}",
                "position": position,
                "market_adp": float(index * 10),
                "season_points_q10": 80.0,
                "season_points_q50": 150.0,
                "season_points_q90": 220.0,
                "league_season_points_q10": 80.0,
                "league_season_points_q50": 150.0,
                "league_season_points_q90": 220.0,
                "league_scoring_exact": True,
                "decision_quantile_policy": policy,
                "scoring_contract_id": config.scoring_contract_id,
            }
        )
    return pd.DataFrame(rows)


def _hub(*, generated_at: datetime | None = None, status: str = "READY") -> dict[str, object]:
    return {
        "authority": "observational_nfl_state_only",
        "status": status,
        "generated_at_utc": (generated_at or (NOW - timedelta(hours=1))).isoformat(),
        "required_source_failures": [],
        "optional_source_failures": [] if status == "READY" else ["injuries"],
        "market_identity": {
            "redraft_identity_coverage": 0.90,
            "usable_market_players": 1000,
        },
    }


def _special() -> dict[str, object]:
    return {
        "authority": "external_market_only",
        "generated_at_utc": (NOW - timedelta(hours=1)).isoformat(),
        "kicker_count": 32,
        "dst_count": 32,
        "model_fields_present": False,
    }


def _assess(
    projection_sets: dict[str, pd.DataFrame],
    metadata: dict[str, dict[str, object]],
    leagues: dict[str, LeagueConfig],
    **overrides: object,
):
    kwargs: dict[str, object] = {
        "bundle_authority": "production_approved",
        "bundle_integrity_verified": True,
        "projection_source_cutoff_utc": NOW - timedelta(hours=2),
        "nfl_hub_snapshot": _hub(),
        "now": NOW,
    }
    kwargs.update(overrides)
    return assess_draft_release_readiness(
        projection_sets,
        metadata,
        leagues,
        **kwargs,  # type: ignore[arg-type]
    )


def test_distinct_ppr_and_half_ppr_contracts_can_share_one_release_bundle() -> None:
    ppr = _config(scoring="ppr")
    half = _config(scoring="half_ppr")
    projections = {
        ppr.scoring_contract_id: _players(ppr, "qualified_distribution"),
        half.scoring_contract_id: _players(half, "q50_only"),
    }
    metadata = {
        ppr.scoring_contract_id: {
            "scoring_contract_id": ppr.scoring_contract_id,
            "decision_quantile_policy": "qualified_distribution",
        },
        half.scoring_contract_id: {
            "scoring_contract_id": half.scoring_contract_id,
            "decision_quantile_policy": "q50_only",
        },
    }

    report = _assess(projections, metadata, {"ppr": ppr, "half": half})

    assert report.status == "READY"
    assert report.can_use_core_draft_board is True
    assert {item.scoring_contract_id for item in report.leagues} == {
        ppr.scoring_contract_id,
        half.scoring_contract_id,
    }
    assert {item.decision_quantile_policy for item in report.leagues} == {
        "qualified_distribution",
        "q50_only",
    }


def test_missing_scoring_contract_cannot_fall_back_to_another_projection_slate() -> None:
    ppr = _config(scoring="ppr")
    half = _config(scoring="half_ppr")
    projections = {ppr.scoring_contract_id: _players(ppr, "qualified_distribution")}
    metadata = {
        ppr.scoring_contract_id: {
            "scoring_contract_id": ppr.scoring_contract_id,
            "decision_quantile_policy": "qualified_distribution",
        }
    }

    report = _assess(projections, metadata, {"ppr": ppr, "half": half})

    assert report.status == "BLOCKED"
    half_result = next(item for item in report.leagues if item.league == "half")
    assert half_result.blocking_reasons == ("SCORING_CONTRACT_PROJECTIONS_MISSING",)


def test_legacy_or_mixed_decision_policy_is_blocked() -> None:
    ppr = _config(scoring="ppr")
    frame = _players(ppr, "legacy_distribution")
    metadata = {
        ppr.scoring_contract_id: {
            "scoring_contract_id": ppr.scoring_contract_id,
            "decision_quantile_policy": "legacy_distribution",
        }
    }
    report = _assess({ppr.scoring_contract_id: frame}, metadata, {"ppr": ppr})
    assert report.status == "BLOCKED"
    assert "ppr:DECISION_QUANTILE_POLICY_UNQUALIFIED" in report.blocking_reasons

    frame.loc[0, "decision_quantile_policy"] = "q50_only"
    metadata[ppr.scoring_contract_id]["decision_quantile_policy"] = "qualified_distribution"
    report = _assess({ppr.scoring_contract_id: frame}, metadata, {"ppr": ppr})
    assert report.status == "BLOCKED"
    assert "ppr:DECISION_QUANTILE_POLICY_MISMATCH" in report.blocking_reasons


def test_median_policy_is_provisional_overlay_not_a_false_ready_badge() -> None:
    half = _config(scoring="half_ppr", median=True)
    frame = _players(half, "q50_only")
    metadata = {
        half.scoring_contract_id: {
            "scoring_contract_id": half.scoring_contract_id,
            "decision_quantile_policy": "q50_only",
        }
    }

    report = _assess({half.scoring_contract_id: frame}, metadata, {"median": half})

    assert report.status == "PROVISIONAL"
    assert report.can_use_core_draft_board is True
    result = report.leagues[0]
    assert result.status == "PROVISIONAL"
    assert result.core_readiness is not None and result.core_readiness.ready is True
    assert "MEDIAN_SCORING_POLICY_UNVALIDATED" in result.provisional_reasons
    assert "MEDIAN_SCORING_POLICY_UNVALIDATED" in result.readiness.blocking_flags


def test_market_only_special_teams_are_provisional_only_when_fresh_and_explicit() -> None:
    ppr = _config(scoring="ppr", special=True)
    frame = _players(ppr, "qualified_distribution")
    metadata = {
        ppr.scoring_contract_id: {
            "scoring_contract_id": ppr.scoring_contract_id,
            "decision_quantile_policy": "qualified_distribution",
        }
    }

    report = _assess(
        {ppr.scoring_contract_id: frame},
        metadata,
        {"expanded": ppr},
        special_teams_market_snapshot=_special(),
    )
    assert report.status == "PROVISIONAL"
    assert report.can_use_core_draft_board is True
    assert report.leagues[0].market_only_positions == ("DST", "K")

    report = _assess({ppr.scoring_contract_id: frame}, metadata, {"expanded": ppr})
    assert report.status == "BLOCKED"
    assert any("MARKET_ONLY_SUPPORT_MISSING:DST,K" in item for item in report.blocking_reasons)


def test_bundle_integrity_freshness_and_hub_identity_are_hard_blockers() -> None:
    ppr = _config(scoring="ppr")
    frame = _players(ppr, "qualified_distribution")
    metadata = {
        ppr.scoring_contract_id: {
            "scoring_contract_id": ppr.scoring_contract_id,
            "decision_quantile_policy": "qualified_distribution",
        }
    }
    hub = _hub(generated_at=NOW - timedelta(hours=30))
    hub["market_identity"] = {"redraft_identity_coverage": 0.2, "usable_market_players": 20}

    report = _assess(
        {ppr.scoring_contract_id: frame},
        metadata,
        {"ppr": ppr},
        bundle_authority="challenger",
        bundle_integrity_verified=False,
        projection_source_cutoff_utc=NOW - timedelta(hours=72),
        nfl_hub_snapshot=hub,
    )

    assert report.status == "BLOCKED"
    assert "PROJECTION_BUNDLE_NOT_PRODUCTION_APPROVED" in report.blocking_reasons
    assert "PROJECTION_BUNDLE_INTEGRITY_UNVERIFIED" in report.blocking_reasons
    assert "PROJECTION_SOURCE_CUTOFF_STALE" in report.blocking_reasons
    assert "NFL_HUB_STALE" in report.blocking_reasons
    assert "NFL_HUB_MARKET_IDENTITY_COVERAGE_LOW" in report.blocking_reasons
    assert "NFL_HUB_MARKET_PLAYER_COVERAGE_LOW" in report.blocking_reasons


def test_optional_hub_degradation_is_provisional_when_everything_else_is_ready() -> None:
    ppr = _config(scoring="ppr")
    frame = _players(ppr, "qualified_distribution")
    metadata = {
        ppr.scoring_contract_id: {
            "scoring_contract_id": ppr.scoring_contract_id,
            "decision_quantile_policy": "qualified_distribution",
        }
    }

    report = _assess(
        {ppr.scoring_contract_id: frame},
        metadata,
        {"ppr": ppr},
        nfl_hub_snapshot=_hub(status="DEGRADED"),
    )

    assert report.status == "PROVISIONAL"
    assert report.can_use_core_draft_board is True
    assert "NFL_HUB_OPTIONAL_SOURCE_DEGRADED" in report.provisional_reasons
