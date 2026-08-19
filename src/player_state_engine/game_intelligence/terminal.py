from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from player_state_engine.game_intelligence.decision import (
    DriveTerminationHazardModel,
    _add_context,
    _chronology,
    _normalize_game_id,
    _numeric,
    _play_family,
    _recency_weights,
)

TERMINAL_FAMILIES = ("CONTINUE", "SCORE", "TURNOVER", "DOWNS", "END_HALF")
TERMINAL_END_FAMILIES = TERMINAL_FAMILIES[1:]
_TERMINAL_FAMILY_CONTEXT_COLUMNS = (
    "down_bucket",
    "field_zone",
    "distance_bucket",
    "clock_bucket",
    "score_state",
    "play_family",
    "end_window",
)


def _quarter_from_clock(value: float) -> int:
    if value > 2700:
        return 1
    if value > 1800:
        return 2
    if value > 900:
        return 3
    return 4


def _seconds_to_boundary(clock: float) -> float:
    quarter = _quarter_from_clock(float(clock))
    if quarter == 2:
        return max(0.0, float(clock) - 1800.0)
    if quarter == 4:
        return max(0.0, float(clock))
    return float("inf")


def _with_terminal_context(frame: pd.DataFrame) -> pd.DataFrame:
    data = _add_context(frame)
    clock = _numeric(data, "game_seconds_remaining", 3600.0).clip(0.0, 3600.0)
    if "qtr" in data:
        qtr = pd.to_numeric(data["qtr"], errors="coerce")
        fallback = clock.map(_quarter_from_clock)
        qtr = qtr.fillna(fallback).astype(int)
    else:
        qtr = clock.map(_quarter_from_clock).astype(int)
    data["qtr"] = qtr
    seconds = pd.Series(
        [_seconds_to_boundary(value) for value in clock.to_numpy(dtype=float)],
        index=data.index,
        dtype=float,
    )
    data["seconds_to_half_or_game"] = seconds
    data["end_window"] = seconds.le(120.0).astype(int)
    return data


def extract_terminal_family_events(pbp: pd.DataFrame) -> pd.DataFrame:
    """Label the realized possession family after each offensive scrimmage play.

    Unlike the v0.15 diagnostic hazard, a third-down failure followed by a punt or field-goal
    attempt remains ``CONTINUE`` here. The possession has not ended yet; the fourth-down policy
    still owns the next action. Only a score, turnover, failed fourth down, or half/game expiry
    is terminal for this generative target.
    """
    data = _normalize_game_id(pbp)
    required = {
        "season",
        "week",
        "game_id",
        "play_id",
        "posteam",
        "down",
        "ydstogo",
        "yardline_100",
        "game_seconds_remaining",
    }
    missing = required - set(data)
    if missing:
        raise ValueError(f"Terminal-family extraction missing columns: {sorted(missing)}")

    data = data.sort_values(["season", "week", "game_id", "play_id"], kind="mergesort").copy()
    data = _with_terminal_context(data)
    family = _play_family(data)
    no_play = _numeric(data, "no_play")
    scrimmage = family.ne("OTHER") & no_play.lt(0.5) & data["posteam"].notna()

    play_type = data.get("play_type", pd.Series("", index=data.index)).astype(str).str.lower()
    punt = _numeric(data, "punt_attempt").ge(0.5) | play_type.eq("punt")
    field_goal = _numeric(data, "field_goal_attempt").ge(0.5) | play_type.isin(
        {"field_goal", "field goal"}
    )
    possession_event = (scrimmage | punt | field_goal) & no_play.lt(0.5)
    event_rows = data.loc[possession_event, ["game_id", "qtr"]].copy()
    event_rows["next_event_qtr"] = event_rows.groupby("game_id", sort=False)["qtr"].shift(-1)
    next_event_qtr = event_rows["next_event_qtr"].reindex(data.index)

    result = data.loc[scrimmage].copy()
    if result.empty:
        return pd.DataFrame()
    result["play_family"] = family.loc[result.index]
    result["team"] = result["posteam"].astype(str)
    result["opponent"] = result.get("defteam", pd.Series("UNKNOWN", index=result.index)).astype(str)
    result["ydstogo"] = _numeric(result, "ydstogo", 10.0).clip(0.1, 99.0)
    result["yardline_100"] = _numeric(result, "yardline_100", 75.0).clip(0.5, 99.5)
    result["game_seconds_remaining"] = _numeric(
        result, "game_seconds_remaining", 3600.0
    ).clip(0.0, 3600.0)
    result["score_differential"] = _numeric(result, "score_differential", 0.0)
    result = _with_terminal_context(result)

    turnover = (
        _numeric(result, "turnover")
        .add(_numeric(result, "interception"))
        .add(_numeric(result, "fumble_lost"))
        .gt(0)
    )
    touchdown = _numeric(result, "touchdown").ge(0.5) & ~turnover
    first_down = _numeric(result, "first_down").ge(0.5)
    failed_fourth = _numeric(result, "down").eq(4) & ~first_down & ~turnover & ~touchdown
    current_qtr = pd.to_numeric(result["qtr"], errors="coerce").fillna(4).astype(int)
    next_qtr = next_event_qtr.reindex(result.index)
    end_half = current_qtr.isin([2, 4]) & (next_qtr.isna() | next_qtr.gt(current_qtr))

    result["terminal_family"] = np.select(
        [turnover, touchdown, failed_fourth, end_half],
        ["TURNOVER", "SCORE", "DOWNS", "END_HALF"],
        default="CONTINUE",
    )
    result["terminated"] = result["terminal_family"].ne("CONTINUE").astype(int)
    result["recency_weight"] = 1.0

    columns = [
        "season",
        "week",
        "game_id",
        "play_id",
        "team",
        "opponent",
        "terminated",
        "terminal_family",
        "down",
        "ydstogo",
        "yardline_100",
        "game_seconds_remaining",
        "score_differential",
        "qtr",
        "seconds_to_half_or_game",
        "play_family",
        *_TERMINAL_FAMILY_CONTEXT_COLUMNS,
    ]
    columns = list(dict.fromkeys(columns))
    return result[columns].reset_index(drop=True)


