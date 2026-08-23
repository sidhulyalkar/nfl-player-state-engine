from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from player_state_engine.data.io import read_table
from player_state_engine.product.provenance import artifact_metadata, frame_records
from player_state_engine.state_graph.experiments import (
    EvidenceTier,
    ExperimentRecord,
    PromotionPolicy,
    consistency_rate,
    paired_block_bootstrap,
)


@dataclass(frozen=True, slots=True)
class ScenarioControls:
    """Explicit sensitivity controls, not inferred football facts."""

    role_multiplier: float = 1.0
    team_volume_multiplier: float = 1.0
    availability_probability: float | None = None

    def __post_init__(self) -> None:
        if not 0.5 <= self.role_multiplier <= 1.5:
            raise ValueError("role_multiplier must be between 0.5 and 1.5")
        if not 0.75 <= self.team_volume_multiplier <= 1.25:
            raise ValueError("team_volume_multiplier must be between 0.75 and 1.25")
        if self.availability_probability is not None and not 0.0 <= self.availability_probability <= 1.0:
            raise ValueError("availability_probability must be between 0 and 1")


class StateGraphArtifactStore:
    """Read-only adapter over Player State Graph research outputs.

    Missing artifacts are intentionally represented as unavailable. The product layer must never
    synthesize latent states just so a comparison card has something to render.
    """

    def __init__(self, root: str | Path = "artifacts/player_state_graph") -> None:
        self.root = Path(root)
        self.summary_path = self.root / "player_state_graph_summaries.parquet"
        self.roles_path = self.root / "dynamic_role_states.parquet"
        self.draws_path = self.root / "coherent_scored_draws.parquet"
        self.evaluation_path = self.root / "shadow_evaluation.json"

    @staticmethod
    def _read(path: Path) -> pd.DataFrame:
        if not path.is_file():
            return pd.DataFrame()
        return read_table(path)

    def health(self) -> dict[str, object]:
        artifacts = {
            "summaries": artifact_metadata(self.summary_path),
            "roles": artifact_metadata(self.roles_path),
            "draws": artifact_metadata(self.draws_path),
        }
        return {
            "root": self.root.as_posix(),
            "available": bool(artifacts["summaries"]["available"]),
            "artifacts": artifacts,
        }

    def latest_player(self, player_id: str) -> dict[str, object] | None:
        frame = self._read(self.summary_path)
        if frame.empty or "player_id" not in frame:
            return None
        rows = frame.loc[frame["player_id"].astype(str).eq(str(player_id))].copy()
        if rows.empty:
            return None
        sort_columns = [column for column in ("season", "week") if column in rows]
        if sort_columns:
            rows = rows.sort_values(sort_columns, ascending=[False] * len(sort_columns))
        return frame_records(rows.head(1))[0]

    def player_role(self, player_id: str, *, season: int | None = None, week: int | None = None) -> dict[str, object] | None:
        frame = self._read(self.roles_path)
        if frame.empty or "player_id" not in frame:
            return None
        rows = frame.loc[frame["player_id"].astype(str).eq(str(player_id))].copy()
        if season is not None and "season" in rows:
            rows = rows.loc[pd.to_numeric(rows["season"], errors="coerce").eq(season)]
        if week is not None and "week" in rows:
            rows = rows.loc[pd.to_numeric(rows["week"], errors="coerce").eq(week)]
        if rows.empty:
            return None
        sort_columns = [column for column in ("season", "week") if column in rows]
        if sort_columns:
            rows = rows.sort_values(sort_columns, ascending=[False] * len(sort_columns))
        return frame_records(rows.head(1))[0]

    def opportunity_audit(self, player_id: str) -> dict[str, object]:
        player = self.latest_player(player_id)
        if player is None:
            return {
                "available": False,
                "reason": "player_state_graph_summary_unavailable",
                "target_share": None,
                "carry_share": None,
            }
        season = _int_or_none(player.get("season"))
        week = _int_or_none(player.get("week"))
        team = str(player.get("team") or "")
        roles = self._read(self.roles_path)
        if roles.empty or not {"team", "player_id"}.issubset(roles.columns):
            return {
                "available": False,
                "reason": "dynamic_role_state_artifact_unavailable",
                "team": team or None,
                "season": season,
                "week": week,
            }
        rows = roles.loc[roles["team"].astype(str).eq(team)].copy()
        if season is not None and "season" in rows:
            rows = rows.loc[pd.to_numeric(rows["season"], errors="coerce").eq(season)]
        if week is not None and "week" in rows:
            rows = rows.loc[pd.to_numeric(rows["week"], errors="coerce").eq(week)]
        if rows.empty:
            return {
                "available": False,
                "reason": "team_week_role_state_unavailable",
                "team": team or None,
                "season": season,
                "week": week,
            }
        return {
            "available": True,
            "authority": "research_audit_only",
            "team": team,
            "season": season,
            "week": week,
            "target_share": _opportunity_family(rows, "target_share_mean", player_id),
            "carry_share": _opportunity_family(rows, "carry_share_mean", player_id),
            "note": (
                "Raw independent role posteriors are shown beside the coherent sampler support. "
                "If modeled shares exceed 100%, the sampler proportionally projects them back to "
                "legal support; if they are below 100%, residual opportunity belongs to unmodeled teammates."
            ),
        }

    def player_comparison(
        self,
        player_id: str,
        *,
        production_week_projection: dict[str, float | None],
    ) -> dict[str, object]:
        graph = self.latest_player(player_id)
        if graph is None:
            return {
                "available": False,
                "reason": "player_state_graph_artifact_unavailable_for_player",
                "authority": "research_challenger",
            }
        graph_projection = {
            "q10": _finite(graph.get("q10")),
            "q50": _finite(graph.get("q50")),
            "q90": _finite(graph.get("q90")),
        }
        comparable = all(
            production_week_projection.get(key) is not None and graph_projection.get(key) is not None
            for key in ("q10", "q50", "q90")
        )
        if comparable:
            direct_q50 = float(production_week_projection["q50"] or 0.0)
            graph_q50 = float(graph_projection["q50"] or 0.0)
            direct_width = float(production_week_projection["q90"] or 0.0) - float(
                production_week_projection["q10"] or 0.0
            )
            graph_width = float(graph_projection["q90"] or 0.0) - float(
                graph_projection["q10"] or 0.0
            )
            median_delta = graph_q50 - direct_q50
            width_delta = graph_width - direct_width
            overlap = _interval_overlap(
                float(production_week_projection["q10"] or 0.0),
                float(production_week_projection["q90"] or 0.0),
                float(graph_projection["q10"] or 0.0),
                float(graph_projection["q90"] or 0.0),
            )
        else:
            median_delta = None
            width_delta = None
            overlap = None
        return {
            "available": True,
            "comparable_horizon": comparable,
            "production": production_week_projection,
            "challenger": graph_projection,
            "disagreement": {
                "median_delta": median_delta,
                "interval_width_delta": width_delta,
                "interval_overlap_ratio": overlap,
                "direction": (
                    "challenger_higher"
                    if median_delta is not None and median_delta > 0.25
                    else "challenger_lower"
                    if median_delta is not None and median_delta < -0.25
                    else "aligned"
                    if median_delta is not None
                    else "not_comparable"
                ),
            },
            "graph_context": {
                key: graph.get(key)
                for key in (
                    "season",
                    "week",
                    "team",
                    "opponent",
                    "position",
                    "probability_active",
                    "role_change_probability",
                    "role_maturity",
                    "regime_maturity",
                    "model_source",
                )
                if key in graph
            },
            "authority": {
                "production": "authoritative",
                "challenger": "research_only",
                "may_change_decision": False,
            },
        }

    def scenario_sensitivity(
        self,
        player_id: str,
        *,
        production_week_projection: dict[str, float | None],
        baseline_availability: float | None,
        controls: ScenarioControls,
    ) -> dict[str, object]:
        comparison = self.player_comparison(
            player_id,
            production_week_projection=production_week_projection,
        )
        production = _stress_distribution(
            production_week_projection,
            baseline_availability=baseline_availability,
            controls=controls,
        )
        challenger_projection = comparison.get("challenger") if comparison.get("available") else None
        challenger = (
            _stress_distribution(
                challenger_projection,
                baseline_availability=_finite(
                    (comparison.get("graph_context") or {}).get("probability_active")
                    if isinstance(comparison.get("graph_context"), dict)
                    else None
                ),
                controls=controls,
            )
            if isinstance(challenger_projection, dict)
            else None
        )
        return {
            "semantics": "sensitivity_only_not_calibrated_forecast",
            "engine": "bounded_distribution_stress_v1",
            "controls": asdict(controls),
            "production": production,
            "challenger": challenger,
            "authority": {
                "may_override_production": False,
                "note": (
                    "This is a transparent stress transform around existing distributions. It is useful "
                    "for counterfactual reasoning, but it is not a retrained or recalibrated forecast."
                ),
            },
        }


