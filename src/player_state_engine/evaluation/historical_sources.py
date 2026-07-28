from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from player_state_engine.data.historical import (
    aggregate_pass_play_participation,
    canonicalize_depth_charts,
    canonicalize_injuries,
    resolve_snap_player_ids,
)
from player_state_engine.evaluation.frozen_opportunity import (
    KEYS,
    _evaluate,
    _pipeline,
    build_frozen_opportunity_features,
)


@dataclass(slots=True)
class HistoricalSourceAblationResult:
    predictions: pd.DataFrame
    summary: pd.DataFrame
    season_metrics: pd.DataFrame
    position_metrics: pd.DataFrame
    feature_manifest: pd.DataFrame
    coverage: pd.DataFrame


def _rolling_prior(
    frame: pd.DataFrame,
    value: str,
    output_prefix: str,
    *,
    group: str = "player_id",
) -> pd.DataFrame:
    data = frame.sort_values([group, "season", "week"]).copy()
    values = pd.to_numeric(data[value], errors="coerce")
    shifted = values.groupby(data[group], sort=False).shift(1)
    data[f"{output_prefix}_lag1"] = shifted
    data[f"{output_prefix}_roll3"] = (
        shifted.groupby(data[group], sort=False)
        .rolling(3, min_periods=1)
        .mean()
        .reset_index(level=0, drop=True)
        .reindex(data.index)
    )
    data[f"{output_prefix}_trend"] = shifted - (
        shifted.groupby(data[group], sort=False)
        .rolling(5, min_periods=1)
        .mean()
        .reset_index(level=0, drop=True)
        .reindex(data.index)
    )
    return data


def _kickoff_cutoffs(schedules: pd.DataFrame, hours_before: float = 1.5) -> pd.DataFrame:
    games = schedules.copy()
    game_col = "game_id" if "game_id" in games else "nflverse_game_id"
    if game_col not in games:
        raise ValueError("Schedules require game_id or nflverse_game_id.")
    if "gameday" not in games:
        raise ValueError("Schedules require gameday for point-in-time injury joins.")
    time = (
        games["gametime"].fillna("13:00")
        if "gametime" in games
        else pd.Series("13:00", index=games.index)
    )
    kickoff = pd.to_datetime(
        games["gameday"].astype(str) + " " + time.astype(str), utc=True, errors="coerce"
    )
    out = pd.DataFrame(
        {
            "game_id": games[game_col].astype(str),
            "prediction_cutoff": kickoff - pd.to_timedelta(hours_before, unit="h"),
        }
    )
    return out.drop_duplicates("game_id", keep="last")


