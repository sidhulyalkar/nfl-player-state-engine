import pandas as pd

from player_state_engine.data.historical import (
    canonicalize_injuries,
    resolve_snap_player_ids,
)
from player_state_engine.evaluation.historical_sources import (
    HISTORICAL_FEATURE_ALLOWLIST,
    HistoricalSourceAblationResult,
    build_historical_source_features,
    persist_historical_source_experiment,
)


def _panel(rows: list[dict[str, object]]) -> pd.DataFrame:
    frame = pd.DataFrame(rows)
    defaults: dict[str, object] = {
        "player_name": "Test Player",
        "opponent_team": "OPP",
        "position": "RB",
        "fantasy_points_ppr_q10": 2.0,
        "fantasy_points_ppr_q50": 8.0,
        "fantasy_points_ppr_q90": 18.0,
        "actual_fantasy_points_ppr": 10.0,
        "actual_carries": 10.0,
        "actual_targets": 2.0,
        "actual_receptions": 1.0,
        "actual_receiving_yards": 5.0,
        "actual_rushing_yards": 50.0,
        "actual_passing_yards": 0.0,
    }
    for column, value in defaults.items():
        if column not in frame:
            frame[column] = value
    return frame


def test_snap_crosswalk_and_prior_shift() -> None:
    panel = _panel(
        [
            {
                "season": 2021,
                "week": 1,
                "game_id": "g1",
                "player_id": "G1",
                "player_name": "Player One",
                "recent_team": "AAA",
            },
            {
                "season": 2021,
                "week": 2,
                "game_id": "g2",
                "player_id": "G1",
                "player_name": "Player One",
                "recent_team": "AAA",
            },
        ]
    )
    snaps = pd.DataFrame(
        {
            "season": [2021, 2021],
            "week": [1, 2],
            "player": ["Player One", "Player One"],
            "pfr_player_id": ["P1", "P1"],
            "team": ["AAA", "AAA"],
            "position": ["RB", "RB"],
            "offense_snaps": [30, 45],
            "offense_pct": [50, 75],
        }
    )
    rosters = pd.DataFrame(
        {
            "season": [2021, 2021],
            "week": [1, 2],
            "gsis_id": ["G1", "G1"],
            "pfr_id": ["P1", "P1"],
            "full_name": ["Player One", "Player One"],
            "team": ["AAA", "AAA"],
            "position": ["RB", "RB"],
        }
    )
    resolved = resolve_snap_player_ids(snaps, rosters)
    assert set(resolved["player_id"]) == {"G1"}
    features, coverage = build_historical_source_features(
        panel, snap_counts=snaps, weekly_rosters=rosters
    )
    assert pd.isna(features.loc[features["week"].eq(1), "source_snap_share_lag1"]).all()
    assert features.loc[features["week"].eq(2), "source_snap_share_lag1"].iloc[0] == 0.5
    snap_coverage = coverage.loc[
        coverage["source_family"].eq("snap_counts") & coverage["season"].eq(2021)
    ].iloc[0]
    assert snap_coverage["source_file_available"]
    assert snap_coverage["id_resolution_rate"] == 1.0
    assert snap_coverage["explicit_evidence_match_rate"] == 0.5


def test_snap_name_fallback_survives_merge_suffixes_and_is_audited() -> None:
    snaps = pd.DataFrame(
        {
            "season": [2024],
            "week": [3],
            "player": ["Fallback Player"],
            "pfr_player_id": ["PFR-MISSING"],
            "team": ["AAA"],
            "position": ["WR"],
            "offense_snaps": [40],
            "offense_pct": [80],
        }
    )
    rosters = pd.DataFrame(
        {
            "season": [2024],
            "week": [3],
            "gsis_id": ["GSIS-1"],
            "pfr_id": ["PFR-OTHER"],
            "full_name": ["Fallback Player"],
            "team": ["AAA"],
            "position": ["WR"],
        }
    )
    resolved = resolve_snap_player_ids(snaps, rosters)
    assert resolved.loc[0, "player_id"] == "GSIS-1"
    assert resolved.loc[0, "pfr_player_id"] == "PFR-MISSING"
    assert resolved.loc[0, "id_match_method"] == "name_team_week"


def test_injury_mapping_is_conservative() -> None:
    injuries = pd.DataFrame(
        {
            "season": [2024],
            "week": [3],
            "gsis_id": ["G1"],
            "full_name": ["Player"],
            "team": ["AAA"],
            "report_status": ["Questionable"],
            "practice_status": ["Limited Participation"],
            "date_modified": ["2024-09-20T18:00:00Z"],
        }
    )
    result = canonicalize_injuries(injuries)
    assert 0 < result["official_availability_prior"].iloc[0] < 1


