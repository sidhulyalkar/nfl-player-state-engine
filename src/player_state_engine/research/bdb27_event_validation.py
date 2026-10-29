"""Blind-review turn-event validation. No skill or perception claims.

Review exposure is defined independently of positive labels so that a reviewed
trial containing zero true turns still contributes to false-positive rates.
One rater's metrics never masquerade as multi-rater agreement.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.optimize import linear_sum_assignment

TRIAL_KEYS = ("source_kind", "source_id", "player_id", "independent_trial_id")
REVIEW_KEYS = (*TRIAL_KEYS, "annotator")


def _keys(frame: pd.DataFrame, names: tuple[str, ...], label: str) -> None:
    missing = set(names) - set(frame.columns)
    if missing:
        raise ValueError(f"{label} missing required columns: {sorted(missing)}")
    if frame[list(names)].isna().any().any():
        raise ValueError(f"{label} contains null identity")


def _match_one(predictions: pd.DataFrame, labels: pd.DataFrame, tolerance_s: float) -> tuple[int, int, int]:
    m, n = len(predictions), len(labels)
    if not m or not n:
        return 0, m, n
    pred_times = predictions.time_s.to_numpy(dtype=float)
    label_times = labels.time_s.to_numpy(dtype=float)
    delta = abs(pred_times[:, None] - label_times[None, :])
    matching_turn = predictions.turn.to_numpy()[:, None] == labels.turn.to_numpy()[None, :]
    valid = (delta <= tolerance_s) & matching_turn
    # Dummy rows/cols allow unmatched events; maximize valid pair count first,
    # then minimize the timing residual of the accepted matches.
    miss_cost = tolerance_s + 1.0
    bad_cost = 10 * miss_cost
    cost = np.zeros((m + n, m + n))
    cost[:m, :n] = np.where(valid, delta, bad_cost)
    cost[:m, n:] = miss_cost
    cost[m:, :n] = miss_cost
    r, c = linear_sum_assignment(cost)
    tp = sum(int(i < m and j < n and valid[i, j]) for i, j in zip(r, c, strict=True))
    return tp, m - tp, n - tp


def evaluate_reviewed_events(
    predictions: pd.DataFrame,
    reviewed_trials: pd.DataFrame,
    human_labels: pd.DataFrame,
    *, tolerance_s: float = 0.2,
) -> pd.DataFrame:
    """Event precision/recall from fully reviewed trials, by independent rater.

    Predictions from unreviewed trials are **excluded** rather than treated as
    false positives. Labels outside the review exposure fail closed.
    """
    if not np.isfinite(tolerance_s) or not 0 < tolerance_s <= 0.5:
        raise ValueError("tolerance_s must be in (0, 0.5] seconds")
    _keys(predictions, (*TRIAL_KEYS, "time_s", "turn"), "predictions")
    _keys(reviewed_trials, (*REVIEW_KEYS, "complete_review"), "reviewed trials")
    _keys(human_labels, (*REVIEW_KEYS, "time_s", "turn"), "human labels")
    if reviewed_trials.duplicated(list(REVIEW_KEYS)).any():
        raise ValueError("duplicate reviewed trial/rater")
    if not reviewed_trials.complete_review.eq(True).all():
        raise ValueError("incomplete review cannot be evaluated")
    for name, frame in (("predictions", predictions), ("human labels", human_labels)):
        if not frame.turn.isin(["left", "right"]).all():
            raise ValueError(f"invalid {name} turn sign")
        t = pd.to_numeric(frame.time_s, errors="coerce").to_numpy(dtype=float)
        if not np.isfinite(t).all() or (t < 0).any() or (t > 300).any():
            raise ValueError(f"invalid {name} event time")
    # All labels must belong to a declared, complete manual review.
    membership = human_labels.merge(reviewed_trials[list(REVIEW_KEYS)],
                                    how="left", on=list(REVIEW_KEYS), indicator=True,
                                    validate="many_to_one")
    if (membership._merge != "both").any():
        raise ValueError("human event label has no matching complete reviewed trial")
    result = []
    for rater, exposure in reviewed_trials.groupby("annotator", sort=True):
        tp = fp = fn = 0
        for row in exposure.itertuples(index=False):
            mask = pd.Series(True, index=predictions.index)
            labels_mask = pd.Series(True, index=human_labels.index)
            for col in TRIAL_KEYS:
                value = getattr(row, col)
                mask &= predictions[col].eq(value)
                labels_mask &= human_labels[col].eq(value)
            labels_mask &= human_labels.annotator.eq(rater)
            t, f, n = _match_one(predictions.loc[mask], human_labels.loc[labels_mask], tolerance_s)
            tp += t
            fp += f
            fn += n
        precision = tp / (tp + fp) if tp + fp else None
        recall = tp / (tp + fn) if tp + fn else None
        f1 = 2 * precision * recall / (precision + recall) if precision is not None and recall is not None and precision + recall else None
        result.append({"annotator": rater, "reviewed_trials": len(exposure),
                       "true_positive": tp, "false_positive": fp, "false_negative": fn,
                       "precision": precision, "recall": recall, "f1": f1,
                       "tolerance_s": tolerance_s,
                       "status": "evaluated_events_not_cognition"})
    return pd.DataFrame(result)
