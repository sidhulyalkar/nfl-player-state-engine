from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.game_intelligence.decision import (
    DriveTerminationHazardModel,
    FourthDownDecisionModel,
)
from player_state_engine.game_intelligence.decision_simulator import (
    simulate_matchup_decision_probe,
)
from player_state_engine.game_intelligence.drive import DriveVolumeModel
from player_state_engine.game_intelligence.models import EmpiricalPlayOutcomeModel, PlayCallModel
from player_state_engine.game_intelligence.opportunity import StateConditionedOpportunityModel
from player_state_engine.game_intelligence.schema import MatchupSpec, SimulationConfig
from player_state_engine.game_intelligence.simulator import PlayByPlaySimulationResult
from player_state_engine.game_intelligence.terminal import (
    TERMINAL_FAMILIES,
    TerminalFamilyModel,
    _seconds_to_boundary,
)
from player_state_engine.game_intelligence.transition import PossessionTransitionModel


def _shadow_rng(
    rng: np.random.Generator,
    *,
    salt: str,
    state_key: str,
) -> np.random.Generator:
    """Derive a deterministic non-consuming substream from the current RNG state."""
    payload = f"{salt}|{state_key}|{repr(rng.bit_generator.state)}".encode()
    digest = hashlib.blake2b(payload, digest_size=16).digest()
    words = np.frombuffer(digest, dtype=np.uint32).astype(np.uint64)
    seed = int(np.bitwise_xor.reduce(words))
    return np.random.default_rng(seed)


@dataclass(slots=True)
class TerminalAuthorityBridge:
    """Expose a v0.16 family distribution through the v0.15 hazard interface."""

    model: TerminalFamilyModel
    model_source: str = "terminal_family_authority_bridge_v016"
    current_distribution: dict[str, float] | None = None
    current_team: str | None = None
    current_state: dict[str, object] | None = None
    current_play_family: str | None = None
    current_family: str | None = None
    probability_calls: int = 0
    conditioning_fallbacks: int = 0
    aligned_legacy_outcome_draws: int = 0
    discarded_legacy_outcomes: int = 0
    counts: defaultdict[str, defaultdict[str, int]] = field(
        default_factory=lambda: defaultdict(lambda: defaultdict(int)),
        repr=False,
    )

    def probability(
        self,
        *,
        team: str,
        state: dict[str, object] | pd.Series,
        play_family: str,
        use_team: bool = True,
        use_context: bool = True,
    ) -> float:
        state_dict = state.to_dict() if isinstance(state, pd.Series) else dict(state)
        self.current_distribution = self.model.distribution(
            team=str(team),
            state=state_dict,
            play_family=str(play_family),
            use_team=use_team,
            use_context=use_context,
            authority_mode=True,
        )
        self.current_team = str(team)
        self.current_state = state_dict
        self.current_play_family = str(play_family)
        self.current_family = None
        self.probability_calls += 1
        return float(1.0 - self.current_distribution["CONTINUE"])

    def state_key(self) -> str:
        state = self.current_state or {}
        return "|".join(
            [
                str(self.current_team or "UNKNOWN"),
                str(self.current_play_family or "OTHER"),
                f"{float(state.get('down', 0.0)):.3f}",
                f"{float(state.get('ydstogo', 0.0)):.3f}",
                f"{float(state.get('yardline_100', 0.0)):.3f}",
                f"{float(state.get('game_seconds_remaining', 0.0)):.3f}",
                f"{float(state.get('score_differential', 0.0)):.3f}",
                str(self.probability_calls),
            ]
        )

    def record_family(self, family: str) -> None:
        self.current_family = str(family)
        if self.current_team is not None:
            self.counts[self.current_team][self.current_family] += 1

    def sample_family(self, rng: np.random.Generator) -> str:
        if self.current_distribution is None or self.current_team is None:
            raise RuntimeError("Terminal authority bridge was sampled before probability evaluation")
        shadow = _shadow_rng(rng, salt="terminal-family", state_key=self.state_key())
        probability = np.asarray(
            [self.current_distribution[family] for family in TERMINAL_FAMILIES],
            dtype=float,
        )
        family = str(
            TERMINAL_FAMILIES[
                int(shadow.choice(np.arange(len(TERMINAL_FAMILIES)), p=probability))
            ]
        )
        self.record_family(family)
        return family

    def seconds_to_boundary(self) -> float:
        if self.current_state is None:
            return float("inf")
        return _seconds_to_boundary(
            float(self.current_state.get("game_seconds_remaining", 3600.0))
        )

    def infer_legacy_family(self, outcome: dict[str, float]) -> str:
        """Mirror the frozen simulator's realized terminal ordering for fallback accounting."""
        state = self.current_state or {}
        yardline = float(state.get("yardline_100", 99.5))
        distance = float(state.get("ydstogo", 10.0))
        down = int(round(float(state.get("down", 1.0))))
        yards = float(np.clip(outcome.get("yards_gained", 0.0), -25.0, 99.0))
        touchdown = bool(outcome.get("touchdown", 0.0) >= 0.5 or yards >= yardline)
        turnover = bool(outcome.get("turnover", 0.0) >= 0.5)
        first_down = bool(outcome.get("first_down", 0.0) >= 0.5 or yards >= distance)
        if touchdown:
            return "SCORE"
        if turnover:
            return "TURNOVER"
        if down == 4 and not first_down:
            return "DOWNS"
        return "CONTINUE"


