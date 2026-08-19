from __future__ import annotations

import numpy as np

from player_state_engine.game_intelligence.terminal import (
    TerminalFamilyModel,
    _normalize_with_support,
)
from player_state_engine.game_intelligence.terminal_simulator import (
    TerminalAuthorityBridge,
    TerminalConditionedOutcomeModel,
)


def test_sparse_structural_fallback_never_reintroduces_illegal_family() -> None:
    learned = np.asarray([0.0, 0.0, 1.0, 0.0], dtype=float)
    legal = TerminalFamilyModel._structural_terminal_support(
        {
            "down": 3.0,
            "game_seconds_remaining": 1300.0,
        },
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