def test_missing_injury_status_is_not_silently_healthy() -> None:
    injuries = pd.DataFrame(
        {
            "season": [2024],
            "week": [3],
            "gsis_id": ["G1"],
            "full_name": ["Player"],
            "team": ["AAA"],
            "report_status": [None],
            "practice_status": [None],
            "date_modified": ["2024-09-20T18:00:00Z"],
        }
    )
    result = canonicalize_injuries(injuries)
    assert result["official_injury_evidence_present"].iloc[0] == 0
    assert pd.isna(result["official_availability_prior"].iloc[0])


def test_injury_join_uses_player_team_game_cutoffs_and_excludes_late_reports() -> None:
    panel = _panel(
        [
            {
                "season": 2024,
                "week": 3,
                "game_id": "2024_03_BBB_AAA",
                "player_id": "G-THU",
                "recent_team": "AAA",
            },
            {
                "season": 2024,
                "week": 3,
                "game_id": "2024_03_DDD_CCC",
                "player_id": "G-SUN",
                "recent_team": "CCC",
            },
            {
                "season": 2024,
                "week": 3,
                "game_id": "2024_03_DDD_CCC",
                "player_id": "G-NONE",
                "recent_team": "CCC",
            },
        ]
    )
    schedules = pd.DataFrame(
        {
            "game_id": ["2024_03_BBB_AAA", "2024_03_DDD_CCC"],
            "gameday": ["2024-09-19", "2024-09-22"],
            "gametime": ["20:15", "13:00"],
        }
    )
    injuries = pd.DataFrame(
        {
            "season": [2024, 2024, 2024, 2024],
            "week": [3, 3, 3, 3],
            "gsis_id": ["G-THU", "G-THU", "G-SUN", "G-SUN"],
            "full_name": ["Thursday", "Thursday", "Sunday", "Sunday"],
            "team": ["AAA", "AAA", "CCC", "CCC"],
            "report_status": ["Questionable", "Out", "Questionable", "Out"],
            "practice_status": ["Limited", "DNP", "Limited", "DNP"],
            # Thursday cutoff is 22:45Z; Sunday cutoff is 15:30Z.
            "date_modified": [
                "2024-09-19T22:00:00Z",
                "2024-09-19T23:00:00Z",
                "2024-09-22T15:00:00Z",
                "2024-09-22T16:00:00Z",
            ],
        }
    )
    features, coverage = build_historical_source_features(
        panel,
        injuries=injuries,
        schedules=schedules,
    )
    thursday = features.loc[features["player_id"].eq("G-THU")].iloc[0]
    sunday = features.loc[features["player_id"].eq("G-SUN")].iloc[0]
    missing = features.loc[features["player_id"].eq("G-NONE")].iloc[0]
    assert thursday["official_availability_prior"] == 0.72
    assert thursday["official_evidence_date_modified"] == pd.Timestamp("2024-09-19T22:00:00Z")
    assert sunday["official_availability_prior"] == 0.72
    assert missing["official_injury_evidence_present"] == 0
    assert pd.isna(missing["official_availability_prior"])

    injury_coverage = coverage.loc[
        coverage["source_family"].eq("official_injuries") & coverage["season"].eq(2024)
    ].iloc[0]
    assert injury_coverage["explicit_evidence_rows"] == 2
    assert injury_coverage["post_imputation_feature_rows"] == 2
    assert injury_coverage["explicit_evidence_match_rate"] == 2 / 3


def test_timestamped_depth_schema_uses_only_pre_cutoff_snapshot() -> None:
    panel = _panel(
        [
            {
                "season": 2025,
                "week": 1,
                "game_id": "2025_01_BBB_AAA",
                "player_id": "G1",
                "recent_team": "AAA",
            }
        ]
    )
    schedules = pd.DataFrame(
        {
            "game_id": ["2025_01_BBB_AAA"],
            "gameday": ["2025-09-07"],
            "gametime": ["13:00"],
        }
    )
    depth = pd.DataFrame(
        {
            "dt": ["2025-09-07T14:00:00Z", "2025-09-07T16:00:00Z"],
            "team": ["AAA", "AAA"],
            "player_name": ["Player", "Player"],
            "gsis_id": ["G1", "G1"],
            "pos_abb": ["RB", "RB"],
            "pos_rank": [1, 3],
        }
    )
    features, coverage = build_historical_source_features(
        panel,
        depth_charts=depth,
        schedules=schedules,
    )
    row = features.iloc[0]
    assert row["source_depth_rank_pit"] == 1
    assert row["source_depth_rank_pregame"] == 1
    assert row["source_depth_observed_at"] == pd.Timestamp("2025-09-07T14:00:00Z")
    depth_coverage = coverage.loc[
        coverage["source_family"].eq("depth_charts") & coverage["season"].eq(2025)
    ].iloc[0]
    assert depth_coverage["source_status"] == "available_timestamped_point_in_time"
    assert depth_coverage["explicit_evidence_match_rate"] == 1.0