class TerminalConditionedOutcomeModel:
    """Preserve the legacy RNG draw while returning a family-compatible empirical outcome."""

    def __init__(
        self,
        base: EmpiricalPlayOutcomeModel,
        bridge: TerminalAuthorityBridge,
    ) -> None:
        self.base = base
        self.bridge = bridge
        self.model_source = f"{base.model_source}+terminal_conditioning_v016"
        self.fitted = base.fitted

    def sample(
        self,
        *,
        play_family: str,
        down: int,
        distance_bucket: int,
        field_zone: int,
        rng: np.random.Generator,
    ) -> dict[str, float]:
        pre_state = repr(rng.bit_generator.state)
        legacy = self.base.sample(
            play_family=play_family,
            down=down,
            distance_bucket=distance_bucket,
            field_zone=field_zone,
            rng=rng,
        )
        self.bridge.aligned_legacy_outcome_draws += 1
        family_rng = np.random.default_rng(
            int.from_bytes(
                hashlib.blake2b(
                    f"family|{self.bridge.state_key()}|{pre_state}".encode(),
                    digest_size=8,
                ).digest(),
                "little",
            )
        )
        probability = np.asarray(
            [
                (self.bridge.current_distribution or {}).get(family, 0.0)
                for family in TERMINAL_FAMILIES
            ],
            dtype=float,
        )
        probability = probability / max(float(probability.sum()), 1e-12)
        terminal_family = str(
            TERMINAL_FAMILIES[
                int(family_rng.choice(np.arange(len(TERMINAL_FAMILIES)), p=probability))
            ]
        )

        outcome_rng = np.random.default_rng(
            int.from_bytes(
                hashlib.blake2b(
                    f"outcome|{self.bridge.state_key()}|{pre_state}".encode(),
                    digest_size=8,
                ).digest(),
                "little",
            )
        )
        try:
            outcome = self.base.sample_for_terminal_family(
                play_family=play_family,
                down=down,
                distance_bucket=distance_bucket,
                field_zone=field_zone,
                terminal_family=terminal_family,
                rng=outcome_rng,
            )
        except ValueError:
            self.bridge.conditioning_fallbacks += 1
            self.bridge.record_family(self.bridge.infer_legacy_family(legacy))
            return legacy

        self.bridge.discarded_legacy_outcomes += 1
        self.bridge.record_family(terminal_family)
        if terminal_family == "END_HALF":
            seconds = self.bridge.seconds_to_boundary()
            if np.isfinite(seconds) and seconds > 0:
                outcome["seconds_between_plays"] = float(seconds)
        return outcome


class TerminalAwareDriveVolumeModel:
    """Delegate v0.13 pace except when an END_HALF family owns the clock boundary."""

    def __init__(self, base: DriveVolumeModel, bridge: TerminalAuthorityBridge) -> None:
        self.base = base
        self.bridge = bridge
        self.model_source = f"{base.model_source}+terminal_clock_bridge_v016"
        self.fitted = base.fitted

    def sample_start_yardline(self, **kwargs: object) -> float:
        return float(self.base.sample_start_yardline(**kwargs))

    def sample_seconds(
        self,
        *,
        team: str,
        state: dict[str, float | str] | pd.Series,
        play_family: str,
        rng: np.random.Generator,
        use_context: bool = True,
        fallback_seconds: float = 28.0,
    ) -> float:
        if self.bridge.current_family == "END_HALF":
            seconds = self.bridge.seconds_to_boundary()
            if np.isfinite(seconds) and seconds > 0:
                return float(seconds)
        return float(
            self.base.sample_seconds(
                team=team,
                state=state,
                play_family=play_family,
                rng=rng,
                use_context=use_context,
                fallback_seconds=fallback_seconds,
            )
        )


def _add_terminal_count_columns(
    result: PlayByPlaySimulationResult,
    *,
    bridge: TerminalAuthorityBridge | None,
    simulations: int,
) -> None:
    draws = result.team_draws.copy()
    if draws.empty:
        return
    score_from_existing = (
        pd.to_numeric(draws["points"], errors="coerce").fillna(0.0)
        - 3.0 * pd.to_numeric(draws["field_goals_made"], errors="coerce").fillna(0.0)
    ).clip(lower=0.0) / 7.0
    draws["terminal_score_events"] = score_from_existing
    draws["terminal_turnover_events"] = pd.to_numeric(
        draws["turnovers"], errors="coerce"
    ).fillna(0.0)
    draws["terminal_downs_events"] = pd.to_numeric(
        draws["turnovers_on_downs"], errors="coerce"
    ).fillna(0.0)
    draws["terminal_non_clock_events"] = (
        draws["terminal_score_events"]
        + draws["terminal_turnover_events"]
        + draws["terminal_downs_events"]
    )
    draws["terminal_end_half_events"] = np.nan

    if bridge is not None:
        divisor = max(int(simulations), 1)
        for team in draws["team"].astype(str).unique():
            counts = bridge.counts.get(team, {})
            mask = draws["team"].astype(str).eq(team)
            draws.loc[mask, "terminal_score_events"] = float(counts.get("SCORE", 0)) / divisor
            draws.loc[mask, "terminal_turnover_events"] = (
                float(counts.get("TURNOVER", 0)) / divisor
            )
            draws.loc[mask, "terminal_downs_events"] = float(counts.get("DOWNS", 0)) / divisor
            draws.loc[mask, "terminal_non_clock_events"] = (
                float(counts.get("SCORE", 0))
                + float(counts.get("TURNOVER", 0))
                + float(counts.get("DOWNS", 0))
            ) / divisor
            draws.loc[mask, "terminal_end_half_events"] = (
                float(counts.get("END_HALF", 0)) / divisor
            )
    result.team_draws = draws


