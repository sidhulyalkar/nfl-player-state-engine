from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from player_state_engine.fantasy.league import LeagueConfig
from player_state_engine.product.shadow_lab import evaluate_shadow_replay
from player_state_engine.state_graph.builder import PlayerStateGraphBuilder
from player_state_engine.state_graph.coherent import PlayerStateGraphSampler
from player_state_engine.state_graph.insights import build_intelligence_card


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run research-only Player State Graph forecasts from point-in-time weekly data."
    )
    parser.add_argument("--history", type=Path, required=True)
    parser.add_argument("--forecast-rows", type=Path, required=True)
    parser.add_argument("--league-config", type=Path)
    parser.add_argument("--regime-events", type=Path)
    parser.add_argument("--champion-predictions", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("artifacts/player_state_graph"))
    parser.add_argument("--simulations", type=int, default=3000)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def _read(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix in {".parquet", ".pq"}:
        return pd.read_parquet(path)
    if suffix == ".csv":
        return pd.read_csv(path)
    raise ValueError(f"Unsupported tabular input: {path}")


def _actual_from_row(row: pd.Series) -> float | None:
    for column in ("actual", "actual_fantasy_points_ppr", "fantasy_points_ppr"):
        if column not in row or pd.isna(row[column]):
            continue
        return float(row[column])
    return None


def _manifest(league: LeagueConfig, args: argparse.Namespace, rows: int) -> dict[str, object]:
    return {
        "schema_version": 2,
        "authority": "research_challenger_only",
        "model_source": "player_state_graph_research_v2",
        "forecast_horizon": "weekly",
        "rows": rows,
        "simulations_per_player": int(args.simulations),
        "seed": int(args.seed),
        "league_contract": {
            "teams": league.teams,
            "scoring": league.scoring,
            "scoring_weights": dict(league.scoring_weights),
            "roster_slots": dict(league.roster_slots),
            "flex_eligibility": {key: list(value) for key, value in league.flex_eligibility.items()},
            "risk_preference": league.risk_preference,
            "median_scoring": league.median_scoring,
            "median_game_weight": league.median_game_weight,
            "tight_end_premium": league.tight_end_premium,
        },
        "inputs": {
            "history": str(args.history),
            "forecast_rows": str(args.forecast_rows),
            "league_config": str(args.league_config) if args.league_config else None,
            "regime_events": str(args.regime_events) if args.regime_events else None,
            "champion_predictions": (
                str(args.champion_predictions) if args.champion_predictions else None
            ),
        },
        "promotion": {
            "automatic": False,
            "required_evidence": [
                "multi-season paired frozen replay",
                "position and week consistency",
                "calibration and sharpness",
                "negative controls",
                "downstream fantasy decision value",
            ],
        },
    }


def main() -> None:
    args = parse_args()
    history = _read(args.history)
    forecasts = _read(args.forecast_rows)
    regimes = _read(args.regime_events) if args.regime_events else None
    league = LeagueConfig.from_yaml(args.league_config) if args.league_config else LeagueConfig()
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    builder = PlayerStateGraphBuilder()
    sampler = PlayerStateGraphSampler()
    summaries: list[dict[str, object]] = []
    role_records: list[dict[str, object]] = []
    draw_pieces: list[pd.DataFrame] = []
    cards: list[dict[str, object]] = []

    required = {"player_id", "season", "week", "opponent"}
    missing = required - set(forecasts)
    if missing:
        raise ValueError(f"Forecast rows missing columns: {sorted(missing)}")

    for index, row in forecasts.iterrows():
        state = builder.build(
            history,
            player_id=str(row["player_id"]),
            player_name=str(row.get("player_name") or row["player_id"]),
            season=int(row["season"]),
            week=int(row["week"]),
            opponent=str(row["opponent"]),
            regime_events=regimes,
            evidence_cutoff=str(row.get("prediction_cutoff") or "") or None,
        )
        draws = sampler.sample_player(
            state,
            simulations=args.simulations,
            seed=args.seed + int(index) * 7919,
        )
        scored = sampler.score_draws(draws, league)
        quantiles = sampler.summarize(scored)
        draw_pieces.append(scored)
        role_records.append(state.role.to_dict())
        summaries.append(
            {
                "player_id": state.player_id,
                "player_name": state.player_name,
                "team": state.team,
                "opponent": state.opponent,
                "position": state.position,
                "season": state.season,
                "week": state.week,
                "q10": quantiles.q10,
                "q50": quantiles.q50,
                "q90": quantiles.q90,
                "mean": quantiles.mean,
                "actual": _actual_from_row(row),
                "probability_active": state.availability.active.mean,
                "role_change_probability": state.role.aggregate_change_probability,
                "role_maturity": state.role.state_maturity,
                "snap_share_mean": state.role.snap_share.mean,
                "route_participation_mean": state.role.route_participation.mean,
                "target_share_mean": state.role.target_share.mean,
                "carry_share_mean": state.role.carry_share.mean,
                "red_zone_share_mean": state.role.red_zone_share.mean,
                "team_plays_mean": state.team_volume.plays_mean,
                "team_plays_std": state.team_volume.plays_std,
                "team_dropback_rate_mean": state.team_volume.dropback_rate.mean,
                "regime_maturity": state.regime.maturity if state.regime else "UNKNOWN",
                "model_source": "player_state_graph_research_v2",
            }
        )
        card = build_intelligence_card(
            player_id=state.player_id,
            player_name=state.player_name,
            position=state.position,
            scored_draws=scored,
            role=state.role,
            probability_active=state.availability.active.mean,
            evidence_freshness=state.evidence_cutoff,
        )
        cards.append(card.to_dict())

    summary_frame = pd.DataFrame(summaries)
    role_frame = pd.DataFrame(role_records)
    draw_frame = pd.concat(draw_pieces, ignore_index=True, sort=False) if draw_pieces else pd.DataFrame()
    summary_frame.to_parquet(output_dir / "player_state_graph_summaries.parquet", index=False)
    role_frame.to_parquet(output_dir / "dynamic_role_states.parquet", index=False)
    draw_frame.to_parquet(output_dir / "coherent_scored_draws.parquet", index=False)
    (output_dir / "player_intelligence_cards.json").write_text(
        json.dumps(cards, indent=2, default=str), encoding="utf-8"
    )
    manifest = _manifest(league, args, len(summary_frame))
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8"
    )

    evaluation: dict[str, object] | None = None
    if args.champion_predictions:
        champion = _read(args.champion_predictions)
        if "method" in champion:
            champion = champion.loc[champion["method"].astype(str).eq("quantile_engine")].copy()
        evaluation = evaluate_shadow_replay(champion, summary_frame)
        (output_dir / "shadow_evaluation.json").write_text(
            json.dumps(evaluation, indent=2, default=str) + "\n", encoding="utf-8"
        )

    report = [
        "# Player State Graph research run",
        "",
        f"- Players: {len(summary_frame)}",
        f"- Simulations per player: {args.simulations}",
        f"- League teams: {league.teams}",
        f"- League scoring: {league.scoring}",
        "- Forecast horizon: weekly",
        "- Authority: research challenger only",
        f"- Paired shadow evaluation: {'written' if evaluation is not None else 'not requested'}",
        "",
        "This run does not promote the graph over the frozen production champion.",
    ]
    (output_dir / "report.md").write_text("\n".join(report) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
