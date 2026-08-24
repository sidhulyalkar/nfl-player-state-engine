from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

from player_state_engine.data.io import read_table
from player_state_engine.product.provenance import artifact_metadata, frame_records


@lru_cache(maxsize=32)
def _read_cached(path: str, modified_ns: int) -> pd.DataFrame:
    del modified_ns
    try:
        return read_table(path)
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def _read(path: Path) -> pd.DataFrame:
    return _read_cached(str(path.resolve()), path.stat().st_mtime_ns).copy()


class EvidenceArtifactStore:
    """Read-only Product API adapter over Evidence Factory outputs."""

    def __init__(self, root: str | Path = "artifacts/evidence_factory") -> None:
        self.root = Path(root)
        self.method_summary_path = self.root / "method_summary.csv"
        self.slice_metrics_path = self.root / "slice_metrics.csv"
        self.paired_comparisons_path = self.root / "paired_comparisons.csv"
        self.experiment_ledger_path = self.root / "experiment_ledger.csv"
        self.negative_controls_path = self.root / "negative_controls.csv"
        self.manifest_path = self.root / "run_manifest.json"

    def _manifest(self) -> dict[str, object] | None:
        if not self.manifest_path.is_file():
            return None
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        return payload if isinstance(payload, dict) else None

    def health(self) -> dict[str, object]:
        paths = {
            "method_summary": self.method_summary_path,
            "slice_metrics": self.slice_metrics_path,
            "paired_comparisons": self.paired_comparisons_path,
            "experiment_ledger": self.experiment_ledger_path,
            "negative_controls": self.negative_controls_path,
            "manifest": self.manifest_path,
        }
        metadata = {name: artifact_metadata(path) for name, path in paths.items()}
        available_count = sum(bool(item.get("available")) for item in metadata.values())
        return {
            "available": available_count == len(paths),
            "available_count": available_count,
            "expected_count": len(paths),
            "missing": [name for name, item in metadata.items() if not item.get("available")],
            "artifacts": metadata,
        }

    def snapshot(self, *, target: str | None = None) -> dict[str, object]:
        health = self.health()
        if not self.method_summary_path.is_file():
            return {
                "data_mode": "UNAVAILABLE",
                "authority": "research_evidence_only",
                "reason": "evidence_factory_artifacts_unavailable",
                "health": health,
            }

        method_summary = _read(self.method_summary_path)
        slice_metrics = (
            _read(self.slice_metrics_path) if self.slice_metrics_path.is_file() else pd.DataFrame()
        )
        paired = (
            _read(self.paired_comparisons_path)
            if self.paired_comparisons_path.is_file()
            else pd.DataFrame()
        )
        ledger = (
            _read(self.experiment_ledger_path)
            if self.experiment_ledger_path.is_file()
            else pd.DataFrame()
        )
        negative_controls = (
            _read(self.negative_controls_path)
            if self.negative_controls_path.is_file()
            else pd.DataFrame()
        )
        if target:
            for frame in (method_summary, slice_metrics, paired, negative_controls):
                if "target" in frame:
                    frame.drop(frame.index[~frame["target"].astype(str).eq(target)], inplace=True)
            if "experiment_id" in ledger:
                ledger = ledger.loc[
                    ledger["experiment_id"].astype(str).str.startswith(f"{target}:")
                ]

        manifest = self._manifest()
        champion_methods: dict[str, str] = {}
        default_champion_method = "quantile_engine"
        if manifest is not None:
            raw_champions = manifest.get("champion_methods")
            if isinstance(raw_champions, dict):
                champion_methods = {
                    str(key): str(value)
                    for key, value in raw_champions.items()
                    if str(key).strip() and str(value).strip()
                }
            raw_default = manifest.get(
                "default_champion_method",
                manifest.get("champion_method", default_champion_method),
            )
            if raw_default is not None and str(raw_default).strip():
                default_champion_method = str(raw_default)

        return {
            "data_mode": "HISTORICAL_BACKTEST",
            "authority": "research_evidence_only",
            "target": target,
            "health": health,
            "manifest": manifest,
            "method_summary": frame_records(method_summary),
            "slice_metrics": frame_records(slice_metrics),
            "paired_comparisons": frame_records(paired),
            "experiment_ledger": frame_records(ledger),
            "negative_controls": frame_records(negative_controls),
            "promotion": {
                "automatic": False,
                "production_champion": "target_aware_direct_quantile_stack",
                "default_champion_method": default_champion_method,
                "champion_methods": champion_methods,
                "note": (
                    "Evidence Factory outputs summarize frozen comparisons. They do not change model "
                    "authority without the configured promotion evidence gates. Production authority "
                    "is resolved per target from the run manifest."
                ),
            },
        }
