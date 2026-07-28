from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass(slots=True)
class FeatureConfig:
    rolling_windows: tuple[int, ...] = (3, 5, 8)
    ewm_halflives: tuple[int, ...] = (2, 4, 8)
    min_player_history: int = 2
    active_lookback_weeks: int = 4


@dataclass(slots=True)
class ModelConfig:
    targets: tuple[str, ...] = (
        "fantasy_points_ppr",
        "targets",
        "carries",
        "receptions",
        "receiving_yards",
        "rushing_yards",
        "passing_yards",
    )
    quantiles: tuple[float, ...] = (0.1, 0.5, 0.9)
    max_iter: int = 180
    learning_rate: float = 0.05
    max_leaf_nodes: int = 31
    min_samples_leaf: int = 20
    l2_regularization: float = 1.0
    random_seed: int = 42


@dataclass(slots=True)
class BenchmarkConfig:
    min_train_weeks: int = 24
    retrain_every_weeks: int = 4
    rolling_window: int = 5


@dataclass(slots=True)
class ContinualLearningConfig:
    enabled: bool = False
    min_new_completed_weeks: int = 1
    holdout_weeks: int = 4
    auto_promote: bool = False
    min_pinball_improvement_pct: float = 0.0
    max_coverage_error: float = 0.08
    max_position_regression_pct: float = 5.0


@dataclass(slots=True)
class IntelligenceConfig:
    enabled: bool = False
    lookback_days: int = 120
    safety_lag_hours: int = 1
    per_source_limit: int = 50


@dataclass(slots=True)
class ConformalConfig:
    enabled: bool = True
    min_group_rows: int = 75
    shrinkage_rows: float = 200.0
    minimum_calibration_seasons: int = 1


@dataclass(slots=True)
class OpportunityConfig:
    enabled: bool = False
    crossfit_by_season: bool = True
    minimum_training_rows: int = 50
    include_offensive_line_context: bool = True


@dataclass(slots=True)
class IntelligenceAblationConfig:
    enabled: bool = False
    min_improvement_pct: float = 0.25
    min_seasons_won: int = 2
    max_shuffled_gain_pct: float = 0.15


@dataclass(slots=True)
class SimulationConfig:
    draws: int = 10_000
    same_team_correlation: float = 0.12
    opposing_team_correlation: float = -0.03
    seed: int = 42


