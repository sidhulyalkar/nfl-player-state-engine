from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from player_state_engine.fantasy.decision_board import DecisionType, build_decision_board
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.product.league_picture import attach_ownership
from player_state_engine.product.provenance import frame_records
from player_state_engine.product.schemas import LeagueSnapshot


@dataclass(frozen=True, slots=True)
class PlayerProjectionShape:
    q10: float | None
    q50: float | None
    q90: float | None
    interval_width: float | None
    downside_from_median: float | None
    upside_from_median: float | None
    relative_interval_width: float | None

    def as_dict(self) -> dict[str, float | None]:
        return {
            "q10": self.q10,
            "q50": self.q50,
            "q90": self.q90,
            "interval_width": self.interval_width,
            "downside_from_median": self.downside_from_median,
            "upside_from_median": self.upside_from_median,
            "relative_interval_width": self.relative_interval_width,
        }


def _finite(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _text(value: object) -> str | None:
    if value is None:
        return None
    try:
        if not bool(pd.notna(value)):
            return None
    except (TypeError, ValueError):
        return None
    text = str(value).strip()
    return text or None


def _first_finite(row: pd.Series, names: tuple[str, ...]) -> float | None:
    for name in names:
        if name in row:
            value = _finite(row.get(name))
            if value is not None:
                return value
    return None


def _projection_shape(row: pd.Series) -> PlayerProjectionShape:
    q10 = _first_finite(
        row,
        ("valuation_points_q10", "season_points_q10", "fantasy_points_ppr_q10", "week_points_q10"),
    )
    q50 = _first_finite(
        row,
        ("valuation_points_q50", "season_points_q50", "fantasy_points_ppr_q50", "week_points_q50"),
    )
    q90 = _first_finite(
        row,
        ("valuation_points_q90", "season_points_q90", "fantasy_points_ppr_q90", "week_points_q90"),
    )
    if q10 is None or q50 is None or q90 is None:
        return PlayerProjectionShape(q10, q50, q90, None, None, None, None)
    ordered = sorted((q10, q50, q90))
    q10, q50, q90 = ordered
    width = max(q90 - q10, 0.0)
    relative = width / max(abs(q50), 5.0)
    return PlayerProjectionShape(
        q10=q10,
        q50=q50,
        q90=q90,
        interval_width=width,
        downside_from_median=max(q50 - q10, 0.0),
        upside_from_median=max(q90 - q50, 0.0),
        relative_interval_width=relative,
    )


def _signal_rows(row: pd.Series) -> list[dict[str, object]]:
    specs = (
        ("availability", "Availability", _finite(row.get("availability_probability"))),
        ("opportunity", "Opportunity confidence", _finite(row.get("opportunity_confidence"))),
        ("breakout", "Breakout probability", _finite(row.get("breakout_probability"))),
        ("role_growth", "Role growth", _finite(row.get("role_growth_score"))),
        ("scheme_fit", "Scheme fit", _finite(row.get("scheme_fit_score"))),
        ("schedule", "Schedule", _finite(row.get("schedule_score"))),
        ("playoff_schedule", "Playoff schedule", _finite(row.get("playoff_schedule_score"))),
        ("prospect_prior", "Prospect prior", _finite(row.get("prospect_prior_score"))),
    )
    signals: list[dict[str, object]] = []
    for key, label, value in specs:
        if value is None:
            continue
        if key == "availability":
            status = "risk" if value < 0.75 else "watch" if value < 0.9 else "positive"
        elif value >= 0.7:
            status = "positive"
        elif value <= 0.3:
            status = "risk"
        else:
            status = "neutral"
        signals.append({"key": key, "label": label, "value": value, "status": status})
    return signals


def _decision_row(row: pd.Series, decision: DecisionType) -> dict[str, object]:
    return {
        "decision": decision.value,
        "score": _finite(row.get("decision_specific_score")),
        "percentile": _finite(row.get("decision_percentile")),
        "overall_rank": int(row["overall_rank"]) if pd.notna(row.get("overall_rank")) else None,
        "position_rank": int(row["position_rank"]) if pd.notna(row.get("position_rank")) else None,
        "reasons": _text(row.get("decision_reasons")),
        "vorp": _finite(row.get("vorp")),
        "floor_vorp": _finite(row.get("floor_vorp")),
        "upside_vorp": _finite(row.get("upside_vorp")),
        "replacement_points": _finite(row.get("replacement_points")),
        "scarcity_score": _finite(row.get("scarcity_score")),
        "market_adp": _finite(row.get("market_adp")),
        "market_value_gap": _finite(row.get("market_value_gap")),
    }


def build_player_intelligence(
    projections: pd.DataFrame,
    config: LeagueConfig,
    snapshot: LeagueSnapshot,
    player_id: str,
    *,
    trust: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Build one league-specific player truth surface from authoritative product calculations.

    This function intentionally does not run the research Player State Graph or invent latent
    states. It exposes the current production projection, the exact league translation, and all
    decision-specific valuations in one contract while labeling research authority explicitly.
    """

    decisions: list[dict[str, object]] = []
    selected: pd.Series | None = None
    for decision in DecisionType:
        board = build_decision_board(projections, config, decision)
        board = attach_ownership(board, snapshot)
        match = board.loc[board["player_id"].astype(str).eq(str(player_id))]
        if match.empty:
            continue
        row = match.iloc[0]
        if selected is None:
            selected = row
        decisions.append(_decision_row(row, decision))

    if selected is None:
        raise KeyError(f"Player {player_id!r} is not present in the current projection artifact")

    shape = _projection_shape(selected)
    replacement = _finite(selected.get("replacement_points"))
    replacement_margins = {
        "q10": (shape.q10 - replacement if shape.q10 is not None and replacement is not None else None),
        "q50": (shape.q50 - replacement if shape.q50 is not None and replacement is not None else None),
        "q90": (shape.q90 - replacement if shape.q90 is not None and replacement is not None else None),
    }

    owner_roster_id = _text(selected.get("owner_roster_id"))
    owner_team_name = _text(selected.get("owner_team_name"))
    is_free_agent = bool(selected.get("is_free_agent", False))

    league_contract = {
        "teams": config.teams,
        "scoring": config.scoring,
        "roster_slots": dict(config.roster_slots),
        "flex_eligibility": {key: list(value) for key, value in config.flex_eligibility.items()},
        "risk_preference": config.risk_preference,
        "median_scoring": config.median_scoring,
        "median_game_weight": config.median_game_weight,
        "tight_end_premium": config.tight_end_premium,
        "faab_budget": config.faab_budget,
    }

    return {
        "player": {
            "player_id": str(selected["player_id"]),
            "player_name": _text(selected.get("player_name")) or str(selected["player_id"]),
            "position": _text(selected.get("position")),
            "team": _text(selected.get("recent_team")) or _text(selected.get("team")),
            "age": _finite(selected.get("age")),
            "owner_roster_id": owner_roster_id,
            "owner_team_name": owner_team_name,
            "is_free_agent": is_free_agent,
        },
        "projection": shape.as_dict(),
        "replacement_margins": replacement_margins,
        "decision_matrix": decisions,
        "signals": _signal_rows(selected),
        "raw_model_fields": frame_records(pd.DataFrame([selected.to_dict()]))[0],
        "league": league_contract,
        "trust": dict(trust or {}),
        "authority": {
            "production_projection_authoritative": True,
            "decision_board_authoritative": True,
            "player_state_graph_authority": "research_only",
            "forecast_trust_is_guardrail": True,
            "note": (
                "The latent Player State Graph remains a research challenger until frozen "
                "multi-season promotion gates pass."
            ),
        },
    }