def attach_terminal_family_labels(
    play_frame: pd.DataFrame,
    raw_pbp: pd.DataFrame,
) -> pd.DataFrame:
    """Attach canonical terminal labels to normalized scrimmage rows by game/play identity."""
    if "game_id" not in play_frame or "play_id" not in play_frame:
        raise ValueError("Play frame requires game_id and play_id for terminal label attachment")
    labels = extract_terminal_family_events(raw_pbp)
    if labels.empty:
        data = play_frame.copy()
        data["terminal_family"] = pd.NA
        return data
    label_frame = labels[["game_id", "play_id", "terminal_family"]].copy()
    label_frame["game_id"] = label_frame["game_id"].astype(str)
    data = play_frame.copy()
    data["game_id"] = data["game_id"].astype(str)
    return data.merge(
        label_frame,
        on=["game_id", "play_id"],
        how="left",
        validate="one_to_one",
    )


def permute_terminal_families_within_context_season(
    events: pd.DataFrame,
    *,
    seed: int = 42,
) -> pd.DataFrame:
    """Break fine state/team mapping while preserving broad family marginals."""
    data = events.copy() if "terminal_family" in events else extract_terminal_family_events(events)
    rng = np.random.default_rng(seed)
    for _, index in data.groupby(
        ["season", "down_bucket", "field_zone"], sort=False
    ).groups.items():
        labels = list(index)
        values = data.loc[labels, "terminal_family"].to_numpy(copy=True)
        rng.shuffle(values)
        data.loc[labels, "terminal_family"] = values
    data["terminated"] = data["terminal_family"].ne("CONTINUE").astype(int)
    return data


def permute_conditional_terminal_families_within_context_season(
    events: pd.DataFrame,
    *,
    seed: int = 42,
) -> pd.DataFrame:
    """Shuffle terminal type only, preserving the exact termination hazard labels."""
    data = events.copy() if "terminal_family" in events else extract_terminal_family_events(events)
    rng = np.random.default_rng(seed)
    terminal = data["terminal_family"].ne("CONTINUE")
    subset = data.loc[terminal]
    for _, index in subset.groupby(
        ["season", "down_bucket", "field_zone"], sort=False
    ).groups.items():
        labels = list(index)
        values = data.loc[labels, "terminal_family"].to_numpy(copy=True)
        rng.shuffle(values)
        data.loc[labels, "terminal_family"] = values
    data["terminated"] = terminal.astype(int)
    return data