def build_historical_source_features(
    panel: pd.DataFrame,
    *,
    snap_counts: pd.DataFrame | None = None,
    weekly_rosters: pd.DataFrame | None = None,
    participation: pd.DataFrame | None = None,
    pbp: pd.DataFrame | None = None,
    injuries: pd.DataFrame | None = None,
    depth_charts: pd.DataFrame | None = None,
    schedules: pd.DataFrame | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Attach point-in-time historical source families to the frozen panel.

    Snap, participation and untimestamped depth-chart values are shifted one
    player-week. Same-week official injury evidence is allowed only when its
    modification timestamp precedes a schedule-derived prediction cutoff.
    """
    data = build_frozen_opportunity_features(panel)
    coverage_rows: list[dict[str, object]] = []

    def coverage(name: str, columns: list[str]) -> None:
        present = (
            data[columns].notna().any(axis=1) if columns else pd.Series(False, index=data.index)
        )
        for season, group in data.assign(_present=present).groupby("season"):
            coverage_rows.append(
                {
                    "source_family": name,
                    "season": int(season),
                    "rows": len(group),
                    "matched_rows": int(group["_present"].sum()),
                    "coverage_rate": float(group["_present"].mean()),
                }
            )

    if snap_counts is not None and weekly_rosters is not None and not snap_counts.empty:
        snaps = resolve_snap_player_ids(snap_counts, weekly_rosters)
        snaps = snaps.loc[snaps["player_id"].notna()].copy()
        snaps = _rolling_prior(snaps, "snap_share", "source_snap_share")
        snaps = _rolling_prior(snaps, "snap_count", "source_snap_count")
        cols = [
            "season",
            "week",
            "player_id",
            "source_snap_share_lag1",
            "source_snap_share_roll3",
            "source_snap_share_trend",
            "source_snap_count_lag1",
            "source_snap_count_roll3",
            "id_match_method",
        ]
        data = data.merge(
            snaps[cols].drop_duplicates(["season", "week", "player_id"], keep="last"),
            on=["season", "week", "player_id"],
            how="left",
        )
        coverage("snap_counts", ["source_snap_share_lag1", "source_snap_count_lag1"])

    if participation is not None and pbp is not None and not participation.empty:
        pass_usage = aggregate_pass_play_participation(participation, pbp)
        pass_usage = _rolling_prior(
            pass_usage, "pass_play_participation_rate", "source_pass_participation"
        )
        cols = [
            "season",
            "week",
            "player_id",
            "source_pass_participation_lag1",
            "source_pass_participation_roll3",
            "source_pass_participation_trend",
        ]
        data = data.merge(
            pass_usage[cols].drop_duplicates(["season", "week", "player_id"], keep="last"),
            on=["season", "week", "player_id"],
            how="left",
        )
        coverage("pass_play_participation", cols[3:])

    if depth_charts is not None and not depth_charts.empty:
        depth = canonicalize_depth_charts(depth_charts)
        depth = depth.loc[depth["player_id"].notna()].copy()
        depth = _rolling_prior(depth, "depth_rank", "source_depth_rank")
        depth["source_depth_starter_lag1"] = depth["source_depth_rank_lag1"].le(1).astype(float)
        cols = [
            "season",
            "week",
            "player_id",
            "source_depth_rank_lag1",
            "source_depth_rank_roll3",
            "source_depth_starter_lag1",
        ]
        data = data.merge(
            depth[cols].drop_duplicates(["season", "week", "player_id"], keep="last"),
            on=["season", "week", "player_id"],
            how="left",
        )
        coverage("depth_charts", cols[3:])

    if injuries is not None and schedules is not None and not injuries.empty:
        injury = canonicalize_injuries(injuries)
        cutoffs = _kickoff_cutoffs(schedules)
        key_games = data[["season", "week", "game_id"]].drop_duplicates().copy()
        key_games["game_id"] = key_games["game_id"].astype(str)
        key_games = key_games.merge(cutoffs, on="game_id", how="left")
        injury = injury.merge(
            key_games[["season", "week", "prediction_cutoff"]].drop_duplicates(),
            on=["season", "week"],
            how="left",
        )
        known = (
            injury["date_modified"].notna()
            & injury["prediction_cutoff"].notna()
            & injury["date_modified"].le(injury["prediction_cutoff"])
        )
        injury = (
            injury.loc[known]
            .sort_values("date_modified")
            .drop_duplicates(["season", "week", "player_id"], keep="last")
        )
        injury_cols = [
            "season",
            "week",
            "player_id",
            "official_report_availability_prior",
            "official_practice_availability_prior",
            "official_availability_prior",
            "official_injury_evidence_present",
            "report_status",
            "practice_status",
            "primary_injury",
        ]
        data = data.merge(injury[injury_cols], on=["season", "week", "player_id"], how="left")
        available_seasons = set(
            pd.to_numeric(canonicalize_injuries(injuries)["season"], errors="coerce")
            .dropna()
            .astype(int)
        )
        data["official_injury_source_available"] = (
            data["season"].astype(int).isin(available_seasons).astype(int)
        )
        source_available = data["official_injury_source_available"].eq(1)
        for col in (
            "official_report_availability_prior",
            "official_practice_availability_prior",
            "official_availability_prior",
        ):
            data.loc[source_available & data[col].isna(), col] = 1.0
        data.loc[
            source_available & data["official_injury_evidence_present"].isna(),
            "official_injury_evidence_present",
        ] = 0.0
        coverage("official_injuries", ["official_availability_prior"])

    return data, pd.DataFrame(coverage_rows)


def run_historical_source_ablation(
    data: pd.DataFrame, coverage: pd.DataFrame
) -> HistoricalSourceAblationResult:
    base = [
        "position",
        "fantasy_points_ppr_q10",
        "fantasy_points_ppr_q50",
        "fantasy_points_ppr_q90",
    ]
    families = {
        "snap_counts": [c for c in data if c.startswith("source_snap_")],
        "pass_participation": [c for c in data if c.startswith("source_pass_participation_")],
        "depth_charts": [c for c in data if c.startswith("source_depth_")],
        "official_availability": [
            c
            for c in data
            if c.startswith("official_") and c not in {"official_injury_source_available"}
        ],
    }
    families = {name: cols for name, cols in families.items() if cols}
    objective = [
        c
        for name in ("snap_counts", "pass_participation", "depth_charts")
        for c in families.get(name, [])
    ]
    combined = [*objective, *families.get("official_availability", [])]
    variants: dict[str, tuple[pd.DataFrame, list[str]]] = {"numerical_baseline": (data, [])}
    variants.update({name: (data, cols) for name, cols in families.items()})
    if objective:
        variants["objective_sources_combined"] = (data, objective)
    if combined:
        variants["objective_plus_availability"] = (data, combined)
        shuffled = data.copy()
        rng = np.random.default_rng(42)
        for _, index in shuffled.groupby(
            ["season", "week", "position"], dropna=False
        ).groups.items():
            idx = np.asarray(list(index))
            if len(idx) > 1:
                perm = rng.permutation(idx)
                shuffled.loc[idx, combined] = shuffled.loc[perm, combined].to_numpy()
        shifted = data.sort_values(["player_id", "season", "week"]).copy()
        shifted[combined] = shifted.groupby("player_id", sort=False)[combined].shift(-1)
        variants["shuffled_player_control"] = (shuffled, combined)
        variants["shifted_time_leakage_control"] = (shifted, combined)

    predictions: list[pd.DataFrame] = []
    seasons = sorted(int(s) for s in data["season"].dropna().unique())
    for test_season in seasons[1:]:
        for method, (working, extra) in variants.items():
            train = working.loc[working["season"] < test_season].copy()
            test = working.loc[working["season"] == test_season].copy()
            out = test[
                KEYS
                + [
                    "actual_fantasy_points_ppr",
                    "fantasy_points_ppr_q10",
                    "fantasy_points_ppr_q50",
                    "fantasy_points_ppr_q90",
                ]
            ].copy()
            out["method"] = method
            out["test_season"] = test_season
            if not extra:
                shift = np.zeros(len(test))
            else:
                features = list(dict.fromkeys([*base, *extra]))
                model = _pipeline(train, features)
                residual = train["actual_fantasy_points_ppr"] - train["fantasy_points_ppr_q50"]
                model.fit(train[features], residual)
                raw = model.predict(test[features])
                half_width = (
                    (test["fantasy_points_ppr_q90"] - test["fantasy_points_ppr_q10"]) / 2.0
                ).clip(lower=1.0)
                shift = np.clip(raw, -0.30 * half_width, 0.30 * half_width)
            out["center_shift"] = shift
            for q in (10, 50, 90):
                out[f"adjusted_q{q}"] = np.maximum(
                    test[f"fantasy_points_ppr_q{q}"].to_numpy() + np.asarray(shift), 0.0
                )
            predictions.append(out)

    pred = pd.concat(predictions, ignore_index=True)
    summary = pd.DataFrame([_evaluate(group, method) for method, group in pred.groupby("method")])
    baseline = float(
        summary.loc[summary["method"].eq("numerical_baseline"), "mean_pinball"].iloc[0]
    )
    summary["pinball_improvement_vs_baseline_pct"] = (
        100 * (baseline - summary["mean_pinball"]) / baseline
    )
    summary = summary.sort_values("mean_pinball").reset_index(drop=True)

    season_rows = []
    position_rows = []
    for (method, season), group in pred.groupby(["method", "test_season"]):
        row = _evaluate(group, method)
        row["season"] = season
        season_rows.append(row)
    for (method, position), group in pred.groupby(["method", "position"]):
        row = _evaluate(group, method)
        row["position"] = position
        position_rows.append(row)

    manifest = pd.DataFrame(
        [
            {"ablation": name, "feature": feature}
            for name, (_, features) in variants.items()
            for feature in features
        ]
    )
    return HistoricalSourceAblationResult(
        pred,
        summary,
        pd.DataFrame(season_rows),
        pd.DataFrame(position_rows),
        manifest,
        coverage,
    )


def persist_historical_source_ablation(
    result: HistoricalSourceAblationResult, output_dir: str | Path
) -> dict[str, Path]:
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    frames = {
        "predictions": result.predictions,
        "summary": result.summary,
        "season_metrics": result.season_metrics,
        "position_metrics": result.position_metrics,
        "feature_manifest": result.feature_manifest,
        "source_coverage": result.coverage,
    }
    paths: dict[str, Path] = {}
    for name, frame in frames.items():
        path = output / f"historical_source_{name}.csv"
        frame.to_csv(path, index=False)
        paths[name] = path
    return paths
