from __future__ import annotations

from collections import defaultdict

import numpy as np
import pandas as pd

from player_state_engine.game_intelligence.simulator import PlayByPlaySimulationResult
from player_state_engine.game_intelligence.terminal import (
    TerminalFamilyModel,
    _normalize_with_support,
    extract_terminal_family_events,
)
from player_state_engine.game_intelligence.terminal_benchmark import (
    _aggregate,
    _aggregate_isolated,
)
from player_state_engine.game_intelligence.terminal_simulator import (
    TerminalAuthorityBridge,
    TerminalConditionedOutcomeModel,
    _add_terminal_count_columns,
)


def test_sparse_structural_fallback_never_reintroduces_illegal_family() -> None:
    learned = np.asarray([0.0, 0.0, 1.0, 0.0], dtype=float)
    legal = TerminalFamilyModel._structural_terminal_support(
        {"down": 3.0, "game_seconds_remaining": 1300.0},
        authority_mode=True,
        authority_end_window_seconds=45.0,
    )
    normalized = _normalize_with_support(learned, legal)
    assert np.isclose(normalized.sum(), 1.0)
    assert normalized[2] == 0.0  # DOWNS is illegal before fourth down.
    assert normalized[3] == 0.0  # END_HALF is illegal away from a clock boundary.
    assert np.isclose(normalized[0] + normalized[1], 1.0)


class _FallbackOutcomeModel:
    model_source = "fallback_fixture"
    fitted = True

    def sample(self, **_: object) -> dict[str, float]:
        return {
            "yards_gained": 0.0,
            "touchdown": 0.0,
            "turnover": 1.0,
            "first_down": 0.0,
        }

    def sample_for_terminal_family(self, **_: object) -> dict[str, float]:
        raise ValueError("no compatible terminal-conditioned pool")


def test_conditioning_fallback_records_realized_legacy_family_and_removes_clock_authority() -> None:
    bridge = TerminalAuthorityBridge(TerminalFamilyModel())
    bridge.current_distribution = {
        "CONTINUE": 0.0,
        "SCORE": 0.0,
        "TURNOVER": 0.0,
        "DOWNS": 0.0,
        "END_HALF": 1.0,
    }
    bridge.current_team = "AAA"
    bridge.current_play_family = "DROPBACK"
    bridge.current_state = {
        "down": 2.0,
        "ydstogo": 8.0,
        "yardline_100": 35.0,
        "game_seconds_remaining": 20.0,
        "score_differential": 0.0,
    }
    bridge.probability_calls = 1
    wrapper = TerminalConditionedOutcomeModel(_FallbackOutcomeModel(), bridge)  # type: ignore[arg-type]
    outcome = wrapper.sample(
        play_family="DROPBACK",
        down=2,
        distance_bucket=2,
        field_zone=1,
        rng=np.random.default_rng(31),
    )
    assert outcome["turnover"] == 1.0
    assert bridge.conditioning_fallbacks == 1
    assert bridge.current_family == "TURNOVER"
    assert bridge.counts["AAA"]["TURNOVER"] == 1
    assert bridge.counts["AAA"]["END_HALF"] == 0


def test_terminal_labels_match_frozen_simulator_realization_order() -> None:
    base = {
        "season": 2026,
        "week": 1,
        "game_id": "realization",
        "home_team": "AAA",
        "away_team": "BBB",
        "score_differential": 0.0,
        "no_play": 0,
        "punt_attempt": 0,
        "field_goal_attempt": 0,
        "sack": 0,
        "qb_scramble": 0,
        "fumble_lost": 0,
    }
    frame = pd.DataFrame(
        [
            {
                **base,
                "play_id": 1,
                "posteam": "AAA",
                "defteam": "BBB",
                "pass_attempt": 0,
                "rush_attempt": 1,
                "qb_dropback": 0,
                "down": 4,
                "ydstogo": 2.0,
                "yardline_100": 50.0,
                "qtr": 1,
                "game_seconds_remaining": 3500.0,
                "yards_gained": 3.0,
                "touchdown": 0,
                "first_down": 0,
                "interception": 0,
                "turnover": 0,
                "play_type": "run",
            },
            {
                **base,
                "play_id": 2,
                "posteam": "BBB",
                "defteam": "AAA",
                "pass_attempt": 0,
                "rush_attempt": 1,
                "qb_dropback": 0,
                "down": 1,
                "ydstogo": 10.0,
                "yardline_100": 75.0,
                "qtr": 1,
                "game_seconds_remaining": 3470.0,
                "yards_gained": 2.0,
                "touchdown": 0,
                "first_down": 0,
                "interception": 0,
                "turnover": 0,
                "play_type": "run",
            },
            {
                **base,
                "play_id": 3,
                "posteam": "AAA",
                "defteam": "BBB",
                "pass_attempt": 1,
                "rush_attempt": 0,
                "qb_dropback": 1,
                "down": 2,
                "ydstogo": 8.0,
                "yardline_100": 5.0,
                "qtr": 4,
                "game_seconds_remaining": 10.0,
                "yards_gained": 5.0,
                "touchdown": 0,
                "first_down": 0,
                "interception": 1,
                "turnover": 1,
                "play_type": "pass",
            },
        ]
    )
    labels = extract_terminal_family_events(frame).set_index("play_id")["terminal_family"]
    assert labels.loc[1] == "CONTINUE"  # conversion by yards despite missing first_down flag
    assert labels.loc[3] == "SCORE"  # goal-line crossing wins before contradictory turnover flag


