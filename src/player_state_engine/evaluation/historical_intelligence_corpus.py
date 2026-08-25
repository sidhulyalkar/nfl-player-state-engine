from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from player_state_engine.data.historical import (
    RELEASE,
    canonicalize_depth_charts,
    canonicalize_injuries,
)
from player_state_engine.evaluation.historical_sources import (
    _kickoff_cutoffs,
    _point_in_time_depth,
)
from player_state_engine.evaluation.intelligence_provenance import (
    IntelligenceEvidenceProvenance,
)
from player_state_engine.intelligence.availability import OfficialAvailabilityEvidence
from player_state_engine.state_graph.experiments import EvidenceTier

HISTORICAL_NFLVERSE_INJURY_MAX_SEASON = 2024
DEFAULT_DEPTH_MAX_AGE_DAYS = 14.0
_PANEL_KEYS = ["season", "week", "player_id"]


@dataclass(slots=True, frozen=True)
class SourceArchiveVerification:
    verified: bool
    archive_identity_sha256: str | None
    files: tuple[dict[str, object], ...]
    failures: tuple[str, ...]


@dataclass(slots=True)
class HistoricalIntelligenceCorpus:
    official_evidence: pd.DataFrame
    source_coverage: pd.DataFrame
    provenance: IntelligenceEvidenceProvenance
    audit: dict[str, object]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_frame_digest(frame: pd.DataFrame) -> str:
    digest = hashlib.sha256()
    if frame.empty:
        digest.update(b"<empty>")
        return digest.hexdigest()
    normalized = frame.reindex(sorted(frame.columns), axis=1).copy()
    sort_columns = [
        column
        for column in ("season", "week", "player_id", "evidence_id", "game_id")
        if column in normalized
    ]
    if sort_columns:
        normalized = normalized.sort_values(sort_columns, kind="mergesort")
    digest.update(normalized.to_csv(index=False, na_rep="<NA>").encode("utf-8"))
    return digest.hexdigest()


def _clean_manifest_value(value: object) -> str:
    return "" if pd.isna(value) else str(value).strip()


def verify_source_archive_manifest(
    paths: Iterable[str | Path],
    manifest: pd.DataFrame,
) -> SourceArchiveVerification:
    """Verify archived evidence files against the immutable acquisition manifest."""

    required = {"path", "sha256", "status"}
    missing = required - set(manifest.columns)
    if missing:
        raise ValueError(f"Source manifest missing columns: {sorted(missing)}")

    rows: list[dict[str, object]] = []
    failures: list[str] = []
    working = manifest.copy()
    working["_basename"] = working["path"].astype(str).map(lambda value: Path(value).name)

    for raw_path in paths:
        path = Path(raw_path)
        matches = working.loc[working["_basename"].eq(path.name)]
        if len(matches) != 1:
            failures.append(f"manifest_match_count:{path.name}:{len(matches)}")
            continue
        record = matches.iloc[0]
        expected = _clean_manifest_value(record["sha256"]).lower()
        status = _clean_manifest_value(record["status"]).lower()
        if not path.is_file():
            failures.append(f"missing_file:{path.as_posix()}")
            continue
        actual = _sha256_file(path)
        if not status.startswith("available"):
            failures.append(f"manifest_status_not_available:{path.name}:{status}")
        if not expected or actual != expected:
            failures.append(f"sha256_mismatch:{path.name}")
        rows.append(
            {
                "name": path.name,
                "path": path.as_posix(),
                "bytes": path.stat().st_size,
                "sha256": actual,
                "manifest_sha256": expected,
                "manifest_status": status,
            }
        )

    archive_identity: str | None = None
    if rows and not failures:
        digest = hashlib.sha256()
        for row in sorted(rows, key=lambda item: str(item["name"])):
            digest.update(str(row["name"]).encode("utf-8"))
            digest.update(str(row["sha256"]).encode("ascii"))
        archive_identity = digest.hexdigest()
    return SourceArchiveVerification(
        verified=bool(rows) and not failures,
        archive_identity_sha256=archive_identity,
        files=tuple(rows),
        failures=tuple(failures),
    )


