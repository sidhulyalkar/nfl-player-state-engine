from __future__ import annotations

import hashlib
import json

import pandas as pd

from scripts.run_bdb27_bilateral_pilot import run
from tests.research.test_bilateral import trajectory


def test_offline_pilot_provenance_and_immutable_raw_input(tmp_path) -> None:
    data = pd.concat([trajectory("left", 1), trajectory("right", -1)])
    input_csv = tmp_path / "canonical.csv"
    data.to_csv(input_csv, index=False)
    digest = hashlib.sha256(input_csv.read_bytes()).hexdigest()
    result = run(input_csv, tmp_path / "pilot", synthetic=True)
    assert result["input_sha256"] == digest
    assert result["authority"] == "RESEARCH_ONLY_NO_PROMOTION"
    assert result["events"] == 2
    assert result["estimated_profiles"] == 0
    assert hashlib.sha256(input_csv.read_bytes()).hexdigest() == digest
    assert json.loads((tmp_path / "pilot" / "manifest.json").read_text())["source"] == "synthetic_fixture"