def test_realized_team_metrics_are_never_overwritten_by_requested_families() -> None:
    team_draws = pd.DataFrame(
        [
            {
                "game_id": "g",
                "simulation": 0,
                "team": "AAA",
                "points": 7.0,
                "field_goals_made": 0.0,
                "turnovers": 0.0,
                "turnovers_on_downs": 0.0,
            },
            {
                "game_id": "g",
                "simulation": 0,
                "team": "BBB",
                "points": 0.0,
                "field_goals_made": 0.0,
                "turnovers": 1.0,
                "turnovers_on_downs": 0.0,
            },
        ]
    )
    result = PlayByPlaySimulationResult(
        game_summary=pd.DataFrame(),
        team_summary=pd.DataFrame(),
        player_summary=pd.DataFrame(),
        game_draws=pd.DataFrame(),
        team_draws=team_draws,
        player_draws=pd.DataFrame(),
        diagnostics={},
    )
    bridge = TerminalAuthorityBridge(TerminalFamilyModel())
    bridge.counts = defaultdict(lambda: defaultdict(int))
    bridge.counts["AAA"]["TURNOVER"] = 1  # deliberately contradict realized touchdown
    bridge.counts["BBB"]["SCORE"] = 1  # deliberately contradict realized turnover
    mismatch = _add_terminal_count_columns(result, bridge=bridge, simulations=1)

    aaa = result.team_draws.loc[result.team_draws["team"].eq("AAA")].iloc[0]
    bbb = result.team_draws.loc[result.team_draws["team"].eq("BBB")].iloc[0]
    assert aaa["terminal_score_events"] == 1.0
    assert aaa["terminal_turnover_events"] == 0.0
    assert aaa["requested_terminal_turnover_events"] == 1.0
    assert bbb["terminal_turnover_events"] == 1.0
    assert bbb["requested_terminal_score_events"] == 1.0
    assert mismatch == 4.0


def test_terminal_aggregate_uses_event_denominators_and_count_weighted_fallbacks() -> None:
    aggregate = _aggregate(
        [
            {
                "games": 1.0,
                "terminal_conditioning_fallbacks": 1.0,
                "terminal_probability_calls": 1.0,
                "terminal_conditioning_fallback_rate": 1.0,
            },
            {
                "games": 1.0,
                "terminal_conditioning_fallbacks": 0.0,
                "terminal_probability_calls": 99.0,
                "terminal_conditioning_fallback_rate": 0.0,
            },
        ]
    )
    assert aggregate["terminal_conditioning_fallback_rate"] == 0.01

    isolated = _aggregate_isolated(
        pd.DataFrame(
            [
                {
                    "terminal_family_rows": 100.0,
                    "conditional_terminal_rows": 1.0,
                    "score_rows": 1.0,
                    "terminal_family_log_loss": 1.0,
                    "conditional_terminal_log_loss": 10.0,
                    "score_recall": 0.0,
                },
                {
                    "terminal_family_rows": 1.0,
                    "conditional_terminal_rows": 9.0,
                    "score_rows": 9.0,
                    "terminal_family_log_loss": 3.0,
                    "conditional_terminal_log_loss": 0.0,
                    "score_recall": 1.0,
                },
            ]
        )
    )
    assert np.isclose(isolated["terminal_family_log_loss"], 103.0 / 101.0)
    assert np.isclose(isolated["conditional_terminal_log_loss"], 1.0)
    assert np.isclose(isolated["score_recall"], 0.9)
