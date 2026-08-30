from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from typing import Literal

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.readiness import LeagueReadinessReport, assess_league_readiness

ReleaseStatus = Literal["READY", "PROVISIONAL", "BLOCKED"]
_SUPPORTED_DECISION_POLICIES = {"qualified_distribution", "q50_only"}
_SPECIAL_POSITIONS = {"K", "DST"}
_POSITION_ALIASES = {"DEF": "DST", "D/ST": "DST", "DEFENSE": "DST", "PK": "K"}


@dataclass(frozen=True, slots=True)
class LeagueReleaseAssessment:
    league: str
    status: ReleaseStatus
    scoring_contract_id: str
    decision_quantile_policy: str | None
    readiness: LeagueReadinessReport | None
    core_readiness: LeagueReadinessReport | None
    market_only_positions: tuple[str, ...]
    provisional_reasons: tuple[str, ...]
    blocking_reasons: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class DraftReleaseReport:
    status: ReleaseStatus
    can_use_core_draft_board: bool
    blocking_reasons: tuple[str, ...]
    provisional_reasons: tuple[str, ...]
    special_teams_supported_positions: tuple[str, ...]
    leagues: tuple[LeagueReleaseAssessment, ...]
    checked_at_utc: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _canonical_position(value: object) -> str:
    position = str(value or "").strip().upper()
    return _POSITION_ALIASES.get(position, position)


def _aware_utc(value: object) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(UTC)


def _is_fresh(value: object, now: datetime, max_age_hours: float) -> bool:
    parsed = _aware_utc(value)
    if parsed is None:
        return False
    age_hours = (now - parsed).total_seconds() / 3600.0
    return -0.25 <= age_hours <= float(max_age_hours)


def _exact_identity_count(value: object, expected_count: int) -> bool:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        return False
    identities = [str(item).strip() for item in value]
    return (
        expected_count > 0
        and len(identities) == expected_count
        and all(identities)
        and len(set(identities)) == expected_count
    )


def _special_teams_support(
    snapshot: Mapping[str, object] | None,
    *,
    now: datetime,
    max_age_hours: float,
) -> tuple[str, ...]:
    if not snapshot:
        return ()
    if snapshot.get("authority") != "external_market_only":
        return ()
    if bool(snapshot.get("model_fields_present", False)):
        return ()
    if not _is_fresh(snapshot.get("generated_at_utc"), now, max_age_hours):
        return ()

    supported: list[str] = []
    kicker_count = int(snapshot.get("kicker_count", 0) or 0)
    if (
        snapshot.get("kicker_identity_scheme") == "gsis_id"
        and _exact_identity_count(snapshot.get("kicker_ids"), kicker_count)
    ):
        supported.append("K")

    dst_count = int(snapshot.get("dst_count", 0) or 0)
    if (
        snapshot.get("dst_identity_scheme") == "team_abbr"
        and _exact_identity_count(snapshot.get("dst_ids"), dst_count)
    ):
        supported.append("DST")
    return tuple(supported)


def _core_config(config: LeagueConfig) -> LeagueConfig:
    roster_slots = {
        slot: count
        for slot, count in config.roster_slots.items()
        if _canonical_position(slot) not in _SPECIAL_POSITIONS
    }
    return replace(config, roster_slots=roster_slots, median_scoring=False)


def _frame_contract_id(frame: pd.DataFrame) -> str | None:
    if "scoring_contract_id" not in frame or frame.empty:
        return None
    values = frame["scoring_contract_id"].astype("string").dropna().str.strip()
    unique = tuple(sorted(set(values.loc[values.ne("")].astype(str))))
    return unique[0] if len(unique) == 1 else None


def _frame_decision_policy(frame: pd.DataFrame) -> str | None:
    if "decision_quantile_policy" not in frame or frame.empty:
        return None
    values = (
        frame["decision_quantile_policy"].astype("string").dropna().str.strip().str.lower()
    )
    unique = tuple(sorted(set(values.loc[values.ne("")].astype(str))))
    return unique[0] if len(unique) == 1 else None