def _normalize(values: np.ndarray) -> np.ndarray:
    array = np.asarray(values, dtype=float)
    array[~np.isfinite(array)] = 0.0
    array = np.clip(array, 0.0, None)
    total = float(array.sum())
    if total <= 0:
        return np.full(len(array), 1.0 / max(len(array), 1), dtype=float)
    return array / total


def _weighted_terminal_counts(frame: pd.DataFrame) -> np.ndarray:
    if frame.empty:
        return np.zeros(len(TERMINAL_END_FAMILIES), dtype=float)
    weights = pd.to_numeric(frame["recency_weight"], errors="coerce").fillna(0.0)
    return np.asarray(
        [
            float(weights.loc[frame["terminal_family"].eq(family)].sum())
            for family in TERMINAL_END_FAMILIES
        ],
        dtype=float,
    )


def _top_label_ece(actual: np.ndarray, matrix: np.ndarray, bins: int = 10) -> float:
    confidence = np.max(matrix, axis=1)
    predicted = np.argmax(matrix, axis=1)
    correctness = (predicted == actual).astype(float)
    edges = np.linspace(0.0, 1.0, bins + 1)
    total = max(len(actual), 1)
    error = 0.0
    for index in range(bins):
        lower, upper = edges[index], edges[index + 1]
        mask = (confidence >= lower) & (
            confidence <= upper if index == bins - 1 else confidence < upper
        )
        if not mask.any():
            continue
        error += float(mask.sum()) / total * abs(
            float(correctness[mask].mean()) - float(confidence[mask].mean())
        )
    return float(error)


