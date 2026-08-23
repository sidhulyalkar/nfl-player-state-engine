from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from player_state_engine.product.portfolio_exposure import build_portfolio_exposure
from player_state_engine.product.schemas import (
    FantasyManager,
    FantasyRoster,
    LeagueIdentity,
    LeagueSettings,
    LeagueSnapshot,
    RosterEntry,
)
from player_state_engine.product.shadow_lab import (
    ScenarioControls,
    StateGraphArtifactStore,
    evaluate_shadow_replay,
)
from player_state_engine.product.store import LeagueSnapshotStore


def _write_graph_artifacts(root: Path) -> StateGraphArtifactStore:
    root.mkdir(parents=True)
    pd.DataFrame(
        [
            {
                "player_id": "p1",
                "player_name": "Player One",
                "team": "AAA",
                "position": "WR",
                "season": 2026,
                "week": 3,
                "q10": 7.0,
                "q50": 15.0,
                "q90": 25.0,
                "probability_active": 0.9,
                "role_change_probability": 0.35,
                "role_maturity": "MATURE",
                "regime_maturity": "MATURE",
            }
        ]
    ).to_parquet(root / "player_state_graph_summaries.parquet", index=False)
    pd.DataFrame(
        [
            {
                "player_id": "p1",
                "team": "AAA",
                "position": "WR",
                "season": 2026,
                "week": 3,
                "target_share_mean": 0.72,
                "carry_share_mean": 0.05,
            },
            {
                "player_id": "p2",
                "team": "AAA",
                "position": "TE",
                "season": 2026,
                "week": 3,
                "target_share_mean": 0.48,
                "carry_share_mean": 0.02,
            },
        ]
    ).to_parquet(root / "dynamic_role_states.parquet", index=False)
    return StateGraphArtifactStore(root)


def test_shadow_comparison_and_opportunity_audit_are_artifact_backed(tmp_path: Path) -> None:
    store = _write_graph_artifacts(tmp_path / "graph")
    comparison = store.player_comparison(
        "p1",
        production_week_projection={"q10": 8.0, "q50": 14.0, "q90": 22.0},
    )
    assert comparison["available"] is True
    assert comparison["comparable_horizon"] is True
    assert comparison["disagreement"]["median_delta"] == pytest.approx(1.0)
    assert comparison["authority"]["challenger"] == "research_only"
    assert comparison["authority"]["may_change_decision"] is False

    audit = store.opportunity_audit("p1")
    assert audit["available"] is True
    targets = audit["target_share"]
    assert targets["raw_modeled_total"] == pytest.approx(1.20)
    assert targets["normalization_applied"] is True
    assert targets["coherent_modeled_total"] == pytest.approx(1.0)
    assert targets["residual_unmodeled_share"] == pytest.approx(0.0)
    assert sum(row["coherent_share"] for row in targets["players"]) == pytest.approx(1.0)


def test_scenario_controls_are_bounded_and_labeled_as_sensitivity(tmp_path: Path) -> None:
    store = _write_graph_artifacts(tmp_path / "graph")
    result = store.scenario_sensitivity(
        "p1",
        production_week_projection={"q10": 8.0, "q50": 14.0, "q90": 22.0},
        baseline_availability=0.9,
        controls=ScenarioControls(
            role_multiplier=1.10,
            team_volume_multiplier=1.05,
            availability_probability=0.95,
        ),
    )
    assert result["semantics"] == "sensitivity_only_not_calibrated_forecast"
    assert result["authority"]["may_override_production"] is False
    assert result["production"]["scenario"]["q50"] > result["production"]["baseline"]["q50"]
    assert result["challenger"] is not None

    with pytest.raises(ValueError):
        ScenarioControls(role_multiplier=2.0)


