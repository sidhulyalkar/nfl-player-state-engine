from __future__ import annotations

import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
import pandas as pd

from player_state_engine.data.io import read_table, write_table

TOP_N_BY_POSITION: dict[str, int] = {"QB": 12, "RB": 24, "WR": 36, "TE": 12}
PRIMARY_POSITIONS = tuple(TOP_N_BY_POSITION)
ShowcaseWinner = Literal["model", "expert", "tie", "unavailable"]


@dataclass(frozen=True, slots=True)
class SnapshotProvenance:
    source: str
    captured_at_utc: str
    source_path: str | None = None


def _utc_iso(value: str | datetime) -> str:
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Snapshot timestamps must be timezone-aware.")
    return parsed.astimezone(UTC).isoformat()


def _required(frame: pd.DataFrame, columns: set[str], label: str) -> None:
    missing = sorted(columns - set(frame.columns))
    if missing:
        raise ValueError(f"{label} is missing required columns: {missing}")


def _numeric(frame: pd.DataFrame, column: str, *, label: str) -> pd.Series:
    values = pd.to_numeric(frame[column], errors="coerce")
    if values.isna().all():
        raise ValueError(f"{label} column {column!r} contains no numeric values.")
    return values


def _unique_player_rows(frame: pd.DataFrame, *, label: str) -> pd.DataFrame:
    if frame["player_id"].isna().any():
        raise ValueError(f"{label} contains missing player_id values.")
    data = frame.copy()
    data["player_id"] = data["player_id"].astype(str).str.strip()
    if data["player_id"].eq("").any():
        raise ValueError(f"{label} contains blank player_id values.")
    duplicated = data.loc[data["player_id"].duplicated(keep=False), "player_id"].unique().tolist()
    if duplicated:
        raise ValueError(f"{label} contains duplicate player_id rows: {duplicated[:8]}")
    return data


def normalize_model_snapshot(
    frame: pd.DataFrame,
    *,
    points_column: str,
    q10_column: str | None = None,
    q90_column: str | None = None,
) -> pd.DataFrame:
    _required(frame, {"player_id", "position", points_column}, "model snapshot")
    data = _unique_player_rows(frame, label="model snapshot")
    out = pd.DataFrame(index=data.index)
    out["player_id"] = data["player_id"]
    out["player_name"] = data.get("player_name", data["player_id"]).astype(str)
    out["position"] = data["position"].astype(str).str.upper().str.strip()
    out["nfl_team"] = data.get("nfl_team", data.get("recent_team", pd.Series("", index=data.index))).astype(str)
    out["model_points"] = _numeric(data, points_column, label="model snapshot")
    if q10_column and q10_column in data:
        out["model_q10"] = pd.to_numeric(data[q10_column], errors="coerce")
    if q90_column and q90_column in data:
        out["model_q90"] = pd.to_numeric(data[q90_column], errors="coerce")
    return out.reset_index(drop=True)


def normalize_expert_snapshot(
    frame: pd.DataFrame,
    *,
    rank_column: str,
    points_column: str | None = None,
) -> pd.DataFrame:
    _required(frame, {"player_id", rank_column}, "expert snapshot")
    data = _unique_player_rows(frame, label="expert snapshot")
    out = pd.DataFrame(index=data.index)
    out["player_id"] = data["player_id"]
    out["expert_rank"] = _numeric(data, rank_column, label="expert snapshot")
    if points_column:
        if points_column not in data:
            raise ValueError(f"expert snapshot is missing requested points column {points_column!r}")
        out["expert_points"] = _numeric(data, points_column, label="expert snapshot")
    if "position" in data:
        out["expert_position"] = data["position"].astype(str).str.upper().str.strip()
    return out.reset_index(drop=True)


def normalize_actuals_snapshot(frame: pd.DataFrame, *, points_column: str) -> pd.DataFrame:
    _required(frame, {"player_id", points_column}, "actuals snapshot")
    data = _unique_player_rows(frame, label="actuals snapshot")
    out = pd.DataFrame(index=data.index)
    out["player_id"] = data["player_id"]
    out["actual_points"] = _numeric(data, points_column, label="actuals snapshot")
    return out.reset_index(drop=True)