def evaluate_shadow_replay(
    champion_predictions: pd.DataFrame,
    challenger_predictions: pd.DataFrame,
    *,
    experiment_id: str = "player_state_graph_shadow_replay",
    bootstrap_samples: int = 2000,
    seed: int = 42,
) -> dict[str, object]:
    """Paired frozen replay for the graph challenger with fail-closed promotion authority."""

    champion = _normalize_champion_predictions(champion_predictions)
    challenger = _normalize_challenger_predictions(challenger_predictions)
    keys = [column for column in ("player_id", "season", "week") if column in champion and column in challenger]
    if keys != ["player_id", "season", "week"]:
        raise ValueError("Shadow replay requires player_id, season, and week in both artifacts")
    paired = champion.merge(challenger, on=keys, how="inner", suffixes=("_champion", "_challenger"))
    if "position_champion" in paired:
        paired["position"] = paired["position_champion"]
    elif "position" not in paired and "position_challenger" in paired:
        paired["position"] = paired["position_challenger"]
    paired["actual"] = pd.to_numeric(paired["actual"], errors="coerce")
    for side in ("champion", "challenger"):
        for quantile in ("q10", "q50", "q90"):
            column = f"{quantile}_{side}"
            paired[column] = pd.to_numeric(paired[column], errors="coerce")
    paired = paired.dropna(
        subset=[
            "actual",
            "q10_champion",
            "q50_champion",
            "q90_champion",
            "q10_challenger",
            "q50_challenger",
            "q90_challenger",
        ]
    ).copy()
    if paired.empty:
        raise ValueError("No paired frozen observations between champion and challenger")

    for side in ("champion", "challenger"):
        paired[f"pinball_{side}"] = (
            _pinball_vector(paired["actual"], paired[f"q10_{side}"], 0.1)
            + _pinball_vector(paired["actual"], paired[f"q50_{side}"], 0.5)
            + _pinball_vector(paired["actual"], paired[f"q90_{side}"], 0.9)
        ) / 3.0
        paired[f"absolute_error_{side}"] = (paired["actual"] - paired[f"q50_{side}"]).abs()
        paired[f"covered_{side}"] = (
            (paired["actual"] >= paired[f"q10_{side}"])
            & (paired["actual"] <= paired[f"q90_{side}"])
        ).astype(float)
        paired[f"width_{side}"] = paired[f"q90_{side}"] - paired[f"q10_{side}"]
    paired["effect"] = paired["pinball_champion"] - paired["pinball_challenger"]

    seasons = int(paired["season"].nunique())
    tier = EvidenceTier.MULTI_SEASON_ISOLATED if seasons >= 2 else EvidenceTier.SINGLE_HISTORICAL_SLICE
    bootstrap = None
    try:
        bootstrap = paired_block_bootstrap(
            paired,
            champion_column="pinball_champion",
            challenger_column="pinball_challenger",
            bootstrap_samples=bootstrap_samples,
            seed=seed,
        )
    except ValueError:
        pass
    effect = float(paired["effect"].mean()) if bootstrap is None else bootstrap.effect
    ci_low = float("nan") if bootstrap is None else bootstrap.ci_low
    ci_high = float("nan") if bootstrap is None else bootstrap.ci_high
    overlap_denominator = max(1, min(len(champion), len(challenger)))
    overlap = min(1.0, len(paired) / overlap_denominator)
    record = ExperimentRecord(
        experiment_id=experiment_id,
        challenger="player_state_graph",
        champion="direct_player_quantile_model",
        primary_metric="mean_pinball",
        evidence_tier=tier,
        effect=effect,
        ci_low=ci_low,
        ci_high=ci_high,
        season_consistency=consistency_rate(paired, effect_column="effect", group_columns=("season",)),
        position_consistency=consistency_rate(paired, effect_column="effect", group_columns=("position",)),
        week_consistency=consistency_rate(paired, effect_column="effect", group_columns=("season", "week")),
        coverage=overlap,
        data_availability=overlap,
        negative_control_passed=False,
        downstream_decision_effect=None,
    )
    PromotionPolicy().evaluate(record)
    return {
        "data_mode": "HISTORICAL_BACKTEST",
        "authority": "research_shadow_only",
        "paired_rows": len(paired),
        "seasons": seasons,
        "metrics": {
            "champion_mean_pinball": float(paired["pinball_champion"].mean()),
            "challenger_mean_pinball": float(paired["pinball_challenger"].mean()),
            "pinball_effect_champion_minus_challenger": effect,
            "champion_q50_mae": float(paired["absolute_error_champion"].mean()),
            "challenger_q50_mae": float(paired["absolute_error_challenger"].mean()),
            "champion_80_coverage": float(paired["covered_champion"].mean()),
            "challenger_80_coverage": float(paired["covered_challenger"].mean()),
            "champion_mean_width": float(paired["width_champion"].mean()),
            "challenger_mean_width": float(paired["width_challenger"].mean()),
            "overlap_rate": overlap,
        },
        "bootstrap": asdict(bootstrap) if bootstrap is not None else None,
        "promotion_record": record.to_dict(),
        "promotion_status": "eligible" if record.promoted else "blocked",
        "blockers": record.blockers,
        "note": (
            "A better paired loss is not enough for promotion. Negative controls, downstream decision "
            "evidence, coverage, consistency, and the configured evidence tier remain mandatory."
        ),
    }


