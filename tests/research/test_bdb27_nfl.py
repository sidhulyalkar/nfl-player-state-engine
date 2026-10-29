"""Synthetic integration gates for rookie NFL linkage. No NFL result claims."""
from __future__ import annotations

import pandas as pd
import pytest

from player_state_engine.research.bdb27_nfl import (
    canonical_rookie_game,
    rookie_linkage,
    run_rookie_game_audit,
)
from player_state_engine.research.bdb27_qualification import QualificationConfig
from player_state_engine.research.bilateral import (
    asymmetry_profiles,
    extract_turn_events,
    tag_event_field_sides,
)
from tests.research.test_bdb27_qualification import attempt, players


def games():
    return pd.DataFrame({"game_id": [11, 12, 13], "season": [2023, 2023, 2024],
                         "season_type": ["REG", "PRE", "REG"]})


def nfl_frames():
    rows = []
    for play in range(1, 9):
        src = attempt(play, side=1 if play <= 4 else -1)
        for k, (_, row) in enumerate(src.iterrows()):
            rows.append({"nfl_id": row.nfl_id, "game_id": 11, "play_id": play,
                         "frame_id": k+1, "x": row.x, "y": row.y})
    # Same athlete but a preseason game should never enter the rookie result.
    rows.append({"nfl_id": 1001, "game_id": 12, "play_id": 99,
                 "frame_id": 1, "x": 5., "y": 23.})
    # A ball row can legitimately lack nfl_id.
    rows.append({"nfl_id": None, "game_id": 11, "play_id": 1,
                 "frame_id": 1, "x": 2., "y": 24.})
    # 2024 rookie WR, not the 2023 DB selection.
    rows.append({"nfl_id": 1002, "game_id": 13, "play_id": 4,
                 "frame_id": 1, "x": 2., "y": 24.})
    return pd.DataFrame(rows)


def test_rookie_regular_season_only_and_no_ball_confusion():
    c, coverage, audit = canonical_rookie_game(
        nfl_frames(), games(), players(), QualificationConfig(1), position="DB")
    assert len(coverage) == 8
    assert audit["eligible_players"] == 1
    assert audit["excluded_ball_or_missing_player_id"] == 1
    assert audit["eligible_frames"] == 96
    assert c.independent_trial_id.nunique() == 8
    assert c.source_kind.eq("nfl").all()
    assert c.draft_year.eq(2023).all()
    events = tag_event_field_sides(extract_turn_events(c), c)
    assert events.boundary_field.isna().all()
    result = asymmetry_profiles(events, bootstrap_samples=100)
    assert result.iloc[0].status == "estimated"
    assert result.iloc[0].segments_left == 4
    assert result.iloc[0].segments_right == 4


def test_bad_game_key_is_not_silently_dropped():
    bad = nfl_frames()
    bad.loc[0, "game_id"] = 1999
    with pytest.raises(ValueError, match="missing from games.csv"):
        canonical_rookie_game(bad, games(), players(), QualificationConfig(1))


def test_no_pregame_game_leakage():
    only_pre = nfl_frames().query("game_id == 12")
    with pytest.raises(ValueError, match="no valid rookie regular-season"):
        canonical_rookie_game(only_pre, games(), players(), QualificationConfig(1))


def test_missing_frame_id_and_time_fails_closed():
    data = nfl_frames().drop(columns="frame_id")
    with pytest.raises(ValueError, match="frame_id or time"):
        canonical_rookie_game(data, games(), players(), QualificationConfig(1))


def test_duplicate_tracking_frame_fails_closed():
    data = nfl_frames()
    data = pd.concat([data, data.iloc[[0]]], ignore_index=True)
    with pytest.raises(ValueError, match="duplicate frame"):
        canonical_rookie_game(data, games(), players(), QualificationConfig(1))


def test_game_profile_linkage_abstains_without_observations():
    combine = pd.DataFrame({"source_kind": ["combine", "combine"],
                            "source_id": ["BACKPEDAL", "SPEED_OUT"],
                            "player_id": ["1001", "1002"], "position": ["DB", "WR"],
                            "status": ["estimated", "insufficient_matched_evidence"],
                            "asymmetry_pct": [12., None]})
    game = pd.DataFrame({"source_kind": ["nfl"], "source_id": ["ROOKIE_REGULAR_SEASON"],
                         "player_id": ["1001"], "position": ["DB"],
                         "status": ["estimated"], "asymmetry_pct": [4.]})
    joined = rookie_linkage(combine, game)
    assert joined.iloc[0].link_status == "paired_estimate_not_yet_validation"
    assert joined.iloc[1].nfl_status == "no_rookie_tracking"
    assert joined.iloc[1].link_status == "insufficient_evidence"


def test_realpath_guard_and_local_source_digest(tmp_path):
    source = tmp_path / "raw"
    source.mkdir()
    players().to_csv(source / "players.csv", index=False)
    games().to_csv(source / "games.csv", index=False)
    nfl_frames().to_csv(source / "game_tracking_2023.csv", index=False)
    out = tmp_path / "out"
    with pytest.raises(ValueError, match="acknowledgement"):
        run_rookie_game_audit(source, out, position="DB", year=2023,
                              config=QualificationConfig(1))
    manifest = run_rookie_game_audit(source, out, position="DB", year=2023,
                                     config=QualificationConfig(1), rights_acknowledged=True)
    assert manifest["audit"]["eligible_frames"] == 96
    assert manifest["audit"]["profiles_estimated"] == 1
    assert "game_tracking_2023.csv" in manifest["source_files"]
    assert (out / "nfl_2023_DB_profiles_RESEARCH_ONLY.csv").is_file()


def test_game_reflection_keeps_valid_field_coords_and_flips_turns():
    source = nfl_frames()
    a, _, _ = canonical_rookie_game(source, games(), players(), QualificationConfig(1))
    b, _, _ = canonical_rookie_game(source, games(), players(), QualificationConfig(-1))
    assert ((b.y >= 0) & (b.y <= 160 / 3)).all()
    ae = extract_turn_events(a)
    be = extract_turn_events(b)
    assert len(ae) == len(be) == 8
    assert ae.turn.eq("left").sum() == be.turn.eq("right").sum()
    assert ae.turn.eq("right").sum() == be.turn.eq("left").sum()
    # Side tags cannot be hallucinated from reflected geometry alone.
    assert tag_event_field_sides(be, b).boundary_field.isna().all()