def _rank_descending(values: pd.Series) -> pd.Series:
    return pd.to_numeric(values, errors="coerce").rank(method="min", ascending=False)


def _spearman(predicted: pd.Series, actual: pd.Series) -> float | None:
    paired = pd.DataFrame({"predicted": predicted, "actual": actual}).dropna()
    if len(paired) < 3 or paired["predicted"].nunique() < 2 or paired["actual"].nunique() < 2:
        return None
    value = paired["predicted"].corr(paired["actual"], method="spearman")
    return None if pd.isna(value) else float(value)


def _finite_or_none(value: float | int | None) -> float | int | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _mean(values: pd.Series) -> float | None:
    numeric = pd.to_numeric(values, errors="coerce").dropna()
    return float(numeric.mean()) if len(numeric) else None


def _rmse(errors: pd.Series) -> float | None:
    numeric = pd.to_numeric(errors, errors="coerce").dropna()
    return float(np.sqrt(np.mean(np.square(numeric)))) if len(numeric) else None


def _top_n_hit_rate(frame: pd.DataFrame, rank_column: str, n: int) -> float | None:
    eligible = frame.loc[frame[rank_column].notna() & frame["actual_rank"].notna()]
    if eligible.empty:
        return None
    limit = min(int(n), len(eligible))
    predicted = set(eligible.nsmallest(limit, rank_column)["player_id"])
    actual = set(eligible.nsmallest(limit, "actual_rank")["player_id"])
    return float(len(predicted & actual) / limit) if limit else None


def _scope_metrics(frame: pd.DataFrame, *, position: str | None = None) -> dict[str, Any]:
    data = frame if position is None else frame.loc[frame["position"].eq(position)]
    result: dict[str, Any] = {"rows": int(len(data)), "position": position or "ALL"}
    if data.empty:
        return result

    model_error = data["model_points"] - data["actual_points"]
    result.update(
        {
            "model_mae": _mean(model_error.abs()),
            "model_rmse": _rmse(model_error),
            "model_bias": _mean(model_error),
            "model_spearman": _spearman(data["model_points"], data["actual_points"]),
            "model_rank_mae": _mean((data["model_rank"] - data["actual_rank"]).abs()),
            "expert_spearman": _spearman(-data["expert_rank"], data["actual_points"]),
            "expert_rank_mae": _mean((data["expert_rank"] - data["actual_rank"]).abs()),
        }
    )
    if "expert_points" in data:
        expert_error = data["expert_points"] - data["actual_points"]
        result.update(
            {
                "expert_mae": _mean(expert_error.abs()),
                "expert_rmse": _rmse(expert_error),
                "expert_bias": _mean(expert_error),
            }
        )
        if result["model_mae"] is not None and result["expert_mae"] is not None:
            result["model_mae_advantage"] = float(result["expert_mae"] - result["model_mae"])
    else:
        result.update({"expert_mae": None, "expert_rmse": None, "expert_bias": None, "model_mae_advantage": None})

    if position in TOP_N_BY_POSITION:
        n = TOP_N_BY_POSITION[position]
        result["top_n"] = n
        result["model_top_n_hit_rate"] = _top_n_hit_rate(data, "model_rank", n)
        result["expert_top_n_hit_rate"] = _top_n_hit_rate(data, "expert_rank", n)

    if {"model_q10", "model_q90"}.issubset(data.columns):
        interval = data.loc[data["model_q10"].notna() & data["model_q90"].notna()]
        if len(interval):
            covered = interval["actual_points"].between(interval["model_q10"], interval["model_q90"])
            result["model_interval_coverage_80"] = float(covered.mean())
            result["model_interval_coverage_gap"] = float(covered.mean() - 0.80)
            result["model_interval_mean_width"] = _mean(interval["model_q90"] - interval["model_q10"])
        else:
            result.update(
                {
                    "model_interval_coverage_80": None,
                    "model_interval_coverage_gap": None,
                    "model_interval_mean_width": None,
                }
            )
    else:
        result.update(
            {
                "model_interval_coverage_80": None,
                "model_interval_coverage_gap": None,
                "model_interval_mean_width": None,
            }
        )
    return {key: _finite_or_none(value) if isinstance(value, float) else value for key, value in result.items()}