def _opportunity_family(rows: pd.DataFrame, column: str, player_id: str) -> dict[str, object] | None:
    if column not in rows:
        return None
    values = pd.to_numeric(rows[column], errors="coerce").clip(lower=0.0).fillna(0.0)
    raw_total = float(values.sum())
    scale = 1.0 / raw_total if raw_total > 1.0 else 1.0
    normalized = values * scale
    residual = max(0.0, 1.0 - float(normalized.sum()))
    output = rows.loc[:, [name for name in ("player_id", "position") if name in rows]].copy()
    output["raw_share"] = values
    output["coherent_share"] = normalized
    output["is_selected_player"] = output["player_id"].astype(str).eq(str(player_id))
    output = output.sort_values("coherent_share", ascending=False)
    return {
        "raw_modeled_total": raw_total,
        "normalization_applied": raw_total > 1.0,
        "normalization_scale": scale,
        "coherent_modeled_total": float(normalized.sum()),
        "residual_unmodeled_share": residual,
        "players": frame_records(output),
    }


def _stress_distribution(
    projection: dict[str, Any] | None,
    *,
    baseline_availability: float | None,
    controls: ScenarioControls,
) -> dict[str, object] | None:
    if not isinstance(projection, dict):
        return None
    q10 = _finite(projection.get("q10"))
    q50 = _finite(projection.get("q50"))
    q90 = _finite(projection.get("q90"))
    if q10 is None or q50 is None or q90 is None:
        return None
    low, median, high = sorted((q10, q50, q90))
    base_availability = float(np.clip(baseline_availability if baseline_availability is not None else 1.0, 0.05, 1.0))
    new_availability = float(
        np.clip(
            controls.availability_probability
            if controls.availability_probability is not None
            else base_availability,
            0.0,
            1.0,
        )
    )
    availability_factor = new_availability / base_availability
    volume_factor = controls.role_multiplier * controls.team_volume_multiplier
    center_factor = volume_factor * availability_factor
    stressed_median = max(0.0, median * center_factor)
    uncertainty_factor = (
        1.0
        + 0.35 * abs(controls.role_multiplier - 1.0)
        + 0.25 * abs(controls.team_volume_multiplier - 1.0)
        + 0.50 * max(0.0, base_availability - new_availability)
    )
    stressed_low = max(0.0, stressed_median - (median - low) * volume_factor * uncertainty_factor)
    stressed_high = max(stressed_median, stressed_median + (high - median) * volume_factor * uncertainty_factor)
    return {
        "baseline": {"q10": low, "q50": median, "q90": high},
        "scenario": {"q10": stressed_low, "q50": stressed_median, "q90": stressed_high},
        "median_delta": stressed_median - median,
        "center_factor": center_factor,
        "uncertainty_factor": uncertainty_factor,
        "baseline_availability": base_availability,
        "scenario_availability": new_availability,
    }


