from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from player_state_engine.config import load_config
from player_state_engine.data.catalog import create_duckdb_catalog
from player_state_engine.data.historical import acquire_historical_sources
from player_state_engine.data.io import read_table, write_table
from player_state_engine.data.nflverse import download_nflverse
from player_state_engine.data.synthetic import write_synthetic_dataset
from player_state_engine.evaluation.backtest import walk_forward_backtest
from player_state_engine.evaluation.market import score_prop_board, settle_paper_ledger
from player_state_engine.fantasy.decision_board import DecisionType, build_decision_board
from player_state_engine.fantasy.decisions import optimize_lineup, rank_waiver_candidates
from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.fantasy.opportunity import rank_high_chance_opportunities
from player_state_engine.fantasy.valuation import value_players
from player_state_engine.features.prospect import build_prospect_features
from player_state_engine.features.team_context import (
    build_team_play_structure,
    score_player_scheme_fit,
)
from player_state_engine.features.weekly import feature_columns
from player_state_engine.integrations.csv_import import import_csv_league
from player_state_engine.integrations.sleeper import SleeperImporter
from player_state_engine.intelligence.availability import (
    build_availability_features,
    build_official_availability_features,
)
from player_state_engine.intelligence.io import load_documents_jsonl
from player_state_engine.intelligence.news import (
    claims_to_evidence_frame,
    claims_to_feature_snapshots,
    extract_news_claims,
)
from player_state_engine.intelligence.pipeline import build_persona_workflow, collect_registry
from player_state_engine.learning.registry import load_registry, promote_model, save_registry
from player_state_engine.learning.workflow import continual_update
from player_state_engine.logging_utils import configure_logging
from player_state_engine.pipelines.workflows import (
    attach_intelligence_workflow,
    benchmark_workflow,
    build_features_workflow,
    calibrate_predictions_workflow,
    intelligence_ablation_workflow,
    make_slate_workflow,
    predict_workflow,
    simulate_workflow,
    smoke_test_workflow,
    train_opportunity_workflow,
    train_workflow,
)
from player_state_engine.product.demo import seed_product_demo
from player_state_engine.product.store import LeagueSnapshotStore
from player_state_engine.state import latest_player_states

app = typer.Typer(no_args_is_help=True, help="Probabilistic NFL player projections and simulation.")
console = Console()

ConfigOption = Annotated[Path, typer.Option("--config", help="YAML configuration file.")]


def _show_paths(paths: dict[str, Path]) -> None:
    table = Table(title="Created artifacts")
    table.add_column("Artifact")
    table.add_column("Path")
    for name, path in paths.items():
        table.add_row(name, str(path))
    console.print(table)


@app.command()
def download(
    seasons: Annotated[
        list[int] | None, typer.Option("--season", help="Season; repeat for multiple.")
    ] = None,
    output_dir: Annotated[Path, typer.Option(help="Raw-data output directory.")] = Path("data/raw"),
    include_optional: Annotated[
        bool, typer.Option(help="Also attempt NGS, participation, snaps and charting.")
    ] = False,
    config: ConfigOption = Path("configs/base.yaml"),
) -> None:
    """Download maintained public nflverse data."""
    configure_logging()
    cfg = load_config(config)
    paths = download_nflverse(seasons or cfg.seasons, output_dir, include_optional=include_optional)
    _show_paths(paths)


@app.command("make-synthetic")
def make_synthetic(
    output_dir: Annotated[Path, typer.Option(help="Output directory.")] = Path(
        "data/raw/synthetic"
    ),
    seasons: Annotated[list[int] | None, typer.Option("--season")] = None,
    weeks: Annotated[int, typer.Option(min=4, max=22)] = 12,
    seed: Annotated[int, typer.Option()] = 42,
) -> None:
    """Generate a deterministic miniature league for development and tests."""
    years = tuple(seasons or [2023, 2024])
    dataset = write_synthetic_dataset(output_dir, seasons=years, weeks_per_season=weeks, seed=seed)
    console.print(f"Wrote {len(dataset.player_stats):,} player-weeks to {output_dir}")