def _panel_with_cutoffs(
    panel: pd.DataFrame,
    schedules: pd.DataFrame,
    *,
    cutoff_hours_before: float,
) -> pd.DataFrame:
    required = {"season", "week", "game_id", "player_id", "recent_team"}
    missing = required - set(panel.columns)
    if missing:
        raise ValueError(f"Historical intelligence panel missing columns: {sorted(missing)}")
    if schedules is None or schedules.empty:
        raise ValueError("Historical intelligence corpus requires schedules for point-in-time cutoffs")

    data = panel[["season", "week", "game_id", "player_id", "recent_team"]].copy()
    data["season"] = pd.to_numeric(data["season"], errors="raise").astype(int)
    data["week"] = pd.to_numeric(data["week"], errors="raise").astype(int)
    for column in ("game_id", "player_id", "recent_team"):
        data[column] = data[column].astype(str).str.strip()
    if data[["game_id", "player_id", "recent_team"]].eq("").any().any():
        raise ValueError("Historical intelligence panel contains blank identity fields")
    if data.duplicated(_PANEL_KEYS).any():
        raise ValueError("Historical intelligence panel contains duplicate season/week/player_id rows")

    cutoffs = _kickoff_cutoffs(schedules, hours_before=cutoff_hours_before)
    data = data.merge(cutoffs, on="game_id", how="left", validate="many_to_one")
    data["prediction_cutoff"] = pd.to_datetime(
        data["prediction_cutoff"], utc=True, errors="coerce"
    )
    return data


