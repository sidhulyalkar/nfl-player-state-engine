from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.readiness import (
    LeagueReadinessReport,
    required_projection_positions,
)
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
class DraftActionabilityReport:
    """Trust verdict for an explicit current candidate set, not the entire league model."""

    status: str
    actionable: bool
    blocking_reasons: tuple[str, ...]
    caution_reasons: tuple[str, ...]
    candidate_rows: int
    candidate_player_ids: tuple[str, ...]
    candidate_positions: tuple[str, ...]
    missing_candidate_player_ids: tuple[str, ...]
    exact_scoring_coverage: float
    valuation_coverage: float
    market_coverage: float
    market_source: str | None
    global_league_ready: bool | None
    global_readiness_score: float | None
    global_blocking_reasons: tuple[str, ...]
    unsupported_required_positions: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _canonical_position(value: object) -> str:
    position = str(value or "").strip().upper()
    return _POSITION_ALIASES.get(position, position)


def _market_coverage(frame: pd.DataFrame) -> tuple[float, str | None]:
    if frame.empty:
        return 0.0, None
    for column in _MARKET_COLUMNS:
        if column not in frame:
            continue
        numeric = pd.to_numeric(frame[column], errors="coerce")
        return float(numeric.notna().mean()), column
    return 0.0, None