@app.command("build-features")
def build_features(
    stats: Annotated[Path, typer.Option(help="Weekly player stats CSV/Parquet.")],
    schedules: Annotated[Path, typer.Option(help="Schedules CSV/Parquet.")],
    output: Annotated[Path, typer.Option(help="Feature table path.")] = Path(
        "data/processed/weekly_features.parquet"
    ),
    config: ConfigOption = Path("configs/base.yaml"),
) -> None:
    cfg = load_config(config)
    path = build_features_workflow(stats, schedules, output, cfg)
    console.print(f"Features written to {path}")


@app.command()
def train(
    features: Annotated[Path, typer.Option(help="Feature table.")],
    output: Annotated[Path, typer.Option(help="Model bundle path.")] = Path(
        "artifacts/models/quantile_bundle.joblib"
    ),
    target: Annotated[
        list[str] | None, typer.Option("--target", help="Target; repeat for multiple.")
    ] = None,
    holdout_weeks: Annotated[int, typer.Option(min=1)] = 4,
    metrics: Annotated[Path, typer.Option(help="Holdout metrics path.")] = Path(
        "artifacts/reports/holdout_metrics.csv"
    ),
    config: ConfigOption = Path("configs/base.yaml"),
) -> None:
    cfg = load_config(config)
    model_path, metric_frame = train_workflow(features, output, cfg, target, holdout_weeks, metrics)
    console.print(metric_frame.to_string(index=False))
    console.print(f"Model saved to {model_path}")


@app.command("make-slate")
def make_slate(
    stats: Annotated[Path, typer.Option(help="Historical weekly player stats.")],
    schedules: Annotated[Path, typer.Option(help="Schedules including requested week.")],
    season: Annotated[int, typer.Option()],
    week: Annotated[int, typer.Option(min=1, max=22)],
    output: Annotated[Path, typer.Option(help="Prediction slate path.")] = Path(
        "data/processed/prediction_slate.parquet"
    ),
    config: ConfigOption = Path("configs/base.yaml"),
) -> None:
    cfg = load_config(config)
    path = make_slate_workflow(stats, schedules, output, season, week, cfg)
    console.print(f"Prediction slate written to {path}")


@app.command()
def predict(
    model: Annotated[Path, typer.Option(help="Saved model bundle.")],
    slate: Annotated[Path, typer.Option(help="Feature-complete prediction slate.")],
    output: Annotated[Path, typer.Option(help="Prediction output path.")] = Path(
        "artifacts/predictions/predictions.parquet"
    ),
) -> None:
    path = predict_workflow(model, slate, output)
    console.print(f"Predictions written to {path}")


@app.command()
def simulate(
    predictions: Annotated[Path, typer.Option(help="Quantile predictions.")],
    output_dir: Annotated[Path, typer.Option(help="Simulation report directory.")] = Path(
        "artifacts/reports"
    ),
    target: Annotated[str, typer.Option()] = "fantasy_points_ppr",
    config: ConfigOption = Path("configs/base.yaml"),
) -> None:
    cfg = load_config(config)
    paths = simulate_workflow(predictions, output_dir, cfg, target=target)
    _show_paths(paths)


