from __future__ import annotations

from importlib.metadata import version

from fastapi.testclient import TestClient

from player_state_engine import __version__
from player_state_engine.api.operational import create_app


def test_package_metadata_is_single_version_source(tmp_path) -> None:
    installed = version("nfl-player-state-engine")
    assert __version__ == installed

    app = create_app(
        store_root=tmp_path / "leagues",
        projections_path=tmp_path / "missing-projections.csv",
        ranking_root=tmp_path / "rankings",
        game_intelligence_root=tmp_path / "game-intelligence",
        evidence_factory_root=tmp_path / "evidence",
        shadow_season_root=tmp_path / "shadow",
        structured_intelligence_root=tmp_path / "structured",
    )
    assert app.version == installed
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["version"] == installed
