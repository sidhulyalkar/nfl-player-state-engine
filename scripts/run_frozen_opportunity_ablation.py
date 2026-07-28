from __future__ import annotations

from pathlib import Path

from player_state_engine.evaluation.frozen_opportunity import (
    load_frozen_prediction_panel,
    persist_frozen_ablation,
    run_frozen_opportunity_ablation,
)

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / "artifacts/reports/benchmark_real"
out = ROOT / "artifacts/reports/opportunity_ablation_real"
panel = load_frozen_prediction_panel(source)
result = run_frozen_opportunity_ablation(panel)
paths = persist_frozen_ablation(result, out)
print(result.summary.to_string(index=False))
for name, path in paths.items():
    print(f"{name}: {path}")