@app.command()
def backtest(
    features: Annotated[Path, typer.Option(help="Feature table.")],
    target: Annotated[str, typer.Option()] = "fantasy_points_ppr",
    output_dir: Annotated[Path, typer.Option()] = Path("artifacts/reports/backtest"),
    min_train_weeks: Annotated[int, typer.Option(min=4)] = 24,
    retrain_every: Annotated[int, typer.Option(min=1)] = 4,
    config: ConfigOption = Path("configs/base.yaml"),
) -> None:
    cfg = load_config(config)
    frame = read_table(features)
    cols = feature_columns(frame, targets=(target,))
    result = walk_forward_backtest(
        frame,
        cols,
        target=target,
        config=cfg.model,
        min_train_weeks=min_train_weeks,
        retrain_every_weeks=retrain_every,
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = write_table(result.predictions, output_dir / f"{target}_predictions.csv")
    metrics_path = write_table(result.metrics, output_dir / f"{target}_metrics.csv")
    _show_paths({"predictions": predictions_path, "metrics": metrics_path})


@app.command("benchmark-multiseason")
def benchmark_multiseason(
    features: Annotated[Path, typer.Option(help="Leakage-safe feature table.")],
    target: Annotated[str, typer.Option(help="Outcome to benchmark.")] = "fantasy_points_ppr",
    output_dir: Annotated[Path, typer.Option(help="Benchmark artifact directory.")] = Path(
        "artifacts/reports/benchmark"
    ),
    min_train_weeks: Annotated[int | None, typer.Option(min=4)] = None,
    retrain_every: Annotated[int | None, typer.Option(min=1)] = None,
    rolling_window: Annotated[int | None, typer.Option(min=1)] = None,
    config: ConfigOption = Path("configs/base.yaml"),
) -> None:
    """Compare the quantile engine with rolling and position-prior baselines."""
    cfg = load_config(config)
    paths = benchmark_workflow(
        features,
        output_dir,
        target,
        cfg,
        min_train_weeks=min_train_weeks,
        retrain_every_weeks=retrain_every,
        rolling_window=rolling_window,
    )
    _show_paths(paths)


@app.command("collect-intelligence")
def collect_intelligence(
    registry: Annotated[Path, typer.Option(help="Player source registry CSV.")] = Path(
        "examples/player_sources_template.csv"
    ),
    output: Annotated[Path, typer.Option(help="Deduplicated public documents JSONL.")] = Path(
        "data/external/intelligence/documents.jsonl"
    ),
    cache_dir: Annotated[Path, typer.Option(help="Raw API and page cache.")] = Path(
        "data/external/intelligence/cache"
    ),
    platform: Annotated[
        list[str] | None, typer.Option("--platform", help="Limit to platform; repeat as needed.")
    ] = None,
    per_source_limit: Annotated[int | None, typer.Option(min=1, max=100)] = None,
    strict: Annotated[bool, typer.Option(help="Stop on the first source error.")] = False,
    config: ConfigOption = Path("configs/base.yaml"),
) -> None:
    """Collect authorized public content through official APIs or robots-aware URLs."""
    cfg = load_config(config)
    path, errors = collect_registry(
        registry,
        output,
        cache_dir=cache_dir,
        platforms=platform,
        per_source_limit=per_source_limit or cfg.intelligence.per_source_limit,
        continue_on_error=not strict,
    )
    console.print(f"Documents written to {path}")
    if errors:
        console.print(
            f"[yellow]{len(errors)} source(s) were skipped. See logs for details.[/yellow]"
        )


@app.command("build-personas")
def build_personas(
    documents: Annotated[Path, typer.Option(help="Collected documents JSONL.")],
    output: Annotated[Path, typer.Option(help="Numeric persona feature table.")] = Path(
        "data/processed/persona_features.parquet"
    ),
    evidence: Annotated[Path, typer.Option(help="Auditable evidence JSON.")] = Path(
        "artifacts/reports/persona_evidence.json"
    ),
    lookback_days: Annotated[int | None, typer.Option(min=7, max=730)] = None,
    config: ConfigOption = Path("configs/base.yaml"),
) -> None:
    """Build conservative public-context features and retain supporting evidence."""
    cfg = load_config(config)
    paths = build_persona_workflow(
        documents,
        output,
        evidence,
        lookback_days=lookback_days or cfg.intelligence.lookback_days,
    )
    _show_paths(paths)


@app.command("build-availability")
def build_availability(
    evidence: Annotated[Path, typer.Option(help="Timestamped availability evidence CSV/Parquet.")],
    output: Annotated[Path, typer.Option(help="Availability feature snapshots.")] = Path(
        "data/processed/availability_features.parquet"
    ),
) -> None:
    """Normalize official injury and transaction evidence into model-ready snapshots."""
    features = build_availability_features(read_table(evidence))
    path = write_table(features, output)
    console.print(f"Availability features written to {path}")


@app.command("attach-intelligence")
def attach_intelligence(
    features: Annotated[Path, typer.Option(help="Football feature table containing gameday.")],
    intelligence: Annotated[Path, typer.Option(help="Persona or availability feature snapshots.")],
    output: Annotated[Path, typer.Option(help="Point-in-time joined feature table.")] = Path(
        "data/processed/weekly_features_with_intelligence.parquet"
    ),
    config: ConfigOption = Path("configs/base.yaml"),
) -> None:
    """Attach only intelligence snapshots known before each game's cutoff."""
    cfg = load_config(config)
    path = attach_intelligence_workflow(features, intelligence, output, cfg)
    console.print(f"Point-in-time feature table written to {path}")


@app.command("calibrate-predictions")
def calibrate_predictions(
    predictions: Annotated[Path, typer.Option(help="Archived walk-forward predictions.")],
    target: Annotated[str, typer.Option(help="Target represented by the predictions.")],
    output_dir: Annotated[Path, typer.Option(help="Conformal artifact directory.")] = Path(
        "artifacts/reports/conformal"
    ),
    config: ConfigOption = Path("configs/base.yaml"),
) -> None:
    """Apply target-and-position conformal correction using earlier seasons only."""
    cfg = load_config(config)
    _show_paths(calibrate_predictions_workflow(predictions, target, output_dir, cfg))


@app.command("train-opportunity-heads")
def train_opportunity_heads(
    features: Annotated[
        Path, typer.Option(help="Feature table with opportunity supervision columns.")
    ],
    model: Annotated[Path, typer.Option(help="Saved opportunity-head bundle.")] = Path(
        "artifacts/models/opportunity_heads.joblib"
    ),
    predictions: Annotated[Path, typer.Option(help="Held-out opportunity predictions.")] = Path(
        "artifacts/predictions/opportunity_holdout.parquet"
    ),
    holdout_season: Annotated[
        int | None, typer.Option(help="Season reserved for evaluation.")
    ] = None,
    config: ConfigOption = Path("configs/base.yaml"),
) -> None:
    """Train the active→participation→volume→conversion→fantasy ladder."""
    cfg = load_config(config)
    _show_paths(train_opportunity_workflow(features, model, predictions, cfg, holdout_season))


@app.command("build-official-availability")
def build_official_availability(
    evidence: Annotated[Path, typer.Option(help="Normalized official evidence CSV/Parquet.")],
    output: Annotated[Path, typer.Option(help="Point-in-time official feature snapshots.")] = Path(
        "data/processed/official_availability_features.parquet"
    ),
) -> None:
    """Activate official evidence families while retaining family-level columns."""
    features = build_official_availability_features(read_table(evidence))
    console.print(f"Official availability features written to {write_table(features, output)}")


@app.command("extract-news-claims")
def extract_news_claims_command(
    documents: Annotated[Path, typer.Option(help="Collected public documents JSONL.")],
    features: Annotated[Path, typer.Option(help="News feature snapshots.")] = Path(
        "data/processed/news_features.parquet"
    ),
    evidence: Annotated[Path, typer.Option(help="Auditable extracted claim table.")] = Path(
        "artifacts/reports/news_claims.csv"
    ),
) -> None:
    """Extract timestamped role, workload, travel and weather claims."""
    claims = extract_news_claims(load_documents_jsonl(documents))
    paths = {
        "features": write_table(claims_to_feature_snapshots(claims), features),
        "evidence": write_table(claims_to_evidence_frame(claims), evidence),
    }
    _show_paths(paths)


@app.command("benchmark-intelligence-ablations")
def benchmark_intelligence_ablations(
    features: Annotated[
        Path, typer.Option(help="Point-in-time table containing all feature families.")
    ],
    target: Annotated[str, typer.Option()] = "fantasy_points_ppr",
    output_dir: Annotated[Path, typer.Option()] = Path("artifacts/reports/intelligence_ablations"),
    config: ConfigOption = Path("configs/base.yaml"),
) -> None:
    """Run required intelligence ablations and negative controls."""
    cfg = load_config(config)
    _show_paths(intelligence_ablation_workflow(features, target, output_dir, cfg))


@app.command("continual-update")
def continual_update_command(
    features: Annotated[
        Path, typer.Option(help="Leakage-safe feature table with newly completed weeks.")
    ],
    target: Annotated[str, typer.Option(help="Target to retrain and gate.")] = "fantasy_points_ppr",
    registry: Annotated[Path, typer.Option(help="Model registry JSON.")] = Path(
        "artifacts/models/registry.json"
    ),
    output_dir: Annotated[Path, typer.Option(help="Candidate model directory.")] = Path(
        "artifacts/models/candidates"
    ),
    force: Annotated[
        bool, typer.Option(help="Retrain even if no new completed week is detected.")
    ] = False,
    config: ConfigOption = Path("configs/base.yaml"),
) -> None:
    """Create a guarded expanding-window challenger and run promotion gates."""
    cfg = load_config(config)
    record = continual_update(features, target, registry, output_dir, cfg, force=force)
    if record is None:
        console.print("No retraining required; the configured number of new weeks has not arrived.")
        return
    console.print_json(record.model_dump_json(indent=2))


@app.command("learning-status")
def learning_status(
    registry: Annotated[Path, typer.Option(help="Model registry JSON.")] = Path(
        "artifacts/models/registry.json"
    ),
) -> None:
    """Show champions and the latest challenger for every target."""
    state = load_registry(registry)
    console.print_json(state.model_dump_json(indent=2))


@app.command("promote-model")
def promote_model_command(
    model_id: Annotated[str, typer.Argument(help="Registered model identifier.")],
    registry: Annotated[Path, typer.Option(help="Model registry JSON.")] = Path(
        "artifacts/models/registry.json"
    ),
) -> None:
    """Manually promote a gated model after reviewing its report."""
    state = load_registry(registry)
    record = promote_model(state, model_id)
    save_registry(state, registry)
    console.print(f"Promoted {record.model_id} as champion for {record.target}.")


@app.command()
def catalog(
    database: Annotated[Path, typer.Option()] = Path("data/player_state_engine.duckdb"),
    table: Annotated[list[str] | None, typer.Option(help="NAME=PATH; repeat for multiple.")] = None,
) -> None:
    mapping: dict[str, Path] = {}
    for item in table or []:
        if "=" not in item:
            raise typer.BadParameter("Each --table must use NAME=PATH.")
        name, path = item.split("=", 1)
        mapping[name] = Path(path)
    path = create_duckdb_catalog(database, mapping)
    console.print(f"DuckDB catalog written to {path}")


@app.command("export-states")
def export_states(
    features: Annotated[Path, typer.Option(help="Feature table.")],
    output: Annotated[Path, typer.Option(help="State-vector output.")] = Path(
        "artifacts/reports/player_states.csv"
    ),
) -> None:
    states = latest_player_states(read_table(features))
    path = write_table(states, output)
    console.print(f"Player states written to {path}")


@app.command("score-props")
def score_props(
    predictions: Annotated[Path, typer.Option(help="Timestamped model predictions.")],
    props: Annotated[Path, typer.Option(help="Manual prop-board CSV/Parquet.")],
    output: Annotated[Path, typer.Option(help="Scored paper board.")] = Path(
        "artifacts/reports/scored_props.csv"
    ),
) -> None:
    scored = score_prop_board(read_table(predictions), read_table(props))
    path = write_table(scored, output)
    console.print(f"Scored {len(scored):,} paper props to {path}")


@app.command("settle-props")
def settle_props(
    scored: Annotated[Path, typer.Option(help="Previously scored prop board.")],
    outcomes: Annotated[Path, typer.Option(help="Observed outcomes.")],
    output: Annotated[Path, typer.Option(help="Settled paper ledger.")] = Path(
        "artifacts/reports/settled_props.csv"
    ),
) -> None:
    ledger = settle_paper_ledger(read_table(scored), read_table(outcomes))
    path = write_table(ledger, output)
    console.print(f"Settled {len(ledger):,} paper entries to {path}")


@app.command("smoke-test")
def smoke_test(
    work_dir: Annotated[Path, typer.Option(help="Isolated smoke-test directory.")] = Path(".smoke"),
    config: ConfigOption = Path("configs/base.yaml"),
) -> None:
    cfg = load_config(config)
    paths = smoke_test_workflow(work_dir, cfg)
    _show_paths(paths)
    console.print("[bold green]Smoke test passed.[/bold green]")


@app.command()
def dashboard(
    predictions: Annotated[Path, typer.Option(help="Predictions CSV/Parquet.")] = Path(
        "artifacts/predictions/predictions.parquet"
    ),
) -> None:
    """Launch the optional Streamlit projection explorer."""
    import subprocess
    import sys

    app_path = Path(__file__).parent / "dashboard" / "app.py"
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app_path), "--", str(predictions)],
        check=True,
    )