def assess_candidate_scope_actionability(
    projections: pd.DataFrame,
    candidates: pd.DataFrame,
    config: LeagueConfig,
    *,
    global_readiness: LeagueReadinessReport | None = None,
    minimum_market_coverage: float = 0.70,
) -> DraftActionabilityReport:
    """Audit only the player options currently under consideration.

    This deliberately does not replace ``LeagueReadinessReport`` or live-draft qualification.
    The full league can remain blocked because K/DST or another required position is unsupported
    while a specific QB/RB/WR/TE candidate set is internally complete and exactly scored.

    ``actionable=True`` therefore means only that the supplied candidate set has enough verified
    numerical support to compare those candidates. It does not mean the overall draft strategy is
    complete, and callers must continue to surface the global league verdict alongside this report.
    """

    if not 0.0 <= minimum_market_coverage <= 1.0:
        raise ValueError("minimum_market_coverage must be between zero and one")

    blockers: list[str] = []
    cautions: list[str] = []

    if candidates.empty:
        blockers.append("NO_CANDIDATES")
    for column in ("player_id", "position"):
        if column not in candidates:
            blockers.append(f"MISSING_CANDIDATE_{column.upper()}")
    if "player_id" not in projections:
        blockers.append("MISSING_PROJECTION_PLAYER_ID")
    if "position" not in projections:
        blockers.append("MISSING_PROJECTION_POSITION")

    if blockers:
        candidate_ids: tuple[str, ...] = ()
        candidate_positions: tuple[str, ...] = ()
        missing_ids: tuple[str, ...] = ()
        exact_scoring_coverage = valuation_coverage = market_coverage = 0.0
        market_source = None
    else:
        candidate_work = candidates[["player_id", "position"]].copy()
        candidate_work["player_id"] = candidate_work["player_id"].astype("string").str.strip()
        invalid_candidate_id = candidate_work["player_id"].isna() | candidate_work["player_id"].eq("")
        if invalid_candidate_id.any():
            blockers.append("MISSING_CANDIDATE_PLAYER_ID_VALUES")
        if candidate_work["player_id"].dropna().duplicated().any():
            blockers.append("DUPLICATE_CANDIDATE_IDS")

        candidate_work["position"] = candidate_work["position"].map(_canonical_position)
        candidate_ids = tuple(candidate_work["player_id"].dropna().astype(str))
        candidate_positions = tuple(
            sorted(position for position in candidate_work["position"].unique() if position)
        )

        projection_work = projections.copy()
        projection_work["player_id"] = projection_work["player_id"].astype("string").str.strip()
        selected = projection_work.loc[
            projection_work["player_id"].isin(candidate_work["player_id"])
        ].copy()
        duplicate_projection_ids = selected["player_id"].dropna().duplicated(keep=False)
        if duplicate_projection_ids.any():
            blockers.append("DUPLICATE_CANDIDATE_PROJECTION_ROWS")

        selected_ids = set(selected["player_id"].dropna().astype(str))
        missing_ids = tuple(sorted(set(candidate_ids) - selected_ids))
        if missing_ids:
            blockers.append("MISSING_CANDIDATE_PROJECTIONS")

        if not selected.empty and not duplicate_projection_ids.any():
            selected_positions = selected[["player_id", "position"]].copy()
            selected_positions["position"] = selected_positions["position"].map(_canonical_position)
            expected_positions = candidate_work.dropna(subset=["player_id"]).copy()
            joined = expected_positions.merge(
                selected_positions,
                on="player_id",
                how="inner",
                suffixes=("_candidate", "_projection"),
                validate="one_to_one",
            )
            if not joined["position_candidate"].eq(joined["position_projection"]).all():
                blockers.append("CANDIDATE_POSITION_MISMATCH")

        exact_scoring_coverage = 0.0
        valuation_coverage = 0.0
        market_coverage, market_source = _market_coverage(selected)
        if selected.empty or missing_ids or duplicate_projection_ids.any():
            pass
        else:
            try:
                scored = prepare_league_scoring_quantiles(selected, config)
            except ValueError:
                blockers.append("UNSCORABLE_CANDIDATE_PROJECTIONS")
            else:
                source = scored["league_scoring_source"].astype(str)
                exact_scoring_coverage = float(source.ne("generic_points_fallback").mean())
                valuation = pd.to_numeric(scored["valuation_points_q50"], errors="coerce")
                valuation_coverage = float(valuation.notna().mean())
                if exact_scoring_coverage < 1.0 - 1e-12:
                    blockers.append("CANDIDATE_GENERIC_SCORING_FALLBACK")
                if valuation_coverage < 1.0 - 1e-12:
                    blockers.append("INCOMPLETE_CANDIDATE_VALUATION")

        if market_source is None:
            cautions.append("CANDIDATE_MARKET_DATA_UNAVAILABLE")
        elif market_coverage < minimum_market_coverage:
            cautions.append("LOW_CANDIDATE_MARKET_COVERAGE")

    projection_positions = (
        {
            _canonical_position(value)
            for value in projections["position"].dropna().tolist()
            if _canonical_position(value)
        }
        if "position" in projections
        else set()
    )
    required = set(required_projection_positions(config))
    unsupported = tuple(sorted(required - projection_positions))
    if unsupported:
        if set(candidate_positions).intersection(unsupported):
            blockers.append("UNSUPPORTED_POSITION_IN_CANDIDATE_SCOPE")
        else:
            cautions.append("UNSUPPORTED_REQUIRED_POSITIONS_OUTSIDE_SCOPE")

    global_blockers: tuple[str, ...] = ()
    global_ready: bool | None = None
    global_score: float | None = None
    if global_readiness is not None:
        global_ready = bool(global_readiness.ready)
        global_score = float(global_readiness.score)
        global_blockers = tuple(global_readiness.blocking_flags)
        if not global_ready:
            cautions.append("GLOBAL_LEAGUE_READINESS_BLOCKED")

    blockers = list(dict.fromkeys(blockers))
    cautions = [reason for reason in dict.fromkeys(cautions) if reason not in blockers]
    if blockers:
        status = "BLOCKED"
    elif cautions:
        status = "CAUTION"
    else:
        status = "READY"

    return DraftActionabilityReport(
        status=status,
        actionable=not blockers,
        blocking_reasons=tuple(blockers),
        caution_reasons=tuple(cautions),
        candidate_rows=int(len(candidates)),
        candidate_player_ids=candidate_ids,
        candidate_positions=candidate_positions,
        missing_candidate_player_ids=missing_ids,
        exact_scoring_coverage=float(exact_scoring_coverage),
        valuation_coverage=float(valuation_coverage),
        market_coverage=float(market_coverage),
        market_source=market_source,
        global_league_ready=global_ready,
        global_readiness_score=global_score,
        global_blocking_reasons=global_blockers,
        unsupported_required_positions=unsupported,
    )