def simulate_matchup_terminal_probe(
    matchup: MatchupSpec,
    *,
    tendencies: pd.DataFrame,
    usage: pd.DataFrame,
    outcome_model: EmpiricalPlayOutcomeModel,
    play_call_model: PlayCallModel | None = None,
    opportunity_model: StateConditionedOpportunityModel | None = None,
    drive_volume_model: DriveVolumeModel | None = None,
    transition_model: PossessionTransitionModel | None = None,
    decision_model: FourthDownDecisionModel | None = None,
    terminal_family_model: TerminalFamilyModel | None = None,
    termination_hazard_model: DriveTerminationHazardModel | None = None,
    league_config: LeagueConfig | None = None,
    config: SimulationConfig | None = None,
) -> PlayByPlaySimulationResult:
    """Run the v0.16 terminal-family intervention without mutating the live simulator path."""
    config = config or SimulationConfig()
    if terminal_family_model is None:
        result = simulate_matchup_decision_probe(
            matchup,
            tendencies=tendencies,
            usage=usage,
            outcome_model=outcome_model,
            play_call_model=play_call_model,
            opportunity_model=opportunity_model,
            drive_volume_model=drive_volume_model,
            transition_model=transition_model,
            decision_model=decision_model,
            termination_hazard_model=termination_hazard_model,
            league_config=league_config,
            config=config,
        )
        _add_terminal_count_columns(result, bridge=None, simulations=config.simulations)
        result.diagnostics.update(
            {
                "terminal_family_model": "disabled_v015_parity",
                "terminal_family_authority": False,
                "terminal_conditioned_outcomes": False,
                "terminal_shadow_rng_stream": False,
            }
        )
        return result

    if not outcome_model.terminal_conditioning_available:
        raise ValueError(
            "v0.16 terminal authority requires EmpiricalPlayOutcomeModel fitted with terminal labels"
        )
    bridge = TerminalAuthorityBridge(terminal_family_model)
    conditioned_outcome = TerminalConditionedOutcomeModel(outcome_model, bridge)
    terminal_drive = (
        TerminalAwareDriveVolumeModel(drive_volume_model, bridge)
        if drive_volume_model is not None
        else None
    )
    result = simulate_matchup_decision_probe(
        matchup,
        tendencies=tendencies,
        usage=usage,
        outcome_model=conditioned_outcome,
        play_call_model=play_call_model,
        opportunity_model=opportunity_model,
        drive_volume_model=terminal_drive,
        transition_model=transition_model,
        decision_model=decision_model,
        termination_hazard_model=bridge,
        league_config=league_config,
        config=config,
    )
    _add_terminal_count_columns(result, bridge=bridge, simulations=config.simulations)
    fallback_rate = bridge.conditioning_fallbacks / max(bridge.probability_calls, 1)
    result.diagnostics.update(
        {
            "model_source": "terminal_family_probe_v016",
            "terminal_family_model": terminal_family_model.model_source,
            "terminal_family_authority": True,
            "terminal_conditioned_outcomes": True,
            "terminal_shadow_rng_stream": True,
            "terminal_shadow_rng_advances_legacy_stream": False,
            "aligned_legacy_outcome_draws": int(bridge.aligned_legacy_outcome_draws),
            "discarded_legacy_outcomes": int(bridge.discarded_legacy_outcomes),
            "terminal_conditioning_fallbacks": int(bridge.conditioning_fallbacks),
            "terminal_conditioning_fallback_rate": float(fallback_rate),
            "terminal_probability_calls": int(bridge.probability_calls),
            "end_half_clock_authority": True,
            "termination_hazard_authority": True,
            "automatic_promotion": False,
            "production_projection_changed": False,
            "limitations": [
                "v0.16 terminal-family authority is research-only and the live simulator remains frozen",
                "terminal family selection uses hierarchical empirical state rather than a deep sequence model",
                "terminal-conditioned outcomes reuse observed historical rows and do not model causal execution heads separately",
                "END_HALF authority is restricted to a short structural clock window and delegates halftime possession to the frozen state machine",
                "no overtime state machine, PAT/two-point strategy model, or player-level return model",
            ],
        }
    )
    return result