@app.command("show-config")
def show_config(config: ConfigOption = Path("configs/base.yaml")) -> None:
    cfg = load_config(config)
    console.print_json(json.dumps(cfg, default=str, indent=2))


@app.command("acquire-historical")
def acquire_historical(
    seasons: Annotated[list[int] | None, typer.Option("--season")] = None,
    output_dir: Annotated[Path, typer.Option()] = Path("data/raw/historical_sources"),
) -> None:
    manifest = acquire_historical_sources(seasons or list(range(2020, 2026)), output_dir)
    console.print(manifest.to_string(index=False))


@app.command("value-fantasy-players")
def value_fantasy_players(
    projections: Annotated[Path, typer.Option()],
    league: Annotated[Path, typer.Option()] = Path("configs/fantasy_league_example.yaml"),
    output: Annotated[Path, typer.Option()] = Path("artifacts/reports/fantasy_player_values.csv"),
) -> None:
    valued = value_players(read_table(projections), LeagueConfig.from_yaml(league))
    path = write_table(valued, output)
    console.print(f"Fantasy values written to {path}")


@app.command("rank-opportunities")
def rank_opportunities(
    features: Annotated[Path, typer.Option()],
    output: Annotated[Path, typer.Option()] = Path(
        "artifacts/reports/high_chance_opportunities.csv"
    ),
) -> None:
    ranked = rank_high_chance_opportunities(read_table(features))
    path = write_table(ranked, output)
    console.print(f"Opportunity watchlist written to {path}")