def _required_market_only_positions(readiness: LeagueReadinessReport) -> tuple[str, ...]:
    needed: list[str] = []
    for position in _SPECIAL_POSITIONS:
        if position not in readiness.required_positions:
            continue
        exact = float(readiness.required_position_exact_scoring.get(position, 0.0))
        if position in readiness.missing_positions or exact < 0.80:
            needed.append(position)
    return tuple(sorted(needed))


def assess_draft_release_readiness(
    projection_sets: Mapping[str, pd.DataFrame],
    contract_metadata: Mapping[str, Mapping[str, object]],
    leagues: Mapping[str, LeagueConfig],
    *,
    bundle_authority: str,
    bundle_integrity_verified: bool,
    projection_source_cutoff_utc: datetime,
    nfl_hub_snapshot: Mapping[str, object],
    special_teams_market_snapshot: Mapping[str, object] | None = None,
    package_version: str | None = None,
    expected_release_version: str | None = None,
    now: datetime | None = None,
    projection_max_age_hours: float = 36.0,
    hub_max_age_hours: float = 12.0,
    special_teams_max_age_hours: float = 36.0,
    minimum_market_identity_coverage: float = 0.70,
    minimum_usable_market_players: int = 250,
) -> DraftReleaseReport:
    """Aggregate production readiness across exact fantasy scoring contracts.

    One immutable release bundle may contain multiple player projection slates. Each league is
    matched by ``LeagueConfig.scoring_contract_id`` so PPR and half-PPR can never share a slate by
    filename accident. Median-game policy and market-only K/DST support are isolated provisional
    overlays; neither can upgrade model authority or hide a broken skill-position scoring lane.
    """

    checked = (now or datetime.now(UTC)).astimezone(UTC)
    global_blockers: list[str] = []
    global_provisional: list[str] = []

    if bundle_authority != "production_approved":
        global_blockers.append("PROJECTION_BUNDLE_NOT_PRODUCTION_APPROVED")
    if not bundle_integrity_verified:
        global_blockers.append("PROJECTION_BUNDLE_INTEGRITY_UNVERIFIED")
    if expected_release_version is not None and package_version != expected_release_version:
        global_blockers.append("RELEASE_VERSION_NOT_FROZEN")
    if not _is_fresh(projection_source_cutoff_utc, checked, projection_max_age_hours):
        global_blockers.append("PROJECTION_SOURCE_CUTOFF_STALE")

    if nfl_hub_snapshot.get("authority") != "observational_nfl_state_only":
        global_blockers.append("NFL_HUB_AUTHORITY_INVALID")
    if not _is_fresh(nfl_hub_snapshot.get("generated_at_utc"), checked, hub_max_age_hours):
        global_blockers.append("NFL_HUB_STALE")
    required_failures = tuple(nfl_hub_snapshot.get("required_source_failures") or ())
    if required_failures:
        global_blockers.append("NFL_HUB_REQUIRED_SOURCE_FAILURE")
    hub_status = str(nfl_hub_snapshot.get("status") or "").upper()
    if hub_status not in {"READY", "DEGRADED"}:
        global_blockers.append("NFL_HUB_NOT_READY")
    elif hub_status == "DEGRADED":
        global_provisional.append("NFL_HUB_OPTIONAL_SOURCE_DEGRADED")

    market_identity = nfl_hub_snapshot.get("market_identity") or {}
    if not isinstance(market_identity, Mapping):
        market_identity = {}
    identity_coverage = float(market_identity.get("redraft_identity_coverage", 0.0) or 0.0)
    usable_market_players = int(market_identity.get("usable_market_players", 0) or 0)
    if identity_coverage < minimum_market_identity_coverage:
        global_blockers.append("NFL_HUB_MARKET_IDENTITY_COVERAGE_LOW")
    if usable_market_players < minimum_usable_market_players:
        global_blockers.append("NFL_HUB_MARKET_PLAYER_COVERAGE_LOW")

    special_supported = _special_teams_support(
        special_teams_market_snapshot,
        now=checked,
        max_age_hours=special_teams_max_age_hours,
    )
    special_supported_set = set(special_supported)

    league_results: list[LeagueReleaseAssessment] = []
    for name, config in leagues.items():
        contract_id = config.scoring_contract_id
        league_blockers: list[str] = []
        league_provisional: list[str] = []
        frame = projection_sets.get(contract_id)
        metadata = contract_metadata.get(contract_id)
        policy: str | None = None

        if frame is None or metadata is None:
            league_blockers.append("SCORING_CONTRACT_PROJECTIONS_MISSING")
            league_results.append(
                LeagueReleaseAssessment(
                    league=name,
                    status="BLOCKED",
                    scoring_contract_id=contract_id,
                    decision_quantile_policy=None,
                    readiness=None,
                    core_readiness=None,
                    market_only_positions=(),
                    provisional_reasons=(),
                    blocking_reasons=tuple(league_blockers),
                )
            )
            continue

        if str(metadata.get("scoring_contract_id") or "") != contract_id:
            league_blockers.append("SCORING_CONTRACT_METADATA_MISMATCH")
        if _frame_contract_id(frame) != contract_id:
            league_blockers.append("SCORING_CONTRACT_FRAME_MISMATCH")

        metadata_policy = str(metadata.get("decision_quantile_policy") or "").strip().lower()
        frame_policy = _frame_decision_policy(frame)
        if metadata_policy not in _SUPPORTED_DECISION_POLICIES:
            league_blockers.append("DECISION_QUANTILE_POLICY_UNQUALIFIED")
        elif frame_policy != metadata_policy:
            league_blockers.append("DECISION_QUANTILE_POLICY_MISMATCH")
        else:
            policy = metadata_policy

        readiness = assess_league_readiness(frame, config)
        core_readiness = assess_league_readiness(frame, _core_config(config))
        if not core_readiness.ready:
            league_blockers.extend(
                f"CORE_READINESS:{reason}" for reason in core_readiness.blocking_flags
            )

        market_only = _required_market_only_positions(readiness)
        unsupported_special = tuple(
            position for position in market_only if position not in special_supported_set
        )
        if unsupported_special:
            league_blockers.append(
                "MARKET_ONLY_SUPPORT_MISSING:" + ",".join(unsupported_special)
            )
        elif market_only:
            league_provisional.append("MARKET_ONLY_SPECIAL_TEAMS:" + ",".join(market_only))

        if config.median_scoring:
            league_provisional.append("MEDIAN_SCORING_POLICY_UNVALIDATED")

        if not readiness.ready and not league_blockers:
            allowed = {"MEDIAN_SCORING_POLICY_UNVALIDATED"}
            if market_only:
                allowed.update(
                    {
                        "MISSING_REQUIRED_POSITIONS",
                        "INEXACT_REQUIRED_POSITION_SCORING",
                        "READINESS_SCORE_BELOW_THRESHOLD",
                    }
                )
            unexpected = tuple(
                reason for reason in readiness.blocking_flags if reason not in allowed
            )
            if unexpected:
                league_blockers.extend(f"READINESS:{reason}" for reason in unexpected)

        status: ReleaseStatus
        if league_blockers:
            status = "BLOCKED"
        elif league_provisional:
            status = "PROVISIONAL"
        else:
            status = "READY"
        league_results.append(
            LeagueReleaseAssessment(
                league=name,
                status=status,
                scoring_contract_id=contract_id,
                decision_quantile_policy=policy,
                readiness=readiness,
                core_readiness=core_readiness,
                market_only_positions=market_only,
                provisional_reasons=tuple(dict.fromkeys(league_provisional)),
                blocking_reasons=tuple(dict.fromkeys(league_blockers)),
            )
        )

    for result in league_results:
        global_blockers.extend(f"{result.league}:{reason}" for reason in result.blocking_reasons)
        global_provisional.extend(
            f"{result.league}:{reason}" for reason in result.provisional_reasons
        )

    global_blockers = list(dict.fromkeys(global_blockers))
    global_provisional = list(dict.fromkeys(global_provisional))
    if global_blockers:
        status: ReleaseStatus = "BLOCKED"
    elif global_provisional:
        status = "PROVISIONAL"
    else:
        status = "READY"

    return DraftReleaseReport(
        status=status,
        can_use_core_draft_board=not global_blockers,
        blocking_reasons=tuple(global_blockers),
        provisional_reasons=tuple(global_provisional),
        special_teams_supported_positions=tuple(sorted(special_supported)),
        leagues=tuple(league_results),
        checked_at_utc=checked.isoformat(),
    )
