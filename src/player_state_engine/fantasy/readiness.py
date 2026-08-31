from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.projection_contracts import select_projection_scoring_contract
from player_state_engine.fantasy.scoring import prepare_league_scoring_quantiles

_POSITION_ALIASES = {
    "D/ST": "DST",
    "DEF": "DST",
    "DEFENSE": "DST",
    "PK": "K",
    "KICKER": "K",
}
_MARKET_COLUMNS = (
    "market_adp",
    "consensus_adp",
    "adp",
    "market_pick_q50",
    "market_cost",
)


@dataclass(frozen=True, slots=True)
class LeagueReadinessReport:
    """Draft-input health for one exact fantasy league contract."""

    score: float
    ready: bool
    flags: tuple[str, ...]
    blocking_flags: tuple[str, ...]
    required_positions: tuple[str, ...]
    present_positions: tuple[str, ...]
    missing_positions: tuple[str, ...]
    projection_rows: int
    unique_player_coverage: float
    market_adp_coverage: float
    market_coverage: float
    market_source: str | None
    exact_scoring_coverage: float
    valuation_coverage: float
    required_position_exact_scoring: dict[str, float] = field(default_factory=dict)
    inexact_required_positions: tuple[str, ...] = ()
    approximate_scoring_coverage: float = 0.0

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _canonical_position(value: object) -> str:
    position = str(value or "").strip().upper()
    return _POSITION_ALIASES.get(position, position)


def required_projection_positions(config: LeagueConfig) -> tuple[str, ...]:
    """Return every real position that can legally occupy a starting slot."""

    positions = {_canonical_position(position) for position in config.direct_starter_slots}
    for slot, count in config.flex_slots.items():
        if count > 0:
            positions.update(
                _canonical_position(position) for position in config.flex_eligibility.get(slot, ())
            )
    ignored = {"", "BENCH", "IR", "RESERVE", "TAXI"}
    return tuple(sorted(position for position in positions if position not in ignored))


def _market_coverage(frame: pd.DataFrame) -> tuple[float, str | None]:
    if frame.empty:
        return 0.0, None
    for column in _MARKET_COLUMNS:
        if column not in frame:
            continue
        numeric = pd.to_numeric(frame[column], errors="coerce")
        return float(numeric.notna().mean()), column
    return 0.0, None


def _bool_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series(False, index=frame.index, dtype=bool)
    values = frame[column]
    if pd.api.types.is_bool_dtype(values):
        return values.fillna(False).astype(bool)
    normalized = values.astype("string").str.strip().str.lower()
    return normalized.isin({"true", "1", "yes"})


