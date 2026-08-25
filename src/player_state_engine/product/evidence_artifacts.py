from __future__ import annotations

import hashlib
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


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class EvidenceArtifactStore:
    """Read-only Product API adapter over cryptographically verified Evidence Factory outputs."""

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
        manifest = self._manifest()
        outputs = manifest.get("outputs") if manifest is not None else None
        output_manifest = outputs if isinstance(outputs, dict) else {}
        metadata: dict[str, dict[str, object]] = {}
        integrity_failures: list[str] = []

        for name, path in paths.items():
            item = artifact_metadata(path)
            if name == "manifest":
                item["parse_valid"] = manifest is not None
                if path.is_file() and manifest is None:
                    integrity_failures.append("manifest_invalid")
            elif path.is_file():
                output_record = output_manifest.get(name)
                expected_sha = (
                    output_record.get("sha256") if isinstance(output_record, dict) else None
                )
                actual_sha = _sha256_file(path)
                hash_recorded = isinstance(expected_sha, str) and bool(expected_sha.strip())
                integrity_match = hash_recorded and actual_sha == expected_sha
                item.update(
                    {
                        "sha256": actual_sha,
                        "expected_sha256": expected_sha if hash_recorded else None,
                        "integrity_match": integrity_match,
                    }
                )
                if not hash_recorded:
                    integrity_failures.append(f"{name}_hash_missing")
                elif not integrity_match:
                    integrity_failures.append(f"{name}_hash_mismatch")
            metadata[name] = item

        available_count = sum(bool(item.get("available")) for item in metadata.values())
        missing = [name for name, item in metadata.items() if not item.get("available")]
        available = (
            available_count == len(paths)
            and manifest is not None
            and not integrity_failures
        )
        return {
            "available": available,
            "available_count": available_count,
            "expected_count": len(paths),
            "missing": missing,
            "integrity_verified": available,
            "integrity_failures": integrity_failures,
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
        manifest = self._manifest()
        if manifest is None:
            return {
                "data_mode": "UNAVAILABLE",
                "authority": "research_evidence_only",
                "reason": "evidence_factory_manifest_invalid",
                "health": health,
            }
        if not bool(health["available"]):
            return {
                "data_mode": "UNAVAILABLE",
                "authority": "research_evidence_only",
                "reason": "evidence_factory_artifact_integrity_failed",
                "health": health,
            }

        method_summary = _read(self.method_summary_path)
        slice_metrics = _read(self.slice_metrics_path)
        paired = _read(self.paired_comparisons_path)
        ledger = _read(self.experiment_ledger_path)
        negative_controls = _read(self.negative_controls_path)
        if target:
            for frame in (method_summary, slice_metrics, paired, negative_controls):
                if "target" in frame:
                    frame.drop(frame.index[~frame["target"].astype(str).eq(target)], inplace=True)
            if "experiment_id" in ledger:
                ledger = ledger.loc[
                    ledger["experiment_id"].astype(str).str.startswith(f"{target}:")
                ]

        champion_methods: dict[str, str] = {}
        default_champion_method = "quantile_engine"
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
                    "is resolved per target from the cryptographically verified run manifest."
                ),
            },
        }