def test_better_shadow_loss_still_fails_closed_without_required_evidence() -> None:
    champion = pd.DataFrame(
        [
            {"player_id": "p1", "season": 2024, "week": 1, "position": "WR", "q10": 2, "q50": 10, "q90": 20, "actual": 15},
            {"player_id": "p2", "season": 2024, "week": 2, "position": "RB", "q10": 2, "q50": 10, "q90": 20, "actual": 16},
            {"player_id": "p1", "season": 2025, "week": 1, "position": "WR", "q10": 2, "q50": 10, "q90": 20, "actual": 14},
            {"player_id": "p2", "season": 2025, "week": 2, "position": "RB", "q10": 2, "q50": 10, "q90": 20, "actual": 17},
        ]
    )
    challenger = pd.DataFrame(
        [
            {"player_id": "p1", "season": 2024, "week": 1, "position": "WR", "q10": 8, "q50": 14, "q90": 20},
            {"player_id": "p2", "season": 2024, "week": 2, "position": "RB", "q10": 8, "q50": 15, "q90": 21},
            {"player_id": "p1", "season": 2025, "week": 1, "position": "WR", "q10": 8, "q50": 14, "q90": 20},
            {"player_id": "p2", "season": 2025, "week": 2, "position": "RB", "q10": 8, "q50": 16, "q90": 22},
        ]
    )
    evaluation = evaluate_shadow_replay(champion, challenger, bootstrap_samples=400, seed=7)
    assert evaluation["metrics"]["pinball_effect_champion_minus_challenger"] > 0
    assert evaluation["promotion_status"] == "blocked"
    assert "negative_control_failed" in evaluation["blockers"]
    assert "downstream_decision_evidence_missing_or_nonpositive" in evaluation["blockers"] or "evidence_tier<3" in evaluation["blockers"]


def _snapshot(league_id: str, *, include_user: bool = True) -> LeagueSnapshot:
    user_id = "user-1" if include_user else None
    managers = [
        FantasyManager(manager_id="user-1", display_name="Me", team_name="My Team"),
        FantasyManager(manager_id="other", display_name="Other", team_name="Other Team"),
    ]
    rosters = [
        FantasyRoster(
            roster_id="1",
            manager_id="user-1",
            team_name="My Team",
            players=[
                RosterEntry(
                    platform_player_id=f"{league_id}-p1",
                    canonical_player_id="canon-p1",
                    player_name="Shared Star",
                    position="WR",
                    nfl_team="AAA",
                    is_starter=True,
                ),
                RosterEntry(
                    platform_player_id=f"{league_id}-p2",
                    canonical_player_id=f"canon-{league_id}-p2",
                    player_name="Unique Player",
                    position="RB",
                    nfl_team="BBB",
                ),
            ],
        ),
        FantasyRoster(roster_id="2", manager_id="other", team_name="Other Team"),
    ]
    return LeagueSnapshot(
        identity=LeagueIdentity(
            league_id=league_id,
            platform="sleeper",
            name=f"League {league_id}",
            season=2026,
            external_user_id=user_id,
        ),
        settings=LeagueSettings(season=2026, teams=2),
        managers=managers,
        rosters=rosters,
    )


def test_portfolio_exposure_uses_canonical_ids_and_excludes_unresolved_leagues(tmp_path: Path) -> None:
    store = LeagueSnapshotStore(tmp_path / "leagues")
    store.save(_snapshot("one"))
    store.save(_snapshot("two"))
    store.save(_snapshot("unresolved", include_user=False))

    payload = build_portfolio_exposure(store)
    assert payload["summary"]["stored_leagues"] == 3
    assert payload["summary"]["resolved_user_rosters"] == 2
    assert payload["summary"]["unresolved_user_rosters"] == 1
    shared = next(row for row in payload["players"] if row["canonical_player_id"] == "canon-p1")
    assert shared["league_count"] == 2
    assert shared["exposure_rate"] == pytest.approx(1.0)
    assert shared["starter_exposure_rate"] == pytest.approx(1.0)
    assert len(shared["leagues"]) == 2