def test_timestamped_depth_schema_fails_closed_without_schedule_cutoffs() -> None:
    panel = _panel(
        [
            {
                "season": 2025,
                "week": 1,
                "game_id": "2025_01_BBB_AAA",
                "player_id": "G1",
                "recent_team": "AAA",
            }
        ]
    )
    depth = pd.DataFrame(
        {
            "dt": ["2025-09-07T14:00:00Z"],
            "team": ["AAA"],
            "player_name": ["Player"],
            "gsis_id": ["G1"],
            "pos_rank": [1],
        }
    )
    features, coverage = build_historical_source_features(panel, depth_charts=depth)
    assert "source_depth_rank_pit" not in features
    row = coverage.loc[
        coverage["source_family"].eq("depth_charts") & coverage["season"].eq(2025)
    ].iloc[0]
    assert row["source_file_available"]
    assert not row["required_files_available"]
    assert row["source_status"] == "timestamped_schema_missing_schedule_cutoffs"
    assert row["explicit_evidence_match_rate"] == 0.0


def test_timestamped_depth_preserves_rows_with_partial_schedule_cutoffs() -> None:
    panel = _panel(
        [
            {
                "season": 2025,
                "week": 1,
                "game_id": "known-game",
                "player_id": "G1",
                "recent_team": "AAA",
            },
            {
                "season": 2025,
                "week": 1,
                "game_id": "missing-game",
                "player_id": "G2",
                "recent_team": "BBB",
            },
        ]
    )
    schedules = pd.DataFrame(
        {
            "game_id": ["known-game"],
            "gameday": ["2025-09-07"],
            "gametime": ["13:00"],
        }
    )
    depth = pd.DataFrame(
        {
            "dt": ["2025-09-07T14:00:00Z", "2025-09-07T14:00:00Z"],
            "team": ["AAA", "BBB"],
            "player_name": ["Known", "Missing"],
            "gsis_id": ["G1", "G2"],
            "pos_rank": [1, 1],
        }
    )
    features, coverage = build_historical_source_features(
        panel,
        depth_charts=depth,
        schedules=schedules,
    )
    assert features.loc[features["player_id"].eq("G1"), "source_depth_rank_pit"].iloc[0] == 1
    assert pd.isna(features.loc[features["player_id"].eq("G2"), "source_depth_rank_pit"].iloc[0])
    row = coverage.loc[
        coverage["source_family"].eq("depth_charts") & coverage["season"].eq(2025)
    ].iloc[0]
    assert row["source_status"] == "partial_game_cutoffs"
    assert not row["required_files_available"]
    assert row["explicit_evidence_match_rate"] == 0.5


def test_depth_aliases_are_coalesced_across_schema_change() -> None:
    mixed = pd.DataFrame(
        {
            "season": [2024, pd.NA],
            "week": [2, pd.NA],
            "club_code": ["AAA", pd.NA],
            "team": [pd.NA, "AAA"],
            "full_name": ["Legacy Player", pd.NA],
            "player_name": [pd.NA, "Current Player"],
            "gsis_id": ["G-OLD", "G-NEW"],
            "depth_team": [1, pd.NA],
            "pos_rank": [pd.NA, 2],
            "dt": [pd.NA, "2025-09-07T14:00:00Z"],
        }
    )
    panel = _panel(
        [
            {
                "season": 2025,
                "week": 1,
                "game_id": "2025_01_BBB_AAA",
                "player_id": "G-NEW",
                "recent_team": "AAA",
            }
        ]
    )
    _, coverage = build_historical_source_features(panel, depth_charts=mixed)
    row = coverage.loc[
        coverage["source_family"].eq("depth_charts") & coverage["season"].eq(2025)
    ].iloc[0]
    assert row["source_rows"] == 1
    assert row["source_status"] == "timestamped_schema_missing_schedule_cutoffs"


def test_predictor_allowlist_excludes_audit_timestamps_and_match_methods() -> None:
    features = {
        feature
        for family_features in HISTORICAL_FEATURE_ALLOWLIST.values()
        for feature in family_features
    }
    assert "source_depth_observed_at" not in features
    assert "source_depth_rank_pit" not in features
    assert "source_depth_rank_pregame" in features
    assert "official_evidence_date_modified" not in features
    assert "official_prediction_cutoff" not in features
    assert "source_snap_id_match_method_lag1" not in features