@app.command("build-prospect-features")
def build_prospect_features_command(
    combine: Annotated[Path, typer.Option(help="NFL combine CSV/Parquet.")],
    draft: Annotated[Path, typer.Option(help="NFL draft-pick CSV/Parquet.")],
    output: Annotated[Path, typer.Option()] = Path("data/processed/prospect_features.parquet"),
    college: Annotated[Path | None, typer.Option(help="Optional college production table.")] = None,
) -> None:
    """Build combine, draft-capital and optional college-production priors."""
    features = build_prospect_features(
        read_table(combine), read_table(draft), read_table(college) if college else None
    )
    console.print(f"Prospect features written to {write_table(features, output)}")


@app.command("build-team-context")
def build_team_context_command(
    pbp: Annotated[Path, typer.Option(help="Play-by-play CSV/Parquet.")],
    output: Annotated[Path, typer.Option()] = Path("data/processed/team_play_structure.parquet"),
) -> None:
    """Build lagged team pace, play calling, formation and concentration features."""
    context = build_team_play_structure(read_table(pbp))
    console.print(f"Team context written to {write_table(context, output)}")


@app.command("score-scheme-fit")
def score_scheme_fit_command(
    players: Annotated[Path, typer.Option(help="Player slate or feature table.")],
    team_context: Annotated[Path, typer.Option(help="Lagged team-context table.")],
    output: Annotated[Path, typer.Option()] = Path("data/processed/player_scheme_fit.parquet"),
) -> None:
    """Score observable player-role integration with team play structure."""
    result = score_player_scheme_fit(read_table(players), read_table(team_context))
    console.print(f"Scheme-fit features written to {write_table(result, output)}")


