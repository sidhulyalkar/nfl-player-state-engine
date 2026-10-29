"""Tests for blind manual annotation exposure, matching and abstention."""
from __future__ import annotations

import pandas as pd
import pytest

from player_state_engine.research.bdb27_event_validation import evaluate_reviewed_events


def key(trial="t1"):
    return dict(source_kind="combine", source_id="BACKPEDAL", player_id="p1",
                independent_trial_id=trial)


def events():
    return pd.DataFrame([{**key(), "time_s": 0.5, "turn": "left"},
                         {**key(), "time_s": 1.6, "turn": "right"},
                         {**key("t2"), "time_s": 0.4, "turn": "left"}])


def exposure():
    return pd.DataFrame([{**key(), "annotator": "A", "complete_review": True},
                         {**key("t2"), "annotator": "A", "complete_review": True}])


def labels():
    return pd.DataFrame([{**key(), "annotator": "A", "time_s": 0.58, "turn": "left"}])


def test_recall_precision_respects_negative_trials_and_wrong_sign():
    score = evaluate_reviewed_events(events(), exposure(), labels()).iloc[0]
    assert score.true_positive == 1
    assert score.false_positive == 2  # t1 unmatched right and empty-labeled t2
    assert score.false_negative == 0
    assert score.precision == pytest.approx(1/3)
    assert score.recall == 1.0


def test_unreviewed_predictions_are_excluded():
    reviewed = exposure().iloc[:1]
    score = evaluate_reviewed_events(events(), reviewed, labels()).iloc[0]
    assert score.false_positive == 1
    assert score.reviewed_trials == 1


def test_wrong_turn_sign_is_not_near_time_match():
    bad = labels().assign(turn="right")
    score = evaluate_reviewed_events(events().iloc[[0]], exposure().iloc[:1], bad).iloc[0]
    assert (score.true_positive, score.false_positive, score.false_negative) == (0, 1, 1)


def test_an_annotation_without_complete_review_is_refused():
    with pytest.raises(ValueError, match="no matching complete reviewed trial"):
        evaluate_reviewed_events(events(), exposure().iloc[:1],
                                 pd.DataFrame([{**key("t2"), "annotator": "A", "time_s": 0.4, "turn": "left"}]))
    with pytest.raises(ValueError, match="incomplete review"):
        evaluate_reviewed_events(events(), exposure().assign(complete_review=False), labels())


def test_duplicate_exposure_refused():
    with pytest.raises(ValueError, match="duplicate reviewed trial"):
        evaluate_reviewed_events(events(), pd.concat([exposure(), exposure().iloc[:1]]), labels())


def test_independent_raters_not_pooled_and_second_rater_can_disagree():
    exp = pd.concat([exposure(), exposure().assign(annotator="B")], ignore_index=True)
    annotated = pd.concat([labels(), labels().assign(annotator="B", turn="right")], ignore_index=True)
    result = evaluate_reviewed_events(events(), exp, annotated)
    assert set(result.annotator) == {"A", "B"}
    assert result.loc[result.annotator.eq("A"), "true_positive"].iloc[0] == 1
    assert result.loc[result.annotator.eq("B"), "true_positive"].iloc[0] == 0


def test_invalid_time_and_tolerance_fail():
    with pytest.raises(ValueError, match="tolerance_s"):
        evaluate_reviewed_events(events(), exposure(), labels(), tolerance_s=2.)
    with pytest.raises(ValueError, match="event time"):
        evaluate_reviewed_events(events().assign(time_s=-1), exposure(), labels())