@dataclass(slots=True)
class TerminalFamilyModel:
    """Two-stage point-in-time terminal-family generator.

    Stage one estimates whether the current offensive scrimmage play ends the possession.
    Stage two estimates the terminal type conditional on an ending. The decomposition keeps
    the v0.15 hazard question visible instead of allowing a strong CONTINUE majority class to
    hide a weak SCORE/TURNOVER/DOWNS/END_HALF classifier.
    """

    prior_strength: float = 30.0
    half_life_weeks: float = 8.0
    authority_end_window_seconds: float = 45.0
    model_source: str = "hierarchical_terminal_family_v016"
    fitted: bool = False
    train_max_season: int | None = None
    train_max_week: int | None = None
    events: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)
    hazard_model: DriveTerminationHazardModel = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.hazard_model = DriveTerminationHazardModel(
            prior_strength=float(self.prior_strength),
            half_life_weeks=float(self.half_life_weeks),
            model_source="canonical_possession_termination_hazard_v016",
        )

    def fit(self, pbp: pd.DataFrame) -> TerminalFamilyModel:
        frame = pbp.copy() if "terminal_family" in pbp else extract_terminal_family_events(pbp)
        return self.fit_frame(frame)

    def fit_frame(self, frame: pd.DataFrame) -> TerminalFamilyModel:
        required = {
            "season",
            "week",
            "team",
            "terminated",
            "terminal_family",
            *_TERMINAL_FAMILY_CONTEXT_COLUMNS,
        }
        missing = required - set(frame)
        if missing:
            raise ValueError(f"TerminalFamilyModel missing columns: {sorted(missing)}")
        data = frame.loc[frame["terminal_family"].isin(TERMINAL_FAMILIES)].copy()
        if len(data) < 50:
            raise ValueError("TerminalFamilyModel requires at least 50 labeled scrimmage events")
        if data["terminal_family"].nunique() < 2:
            raise ValueError("TerminalFamilyModel requires more than one terminal family")
        data["terminated"] = data["terminal_family"].ne("CONTINUE").astype(int)
        data["recency_weight"] = _recency_weights(data, self.half_life_weeks)
        self.events = data.reset_index(drop=True)
        self.hazard_model.fit_frame(self.events)
        cutoff = data[["season", "week"]].apply(pd.to_numeric, errors="coerce").dropna()
        if not cutoff.empty:
            last = cutoff.sort_values(["season", "week"], kind="mergesort").iloc[-1]
            self.train_max_season = int(last["season"])
            self.train_max_week = int(last["week"])
        self.fitted = True
        return self

    def _context_pool(
        self,
        frame: pd.DataFrame,
        state: dict[str, object] | pd.Series,
        *,
        play_family: str,
    ) -> pd.DataFrame:
        state_dict = state.to_dict() if isinstance(state, pd.Series) else dict(state)
        one = _with_terminal_context(
            pd.DataFrame(
                [
                    {
                        "down": float(state_dict.get("down", 1.0)),
                        "ydstogo": float(state_dict.get("ydstogo", 10.0)),
                        "yardline_100": float(state_dict.get("yardline_100", 75.0)),
                        "game_seconds_remaining": float(
                            state_dict.get("game_seconds_remaining", 3600.0)
                        ),
                        "score_differential": float(state_dict.get("score_differential", 0.0)),
                        "play_family": str(play_family),
                    }
                ]
            )
        ).iloc[0]
        contextual = frame
        for column in _TERMINAL_FAMILY_CONTEXT_COLUMNS:
            contextual = contextual.loc[contextual[column].astype(str).eq(str(one[column]))]
        return contextual

    def _conditional_distribution(
        self,
        *,
        team: str,
        state: dict[str, object] | pd.Series,
        play_family: str,
        use_team: bool,
        use_context: bool,
    ) -> np.ndarray:
        terminal = self.events.loc[self.events["terminal_family"].ne("CONTINUE")]
        global_probability = _normalize(_weighted_terminal_counts(terminal))
        team_pool = terminal.loc[terminal["team"].astype(str).eq(str(team))]
        strength = max(float(self.prior_strength), 1e-6)

        def shrink(pool: pd.DataFrame, prior: np.ndarray) -> np.ndarray:
            return _normalize(_weighted_terminal_counts(pool) + strength * prior)

        team_probability = (
            shrink(team_pool, global_probability)
            if use_team and not team_pool.empty
            else global_probability
        )
        if not use_context:
            return team_probability
        global_context = self._context_pool(terminal, state, play_family=play_family)
        context_probability = (
            shrink(global_context, global_probability)
            if not global_context.empty
            else global_probability
        )
        if not use_team:
            return context_probability
        prior = _normalize(team_probability + context_probability)
        team_context = (
            self._context_pool(team_pool, state, play_family=play_family)
            if not team_pool.empty
            else pd.DataFrame()
        )
        return shrink(team_context, prior) if not team_context.empty else prior

    @staticmethod
    def _structural_terminal_support(
        state: dict[str, object] | pd.Series,
        *,
        authority_mode: bool,
        authority_end_window_seconds: float,
    ) -> np.ndarray:
        state_dict = state.to_dict() if isinstance(state, pd.Series) else dict(state)
        down = int(round(float(state_dict.get("down", 1.0))))
        clock = float(state_dict.get("game_seconds_remaining", 3600.0))
        support = np.ones(len(TERMINAL_END_FAMILIES), dtype=float)
        support[TERMINAL_END_FAMILIES.index("DOWNS")] = float(down == 4)
        if authority_mode:
            seconds = _seconds_to_boundary(clock)
            support[TERMINAL_END_FAMILIES.index("END_HALF")] = float(
                np.isfinite(seconds) and seconds <= float(authority_end_window_seconds)
            )
        return support

    def distribution(
        self,
        *,
        team: str,
        state: dict[str, object] | pd.Series,
        play_family: str,
        use_team: bool = True,
        use_context: bool = True,
        authority_mode: bool = False,
    ) -> dict[str, float]:
        if not self.fitted:
            raise RuntimeError("TerminalFamilyModel must be fitted before prediction")
        hazard = self.hazard_model.probability(
            team=team,
            state=state,
            play_family=play_family,
            use_team=use_team,
            use_context=use_context,
        )
        conditional = self._conditional_distribution(
            team=team,
            state=state,
            play_family=play_family,
            use_team=use_team,
            use_context=use_context,
        )
        support = self._structural_terminal_support(
            state,
            authority_mode=authority_mode,
            authority_end_window_seconds=self.authority_end_window_seconds,
        )
        conditional = _normalize(conditional * support)
        probability = np.concatenate(([1.0 - hazard], hazard * conditional))
        probability = _normalize(probability)
        return {
            family: float(probability[index])
            for index, family in enumerate(TERMINAL_FAMILIES)
        }

    def score_events(self, events: pd.DataFrame) -> pd.DataFrame:
        data = events.copy() if "terminal_family" in events else extract_terminal_family_events(events)
        rows: list[dict[str, object]] = []
        for _, row in data.iterrows():
            state = row.to_dict()
            play_family = str(row["play_family"])
            model = self.distribution(
                team=str(row["team"]), state=state, play_family=play_family
            )
            team_base = self.distribution(
                team=str(row["team"]),
                state=state,
                play_family=play_family,
                use_context=False,
            )
            context_base = self.distribution(
                team=str(row["team"]),
                state=state,
                play_family=play_family,
                use_team=False,
                use_context=True,
            )
            global_base = self.distribution(
                team=str(row["team"]),
                state=state,
                play_family=play_family,
                use_team=False,
                use_context=False,
            )
            actual = str(row["terminal_family"])
            record: dict[str, object] = {
                "season": int(row["season"]),
                "week": int(row["week"]),
                "game_id": str(row["game_id"]),
                "team": str(row["team"]),
                "actual_family": actual,
                "actual_probability": model[actual],
                "team_base_probability": team_base[actual],
                "context_base_probability": context_base[actual],
                "global_base_probability": global_base[actual],
            }
            for family in TERMINAL_FAMILIES:
                key = family.lower()
                record[f"p_{key}"] = model[family]
                record[f"team_base_p_{key}"] = team_base[family]
                record[f"context_base_p_{key}"] = context_base[family]
            rows.append(record)
        return pd.DataFrame(rows)