def _lower_wins(model_value: float | None, expert_value: float | None, *, tolerance: float = 1e-9) -> ShowcaseWinner:
    if model_value is None or expert_value is None:
        return "unavailable"
    if abs(model_value - expert_value) <= tolerance:
        return "tie"
    return "model" if model_value < expert_value else "expert"


def _battle_winner(metrics: dict[str, Any]) -> tuple[ShowcaseWinner, str]:
    if metrics.get("expert_mae") is not None and metrics.get("model_mae") is not None:
        return _lower_wins(metrics["model_mae"], metrics["expert_mae"]), "fantasy_points_mae"
    return _lower_wins(metrics.get("model_rank_mae"), metrics.get("expert_rank_mae")), "position_rank_mae"


def evaluate_weekly_showcase(
    model: pd.DataFrame,
    expert: pd.DataFrame,
    actuals: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    merged = model.merge(expert, on="player_id", how="inner", validate="one_to_one").merge(
        actuals, on="player_id", how="inner", validate="one_to_one"
    )
    if merged.empty:
        raise ValueError("No player identities overlap across model, expert, and actual snapshots.")
    if "expert_position" in merged:
        conflicts = merged.loc[
            merged["expert_position"].notna()
            & merged["expert_position"].ne("")
            & merged["position"].ne(merged["expert_position"])
        ]
        if len(conflicts):
            examples = conflicts[["player_id", "position", "expert_position"]].head(8).to_dict("records")
            raise ValueError(f"Expert/model position identity conflicts detected: {examples}")

    merged["model_rank"] = merged.groupby("position", group_keys=False)["model_points"].rank(method="min", ascending=False)
    merged["actual_rank"] = merged.groupby("position", group_keys=False)["actual_points"].rank(method="min", ascending=False)
    merged["model_abs_error"] = (merged["model_points"] - merged["actual_points"]).abs()
    merged["model_rank_error"] = (merged["model_rank"] - merged["actual_rank"]).abs()
    merged["expert_rank_error"] = (merged["expert_rank"] - merged["actual_rank"]).abs()
    merged["rank_edge_vs_expert"] = merged["expert_rank_error"] - merged["model_rank_error"]
    if "expert_points" in merged:
        merged["expert_abs_error"] = (merged["expert_points"] - merged["actual_points"]).abs()
        merged["point_edge_vs_expert"] = merged["expert_abs_error"] - merged["model_abs_error"]
    else:
        merged["expert_abs_error"] = np.nan
        merged["point_edge_vs_expert"] = np.nan

    overall = _scope_metrics(merged)
    positions = {position: _scope_metrics(merged, position=position) for position in PRIMARY_POSITIONS if merged["position"].eq(position).any()}
    winner, winner_metric = _battle_winner(overall)
    position_battles: dict[str, dict[str, Any]] = {}
    for position, metrics in positions.items():
        position_winner, metric = _battle_winner(metrics)
        position_battles[position] = {"winner": position_winner, "metric": metric}

    metrics_payload = {
        "schema_version": 1,
        "primary_comparison_metric": winner_metric,
        "winner": winner,
        "overall": overall,
        "positions": positions,
        "position_battles": position_battles,
        "comparison_contract": {
            "expert_rank_is_ordinal": True,
            "expert_points_required_for_point_error_comparison": True,
            "missing_expert_points_do_not_block_rank_comparison": True,
            "model_interval_target_coverage": 0.80,
        },
    }

    best_calls = merged.sort_values(["rank_edge_vs_expert", "model_abs_error"], ascending=[False, True]).head(5)
    misses = merged.sort_values(["model_rank_error", "model_abs_error"], ascending=[False, False]).head(5)
    position_wins = [position for position, battle in position_battles.items() if battle["winner"] == "model"]
    expert_wins = [position for position, battle in position_battles.items() if battle["winner"] == "expert"]
    narrative = {
        "schema_version": 1,
        "headline": (
            "Our model won the weekly comparison."
            if winner == "model"
            else "Expert consensus won the weekly comparison."
            if winner == "expert"
            else "The weekly comparison finished level."
            if winner == "tie"
            else "The weekly comparison is rank-only because expert point projections are unavailable."
        ),
        "winner": winner,
        "winner_metric": winner_metric,
        "model_position_wins": position_wins,
        "expert_position_wins": expert_wins,
        "best_calls": best_calls[["player_id", "player_name", "position", "model_rank", "expert_rank", "actual_rank", "rank_edge_vs_expert", "model_points", "actual_points"]].to_dict("records"),
        "biggest_misses": misses[["player_id", "player_name", "position", "model_rank", "expert_rank", "actual_rank", "model_rank_error", "model_points", "actual_points"]].to_dict("records"),
    }
    return merged.sort_values(["position", "actual_rank", "player_id"]).reset_index(drop=True), metrics_payload, narrative


def _canonical_frame_hash(frame: pd.DataFrame) -> str:
    ordered = frame.sort_values("player_id").reset_index(drop=True)
    payload = ordered.to_csv(index=False, lineterminator="\n", na_rep="").encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _canonical_json_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _atomic_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_weekly_showcase(
    *,
    model: pd.DataFrame,
    expert: pd.DataFrame,
    actuals: pd.DataFrame,
    season: int,
    week: int,
    scoring: str,
    model_provenance: SnapshotProvenance,
    expert_provenance: SnapshotProvenance,
    actuals_provenance: SnapshotProvenance,
    output_root: str | Path = "artifacts/evaluation/showcase",
) -> dict[str, Any]:
    if int(week) < 1 or int(week) > 22:
        raise ValueError("week must be between 1 and 22")
    normalized_provenance = {
        "model": {"source": model_provenance.source, "captured_at_utc": _utc_iso(model_provenance.captured_at_utc), "source_path": model_provenance.source_path},
        "expert": {"source": expert_provenance.source, "captured_at_utc": _utc_iso(expert_provenance.captured_at_utc), "source_path": expert_provenance.source_path},
        "actuals": {"source": actuals_provenance.source, "captured_at_utc": _utc_iso(actuals_provenance.captured_at_utc), "source_path": actuals_provenance.source_path},
    }
    identity = {
        "schema_version": 1,
        "season": int(season),
        "week": int(week),
        "scoring": str(scoring).strip().lower(),
        "snapshots": normalized_provenance,
        "input_hashes": {
            "model": _canonical_frame_hash(model),
            "expert": _canonical_frame_hash(expert),
            "actuals": _canonical_frame_hash(actuals),
        },
    }
    artifact_id = _canonical_json_hash(identity)
    week_root = Path(output_root) / str(int(season)) / f"week_{int(week):02d}"
    artifact_root = week_root / artifact_id
    manifest_path = artifact_root / "manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("artifact_id") != artifact_id:
            raise RuntimeError("Existing showcase manifest identity does not match directory identity.")
        return manifest

    players, metrics, narrative = evaluate_weekly_showcase(model, expert, actuals)
    artifact_root.mkdir(parents=True, exist_ok=False)
    files = {
        "model_snapshot": write_table(model, artifact_root / "model_snapshot.parquet"),
        "expert_snapshot": write_table(expert, artifact_root / "expert_snapshot.parquet"),
        "actuals": write_table(actuals, artifact_root / "actuals.parquet"),
        "player_deltas": write_table(players, artifact_root / "player_deltas.parquet"),
    }
    _atomic_json(artifact_root / "weekly_metrics.json", metrics)
    _atomic_json(artifact_root / "narrative_summary.json", narrative)
    manifest = {
        **identity,
        "artifact_id": artifact_id,
        "authority": "evaluation_only",
        "may_change_production_decisions": False,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "rows": int(len(players)),
        "metrics_file": "weekly_metrics.json",
        "narrative_file": "narrative_summary.json",
        "files": {key: path.name for key, path in files.items()},
        "winner": metrics["winner"],
        "primary_comparison_metric": metrics["primary_comparison_metric"],
    }
    _atomic_json(manifest_path, manifest)
    _atomic_json(week_root / "latest.json", {"artifact_id": artifact_id})
    return manifest


class WeeklyShowcaseStore:
    """Read immutable weekly showcase artifacts without granting them production authority."""

    def __init__(self, root: str | Path = "artifacts/evaluation/showcase") -> None:
        self.root = Path(root)

    def _week_root(self, season: int, week: int) -> Path:
        return self.root / str(int(season)) / f"week_{int(week):02d}"

    def _artifact_root(self, season: int, week: int, artifact_id: str | None = None) -> Path:
        week_root = self._week_root(season, week)
        if artifact_id is None:
            pointer = week_root / "latest.json"
            if not pointer.is_file():
                raise FileNotFoundError(pointer)
            artifact_id = str(json.loads(pointer.read_text(encoding="utf-8"))["artifact_id"])
        return week_root / artifact_id

    def index(self) -> dict[str, Any]:
        seasons: list[dict[str, Any]] = []
        if self.root.exists():
            for season_dir in sorted((path for path in self.root.iterdir() if path.is_dir()), reverse=True):
                if not season_dir.name.isdigit():
                    continue
                weeks = []
                for week_dir in sorted(path for path in season_dir.glob("week_*") if path.is_dir()):
                    pointer = week_dir / "latest.json"
                    if not pointer.is_file():
                        continue
                    try:
                        week = int(week_dir.name.split("_", 1)[1])
                    except (IndexError, ValueError):
                        continue
                    weeks.append(week)
                if weeks:
                    seasons.append({"season": int(season_dir.name), "weeks": weeks, "latest_week": max(weeks)})
        return {"authority": "evaluation_only", "may_change_production_decisions": False, "available": bool(seasons), "seasons": seasons}

    def week(self, season: int, week: int, *, artifact_id: str | None = None) -> dict[str, Any]:
        root = self._artifact_root(season, week, artifact_id)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        metrics = json.loads((root / manifest["metrics_file"]).read_text(encoding="utf-8"))
        narrative = json.loads((root / manifest["narrative_file"]).read_text(encoding="utf-8"))
        players = read_table(root / manifest["files"]["player_deltas"])
        players = players.replace({np.nan: None})
        return {"manifest": manifest, "metrics": metrics, "narrative": narrative, "players": players.to_dict("records")}

    def season(self, season: int) -> dict[str, Any]:
        season_dir = self.root / str(int(season))
        if not season_dir.is_dir():
            raise FileNotFoundError(season_dir)
        weeks: list[dict[str, Any]] = []
        for week_dir in sorted(path for path in season_dir.glob("week_*") if path.is_dir()):
            try:
                week = int(week_dir.name.split("_", 1)[1])
                payload = self.week(season, week)
            except (FileNotFoundError, KeyError, ValueError, json.JSONDecodeError):
                continue
            overall = payload["metrics"]["overall"]
            weeks.append(
                {
                    "week": week,
                    "artifact_id": payload["manifest"]["artifact_id"],
                    "winner": payload["metrics"]["winner"],
                    "primary_comparison_metric": payload["metrics"]["primary_comparison_metric"],
                    "model_mae": overall.get("model_mae"),
                    "expert_mae": overall.get("expert_mae"),
                    "model_rank_mae": overall.get("model_rank_mae"),
                    "expert_rank_mae": overall.get("expert_rank_mae"),
                    "model_spearman": overall.get("model_spearman"),
                    "expert_spearman": overall.get("expert_spearman"),
                    "rows": overall.get("rows"),
                }
            )
        model_wins = sum(item["winner"] == "model" for item in weeks)
        expert_wins = sum(item["winner"] == "expert" for item in weeks)
        ties = sum(item["winner"] == "tie" for item in weeks)
        return {
            "authority": "evaluation_only",
            "may_change_production_decisions": False,
            "season": int(season),
            "weeks": weeks,
            "record": {"model_wins": model_wins, "expert_wins": expert_wins, "ties": ties, "unavailable": len(weeks) - model_wins - expert_wins - ties},
        }
