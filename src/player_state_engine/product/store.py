from __future__ import annotations

import json
import os
import tempfile
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
        """Atomically replace one normalized league snapshot.

        Draft refreshes and first-time onboarding share this write path. Readers should therefore
        observe either the previous complete JSON document or the new complete document, never a
        partially written snapshot if the process is interrupted mid-write.
        """

        path = self._path(snapshot.identity.league_id)
        encoded = snapshot.model_dump_json(indent=2) + "\n"
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.root,
                prefix=f".{path.stem}.",
                suffix=".next",
                delete=False,
            ) as handle:
                handle.write(encoded)
                handle.flush()
                os.fsync(handle.fileno())
                temporary = Path(handle.name)
            temporary.replace(path)
        finally:
            if temporary is not None and temporary.exists():
                temporary.unlink(missing_ok=True)
        return path

    def load(self, league_id: str) -> LeagueSnapshot:
        """Load a snapshot whose filename is the league id."""

        path = self._path(league_id)
        if not path.exists():
            raise FileNotFoundError(f"League snapshot not found: {league_id}")
        return LeagueSnapshot.model_validate_json(path.read_text(encoding="utf-8"))

    def iter_snapshots(self) -> list[LeagueSnapshot]:
        """Read valid snapshots regardless of the filename used by the sync layer."""

        snapshots: list[LeagueSnapshot] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                snapshots.append(
                    LeagueSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
                )
            except (OSError, ValueError):
                continue
        return snapshots

    def find(self, league_id: str) -> LeagueSnapshot:
        """Find a league by identity, including connection-key-named live snapshots.

        A direct ``<league_id>.json`` file remains the fast path. When live portfolio syncs use a
        connection key as the filename, identity lookup scans valid snapshots and chooses the most
        recently imported matching league instead of making callers duplicate filesystem logic.
        """

        direct = self._path(league_id)
        if direct.is_file():
            return LeagueSnapshot.model_validate_json(direct.read_text(encoding="utf-8"))
        matches = [
            snapshot
            for snapshot in self.iter_snapshots()
            if snapshot.identity.league_id == str(league_id)
        ]
        if not matches:
            raise FileNotFoundError(f"League snapshot not found: {league_id}")
        return max(matches, key=lambda snapshot: snapshot.identity.imported_at)

    def list(self) -> list[dict[str, object]]:
        output: list[dict[str, object]] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
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