def assess_league_readiness(
    projections: pd.DataFrame,
    config: LeagueConfig,
    *,
    minimum_market_coverage: float = 0.70,
    minimum_exact_scoring_coverage: float = 0.80,
    minimum_valuation_coverage: float = 0.98,
    minimum_ready_score: float = 65.0,
    minimum_required_position_exact_scoring_coverage: float = 0.80,
) -> LeagueReadinessReport:
    """Audit whether a projection pool is trustworthy for this league's draft decisions.

    Readiness is deliberately league-specific. A shared multicontract artifact is sliced to the
    exact ``LeagueConfig.scoring_contract_id`` before row counts, identity uniqueness, position
    coverage, market coverage, or scoring authority are measured.

    Numerical valuation coverage and exact-scoring authority are separate concepts. Complete
    component quantiles can support an approximate custom-league valuation, but they are not an
    exact fantasy-score distribution because marginal quantiles are not additive.

    Every position that can legally occupy a starting slot must independently clear the
    exact-scoring gate. This prevents both population dilution and approximate component rescoring
    from masquerading as production-ready league-score distributions.

    A weekly game against the league median is a separate team-week distribution problem. Exact
    player-season league scores do not qualify that policy, so median-scoring formats remain
    fail-closed until a separately replayed team-level policy earns authority.
    """

    if not 0.0 <= minimum_market_coverage <= 1.0:
        raise ValueError("minimum_market_coverage must be between zero and one")
    if not 0.0 <= minimum_exact_scoring_coverage <= 1.0:
        raise ValueError("minimum_exact_scoring_coverage must be between zero and one")
    if not 0.0 <= minimum_valuation_coverage <= 1.0:
        raise ValueError("minimum_valuation_coverage must be between zero and one")
    if not 0.0 <= minimum_ready_score <= 100.0:
        raise ValueError("minimum_ready_score must be between zero and 100")
    if not 0.0 <= minimum_required_position_exact_scoring_coverage <= 1.0:
        raise ValueError(
            "minimum_required_position_exact_scoring_coverage must be between zero and one"
        )

    projections = select_projection_scoring_contract(projections, config)
    flags: list[str] = []
    blockers: list[str] = []
    rows = int(len(projections))
    required = required_projection_positions(config)

    if config.median_scoring:
        flags.append("MEDIAN_SCORING_POLICY_UNVALIDATED")
        blockers.append("MEDIAN_SCORING_POLICY_UNVALIDATED")

    if "position" in projections:
        present = tuple(
            sorted(
                {
                    _canonical_position(value)
                    for value in projections["position"].dropna().tolist()
                    if _canonical_position(value)
                }
            )
        )
    else:
        present = ()
        flags.append("MISSING_POSITION_COLUMN")
        blockers.append("MISSING_POSITION_COLUMN")
    present_set = set(present)
    missing_positions = tuple(position for position in required if position not in present_set)
    if missing_positions:
        flags.append("MISSING_REQUIRED_POSITIONS")
        blockers.append("MISSING_REQUIRED_POSITIONS")

    unique_coverage = 0.0
    if "player_id" not in projections:
        flags.append("MISSING_PLAYER_ID")
        blockers.append("MISSING_PLAYER_ID")
    elif rows:
        ids = projections["player_id"].astype("string").str.strip()
        valid = ids.notna() & ids.ne("")
        unique_coverage = float(ids.loc[valid].nunique() / rows)
        if not bool(valid.all()):
            flags.append("MISSING_PLAYER_ID_VALUES")
            blockers.append("MISSING_PLAYER_ID_VALUES")
        if ids.loc[valid].duplicated().any():
            flags.append("DUPLICATE_PLAYER_IDS")
            blockers.append("DUPLICATE_PLAYER_IDS")

    market_coverage, market_source = _market_coverage(projections)
    if market_source is None:
        flags.append("MISSING_MARKET_DATA")
    elif market_coverage < minimum_market_coverage:
        flags.append("LOW_MARKET_COVERAGE")

    exact_scoring_coverage = 0.0
    approximate_scoring_coverage = 0.0
    valuation_coverage = 0.0
    required_position_exact_scoring: dict[str, float] = {}
    inexact_required_positions: tuple[str, ...] = ()
    if rows:
        try:
            scored = prepare_league_scoring_quantiles(projections, config)
        except ValueError:
            flags.append("UNSCORABLE_PROJECTIONS")
            blockers.append("UNSCORABLE_PROJECTIONS")
        else:
            valuation = pd.to_numeric(scored["valuation_points_q50"], errors="coerce")
            valuation_coverage = float(valuation.notna().mean())
            source = scored["league_scoring_source"].astype(str)
            exact = _bool_series(scored, "league_scoring_exact")
            approximate = _bool_series(scored, "league_scoring_approximate") & valuation.notna()
            exact_scoring_coverage = float(exact.mean())
            approximate_scoring_coverage = float(approximate.mean())

            if source.eq("component_quantile_rescore").any() or source.eq(
                "provided_league_quantiles_unverified"
            ).any():
                flags.append("INEXACT_SCORING_APPROXIMATION")
            if source.eq("generic_points_fallback").any():
                flags.append("GENERIC_SCORING_FALLBACK")

            if "position" in scored:
                normalized_position = scored["position"].map(_canonical_position)
                inexact: list[str] = []
                for position in required:
                    position_mask = normalized_position.eq(position)
                    if not bool(position_mask.any()):
                        coverage = 0.0
                    else:
                        coverage = float(exact.loc[position_mask].mean())
                    required_position_exact_scoring[position] = coverage
                    if coverage < minimum_required_position_exact_scoring_coverage:
                        inexact.append(position)
                inexact_required_positions = tuple(inexact)
                if inexact_required_positions:
                    flags.append("INEXACT_REQUIRED_POSITION_SCORING")
                    blockers.append("INEXACT_REQUIRED_POSITION_SCORING")

    if exact_scoring_coverage < minimum_exact_scoring_coverage and not any(
        flag in flags for flag in ("INEXACT_SCORING_APPROXIMATION", "GENERIC_SCORING_FALLBACK")
    ):
        flags.append("LOW_EXACT_SCORING_COVERAGE")
    if valuation_coverage < minimum_valuation_coverage:
        flags.append("INCOMPLETE_VALUATION_COVERAGE")
        blockers.append("INCOMPLETE_VALUATION_COVERAGE")

    position_coverage = (
        1.0 if not required else 1.0 - (len(missing_positions) / float(len(required)))
    )
    score = 100.0 * (
        0.30 * float(np.clip(position_coverage, 0.0, 1.0))
        + 0.15 * float(np.clip(unique_coverage, 0.0, 1.0))
        + 0.20 * float(np.clip(market_coverage, 0.0, 1.0))
        + 0.20 * float(np.clip(exact_scoring_coverage, 0.0, 1.0))
        + 0.15 * float(np.clip(valuation_coverage, 0.0, 1.0))
    )
    score = float(np.clip(score, 0.0, 100.0))
    if score < minimum_ready_score:
        flags.append("READINESS_SCORE_BELOW_THRESHOLD")
        blockers.append("READINESS_SCORE_BELOW_THRESHOLD")

    flags = list(dict.fromkeys(flags))
    blockers = list(dict.fromkeys(blockers))
    return LeagueReadinessReport(
        score=score,
        ready=not blockers,
        flags=tuple(flags),
        blocking_flags=tuple(blockers),
        required_positions=required,
        present_positions=present,
        missing_positions=missing_positions,
        projection_rows=rows,
        unique_player_coverage=unique_coverage,
        market_adp_coverage=market_coverage,
        market_coverage=market_coverage,
        market_source=market_source,
        exact_scoring_coverage=exact_scoring_coverage,
        valuation_coverage=valuation_coverage,
        required_position_exact_scoring=required_position_exact_scoring,
        inexact_required_positions=inexact_required_positions,
        approximate_scoring_coverage=approximate_scoring_coverage,
    )
