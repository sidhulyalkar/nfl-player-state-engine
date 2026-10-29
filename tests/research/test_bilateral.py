"""Synthetic invariant/negative tests; no claims about actual Combine measurements."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from player_state_engine.research.bilateral import (
    FieldFrame,
    asymmetry_profiles,
    extract_turn_events,
    field_context,
)


def trajectory(segment: str, sign: int, *, exit_speed: float = 4.0, position: str = "DB") -> pd.DataFrame:
    assert sign in (-1, 1)
    points = [(0.5 * j, 0.0) for j in range(6)]
    points += [(2.5, sign * exit_speed * j / 10) for j in range(1, 7)]
    return pd.DataFrame([{
        "source_kind": "combine", "source_id": "drill-a", "segment_id": segment,
        "player_id": "p1", "position": position,
        "frame_id": i, "time_s": i / 10, "x": x, "y": y + 24,
    } for i, (x, y) in enumerate(points)])


def test_offensive_left_flips_with_direction_but_stadium_y_does_not() -> None:
    a = field_context(50, 40, offense_direction=+1, ball_y=10)
    b = field_context(50, 40, offense_direction=-1, ball_y=10)
    assert a["offense_left_right"] == "left"
    assert b["offense_left_right"] == "right"
    assert a["boundary_field"] == "field"
    assert b["boundary_field"] == "field"
    assert a["stadium_y"] == b["stadium_y"]


def test_boundary_requires_known_off_center_ball() -> None:
    assert field_context(20, 8, offense_direction=1, ball_y=9)["boundary_field"] == "boundary"
    assert field_context(20, 8, offense_direction=1)["boundary_field"] is None
    assert field_context(20, 8, offense_direction=1, ball_y=26.5)["boundary_field"] is None
    assert field_context(20, 26.6, offense_direction=1, ball_y=6)["boundary_field"] is None


@pytest.mark.parametrize("direction", [0, 2, -2])
def test_invalid_offense_direction_fails_closed(direction: int) -> None:
    with pytest.raises(ValueError, match="offense_direction"):
        field_context(20, 30, offense_direction=direction)


def test_official_width_and_invalid_ball() -> None:
    assert FieldFrame().field_width_yards == pytest.approx(160 / 3)
    with pytest.raises(ValueError, match="ball_y"):
        field_context(20, 12, offense_direction=1, ball_y=100)


def test_signed_turns_not_anatomical_left_foot() -> None:
    frames = pd.concat([trajectory("a", 1), trajectory("b", -1)], ignore_index=True)
    events = extract_turn_events(frames)
    assert len(events) == 2
    assert dict(zip(events.segment_id, events.turn, strict=True)) == {"a": "left", "b": "right"}
    assert set(events.angle_bin) == {"[75,110)"}
    assert set(events.speed_bin) == {"[4,6)"}
    assert (events.speed_retention < 1).all()


def test_rigid_rotation_preserves_turn_sign() -> None:
    data = trajectory("rotation", 1)
    radians = np.deg2rad(72)
    x, y = data.x.copy(), data.y.copy()
    data.x = x * np.cos(radians) - y * np.sin(radians)
    data.y = x * np.sin(radians) + y * np.cos(radians)
    events = extract_turn_events(data)
    assert len(events) == 1
    assert events.iloc[0].turn == "left"


def test_mirrored_y_flips_turn_sign_and_requires_upstream_convention() -> None:
    data = trajectory("reflection", 1)
    data.y = -data.y
    events = extract_turn_events(data)
    assert len(events) == 1
    assert events.iloc[0].turn == "right"


def test_empty_and_stationary_segments_do_not_invent_events() -> None:
    data = trajectory("static", 1)
    data.x, data.y = 10.0, 10.0
    assert extract_turn_events(data).empty


def test_duplicate_frames_fail_closed() -> None:
    data = trajectory("a", 1)
    with pytest.raises(ValueError, match="duplicate"):
        extract_turn_events(pd.concat([data, data.iloc[[1]]], ignore_index=True))


def test_sampling_gap_fails_closed_not_interpolated() -> None:
    data = trajectory("a", 1)
    data.loc[data.frame_id >= 4, "time_s"] += 0.1
    with pytest.raises(ValueError, match="noncontiguous"):
        extract_turn_events(data)


def test_nonfinite_coordinates_fail_closed() -> None:
    data = trajectory("a", 1)
    data.loc[2, "x"] = np.nan
    with pytest.raises(ValueError, match="nonfinite x"):
        extract_turn_events(data)


def test_player_and_source_separation() -> None:
    a = trajectory("shared", 1)
    b = trajectory("shared", -1)
    b["player_id"] = "p2"
    assert len(extract_turn_events(pd.concat([a, b]))) == 2
    assert set(extract_turn_events(pd.concat([a, b])).player_id) == {"p1", "p2"}


def test_asymmetry_estimated_only_with_matched_independent_segments() -> None:
    data = pd.concat(
        [trajectory(f"left-{i}", 1, exit_speed=3.0) for i in range(5)]
        + [trajectory(f"right-{i}", -1, exit_speed=4.0) for i in range(5)],
        ignore_index=True,
    )
    events = extract_turn_events(data)
    result = asymmetry_profiles(events, bootstrap_samples=200)
    assert len(result) == 1
    row = result.iloc[0]
    assert row.status == "estimated"
    assert row.asymmetry_pct == pytest.approx(100 * (0.8 - 0.6) / 0.7, rel=1e-4)
    assert row.ci_low_pct <= row.asymmetry_pct <= row.ci_high_pct
    assert row.n_left == 5 and row.n_right == 5
    assert row.matched_bins == 1


def test_abstain_when_one_direction_not_repeated() -> None:
    data = pd.concat([trajectory(f"l{i}", 1) for i in range(5)] + [trajectory("r0", -1)])
    row = asymmetry_profiles(extract_turn_events(data)).iloc[0]
    assert row.status == "insufficient_matched_evidence"
    assert pd.isna(row.asymmetry_pct)


def test_asymmetry_abstains_without_matched_demands() -> None:
    events = extract_turn_events(pd.concat(
        [trajectory(f"l{i}", 1, exit_speed=3.0) for i in range(4)]
        + [trajectory(f"r{i}", -1, exit_speed=4.0) for i in range(4)]
    ))
    events.loc[events.turn == "right", "speed_bin"] = "[8,10)"
    result = asymmetry_profiles(events)
    assert result.iloc[0].status == "insufficient_matched_evidence"
    assert result.iloc[0].matched_bins == 0


def test_empty_event_contract() -> None:
    assert len(asymmetry_profiles(extract_turn_events(trajectory("static", 1).assign(x=0.0, y=10.0)))) == 0


def test_tag_field_side_uses_exact_event_frame_and_explicit_ball() -> None:
    from player_state_engine.research.bilateral import tag_event_field_sides

    data = trajectory("game-play", 1)
    data["source_kind"] = "nfl"
    data["source_id"] = "game-1"
    data["y"] += 14  # explicitly place the runner on the north side
    data["offense_direction"] = -1
    data["ball_y"] = 4.0
    events = extract_turn_events(data)
    tagged = tag_event_field_sides(events, data)
    assert len(tagged) == 1
    assert tagged.iloc[0].offense_left_right == "right"  # y near north, offense toward -X
    assert tagged.iloc[0].boundary_field == "field"  # ball near south sideline
    assert tagged.iloc[0].distance_to_nearest_sideline_yd > 0


def test_tag_field_side_abstains_on_combine_and_missing_offense_ball() -> None:
    from player_state_engine.research.bilateral import tag_event_field_sides

    data = trajectory("combine", 1)
    tagged = tag_event_field_sides(extract_turn_events(data), data)
    assert pd.isna(tagged.iloc[0].boundary_field)
    assert pd.isna(tagged.iloc[0].offense_left_right)
    game = data.assign(source_kind="nfl")
    tagged = tag_event_field_sides(extract_turn_events(game), game)
    assert pd.isna(tagged.iloc[0].boundary_field)
    assert pd.isna(tagged.iloc[0].offense_left_right)


def test_stratified_asymmetry_rejects_implicit_untagged_data() -> None:
    events = extract_turn_events(pd.concat([trajectory("l0", 1), trajectory("r0", -1)]))
    with pytest.raises(ValueError, match="tag_event_field_sides"):
        asymmetry_profiles(events, strata_columns=("boundary_field",))


def test_tagged_unknown_strata_never_misreport_boundary() -> None:
    from player_state_engine.research.bilateral import tag_event_field_sides

    data = pd.concat([trajectory(f"l{i}", 1) for i in range(4)] +
                     [trajectory(f"r{i}", -1) for i in range(4)], ignore_index=True)
    tagged = tag_event_field_sides(extract_turn_events(data), data)
    result = asymmetry_profiles(tagged, strata_columns=("boundary_field",), bootstrap_samples=100)
    assert result.iloc[0].boundary_field == "unknown"
    assert not (result.boundary_field == "boundary").any()


def test_field_side_invalid_values_fail_instead_of_guessing() -> None:
    from player_state_engine.research.bilateral import tag_event_field_sides

    data = trajectory("game", 1).assign(source_kind="nfl", offense_direction=0, ball_y=10)
    with pytest.raises(ValueError, match="offense_direction"):
        tag_event_field_sides(extract_turn_events(data), data)


def test_empty_events_preserve_field_side_contract() -> None:
    from player_state_engine.research.bilateral import tag_event_field_sides

    raw = trajectory("static", 1).assign(x=10.0, y=10.0)
    events = extract_turn_events(raw)
    tagged = tag_event_field_sides(events, raw)
    assert tagged.empty
    assert "boundary_field" in tagged.columns
    assert asymmetry_profiles(tagged, strata_columns=("boundary_field",)).empty