@app.command("fantasy-decision-board")
def fantasy_decision_board_command(
    projections: Annotated[Path, typer.Option()],
    decision: Annotated[DecisionType, typer.Option()] = DecisionType.DRAFT,
    league: Annotated[Path, typer.Option()] = Path("configs/fantasy_league_example.yaml"),
    output: Annotated[Path, typer.Option()] = Path("artifacts/reports/fantasy_decision_board.csv"),
) -> None:
    """Rank players for a specific draft, lineup, waiver, trade or stash decision."""
    board = build_decision_board(read_table(projections), LeagueConfig.from_yaml(league), decision)
    console.print(f"Decision board written to {write_table(board, output)}")


@app.command("optimize-lineup")
def optimize_lineup_command(
    players: Annotated[Path, typer.Option(help="Roster projections containing lineup_score.")],
    league: Annotated[Path, typer.Option()] = Path("configs/fantasy_league_example.yaml"),
    output: Annotated[Path, typer.Option()] = Path("artifacts/reports/optimized_lineup.csv"),
) -> None:
    lineup = optimize_lineup(read_table(players), LeagueConfig.from_yaml(league))
    console.print(f"Optimized lineup written to {write_table(lineup, output)}")


@app.command("rank-waivers")
def rank_waivers_command(
    candidates: Annotated[Path, typer.Option()],
    roster: Annotated[Path, typer.Option()],
    output: Annotated[Path, typer.Option()] = Path("artifacts/reports/waiver_board.csv"),
    faab_budget: Annotated[float, typer.Option(min=0)] = 100.0,
) -> None:
    board = rank_waiver_candidates(
        read_table(candidates), read_table(roster), faab_budget=faab_budget
    )
    console.print(f"Waiver board written to {write_table(board, output)}")