def test_participation_file_availability_is_inferred_after_pbp_join() -> None:
    panel = _panel(
        [
            {
                "season": 2024,
                "week": week,
                "game_id": f"g{week}",
                "player_id": "G1",
                "recent_team": "AAA",
            }
            for week in (1, 2)
        ]
    )
    participation = pd.DataFrame(
        {
            "nflverse_game_id": ["g1", "g2"],
            "play_id": [1, 1],
            "possession_team": ["AAA", "AAA"],
            "offense_players": ["G1,GQB", "G1,GQB"],
        }
    )
    pbp = pd.DataFrame(
        {
            "game_id": ["g1", "g2"],
            "play_id": [1, 1],
            "season": [2024, 2024],
            "week": [1, 2],
            "qb_dropback": [1, 1],
        }
    )
    _, coverage = build_historical_source_features(
        panel,
        participation=participation,
        pbp=pbp,
    )
    row = coverage.loc[
        coverage["source_family"].eq("pass_play_participation") & coverage["season"].eq(2024)
    ].iloc[0]
    assert row["source_file_available"]
    assert row["required_files_available"]
    assert row["source_rows"] == 4
    assert row["explicit_evidence_match_rate"] == 0.5


def test_untimestamped_injury_season_remains_unavailable_and_unknown() -> None:
    panel = _panel(
        [
            {
                "season": 2025,
                "week": 1,
                "game_id": "2025_01_BBB_AAA",
                "player_id": "G1",
                "recent_team": "AAA",
            }
        ]
    )
    schedules = pd.DataFrame(
        {
            "game_id": ["2025_01_BBB_AAA"],
            "gameday": ["2025-09-07"],
            "gametime": ["13:00"],
        }
    )
    injuries = pd.DataFrame(
        {
            "season": [2025],
            "week": [1],
            "gsis_id": ["G1"],
            "full_name": ["Player"],
            "team": ["AAA"],
            "report_status": ["Out"],
            "practice_status": ["DNP"],
        }
    )
    features, coverage = build_historical_source_features(
        panel,
        injuries=injuries,
        schedules=schedules,
    )
    row = features.iloc[0]
    assert row["official_injury_source_available"] == 0
    assert pd.isna(row["official_injury_evidence_present"])
    assert pd.isna(row["official_availability_prior"])
    injury_coverage = coverage.loc[
        coverage["source_family"].eq("official_injuries") & coverage["season"].eq(2025)
    ].iloc[0]
    assert injury_coverage["source_file_available"]
    assert not injury_coverage["required_files_available"]
    assert injury_coverage["source_status"] == "source_timestamps_unavailable"
    assert injury_coverage["explicit_evidence_match_rate"] == 0.0


def test_material_experiment_bundle_has_required_contract(tmp_path) -> None:
    methods = [
        "numerical_baseline",
        "snap_counts",
        "shuffled_player_control",
        "shifted_time_leakage_control",
    ]
    predictions = pd.DataFrame(
        {
            "method": methods,
            "actual_fantasy_points_ppr": [10.0] * 4,
            "adjusted_q10": [5.0] * 4,
            "adjusted_q50": [9.0] * 4,
            "adjusted_q90": [15.0] * 4,
            "season": [2025] * 4,
            "position": ["RB"] * 4,
        }
    )
    summary = pd.DataFrame(
        {
            "method": methods,
            "mae": [1.0, 1.1, 1.2, 0.9],
            "mean_pinball": [1.0, 1.1, 1.2, 0.9],
            "interval_coverage": [0.8, 0.8, 0.7, 0.9],
            "interval_width": [10.0] * 4,
            "pinball_improvement_vs_baseline_pct": [0.0, -10.0, -20.0, 10.0],
        }
    )
    coverage = pd.DataFrame(
        {
            "source_family": ["official_injuries"],
            "season": [2025],
            "source_status": ["source_timestamps_unavailable"],
            "required_files_available": [False],
        }
    )
    result = HistoricalSourceAblationResult(
        predictions=predictions,
        summary=summary,
        season_metrics=summary.assign(season=2025),
        position_metrics=summary.assign(position="RB"),
        feature_manifest=pd.DataFrame(
            {"ablation": ["snap_counts"], "feature": ["source_snap_share_lag1"]}
        ),
        coverage=coverage,
    )
    paths = persist_historical_source_experiment(
        result,
        tmp_path,
        config={"experiment_id": "test", "cutoff": "kickoff minus 1.5 hours"},
        git_commit="abc123",
    )
    required = {
        "config.yaml",
        "manifest.json",
        "predictions.parquet",
        "summary_metrics.csv",
        "season_metrics.csv",
        "position_metrics.csv",
        "calibration.csv",
        "notes.md",
        "git_commit.txt",
        "residual_cohorts.csv",
    }
    assert required.issubset({path.name for path in tmp_path.iterdir()})
    assert paths["manifest"].exists()
    assert "Source coverage and cutoff validity" in paths["notes"].read_text(encoding="utf-8")
    assert "q50_bias" in pd.read_csv(tmp_path / "summary_metrics.csv")