def _normalize_champion_predictions(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    mapping = {
        "fantasy_points_ppr_q10": "q10",
        "fantasy_points_ppr_q50": "q50",
        "fantasy_points_ppr_q90": "q90",
    }
    for source, target in mapping.items():
        if target not in data and source in data:
            data[target] = data[source]
    if "actual" not in data and "actual_fantasy_points_ppr" in data:
        data["actual"] = data["actual_fantasy_points_ppr"]
    required = {"player_id", "season", "week", "actual", "q10", "q50", "q90"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"Champion prediction artifact missing columns: {sorted(missing)}")
    return data


def _normalize_challenger_predictions(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    required = {"player_id", "season", "week", "q10", "q50", "q90"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"Challenger prediction artifact missing columns: {sorted(missing)}")
    keep = [column for column in ("player_id", "season", "week", "position", "q10", "q50", "q90") if column in data]
    return data.loc[:, keep]


def _pinball_vector(actual: pd.Series, prediction: pd.Series, quantile: float) -> pd.Series:
    error = actual - prediction
    return pd.Series(np.maximum(quantile * error, (quantile - 1.0) * error), index=actual.index)


def _finite(value: object) -> float | None:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if np.isfinite(numeric) else None


def _int_or_none(value: object) -> int | None:
    numeric = _finite(value)
    return int(numeric) if numeric is not None else None


def _interval_overlap(a_low: float, a_high: float, b_low: float, b_high: float) -> float:
    low = max(a_low, b_low)
    high = min(a_high, b_high)
    intersection = max(0.0, high - low)
    union = max(a_high, b_high) - min(a_low, b_low)
    return intersection / union if union > 0 else 1.0