@app.command("seed-product-demo")
def seed_product_demo_command(
    root: Annotated[Path, typer.Option(help="Repository or product data root.")] = Path("."),
    seed: Annotated[int, typer.Option()] = 42,
) -> None:
    """Create a deterministic league, player-value artifact and NFL schedule for the frontend."""
    _show_paths(seed_product_demo(root, seed=seed))


@app.command("import-sleeper-league")
def import_sleeper_league(
    league_id: Annotated[str, typer.Option(help="Sleeper league ID.")],
    user_id: Annotated[str | None, typer.Option(help="Optional Sleeper user ID.")] = None,
    store_dir: Annotated[Path, typer.Option(help="League snapshot store.")] = Path(
        "data/product/leagues"
    ),
    include_free_agents: Annotated[bool, typer.Option(help="Fetch active free-agent pool.")] = True,
) -> None:
    """Import and normalize a Sleeper league into the product snapshot contract."""
    snapshot = SleeperImporter().import_league(
        league_id, external_user_id=user_id, include_free_agents=include_free_agents
    )
    path = LeagueSnapshotStore(store_dir).save(snapshot)
    console.print(f"League snapshot written to {path}")


@app.command("import-csv-league")
def import_csv_league_command(
    league_id: Annotated[str, typer.Option()],
    league_name: Annotated[str, typer.Option()],
    season: Annotated[int, typer.Option()],
    rosters: Annotated[Path, typer.Option(help="Canonical roster CSV.")],
    free_agents: Annotated[Path | None, typer.Option(help="Optional free-agent CSV.")] = None,
    store_dir: Annotated[Path, typer.Option()] = Path("data/product/leagues"),
) -> None:
    """Import a platform-neutral league snapshot from CSV files."""
    snapshot = import_csv_league(
        league_id=league_id,
        league_name=league_name,
        season=season,
        rosters_path=rosters,
        free_agents_path=free_agents,
    )
    path = LeagueSnapshotStore(store_dir).save(snapshot)
    console.print(f"League snapshot written to {path}")


@app.command("serve-product-api")
def serve_product_api(
    host: Annotated[str, typer.Option()] = "0.0.0.0",
    port: Annotated[int, typer.Option(min=1, max=65535)] = 8000,
    reload: Annotated[bool, typer.Option()] = False,
) -> None:
    """Run the optional FastAPI product service."""
    try:
        import uvicorn
    except ImportError as exc:
        raise typer.BadParameter(
            "Install API extras with: python -m pip install -e '.[api]'"
        ) from exc
    uvicorn.run("player_state_engine.api.app:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()