@dataclass(slots=True)
class EngineConfig:
    project_root: Path = Path(".")
    data_dir: Path = Path("data")
    artifacts_dir: Path = Path("artifacts")
    random_seed: int = 42
    seasons: tuple[int, ...] = (2020, 2021, 2022, 2023, 2024, 2025)
    include_optional: bool = False
    synthetic_players_per_team: int = 7
    features: FeatureConfig = field(default_factory=FeatureConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    benchmark: BenchmarkConfig = field(default_factory=BenchmarkConfig)
    continual_learning: ContinualLearningConfig = field(default_factory=ContinualLearningConfig)
    intelligence: IntelligenceConfig = field(default_factory=IntelligenceConfig)
    conformal: ConformalConfig = field(default_factory=ConformalConfig)
    opportunity: OpportunityConfig = field(default_factory=OpportunityConfig)
    intelligence_ablation: IntelligenceAblationConfig = field(
        default_factory=IntelligenceAblationConfig
    )
    simulation: SimulationConfig = field(default_factory=SimulationConfig)

    def resolve_paths(self) -> EngineConfig:
        root = self.project_root.resolve()
        self.project_root = root
        self.data_dir = (root / self.data_dir).resolve()
        self.artifacts_dir = (root / self.artifacts_dir).resolve()
        return self


def _as_tuple(value: Any, default: tuple[Any, ...]) -> tuple[Any, ...]:
    if value is None:
        return default
    return tuple(value)


def load_config(
    path: str | Path = "configs/base.yaml", project_root: str | Path | None = None
) -> EngineConfig:
    path = Path(path)
    raw: dict[str, Any] = {}
    if path.exists():
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}

    project = raw.get("project", {})
    data = raw.get("data", {})
    feature = raw.get("features", {})
    model = raw.get("model", {})
    benchmark = raw.get("backtest", raw.get("benchmark", {}))
    continual_learning = raw.get("continual_learning", {})
    intelligence = raw.get("intelligence", {})
    conformal = raw.get("conformal", {})
    opportunity = raw.get("opportunity", {})
    intelligence_ablation = raw.get("intelligence_ablation", {})
    simulation = raw.get("simulation", {})

    root = Path(project_root or project.get("project_root", "."))
    seed = int(project.get("random_seed", 42))

    cfg = EngineConfig(
        project_root=root,
        data_dir=Path(project.get("data_dir", "data")),
        artifacts_dir=Path(project.get("artifacts_dir", "artifacts")),
        random_seed=seed,
        seasons=_as_tuple(data.get("seasons"), (2020, 2021, 2022, 2023, 2024, 2025)),
        include_optional=bool(data.get("include_optional", False)),
        synthetic_players_per_team=int(data.get("synthetic_players_per_team", 7)),
        features=FeatureConfig(
            rolling_windows=_as_tuple(feature.get("rolling_windows"), (3, 5, 8)),
            ewm_halflives=_as_tuple(feature.get("ewm_halflives"), (2, 4, 8)),
            min_player_history=int(feature.get("min_player_history", 2)),
            active_lookback_weeks=int(feature.get("active_lookback_weeks", 4)),
        ),
        model=ModelConfig(
            targets=_as_tuple(model.get("targets"), ModelConfig().targets),
            quantiles=_as_tuple(model.get("quantiles"), (0.1, 0.5, 0.9)),
            max_iter=int(model.get("max_iter", 180)),
            learning_rate=float(model.get("learning_rate", 0.05)),
            max_leaf_nodes=int(model.get("max_leaf_nodes", 31)),
            min_samples_leaf=int(model.get("min_samples_leaf", 20)),
            l2_regularization=float(model.get("l2_regularization", 1.0)),
            random_seed=seed,
        ),
        benchmark=BenchmarkConfig(
            min_train_weeks=int(benchmark.get("min_train_weeks", 24)),
            retrain_every_weeks=int(benchmark.get("retrain_every_weeks", 4)),
            rolling_window=int(benchmark.get("rolling_window", 5)),
        ),
        continual_learning=ContinualLearningConfig(
            enabled=bool(continual_learning.get("enabled", False)),
            min_new_completed_weeks=int(continual_learning.get("min_new_completed_weeks", 1)),
            holdout_weeks=int(continual_learning.get("holdout_weeks", 4)),
            auto_promote=bool(continual_learning.get("auto_promote", False)),
            min_pinball_improvement_pct=float(
                continual_learning.get("min_pinball_improvement_pct", 0.0)
            ),
            max_coverage_error=float(continual_learning.get("max_coverage_error", 0.08)),
            max_position_regression_pct=float(
                continual_learning.get("max_position_regression_pct", 5.0)
            ),
        ),
        intelligence=IntelligenceConfig(
            enabled=bool(intelligence.get("enabled", False)),
            lookback_days=int(intelligence.get("lookback_days", 120)),
            safety_lag_hours=int(intelligence.get("safety_lag_hours", 1)),
            per_source_limit=int(intelligence.get("per_source_limit", 50)),
        ),
        conformal=ConformalConfig(
            enabled=bool(conformal.get("enabled", True)),
            min_group_rows=int(conformal.get("min_group_rows", 75)),
            shrinkage_rows=float(conformal.get("shrinkage_rows", 200.0)),
            minimum_calibration_seasons=int(conformal.get("minimum_calibration_seasons", 1)),
        ),
        opportunity=OpportunityConfig(
            enabled=bool(opportunity.get("enabled", False)),
            crossfit_by_season=bool(opportunity.get("crossfit_by_season", True)),
            minimum_training_rows=int(opportunity.get("minimum_training_rows", 50)),
            include_offensive_line_context=bool(
                opportunity.get("include_offensive_line_context", True)
            ),
        ),
        intelligence_ablation=IntelligenceAblationConfig(
            enabled=bool(intelligence_ablation.get("enabled", False)),
            min_improvement_pct=float(intelligence_ablation.get("min_improvement_pct", 0.25)),
            min_seasons_won=int(intelligence_ablation.get("min_seasons_won", 2)),
            max_shuffled_gain_pct=float(intelligence_ablation.get("max_shuffled_gain_pct", 0.15)),
        ),
        simulation=SimulationConfig(
            draws=int(simulation.get("draws", 10_000)),
            same_team_correlation=float(simulation.get("same_team_correlation", 0.12)),
            opposing_team_correlation=float(simulation.get("opposing_team_correlation", -0.03)),
            seed=int(simulation.get("seed", seed)),
        ),
    )
    return cfg.resolve_paths()
