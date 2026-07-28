from __future__ import annotations

import json
from pathlib import Path

from player_state_engine.product.schemas import LeagueSnapshot


class LeagueSnapshotStore:
    """Small filesystem store suitable for local development and AI Studio prototypes.

    Production deployments should replace this with Postgres or Firestore and retain
    immutable snapshot versions. The interface deliberately stays tiny so that swap is painless.
    """

    def __init__(self, root: str | Path = "data/product/leagues") -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, league_id: str) -> Path:
        safe = "".join(
            character for character in str(league_id) if character.isalnum() or character in "-_"
        )
        if not safe:
            raise ValueError("league_id produced an empty safe path")
        return self.root / f"{safe}.json"

    def save(self, snapshot: LeagueSnapshot) -> Path:
        path = self._path(snapshot.identity.league_id)
        path.write_text(snapshot.model_dump_json(indent=2), encoding="utf-8")
        return path

    def load(self, league_id: str) -> LeagueSnapshot:
        path = self._path(league_id)
        if not path.exists():
            raise FileNotFoundError(f"League snapshot not found: {league_id}")
        return LeagueSnapshot.model_validate_json(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        for path in sorted(self.root.glob("*.json")):
            payload = json.loads(path.read_text(encoding="utf-8"))
            identity = payload.get("identity", {})
            output.append(
                {
                    "league_id": identity.get("league_id", path.stem),
                    "name": identity.get("name", path.stem),
                    "platform": identity.get("platform", "unknown"),
                    "season": identity.get("season"),
                    "imported_at": identity.get("imported_at"),
                }
            )
        return output
