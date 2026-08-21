from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from player_state_engine.fantasy.draft import DraftState
from player_state_engine.fantasy.league import LeagueConfig


@dataclass(frozen=True, slots=True)
class DecisionCandidateSnapshot:
    player_id: str
    player_name: str | None
    position: str | None
    rank: int | None
    action: str | None
    projected_value: float | None
    challenger_value: float | None
    survival_probability: float | None
    challenger_survival_probability: float | None
    reliability_score: float | None
    reasons: str | None


@dataclass(frozen=True, slots=True)
class DecisionAuditRecord:
    decision_id: str
    recorded_at: str
    league_key: str
    decision_type: str
    state_key: str
    recommendation_player_id: str | None
    recommendation_action: str | None
    candidates: tuple[DecisionCandidateSnapshot, ...]
    league_contract: Mapping[str, object]
    context: Mapping[str, object]
    model_metadata: Mapping[str, object]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _finite(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _optional_text(*values: object) -> str | None:
    for value in values:
        if value is None:
            continue
        try:
            if not bool(pd.notna(value)):
                continue
        except (TypeError, ValueError):
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _league_contract(config: LeagueConfig) -> dict[str, object]:
    return {
        "teams": config.teams,
        "scoring": config.scoring,
        "roster_slots": dict(config.roster_slots),
        "median_scoring": config.median_scoring,
        "median_game_weight": config.median_game_weight,
        "risk_preference": config.risk_preference,
        "tight_end_premium": config.tight_end_premium,
        "scoring_weights": dict(config.scoring_weights),
        "flex_eligibility": {key: list(value) for key, value in config.flex_eligibility.items()},
    }


def draft_state_key(state: DraftState) -> str:
    payload = {
        "teams": state.teams,
        "draft_slot": state.draft_slot,
        "current_pick": state.current_pick,
        "next_pick": state.next_pick,
        "total_rounds": state.total_rounds,
        "drafted_player_ids": sorted(str(value) for value in state.drafted_player_ids),
        "roster_player_ids": sorted(str(value) for value in state.roster_player_ids),
        "snake": state.snake,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]


def _decision_id(league_key: str, decision_type: str, state_key: str) -> str:
    canonical = f"{league_key}|{decision_type}|{state_key}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]


def build_draft_audit_record(
    board: pd.DataFrame,
    state: DraftState,
    config: LeagueConfig,
    *,
    league_key: str,
    top_n: int = 10,
    recorded_at: datetime | None = None,
    model_metadata: Mapping[str, object] | None = None,
) -> DecisionAuditRecord:
    """Capture the exact information set behind one live draft recommendation."""

    if board.empty:
        candidates: tuple[DecisionCandidateSnapshot, ...] = ()
        recommended_id = None
        recommended_action = None
    else:
        ordered = board.sort_values(
            ["live_rank", "player_id"], ascending=[True, True], kind="mergesort"
        ).head(max(1, int(top_n)))
        snapshots: list[DecisionCandidateSnapshot] = []
        for _, row in ordered.iterrows():
            snapshots.append(
                DecisionCandidateSnapshot(
                    player_id=str(row["player_id"]),
                    player_name=_optional_text(row.get("player_name")),
                    position=_optional_text(row.get("position")),
                    rank=(int(row["live_rank"]) if pd.notna(row.get("live_rank")) else None),
                    action=_optional_text(
                        row.get("guarded_draft_action"), row.get("draft_action")
                    ),
                    projected_value=_finite(row.get("live_draft_score")),
                    challenger_value=_finite(row.get("room_challenger_score")),
                    survival_probability=_finite(row.get("survival_to_next_pick")),
                    challenger_survival_probability=_finite(
                        row.get("room_survival_to_next_pick")
                    ),
                    reliability_score=_finite(row.get("draft_reliability_score")),
                    reasons=_optional_text(
                        row.get("draft_reliability_reasons"), row.get("draft_reasons")
                    ),
                )
            )
        candidates = tuple(snapshots)
        top = ordered.iloc[0]
        recommended_id = str(top["player_id"])
        recommended_action = _optional_text(
            top.get("guarded_draft_action"), top.get("draft_action")
        ) or "CONSIDER"

    state_key = draft_state_key(state)
    recorded = _utc(recorded_at or datetime.now(UTC)).isoformat()
    return DecisionAuditRecord(
        decision_id=_decision_id(str(league_key), "draft", state_key),
        recorded_at=recorded,
        league_key=str(league_key),
        decision_type="draft",
        state_key=state_key,
        recommendation_player_id=recommended_id,
        recommendation_action=recommended_action,
        candidates=candidates,
        league_contract=_league_contract(config),
        context={
            "draft_slot": state.draft_slot,
            "current_pick": state.current_pick,
            "next_pick": state.next_pick,
            "total_rounds": state.total_rounds,
            "roster_player_ids": list(state.roster_player_ids),
            "drafted_player_count": len(state.drafted_player_ids),
        },
        model_metadata=dict(model_metadata or {}),
    )


def append_decision_record(path: str | Path, record: DecisionAuditRecord) -> bool:
    """Append a state snapshot once; repeated refreshes of the same state are deduplicated."""

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        for line in destination.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(payload.get("decision_id")) == record.decision_id:
                return False
    with destination.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record.as_dict(), sort_keys=True, default=str) + "\n")
    return True


def load_decision_records(path: str | Path) -> list[dict[str, Any]]:
    source = Path(path)
    if not source.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in source.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        records.append(json.loads(line))
    return records


def settle_draft_decision_regret(
    records: Sequence[Mapping[str, Any]],
    outcomes: pd.DataFrame,
    *,
    player_id_column: str = "player_id",
    value_column: str = "realized_value",
) -> pd.DataFrame:
    """Measure hindsight regret only against alternatives visible at decision time.

    The outcome table can use realized season VORP, managed-points contribution, or downstream
    championship-probability utility. The function intentionally does not choose that utility
    for the caller; it merely preserves the correct information set for honest settlement.
    """

    required = {player_id_column, value_column}
    missing = required - set(outcomes.columns)
    if missing:
        raise ValueError(f"draft outcome table missing columns: {sorted(missing)}")
    values = outcomes[[player_id_column, value_column]].copy()
    values[player_id_column] = values[player_id_column].astype(str)
    values[value_column] = pd.to_numeric(values[value_column], errors="coerce")
    value_map = dict(zip(values[player_id_column], values[value_column], strict=False))

    rows: list[dict[str, object]] = []
    for record in records:
        candidates = list(record.get("candidates") or [])
        visible_values: list[tuple[str, float]] = []
        for candidate in candidates:
            player_id = str(candidate.get("player_id"))
            value = _finite(value_map.get(player_id))
            if value is not None:
                visible_values.append((player_id, value))
        recommendation = record.get("recommendation_player_id")
        recommended_value = _finite(value_map.get(str(recommendation))) if recommendation else None
        if not visible_values or recommended_value is None:
            best_player = None
            best_value = None
            regret = None
        else:
            best_player, best_value = max(visible_values, key=lambda item: item[1])
            regret = max(0.0, float(best_value) - float(recommended_value))
        rows.append(
            {
                "decision_id": record.get("decision_id"),
                "league_key": record.get("league_key"),
                "recorded_at": record.get("recorded_at"),
                "current_pick": (record.get("context") or {}).get("current_pick"),
                "recommendation_player_id": recommendation,
                "recommended_realized_value": recommended_value,
                "best_visible_player_id": best_player,
                "best_visible_realized_value": best_value,
                "decision_regret": regret,
            }
        )
    return pd.DataFrame(rows)
