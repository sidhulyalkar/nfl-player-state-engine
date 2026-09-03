from __future__ import annotations

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient

from player_state_engine.api.showcase_routes import install_showcase_routes
from player_state_engine.evaluation.weekly_showcase import (
    SnapshotProvenance,
    build_weekly_showcase,
    normalize_actuals_snapshot,
    normalize_expert_snapshot,
    normalize_model_snapshot,
)


def _seed(root) -> None:
    model = normalize_model_snapshot(
        pd.DataFrame(
            {
                "player_id": ["qb1", "qb2", "rb1", "rb2"],
                "player_name": ["QB One", "QB Two", "RB One", "RB Two"],
                "position": ["QB", "QB", "RB", "RB"],
                "q50": [22.0, 18.0, 17.0, 12.0],
            }
        ),
        points_column="q50",
    )
    expert = normalize_expert_snapshot(
        pd.DataFrame(
            {
                "player_id": ["qb1", "qb2", "rb1", "rb2"],
                "position": ["QB", "QB", "RB", "RB"],
                "position_rank": [2, 1, 2, 1],
            }
        ),
        rank_column="position_rank",
    )
    actuals = normalize_actuals_snapshot(
        pd.DataFrame(
            {"player_id": ["qb1", "qb2", "rb1", "rb2"], "actual_points": [24, 16, 18, 10]}
        ),
        points_column="actual_points",
    )
    build_weekly_showcase(
        model=model,
        expert=expert,
        actuals=actuals,
        season=2026,
        week=1,
        scoring="ppr",
        model_provenance=SnapshotProvenance("model", "2026-09-10T15:00:00+00:00"),
        expert_provenance=SnapshotProvenance("experts", "2026-09-10T15:05:00+00:00"),
        actuals_provenance=SnapshotProvenance("actuals", "2026-09-14T06:00:00+00:00"),
        output_root=root,
    )


def test_showcase_routes_are_read_only_and_filterable(tmp_path) -> None:
    _seed(tmp_path)
    app = FastAPI()
    install_showcase_routes(app, root=tmp_path)
    client = TestClient(app)

    index = client.get("/v1/model/showcase")
    assert index.status_code == 200
    assert index.json()["authority"] == "evaluation_only"
    assert index.json()["may_change_production_decisions"] is False

    season = client.get("/v1/model/showcase/2026")
    assert season.status_code == 200
    assert season.json()["record"]["model_wins"] == 1

    week = client.get("/v1/model/showcase/2026/weeks/1", params={"position": "QB"})
    assert week.status_code == 200
    payload = week.json()
    assert payload["authority"] == "evaluation_only"
    assert payload["may_change_production_decisions"] is False
    assert {row["position"] for row in payload["players"]} == {"QB"}


def test_showcase_routes_return_404_for_missing_week(tmp_path) -> None:
    app = FastAPI()
    install_showcase_routes(app, root=tmp_path)
    response = TestClient(app).get("/v1/model/showcase/2026/weeks/9")
    assert response.status_code == 404