def evaluate_terminal_family_scores(scored: pd.DataFrame) -> dict[str, float]:
    if scored.empty:
        raise ValueError("Terminal-family scoring requires held-out scrimmage events")
    actual_name = scored["actual_family"].astype(str).to_numpy()
    family_index = {family: index for index, family in enumerate(TERMINAL_FAMILIES)}
    actual = np.asarray([family_index[value] for value in actual_name], dtype=int)
    model = scored[[f"p_{family.lower()}" for family in TERMINAL_FAMILIES]].to_numpy(dtype=float)
    team_base = scored[
        [f"team_base_p_{family.lower()}" for family in TERMINAL_FAMILIES]
    ].to_numpy(dtype=float)
    context_base = scored[
        [f"context_base_p_{family.lower()}" for family in TERMINAL_FAMILIES]
    ].to_numpy(dtype=float)
    one_hot = np.eye(len(TERMINAL_FAMILIES), dtype=float)[actual]
    predicted = np.argmax(model, axis=1)
    actual_probability = model[np.arange(len(model)), actual]
    team_probability = team_base[np.arange(len(team_base)), actual]
    context_probability = context_base[np.arange(len(context_base)), actual]
    global_probability = pd.to_numeric(
        scored["global_base_probability"], errors="coerce"
    ).to_numpy(dtype=float)
    actual_terminal = (actual_name != "CONTINUE").astype(float)
    terminal_probability = 1.0 - model[:, 0]
    team_terminal_probability = 1.0 - team_base[:, 0]
    context_terminal_probability = 1.0 - context_base[:, 0]

    metrics = {
        "terminal_family_rows": float(len(scored)),
        "terminal_family_log_loss": float(
            -np.mean(np.log(np.clip(actual_probability, 1e-8, 1.0)))
        ),
        "terminal_family_brier": float(np.mean(np.sum((model - one_hot) ** 2, axis=1))),
        "terminal_family_accuracy": float(np.mean(predicted == actual)),
        "terminal_family_ece": _top_label_ece(actual, model),
        "team_base_terminal_family_log_loss": float(
            -np.mean(np.log(np.clip(team_probability, 1e-8, 1.0)))
        ),
        "context_base_terminal_family_log_loss": float(
            -np.mean(np.log(np.clip(context_probability, 1e-8, 1.0)))
        ),
        "global_base_terminal_family_log_loss": float(
            -np.mean(np.log(np.clip(global_probability, 1e-8, 1.0)))
        ),
        "canonical_termination_log_loss": float(
            -np.mean(
                actual_terminal * np.log(np.clip(terminal_probability, 1e-8, 1.0))
                + (1.0 - actual_terminal)
                * np.log(np.clip(1.0 - terminal_probability, 1e-8, 1.0))
            )
        ),
        "canonical_termination_brier": float(
            np.mean((terminal_probability - actual_terminal) ** 2)
        ),
        "team_base_canonical_termination_brier": float(
            np.mean((team_terminal_probability - actual_terminal) ** 2)
        ),
        "context_base_canonical_termination_brier": float(
            np.mean((context_terminal_probability - actual_terminal) ** 2)
        ),
    }

    terminal_mask = actual_name != "CONTINUE"
    metrics["conditional_terminal_rows"] = float(terminal_mask.sum())
    if terminal_mask.any():
        terminal_matrix = model[terminal_mask, 1:]
        terminal_matrix = terminal_matrix / np.clip(
            terminal_matrix.sum(axis=1, keepdims=True), 1e-8, None
        )
        terminal_actual = actual[terminal_mask] - 1
        conditional_probability = terminal_matrix[
            np.arange(len(terminal_matrix)), terminal_actual
        ]
        metrics["conditional_terminal_log_loss"] = float(
            -np.mean(np.log(np.clip(conditional_probability, 1e-8, 1.0)))
        )
        metrics["conditional_terminal_accuracy"] = float(
            np.mean(np.argmax(terminal_matrix, axis=1) == terminal_actual)
        )

    for family in TERMINAL_FAMILIES:
        index = family_index[family]
        actual_binary = (actual == index).astype(float)
        metrics[f"{family.lower()}_brier"] = float(
            np.mean((model[:, index] - actual_binary) ** 2)
        )
        mask = actual == index
        metrics[f"{family.lower()}_rows"] = float(mask.sum())
        if mask.any():
            metrics[f"{family.lower()}_recall"] = float(np.mean(predicted[mask] == index))
    return metrics