def _normalized_text(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return " ".join(str(value).strip().lower().replace("_", " ").split())


def _practice_status(value: object) -> str:
    return {
        "full": "full",
        "full participation": "full",
        "limited": "limited",
        "limited participation": "limited",
        "did not participate": "did_not_participate",
        "dnp": "did_not_participate",
        "not listed": "not_listed",
    }.get(_normalized_text(value), "unknown")


def _game_status(value: object) -> str:
    return {
        "active": "active",
        "probable": "active",
        "questionable": "questionable",
        "doubtful": "doubtful",
        "out": "out",
        "ir": "ir",
        "injured reserve": "ir",
        "pup": "pup",
        "suspended": "suspended",
    }.get(_normalized_text(value), "unknown")


def _depth_role(rank: object) -> str:
    numeric = pd.to_numeric(pd.Series([rank]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "unknown"
    if int(numeric) <= 1:
        return "starter"
    if int(numeric) == 2:
        return "committee"
    return "backup"


def _evidence_id(payload: Mapping[str, object]) -> str:
    canonical = "|".join(f"{key}={payload[key]}" for key in sorted(payload))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]


def _source_url(
    mapping: Mapping[int, str] | None,
    season: int,
    *,
    family: str,
) -> str:
    if mapping is not None and int(season) in mapping:
        return str(mapping[int(season)])
    if family == "injuries":
        return f"{RELEASE}/injuries/injuries_{int(season)}.csv"
    return f"{RELEASE}/depth_charts/depth_charts_{int(season)}.rds"


def _latest_injury_rows(
    panel_cutoffs: pd.DataFrame,
    injuries: pd.DataFrame | None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    coverage = panel_cutoffs.copy()
    coverage["official_injury_report_source_covered"] = False
    coverage["injury_source_first_observed_at"] = pd.NaT
    if injuries is None or injuries.empty:
        return pd.DataFrame(), coverage

    injury = canonicalize_injuries(injuries)
    post_boundary = injury.loc[
        pd.to_numeric(injury["season"], errors="coerce").gt(HISTORICAL_NFLVERSE_INJURY_MAX_SEASON)
    ]
    if not post_boundary.empty:
        seasons = sorted(post_boundary["season"].dropna().astype(int).unique())
        raise ValueError(
            "nflverse historical injury evidence is not certified after 2024; "
            f"found seasons {seasons}. Use a separately archived prospective official source."
        )

    valid_source = injury.dropna(
        subset=["season", "week", "recent_team", "date_modified"]
    ).copy()
    team_first = (
        valid_source.groupby(["season", "week", "recent_team"], as_index=False)["date_modified"]
        .min()
        .rename(columns={"date_modified": "injury_source_first_observed_at"})
    )
    coverage = coverage.drop(columns=["injury_source_first_observed_at"]).merge(
        team_first,
        on=["season", "week", "recent_team"],
        how="left",
        validate="many_to_one",
    )
    coverage["official_injury_report_source_covered"] = (
        coverage["injury_source_first_observed_at"].notna()
        & coverage["prediction_cutoff"].notna()
        & coverage["injury_source_first_observed_at"].le(coverage["prediction_cutoff"])
    )

    keys = ["season", "week", "recent_team", "player_id"]
    candidates = panel_cutoffs[[*keys, "game_id", "prediction_cutoff"]].merge(
        injury, on=keys, how="left"
    )
    known = (
        candidates["date_modified"].notna()
        & candidates["prediction_cutoff"].notna()
        & candidates["date_modified"].le(candidates["prediction_cutoff"])
    )
    selected = (
        candidates.loc[known]
        .sort_values("date_modified")
        .drop_duplicates(["season", "week", "game_id", "player_id"], keep="last")
    )
    return selected, coverage


def _latest_team_depth_observation(
    coverage: pd.DataFrame,
    timestamped: pd.DataFrame,
) -> pd.Series:
    grouped_times: dict[tuple[int, str], pd.DatetimeIndex] = {}
    for (season, team), group in timestamped.groupby(["season", "recent_team"], sort=False):
        if pd.isna(season):
            continue
        grouped_times[(int(season), str(team))] = pd.DatetimeIndex(
            group["observed_at"].dropna().sort_values().unique()
        )

    observed = pd.Series(pd.NaT, index=coverage.index, dtype="datetime64[ns, UTC]")
    for (season, team), indexes in coverage.groupby(["season", "recent_team"], sort=False).groups.items():
        times = grouped_times.get((int(season), str(team)))
        if times is None or len(times) == 0:
            continue
        valid_indexes = [
            index for index in indexes if pd.notna(coverage.at[index, "prediction_cutoff"])
        ]
        if not valid_indexes:
            continue
        cutoffs = pd.DatetimeIndex(coverage.loc[valid_indexes, "prediction_cutoff"])
        positions = times.searchsorted(cutoffs, side="right") - 1
        for index, position in zip(valid_indexes, positions, strict=True):
            if position >= 0:
                observed.at[index] = times[int(position)]
    return observed


def _latest_depth_rows(
    panel: pd.DataFrame,
    panel_cutoffs: pd.DataFrame,
    schedules: pd.DataFrame,
    depth_charts: pd.DataFrame | None,
    *,
    cutoff_hours_before: float,
    maximum_age_days: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    coverage = panel_cutoffs.copy()
    coverage["official_depth_chart_source_covered"] = False
    coverage["depth_source_observed_at"] = pd.NaT
    coverage["depth_source_age_hours"] = np.nan
    if depth_charts is None or depth_charts.empty:
        return pd.DataFrame(), coverage

    depth = canonicalize_depth_charts(depth_charts)
    timestamped = depth.loc[
        depth["schema_status"].eq("supported_timestamped")
        & depth["player_id"].notna()
        & depth["observed_at"].notna()
        & depth["recent_team"].notna()
    ].copy()
    if timestamped.empty:
        return pd.DataFrame(), coverage

    coverage["depth_source_observed_at"] = _latest_team_depth_observation(coverage, timestamped)
    coverage["depth_source_age_hours"] = (
        coverage["prediction_cutoff"] - coverage["depth_source_observed_at"]
    ).dt.total_seconds() / 3600.0
    coverage["official_depth_chart_source_covered"] = (
        coverage["depth_source_observed_at"].notna()
        & coverage["depth_source_age_hours"].ge(0.0)
        & coverage["depth_source_age_hours"].le(float(maximum_age_days) * 24.0)
    )

    cutoffs = _kickoff_cutoffs(schedules, hours_before=cutoff_hours_before)
    point_in_time = _point_in_time_depth(panel, timestamped, cutoffs)
    point_in_time = point_in_time.merge(
        panel_cutoffs[["season", "week", "player_id", "prediction_cutoff"]],
        on=["season", "week", "player_id"],
        how="left",
        validate="one_to_one",
    )
    point_in_time["depth_evidence_age_hours"] = (
        point_in_time["prediction_cutoff"] - point_in_time["source_depth_observed_at"]
    ).dt.total_seconds() / 3600.0
    point_in_time = point_in_time.loc[
        point_in_time["source_depth_observed_at"].notna()
        & point_in_time["depth_evidence_age_hours"].ge(0.0)
        & point_in_time["depth_evidence_age_hours"].le(float(maximum_age_days) * 24.0)
    ].copy()
    return point_in_time, coverage


def _assert_evidence_precedes_cutoff(
    frame: pd.DataFrame,
    *,
    observed_column: str,
    label: str,
) -> None:
    if frame.empty:
        return
    observed = pd.to_datetime(frame[observed_column], utc=True, errors="coerce")
    cutoff = pd.to_datetime(frame["prediction_cutoff"], utc=True, errors="coerce")
    invalid = observed.isna() | cutoff.isna() | observed.gt(cutoff)
    if invalid.any():
        raise ValueError(
            f"{label} contains {int(invalid.sum())} rows not proven available before cutoff"
        )


def _official_evidence_frame(
    injury_rows: pd.DataFrame,
    depth_rows: pd.DataFrame,
    *,
    injury_source_urls: Mapping[int, str] | None,
    depth_source_urls: Mapping[int, str] | None,
) -> pd.DataFrame:
    evidence: list[OfficialAvailabilityEvidence] = []

    for row in injury_rows.to_dict(orient="records"):
        season = int(row["season"])
        observed = pd.Timestamp(row["date_modified"])
        source_url = _source_url(injury_source_urls, season, family="injuries")
        practice = _practice_status(row.get("practice_status"))
        game = _game_status(row.get("report_status"))
        injury_value = row.get("primary_injury")
        injury_text = None if injury_value is None or pd.isna(injury_value) else str(injury_value)
        if practice != "unknown":
            payload = {
                "family": "injuries",
                "season": season,
                "week": int(row["week"]),
                "player_id": str(row["player_id"]),
                "observed_at": observed.isoformat(),
                "event_type": "practice_participation",
                "status": practice,
            }
            evidence.append(
                OfficialAvailabilityEvidence(
                    evidence_id=_evidence_id(payload),
                    player_id=str(row["player_id"]),
                    observed_at_utc=observed.to_pydatetime(),
                    source_url=source_url,
                    event_type="practice_participation",
                    practice_status=practice,
                    evidence_text=(
                        f"Archived official injury-report practice status: {practice}; "
                        f"injury={injury_text}."
                    ),
                    source_reliability=0.98,
                )
            )
        if game != "unknown":
            payload = {
                "family": "injuries",
                "season": season,
                "week": int(row["week"]),
                "player_id": str(row["player_id"]),
                "observed_at": observed.isoformat(),
                "event_type": "game_designation",
                "status": game,
            }
            evidence.append(
                OfficialAvailabilityEvidence(
                    evidence_id=_evidence_id(payload),
                    player_id=str(row["player_id"]),
                    observed_at_utc=observed.to_pydatetime(),
                    source_url=source_url,
                    event_type="game_designation",
                    game_status=game,
                    evidence_text=(
                        f"Archived official injury-report game designation: {game}; "
                        f"injury={injury_text}."
                    ),
                    source_reliability=0.98,
                )
            )

    for row in depth_rows.to_dict(orient="records"):
        rank = pd.to_numeric(
            pd.Series([row.get("source_depth_rank_pit")]), errors="coerce"
        ).iloc[0]
        if pd.isna(rank):
            continue
        season = int(row["season"])
        observed = pd.Timestamp(row["source_depth_observed_at"])
        role = _depth_role(rank)
        payload = {
            "family": "depth_charts",
            "season": season,
            "week": int(row["week"]),
            "player_id": str(row["player_id"]),
            "observed_at": observed.isoformat(),
            "event_type": "depth_chart",
            "rank": int(rank),
        }
        evidence.append(
            OfficialAvailabilityEvidence(
                evidence_id=_evidence_id(payload),
                player_id=str(row["player_id"]),
                observed_at_utc=observed.to_pydatetime(),
                source_url=_source_url(depth_source_urls, season, family="depth_charts"),
                event_type="depth_chart",
                depth_role=role,
                depth_rank=int(rank),
                evidence_text=(
                    "Latest timestamped depth-chart snapshot before the frozen cutoff: "
                    f"role={role}; rank={int(rank)}."
                ),
                source_reliability=0.95,
            )
        )

    columns = list(OfficialAvailabilityEvidence.model_fields)
    if not evidence:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame([item.model_dump(mode="json") for item in evidence]).reindex(columns=columns)


def build_historical_intelligence_corpus(
    panel: pd.DataFrame,
    schedules: pd.DataFrame,
    *,
    injuries: pd.DataFrame | None = None,
    depth_charts: pd.DataFrame | None = None,
    include_injuries: bool = True,
    include_depth_charts: bool = False,
    cutoff_hours_before: float = 1.5,
    depth_maximum_age_days: float = DEFAULT_DEPTH_MAX_AGE_DAYS,
    source_archive_verified: bool = False,
    archive_identity_sha256: str | None = None,
    injury_source_urls: Mapping[int, str] | None = None,
    depth_source_urls: Mapping[int, str] | None = None,
) -> HistoricalIntelligenceCorpus:
    """Build frozen official evidence, source coverage, and authority provenance."""

    if not include_injuries and not include_depth_charts:
        raise ValueError("At least one historical intelligence source family must be enabled")
    if cutoff_hours_before < 0:
        raise ValueError("cutoff_hours_before cannot be negative")
    if depth_maximum_age_days <= 0:
        raise ValueError("depth_maximum_age_days must be positive")
    if source_archive_verified and not archive_identity_sha256:
        raise ValueError("Verified source archives require archive_identity_sha256")

    panel_cutoffs = _panel_with_cutoffs(
        panel,
        schedules,
        cutoff_hours_before=cutoff_hours_before,
    )
    injury_rows, injury_coverage = _latest_injury_rows(
        panel_cutoffs,
        injuries if include_injuries else None,
    )
    depth_rows, depth_coverage = _latest_depth_rows(
        panel,
        panel_cutoffs,
        schedules,
        depth_charts if include_depth_charts else None,
        cutoff_hours_before=cutoff_hours_before,
        maximum_age_days=depth_maximum_age_days,
    )
    _assert_evidence_precedes_cutoff(
        injury_rows,
        observed_column="date_modified",
        label="historical injury evidence",
    )
    _assert_evidence_precedes_cutoff(
        depth_rows,
        observed_column="source_depth_observed_at",
        label="historical depth evidence",
    )

    coverage = panel_cutoffs.copy()
    coverage = coverage.merge(
        injury_coverage[
            [
                *_PANEL_KEYS,
                "official_injury_report_source_covered",
                "injury_source_first_observed_at",
            ]
        ],
        on=_PANEL_KEYS,
        how="left",
        validate="one_to_one",
    )
    coverage = coverage.merge(
        depth_coverage[
            [
                *_PANEL_KEYS,
                "official_depth_chart_source_covered",
                "depth_source_observed_at",
                "depth_source_age_hours",
            ]
        ],
        on=_PANEL_KEYS,
        how="left",
        validate="one_to_one",
    )
    for column in (
        "official_injury_report_source_covered",
        "official_depth_chart_source_covered",
    ):
        coverage[column] = coverage[column].fillna(False).astype(bool)

    enabled_coverage_columns: list[str] = []
    if include_injuries:
        enabled_coverage_columns.append("official_injury_report_source_covered")
    if include_depth_charts:
        enabled_coverage_columns.append("official_depth_chart_source_covered")
    coverage["official_availability_source_covered"] = coverage[enabled_coverage_columns].any(axis=1)

    injury_evidence_keys = set(
        zip(
            injury_rows.get("season", pd.Series(dtype=int)),
            injury_rows.get("week", pd.Series(dtype=int)),
            injury_rows.get("player_id", pd.Series(dtype=str)),
            strict=False,
        )
    )
    depth_evidence_keys = set(
        zip(
            depth_rows.get("season", pd.Series(dtype=int)),
            depth_rows.get("week", pd.Series(dtype=int)),
            depth_rows.get("player_id", pd.Series(dtype=str)),
            strict=False,
        )
    )
    coverage["official_availability_evidence_found"] = [
        (season, week, player_id) in injury_evidence_keys
        or (season, week, player_id) in depth_evidence_keys
        for season, week, player_id in coverage[_PANEL_KEYS].itertuples(index=False, name=None)
    ]

    official_evidence = _official_evidence_frame(
        injury_rows,
        depth_rows,
        injury_source_urls=injury_source_urls,
        depth_source_urls=depth_source_urls,
    )
    covered_seasons = sorted(
        coverage.loc[coverage["official_availability_source_covered"], "season"]
        .dropna()
        .astype(int)
        .unique()
    )
    missing_cutoff_rows = int(coverage["prediction_cutoff"].isna().sum())
    point_in_time_verified = missing_cutoff_rows == 0
    coverage_point_in_time_verified = bool(source_archive_verified and point_in_time_verified)

    sample_digest = hashlib.sha256()
    sample_digest.update(str(archive_identity_sha256 or "unverified-archive").encode("utf-8"))
    sample_digest.update(_stable_frame_digest(official_evidence).encode("ascii"))
    sample_digest.update(
        _stable_frame_digest(
            coverage[
                [
                    "season",
                    "week",
                    "player_id",
                    "official_availability_source_covered",
                    "official_injury_report_source_covered",
                    "official_depth_chart_source_covered",
                ]
            ]
        ).encode("ascii")
    )
    frozen_sample_id = f"historical-official-{sample_digest.hexdigest()[:20]}"

    if (
        source_archive_verified
        and archive_identity_sha256
        and point_in_time_verified
        and coverage_point_in_time_verified
        and len(covered_seasons) >= 2
    ):
        tier = EvidenceTier.MULTI_SEASON_ISOLATED
    elif covered_seasons:
        tier = EvidenceTier.SINGLE_HISTORICAL_SLICE
    else:
        tier = EvidenceTier.SYNTHETIC_ONLY

    provenance = IntelligenceEvidenceProvenance(
        evidence_tier=int(tier),
        frozen_sample_id=frozen_sample_id if covered_seasons else None,
        point_in_time_verified=point_in_time_verified,
        source_coverage_point_in_time_verified=coverage_point_in_time_verified,
        description=(
            "Frozen historical official-intelligence corpus built from archived source rows "
            "selected strictly before schedule-derived player-game prediction cutoffs."
        ),
        metadata={
            "selected_source_families": [
                family
                for family, enabled in (
                    ("nflverse_injuries", include_injuries),
                    ("timestamped_depth_charts", include_depth_charts),
                )
                if enabled
            ],
            "covered_seasons": covered_seasons,
            "cutoff_hours_before_kickoff": float(cutoff_hours_before),
            "depth_maximum_age_days": float(depth_maximum_age_days),
            "nflverse_injury_certified_through_season": HISTORICAL_NFLVERSE_INJURY_MAX_SEASON,
            "source_archive_verified": bool(source_archive_verified),
            "archive_identity_sha256": archive_identity_sha256,
            "missing_cutoff_rows": missing_cutoff_rows,
            "authority": "research_evidence_only",
        },
    )

    audit = {
        "panel_rows": int(len(coverage)),
        "official_evidence_rows": int(len(official_evidence)),
        "injury_player_week_matches": int(len(injury_rows)),
        "depth_player_week_matches": int(len(depth_rows)),
        "source_covered_rows": int(coverage["official_availability_source_covered"].sum()),
        "source_coverage_rate": float(coverage["official_availability_source_covered"].mean()),
        "claim_prevalence_rate": float(coverage["official_availability_evidence_found"].mean()),
        "covered_seasons": covered_seasons,
        "missing_cutoff_rows": missing_cutoff_rows,
        "evidence_tier": int(tier),
        "automatic_promotion": False,
        "production_projection_changed": False,
    }

    return HistoricalIntelligenceCorpus(
        official_evidence=official_evidence.reset_index(drop=True),
        source_coverage=coverage[
            [
                "season",
                "week",
                "player_id",
                "game_id",
                "recent_team",
                "prediction_cutoff",
                "official_availability_source_covered",
                "official_injury_report_source_covered",
                "official_depth_chart_source_covered",
                "official_availability_evidence_found",
                "injury_source_first_observed_at",
                "depth_source_observed_at",
                "depth_source_age_hours",
            ]
        ].reset_index(drop=True),
        provenance=provenance,
        audit=audit,
    )
