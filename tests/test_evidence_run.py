from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from player_state_engine.evaluation.evidence_factory import EvidenceBundle
from player_state_engine.evaluation.evidence_run import (
    DEFAULT_CHAMPION_OVERRIDES,
    apply_run_fdr,
    build_run_bundle,
    parse_champion_overrides,
)


def _target_predictions(method: str, *, offset: float) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    actuals = [8.0, 12.0, 15.0, 18.0, 9.0, 13.0, 16.0, 20.0]
    for index, actual in enumerate(actuals):
        season = 2023 if index < 4 else 2024
        week = index % 4 + 1
        q50 = actual + offset
        rows.append(
            {
                "player_id": f"rb{index % 2}",
                "season": season,
                "week": week,
                "position": "RB",
                "method": method,
                "actual": actual,
                "carries_q10": q50 - 4.0,
                "carries_q50": q50,
                "carries_q90": q50 + 4.0,
            }
        )
    return pd.DataFrame(rows)


def _write_carries_benchmark(root: Path) -> None:
    target_root = root / "carries"
    target_root.mkdir(parents=True)
    pooled = pd.concat(
        [
            _target_predictions("quantile_engine", offset=2.0),
            _target_predictions("rolling_5", offset=1.0),
            _target_predictions("position_prior", offset=3.0),
        ],
        ignore_index=True,
    )
    pooled.to_csv(target_root / "carries_predictions.csv", index=False)
    _target_predictions("position_specific_quantile", offset=0.5).to_csv(
        target_root / "carries_position_specific_predictions.csv",
        index=False,
    )


def test_default_champion_override_matches_current_hybrid_carries_authority() -> None:
    assert DEFAULT_CHAMPION_OVERRIDES == {"carries": "position_specific_quantile"}
    assert parse_champion_overrides([]) == DEFAULT_CHAMPION_OVERRIDES


def test_explicit_champion_override_extends_defaults() -> None:
    overrides = parse_champion_overrides(["targets=experimental_target_champion"])

    assert overrides["carries"] == "position_specific_quantile"
    assert overrides["targets"] == "experimental_target_champion"


def test_invalid_champion_override_fails_closed() -> None:
    with pytest.raises(ValueError, match="expected TARGET=METHOD"):
        parse_champion_overrides(["carries"])


def test_run_wide_fdr_overrides_target_local_q_values() -> None:
    paired = pd.DataFrame(
        [
            {
                "experiment_id": "fantasy_points_ppr:a:vs:quantile_engine",
                "p_value": 0.04,
                "fdr_q_value": 0.04,
                "blockers": "",
                "promotion_status": "eligible",
            },
            {
                "experiment_id": "carries:b:vs:position_specific_quantile",
                "p_value": 0.06,
                "fdr_q_value": 0.06,
                "blockers": "",
                "promotion_status": "eligible",
            },
        ]
    )
    ledger = pd.DataFrame(
        [
            {
                "experiment_id": "fantasy_points_ppr:a:vs:quantile_engine",
                "p_value": 0.04,
                "fdr_q_value": 0.04,
                "blockers": [],
                "promoted": True,
            },
            {
                "experiment_id": "carries:b:vs:position_specific_quantile",
                "p_value": 0.06,
                "fdr_q_value": 0.06,
                "blockers": [],
                "promoted": True,
            },
        ]
    )
    bundle = EvidenceBundle(
        predictions=pd.DataFrame(),
        method_summary=pd.DataFrame(),
        slice_metrics=pd.DataFrame(),
        paired_comparisons=paired,
        experiment_ledger=ledger,
    )

    apply_run_fdr(bundle, maximum_fdr_q=0.05)

    assert bundle.paired_comparisons["fdr_q_value"].tolist() == pytest.approx([0.06, 0.06])
    assert set(bundle.paired_comparisons["promotion_status"]) == {"blocked"}
    assert bundle.paired_comparisons["blockers"].str.contains("fdr_q_above_threshold").all()
    assert bundle.experiment_ledger["fdr_q_value"].tolist() == pytest.approx([0.06, 0.06])
    assert bundle.experiment_ledger["promoted"].eq(False).all()
    assert all(
        "fdr_q_above_threshold" in blockers
        for blockers in bundle.experiment_ledger["blockers"]
    )


def test_run_bundle_uses_position_specific_carries_as_champion(tmp_path: Path) -> None:
    benchmark_root = tmp_path / "benchmark"
    _write_carries_benchmark(benchmark_root)

    bundle, controls, _inputs, graph_status, champion_methods = build_run_bundle(
        benchmark_root=benchmark_root,
        graph_root=tmp_path / "missing_graph",
        targets=("carries",),
        champion_method="quantile_engine",
        champion_overrides=DEFAULT_CHAMPION_OVERRIDES,
        bootstrap_samples=300,
        seed=23,
        calibration_tolerance=0.05,
    )

    assert champion_methods == {"carries": "position_specific_quantile"}
    assert set(bundle.paired_comparisons["champion"]) == {"position_specific_quantile"}
    assert set(bundle.paired_comparisons["challenger"]) == {
        "position_prior",
        "quantile_engine",
        "rolling_5",
    }
    assert set(bundle.experiment_ledger["champion"]) == {"position_specific_quantile"}
    assert set(controls["method"]) == {"position_prior", "quantile_engine", "rolling_5"}
    assert bundle.paired_comparisons["fdr_q_value"].notna().all()
    assert graph_status["included"] is False
