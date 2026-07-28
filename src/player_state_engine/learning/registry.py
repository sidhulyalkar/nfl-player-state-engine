from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

CandidateStatus = Literal["challenger", "approved", "champion", "rejected"]


class ModelRecord(BaseModel):
    model_id: str
    target: str
    created_at_utc: datetime = Field(default_factory=lambda: datetime.now(UTC))
    training_end_fold_week: int
    model_path: str
    metrics_path: str
    benchmark_path: str | None = None
    status: CandidateStatus = "challenger"
    metrics: dict[str, float] = Field(default_factory=dict)
    gate_reasons: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelRegistry(BaseModel):
    version: int = 1
    champions: dict[str, str] = Field(default_factory=dict)
    records: list[ModelRecord] = Field(default_factory=list)

    def latest_for_target(self, target: str) -> ModelRecord | None:
        candidates = [record for record in self.records if record.target == target]
        return max(candidates, key=lambda record: record.training_end_fold_week, default=None)

    def get(self, model_id: str) -> ModelRecord:
        for record in self.records:
            if record.model_id == model_id:
                return record
        raise KeyError(model_id)


def load_registry(path: str | Path) -> ModelRegistry:
    path = Path(path)
    if not path.exists():
        return ModelRegistry()
    return ModelRegistry.model_validate_json(path.read_text(encoding="utf-8"))


def save_registry(registry: ModelRegistry, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(registry.model_dump_json(indent=2), encoding="utf-8")
    return path


def register_model(registry: ModelRegistry, record: ModelRecord) -> None:
    registry.records = [item for item in registry.records if item.model_id != record.model_id]
    registry.records.append(record)


def promote_model(registry: ModelRegistry, model_id: str) -> ModelRecord:
    selected = registry.get(model_id)
    for record in registry.records:
        if record.target == selected.target and record.status == "champion":
            record.status = "approved"
    selected.status = "champion"
    registry.champions[selected.target] = selected.model_id
    return selected
