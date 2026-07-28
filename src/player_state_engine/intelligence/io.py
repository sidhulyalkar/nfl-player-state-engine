from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

from player_state_engine.intelligence.schemas import PlayerSource, PublicDocument


def load_source_registry(path: str | Path) -> list[PlayerSource]:
    frame = pd.read_csv(path)
    records = frame.where(pd.notna(frame), None).to_dict(orient="records")
    return [PlayerSource.model_validate(record) for record in records]


def write_documents_jsonl(documents: Iterable[PublicDocument], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    deduplicated: dict[str, PublicDocument] = {}
    for document in documents:
        deduplicated[document.content_hash or document.document_id] = document
    with path.open("w", encoding="utf-8") as handle:
        for document in deduplicated.values():
            handle.write(document.model_dump_json() + "\n")
    return path


def load_documents_jsonl(path: str | Path) -> list[PublicDocument]:
    documents: list[PublicDocument] = []
    with Path(path).open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                documents.append(PublicDocument.model_validate_json(line))
    return documents


def write_evidence_json(snapshots, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([snapshot.model_dump(mode="json") for snapshot in snapshots], indent=2),
        encoding="utf-8",
    )
    return path