def observed_terminal_family_team_games(pbp: pd.DataFrame) -> pd.DataFrame:
    events = extract_terminal_family_events(pbp)
    columns = [
        "game_id",
        "team",
        "terminal_family_events",
        "terminal_score_events",
        "terminal_turnover_events",
        "terminal_downs_events",
        "terminal_end_half_events",
    ]
    if events.empty:
        return pd.DataFrame(columns=columns)
    data = events.assign(
        terminal=events["terminal_family"].ne("CONTINUE").astype(float),
        score=events["terminal_family"].eq("SCORE").astype(float),
        turnover=events["terminal_family"].eq("TURNOVER").astype(float),
        downs=events["terminal_family"].eq("DOWNS").astype(float),
        end_half=events["terminal_family"].eq("END_HALF").astype(float),
    )
    return (
        data.groupby(["game_id", "team"], dropna=False)
        .agg(
            terminal_family_events=("terminal", "sum"),
            terminal_score_events=("score", "sum"),
            terminal_turnover_events=("turnover", "sum"),
            terminal_downs_events=("downs", "sum"),
            terminal_end_half_events=("end_half", "sum"),
        )
        .reset_index()[columns]
    )


def evaluate_terminal_family_team_draws(
    team_draws: pd.DataFrame,
    observed: pd.DataFrame,
) -> dict[str, float]:
    if team_draws.empty or observed.empty:
        return {}
    metrics = (
        "terminal_family_events",
        "terminal_score_events",
        "terminal_turnover_events",
        "terminal_downs_events",
        "terminal_end_half_events",
    )
    missing = {"game_id", "team", *metrics} - set(team_draws)
    if missing:
        raise ValueError(f"Terminal-family team draws missing columns: {sorted(missing)}")
    predicted = (
        team_draws.groupby(["game_id", "team"], dropna=False)[list(metrics)]
        .mean()
        .reset_index()
    )
    merged = predicted.merge(
        observed,
        on=["game_id", "team"],
        how="outer",
        suffixes=("_pred", "_actual"),
    )
    if merged.empty:
        return {}
    result: dict[str, float] = {"terminal_team_rows": float(len(merged))}
    for metric in metrics:
        predicted_values = pd.to_numeric(
            merged[f"{metric}_pred"], errors="coerce"
        ).fillna(0.0)
        actual_values = pd.to_numeric(
            merged[f"{metric}_actual"], errors="coerce"
        ).fillna(0.0)
        result[f"team_{metric}_mae"] = float(
            np.mean(np.abs(predicted_values - actual_values))
        )
    return result
