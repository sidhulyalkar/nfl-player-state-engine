from __future__ import annotations

import json
from pathlib import Path

from tests.product.test_shadow_lab_api import _client


def test_shadow_comparison_fails_closed_when_tight_end_premium_differs(tmp_path: Path) -> None:
    client = _client(tmp_path)
    manifest_path = tmp_path / "graph/run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["league_contract"]["tight_end_premium"] = 0.5
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    response = client.get("/v1/leagues/demo-league/players/demo-001/shadow")
    assert response.status_code == 200
    comparison = response.json()["comparison"]
    scoring = comparison["scoring_contract"]
    assert scoring["base_weights_match"] is True
    assert scoring["tight_end_premium_match"] is False
    assert scoring["comparable"] is False
    assert comparison["decision_comparable"] is False
