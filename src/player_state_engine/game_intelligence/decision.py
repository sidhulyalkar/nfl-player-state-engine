from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

_ACTIONS = ("GO", "PUNT", "FIELD_GOAL")
_DECISION_CONTEXT_COLUMNS = (
    "field_zone",
    "distance_bucket",
    "clock_bucket",
    "score_state",
)
_TERMINATION_CONTEXT_COLUMNS = (
    "down_bucket",
    "field_zone",
    "distance_bucket",
    "clock_bucket",
    "score_state",
    "play_family",
)


def _chronology(frame: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(frame["season"], errors="coerce") * 25 + pd.to_numeric(
        frame["week"], errors="coerce"
    )


def _normalize_game_id(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    if "game_id" not in data and "nflverse_game_id" in data:
        data["game_id"] = data["nflverse_game_id"]
    if "game_id" not in data:
        raise ValueError("Decision evidence missing game_id or nflverse_game_id")
    return data


def _numeric(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame:
        return pd.Series(float(default), index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(float(default))


def _distance_bucket(value: float) -> str:
    if value <= 1:
        return "ONE"
    if value <= 3:
        return "SHORT"
    if value <= 6:
        return "MEDIUM"
    if value <= 10:
        return "LONG"
    return "VERY_LONG"


def _field_zone(value: float) -> str:
    if value <= 10:
        return "GOAL_TO_GO"
    if value <= 35:
        return "FG_RANGE"
    if value <= 55:
        return "PLUS_MIDFIELD"
    if value <= 80:
        return "OWN_MIDFIELD"
    return "BACKED_UP"


def _clock_bucket(value: float) -> str:
    if value <= 120:
        return "TWO_MINUTE"
    if value <= 900:
        return "LATE"
    if value <= 1800:
        return "SECOND_HALF"
    return "FIRST_HALF"


def _score_state(value: float) -> str:
    if value <= -8:
        return "TRAILING"
    if value >= 8:
        return "LEADING"
    return "NEUTRAL"


def _down_bucket(value: float) -> str:
    rounded = int(np.clip(round(float(value)), 1, 4))
    return f"DOWN_{rounded}"


def _play_family(frame: pd.DataFrame) -> pd.Series:
    dropback = (
        _numeric(frame, "pass_attempt")
        .add(_numeric(frame, "qb_dropback"))
        .add(_numeric(frame, "qb_scramble"))
        .gt(0)
    )
    rush = _numeric(frame, "rush_attempt").gt(0)
    values = np.select([dropback, rush], ["DROPBACK", "RUSH"], default="OTHER")
    return pd.Series(values, index=frame.index, dtype="object")


def _add_context(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    distance = _numeric(data, "ydstogo", 10.0)
    yardline = _numeric(data, "yardline_100", 75.0)
    clock = _numeric(data, "game_seconds_remaining", 3600.0)
    score = _numeric(data, "score_differential", 0.0)
    down = _numeric(data, "down", 1.0)
    data["distance_bucket"] = distance.map(_distance_bucket)
    data["field_zone"] = yardline.map(_field_zone)
    data["clock_bucket"] = clock.map(_clock_bucket)
    data["score_state"] = score.map(_score_state)
    data["down_bucket"] = down.map(_down_bucket)
    if "play_family" not in data:
        data["play_family"] = _play_family(data)
    return data


def _recency_weights(frame: pd.DataFrame, half_life_weeks: float) -> pd.Series:
    chronology = _chronology(frame)
    latest = int(chronology.max())
    age = (latest - chronology).clip(lower=0)
    return np.power(0.5, age / max(float(half_life_weeks), 0.25))


def _weighted_action_counts(frame: pd.DataFrame) -> np.ndarray:
    if frame.empty:
        return np.zeros(len(_ACTIONS), dtype=float)
    weights = pd.to_numeric(frame["recency_weight"], errors="coerce").fillna(0.0)
    return np.asarray(
        [float(weights.loc[frame["action"].eq(action)].sum()) for action in _ACTIONS],
        dtype=float,
    )


def _normalize_probabilities(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=float)
    values[~np.isfinite(values)] = 0.0
    values = np.clip(values, 0.0, None)
    total = float(values.sum())
    if total <= 0:
        return np.full(len(values), 1.0 / max(len(values), 1), dtype=float)
    return values / total


def _binary_log_loss(actual: np.ndarray, probability: np.ndarray) -> float:
    p = np.clip(np.asarray(probability, dtype=float), 1e-8, 1.0 - 1e-8)
    y = np.asarray(actual, dtype=float)
    return float(np.mean(-(y * np.log(p) + (1.0 - y) * np.log(1.0 - p))))


def _binary_brier(actual: np.ndarray, probability: np.ndarray) -> float:
    return float(np.mean((np.asarray(probability, dtype=float) - np.asarray(actual, dtype=float)) ** 2))


def extract_fourth_down_decisions(pbp: pd.DataFrame) -> pd.DataFrame:
    """Extract realized GO / PUNT / FIELD_GOAL choices from raw point-in-time PBP."""
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
        raise ValueError(f"Fourth-down decision extraction missing columns: {sorted(missing)}")

    down = _numeric(data, "down")
    no_play = _numeric(data, "no_play")
    play_type = data.get("play_type", pd.Series("", index=data.index)).astype(str).str.lower()
    punt = _numeric(data, "punt_attempt").ge(0.5) | play_type.eq("punt")
    field_goal = _numeric(data, "field_goal_attempt").ge(0.5) | play_type.isin(
        {"field_goal", "field goal"}
    )
    go = (
        _numeric(data, "pass_attempt")
        .add(_numeric(data, "rush_attempt"))
        .add(_numeric(data, "qb_dropback"))
        .add(_numeric(data, "qb_scramble"))
        .gt(0)
    )
    candidate = down.eq(4) & no_play.lt(0.5) & (punt | field_goal | go)
    result = data.loc[candidate].copy()
    if result.empty:
        return pd.DataFrame(
            columns=[
                "season",
                "week",
                "game_id",
                "play_id",
                "team",
                "opponent",
                "action",
                "ydstogo",
                "yardline_100",
                "game_seconds_remaining",
                "score_differential",
                *_DECISION_CONTEXT_COLUMNS,
            ]
        )

    result_punt = punt.loc[result.index]
    result_fg = field_goal.loc[result.index]
    result_go = go.loc[result.index]
    result["action"] = np.select(
        [result_fg, result_punt, result_go],
        ["FIELD_GOAL", "PUNT", "GO"],
        default="GO",
    )
    result["team"] = result["posteam"].astype(str)
    result["opponent"] = result.get("defteam", pd.Series("UNKNOWN", index=result.index)).astype(str)
    result["ydstogo"] = _numeric(result, "ydstogo", 10.0).clip(0.1, 99.0)
    result["yardline_100"] = _numeric(result, "yardline_100", 75.0).clip(0.5, 99.5)
    result["game_seconds_remaining"] = _numeric(
        result, "game_seconds_remaining", 3600.0
    ).clip(0.0, 3600.0)
    result["score_differential"] = _numeric(result, "score_differential", 0.0)
    result = _add_context(result)
    columns = [
        "season",
        "week",
        "game_id",
        "play_id",
        "team",
        "opponent",
        "action",
        "ydstogo",
        "yardline_100",
        "game_seconds_remaining",
        "score_differential",
        *_DECISION_CONTEXT_COLUMNS,
    ]
    return result[columns].sort_values(
        ["season", "week", "game_id", "play_id"], kind="mergesort"
    ).reset_index(drop=True)


def _derive_drive_id(frame: pd.DataFrame) -> pd.Series:
    data = frame.sort_values(["season", "week", "game_id", "play_id"], kind="mergesort")
    fallback = (
        data.groupby("game_id", sort=False)["posteam"]
        .transform(lambda values: values.ne(values.shift()).cumsum())
        .astype(float)
    )
    if "drive" in data:
        drive = pd.to_numeric(data["drive"], errors="coerce")
        if drive.notna().any():
            return drive.fillna(fallback).reindex(frame.index)
    return fallback.reindex(frame.index)


def extract_drive_termination_events(pbp: pd.DataFrame) -> pd.DataFrame:
    """Label whether each offensive scrimmage play is the final scrimmage play of its drive."""
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
        raise ValueError(f"Drive-termination extraction missing columns: {sorted(missing)}")

    family = _play_family(data)
    no_play = _numeric(data, "no_play")
    scrimmage = family.ne("OTHER") & no_play.lt(0.5) & data["posteam"].notna()
    result = data.loc[scrimmage].copy()
    if result.empty:
        return pd.DataFrame()
    result["play_family"] = family.loc[result.index]
    result["_drive_id"] = _derive_drive_id(data).loc[result.index]
    result = result.sort_values(
        ["season", "week", "game_id", "_drive_id", "posteam", "play_id"],
        kind="mergesort",
    )
    grouped = result.groupby(["game_id", "_drive_id", "posteam"], sort=False)
    result["terminated"] = grouped.cumcount(ascending=False).eq(0).astype(int)
    result["team"] = result["posteam"].astype(str)
    result["opponent"] = result.get("defteam", pd.Series("UNKNOWN", index=result.index)).astype(str)
    result["ydstogo"] = _numeric(result, "ydstogo", 10.0).clip(0.1, 99.0)
    result["yardline_100"] = _numeric(result, "yardline_100", 75.0).clip(0.5, 99.5)
    result["game_seconds_remaining"] = _numeric(
        result, "game_seconds_remaining", 3600.0
    ).clip(0.0, 3600.0)
    result["score_differential"] = _numeric(result, "score_differential", 0.0)
    result = _add_context(result)

    touchdown = _numeric(result, "touchdown").ge(0.5)
    turnover = (
        _numeric(result, "turnover")
        .add(_numeric(result, "interception"))
        .add(_numeric(result, "fumble_lost"))
        .gt(0)
    )
    first_down = _numeric(result, "first_down").ge(0.5)
    fourth_downs = _numeric(result, "down").eq(4) & ~first_down
    result["terminal_family"] = np.where(
        result["terminated"].eq(0),
        "CONTINUE",
        np.select(
            [touchdown, turnover, fourth_downs],
            ["SCORE", "TURNOVER", "DOWNS"],
            default="OTHER_END",
        ),
    )
    columns = [
        "season",
        "week",
        "game_id",
        "play_id",
        "_drive_id",
        "team",
        "opponent",
        "terminated",
        "terminal_family",
        "down",
        "ydstogo",
        "yardline_100",
        "game_seconds_remaining",
        "score_differential",
        "play_family",
        *_TERMINATION_CONTEXT_COLUMNS,
    ]
    columns = list(dict.fromkeys(columns))
    return result[columns].reset_index(drop=True)


def permute_fourth_down_actions_within_context_season(
    decisions: pd.DataFrame,
    *,
    seed: int = 42,
) -> pd.DataFrame:
    """Break team/time/score mapping while preserving broad season/field/distance action marginals."""
    data = decisions.copy() if "action" in decisions else extract_fourth_down_decisions(decisions)
    rng = np.random.default_rng(seed)
    for _, index in data.groupby(
        ["season", "field_zone", "distance_bucket"], sort=False
    ).groups.items():
        labels = list(index)
        values = data.loc[labels, "action"].to_numpy(copy=True)
        rng.shuffle(values)
        data.loc[labels, "action"] = values
    return data


def permute_termination_targets_within_context_season(
    events: pd.DataFrame,
    *,
    seed: int = 42,
) -> pd.DataFrame:
    """Preserve broad down/field-zone termination rates while breaking finer state mapping."""
    data = events.copy() if "terminated" in events else extract_drive_termination_events(events)
    rng = np.random.default_rng(seed)
    for _, index in data.groupby(["season", "down_bucket", "field_zone"], sort=False).groups.items():
        labels = list(index)
        values = data.loc[labels, "terminated"].to_numpy(copy=True)
        rng.shuffle(values)
        data.loc[labels, "terminated"] = values
    return data


def legacy_fourth_down_probabilities(
    *,
    yardline_100: float,
    ydstogo: float,
    aggression_scale: float = 1.0,
) -> dict[str, float]:
    """Analytic probabilities for the frozen simulator's v0.14 fourth-down heuristic."""
    go_probability = 0.62 if ydstogo <= 1 else 0.34 if ydstogo <= 3 else 0.08
    if yardline_100 <= 10:
        go_probability += 0.12
    elif yardline_100 >= 60:
        go_probability *= 0.45
    go_probability = float(np.clip(go_probability * aggression_scale, 0.01, 0.90))
    residual = 1.0 - go_probability
    return {
        "GO": go_probability,
        "FIELD_GOAL": residual if yardline_100 <= 35 else 0.0,
        "PUNT": residual if yardline_100 > 35 else 0.0,
    }


@dataclass(slots=True)
class FourthDownDecisionModel:
    """Hierarchical point-in-time fourth-down action policy."""

    prior_strength: float = 24.0
    half_life_weeks: float = 8.0
    model_source: str = "hierarchical_fourth_down_decision_v015"
    fitted: bool = False
    train_max_season: int | None = None
    train_max_week: int | None = None
    events: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)

    def fit(self, pbp: pd.DataFrame) -> FourthDownDecisionModel:
        frame = pbp.copy() if "action" in pbp else extract_fourth_down_decisions(pbp)
        return self.fit_frame(frame)

    def fit_frame(self, frame: pd.DataFrame) -> FourthDownDecisionModel:
        required = {
            "season",
            "week",
            "team",
            "action",
            *_DECISION_CONTEXT_COLUMNS,
        }
        missing = required - set(frame)
        if missing:
            raise ValueError(f"FourthDownDecisionModel missing columns: {sorted(missing)}")
        data = frame.loc[frame["action"].isin(_ACTIONS)].copy()
        if len(data) < 20:
            raise ValueError("FourthDownDecisionModel requires at least 20 labeled fourth-down decisions")
        data["recency_weight"] = _recency_weights(data, self.half_life_weeks)
        self.events = data.reset_index(drop=True)
        cutoff = data[["season", "week"]].apply(pd.to_numeric, errors="coerce").dropna()
        if not cutoff.empty:
            last = cutoff.sort_values(["season", "week"], kind="mergesort").iloc[-1]
            self.train_max_season = int(last["season"])
            self.train_max_week = int(last["week"])
        self.fitted = True
        return self

    def _shrink(
        self,
        counts: np.ndarray,
        prior_probability: np.ndarray,
    ) -> np.ndarray:
        strength = max(float(self.prior_strength), 1e-6)
        return _normalize_probabilities(counts + strength * prior_probability)

    def _context_pool(
        self,
        frame: pd.DataFrame,
        state: dict[str, object] | pd.Series,
    ) -> pd.DataFrame:
        state_dict = state.to_dict() if isinstance(state, pd.Series) else dict(state)
        one = _add_context(
            pd.DataFrame(
                [
                    {
                        "down": 4,
                        "ydstogo": float(state_dict.get("ydstogo", 10.0)),
                        "yardline_100": float(state_dict.get("yardline_100", 75.0)),
                        "game_seconds_remaining": float(
                            state_dict.get("game_seconds_remaining", 3600.0)
                        ),
                        "score_differential": float(state_dict.get("score_differential", 0.0)),
                    }
                ]
            )
        ).iloc[0]
        contextual = frame
        for column in _DECISION_CONTEXT_COLUMNS:
            contextual = contextual.loc[contextual[column].astype(str).eq(str(one[column]))]
        return contextual

    def distribution(
        self,
        *,
        team: str,
        state: dict[str, object] | pd.Series,
        use_team: bool = True,
        use_context: bool = True,
    ) -> dict[str, float]:
        if not self.fitted:
            raise RuntimeError("FourthDownDecisionModel must be fitted before prediction")
        global_probability = _normalize_probabilities(_weighted_action_counts(self.events))
        team_pool = self.events.loc[self.events["team"].astype(str).eq(str(team))]
        team_probability = self._shrink(
            _weighted_action_counts(team_pool), global_probability
        ) if use_team and not team_pool.empty else global_probability
        if not use_context:
            probability = team_probability
        else:
            global_context = self._context_pool(self.events, state)
            context_probability = self._shrink(
                _weighted_action_counts(global_context), global_probability
            ) if not global_context.empty else global_probability
            prior_probability = _normalize_probabilities(team_probability + context_probability)
            if use_team:
                team_context = self._context_pool(team_pool, state) if not team_pool.empty else pd.DataFrame()
                probability = self._shrink(
                    _weighted_action_counts(team_context), prior_probability
                ) if not team_context.empty else prior_probability
            else:
                probability = context_probability
        return {action: float(probability[index]) for index, action in enumerate(_ACTIONS)}

    def sample_action(
        self,
        *,
        team: str,
        state: dict[str, object] | pd.Series,
        rng: np.random.Generator,
        use_team: bool = True,
        use_context: bool = True,
    ) -> str:
        distribution = self.distribution(
            team=team,
            state=state,
            use_team=use_team,
            use_context=use_context,
        )
        probability = np.asarray([distribution[action] for action in _ACTIONS], dtype=float)
        return str(_ACTIONS[int(rng.choice(np.arange(len(_ACTIONS)), p=probability))])

    def score_events(self, events: pd.DataFrame) -> pd.DataFrame:
        data = events.copy() if "action" in events else extract_fourth_down_decisions(events)
        rows: list[dict[str, object]] = []
        for _, row in data.iterrows():
            state = row.to_dict()
            model = self.distribution(team=str(row["team"]), state=state)
            team_base = self.distribution(
                team=str(row["team"]), state=state, use_context=False
            )
            context_base = self.distribution(
                team=str(row["team"]), state=state, use_team=False, use_context=True
            )
            heuristic = legacy_fourth_down_probabilities(
                yardline_100=float(row["yardline_100"]),
                ydstogo=float(row["ydstogo"]),
            )
            actual = str(row["action"])
            scored: dict[str, object] = {
                "season": int(row["season"]),
                "week": int(row["week"]),
                "game_id": str(row["game_id"]),
                "team": str(row["team"]),
                "actual_action": actual,
                "actual_probability": model[actual],
                "team_base_probability": team_base[actual],
                "context_base_probability": context_base[actual],
                "heuristic_probability": heuristic[actual],
            }
            for action in _ACTIONS:
                scored[f"p_{action.lower()}"] = model[action]
                scored[f"heuristic_p_{action.lower()}"] = heuristic[action]
            rows.append(scored)
        return pd.DataFrame(rows)


@dataclass(slots=True)
class DriveTerminationHazardModel:
    """Hierarchical probability that the current scrimmage play ends its drive.

    v0.15 initially evaluates this hazard independently. It does not synthesize a terminal
    event family or mutate the simulator trajectory merely because the binary hazard fits well.
    """

    prior_strength: float = 36.0
    half_life_weeks: float = 8.0
    model_source: str = "hierarchical_drive_termination_hazard_v015"
    fitted: bool = False
    train_max_season: int | None = None
    train_max_week: int | None = None
    events: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)

    def fit(self, pbp: pd.DataFrame) -> DriveTerminationHazardModel:
        frame = pbp.copy() if "terminated" in pbp else extract_drive_termination_events(pbp)
        return self.fit_frame(frame)

    def fit_frame(self, frame: pd.DataFrame) -> DriveTerminationHazardModel:
        required = {
            "season",
            "week",
            "team",
            "terminated",
            *_TERMINATION_CONTEXT_COLUMNS,
        }
        missing = required - set(frame)
        if missing:
            raise ValueError(f"DriveTerminationHazardModel missing columns: {sorted(missing)}")
        data = frame.copy()
        data["terminated"] = pd.to_numeric(data["terminated"], errors="coerce")
        data = data.loc[data["terminated"].isin([0, 1])].copy()
        if len(data) < 50:
            raise ValueError("DriveTerminationHazardModel requires at least 50 scrimmage observations")
        data["recency_weight"] = _recency_weights(data, self.half_life_weeks)
        self.events = data.reset_index(drop=True)
        cutoff = data[["season", "week"]].apply(pd.to_numeric, errors="coerce").dropna()
        if not cutoff.empty:
            last = cutoff.sort_values(["season", "week"], kind="mergesort").iloc[-1]
            self.train_max_season = int(last["season"])
            self.train_max_week = int(last["week"])
        self.fitted = True
        return self

    @staticmethod
    def _weighted_rate(frame: pd.DataFrame) -> tuple[float, float]:
        if frame.empty:
            return float("nan"), 0.0
        weights = pd.to_numeric(frame["recency_weight"], errors="coerce").fillna(0.0)
        actual = pd.to_numeric(frame["terminated"], errors="coerce").fillna(0.0)
        evidence = float(weights.sum())
        if evidence <= 0:
            return float("nan"), 0.0
        return float(np.average(actual.to_numpy(dtype=float), weights=weights.to_numpy(dtype=float))), evidence

    def _context_pool(
        self,
        frame: pd.DataFrame,
        state: dict[str, object] | pd.Series,
        *,
        play_family: str,
    ) -> pd.DataFrame:
        state_dict = state.to_dict() if isinstance(state, pd.Series) else dict(state)
        one = _add_context(
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
        for column in _TERMINATION_CONTEXT_COLUMNS:
            contextual = contextual.loc[contextual[column].astype(str).eq(str(one[column]))]
        return contextual

    def probability(
        self,
        *,
        team: str,
        state: dict[str, object] | pd.Series,
        play_family: str,
        use_team: bool = True,
        use_context: bool = True,
    ) -> float:
        if not self.fitted:
            raise RuntimeError("DriveTerminationHazardModel must be fitted before prediction")
        global_rate, _ = self._weighted_rate(self.events)
        if not np.isfinite(global_rate):
            global_rate = 0.16
        strength = max(float(self.prior_strength), 1e-6)
        team_pool = self.events.loc[self.events["team"].astype(str).eq(str(team))]
        team_rate, team_evidence = self._weighted_rate(team_pool)
        if not np.isfinite(team_rate):
            team_rate = global_rate
            team_evidence = 0.0
        team_probability = (
            (team_evidence * team_rate + strength * global_rate) / (team_evidence + strength)
            if use_team
            else global_rate
        )
        if not use_context:
            return float(np.clip(team_probability, 1e-4, 1.0 - 1e-4))

        global_context = self._context_pool(self.events, state, play_family=play_family)
        context_rate, context_evidence = self._weighted_rate(global_context)
        if not np.isfinite(context_rate):
            context_rate = global_rate
            context_evidence = 0.0
        context_probability = (
            context_evidence * context_rate + strength * global_rate
        ) / (context_evidence + strength)
        prior = 0.5 * team_probability + 0.5 * context_probability
        if not use_team:
            return float(np.clip(context_probability, 1e-4, 1.0 - 1e-4))
        team_context = self._context_pool(team_pool, state, play_family=play_family) if not team_pool.empty else pd.DataFrame()
        local_rate, local_evidence = self._weighted_rate(team_context)
        if not np.isfinite(local_rate):
            return float(np.clip(prior, 1e-4, 1.0 - 1e-4))
        probability = (local_evidence * local_rate + strength * prior) / (local_evidence + strength)
        return float(np.clip(probability, 1e-4, 1.0 - 1e-4))

    def score_events(self, events: pd.DataFrame) -> pd.DataFrame:
        data = events.copy() if "terminated" in events else extract_drive_termination_events(events)
        rows: list[dict[str, object]] = []
        for _, row in data.iterrows():
            state = row.to_dict()
            family = str(row["play_family"])
            rows.append(
                {
                    "season": int(row["season"]),
                    "week": int(row["week"]),
                    "game_id": str(row["game_id"]),
                    "team": str(row["team"]),
                    "actual_terminated": int(row["terminated"]),
                    "termination_probability": self.probability(
                        team=str(row["team"]), state=state, play_family=family
                    ),
                    "team_base_probability": self.probability(
                        team=str(row["team"]),
                        state=state,
                        play_family=family,
                        use_context=False,
                    ),
                    "context_base_probability": self.probability(
                        team=str(row["team"]),
                        state=state,
                        play_family=family,
                        use_team=False,
                    ),
                }
            )
        return pd.DataFrame(rows)


def evaluate_fourth_down_scores(scored: pd.DataFrame) -> dict[str, float]:
    if scored.empty:
        raise ValueError("Fourth-down scoring requires at least one held-out decision")
    actual_probability = pd.to_numeric(scored["actual_probability"], errors="coerce").to_numpy(dtype=float)
    heuristic_probability = pd.to_numeric(scored["heuristic_probability"], errors="coerce").to_numpy(dtype=float)
    team_base_probability = pd.to_numeric(scored["team_base_probability"], errors="coerce").to_numpy(dtype=float)
    context_base_probability = pd.to_numeric(scored["context_base_probability"], errors="coerce").to_numpy(dtype=float)
    actual = scored["actual_action"].astype(str).to_numpy()
    model_matrix = scored[[f"p_{action.lower()}" for action in _ACTIONS]].to_numpy(dtype=float)
    heuristic_matrix = scored[[f"heuristic_p_{action.lower()}" for action in _ACTIONS]].to_numpy(dtype=float)
    one_hot = np.column_stack([(actual == action).astype(float) for action in _ACTIONS])
    predicted = np.asarray(_ACTIONS, dtype=object)[np.argmax(model_matrix, axis=1)]
    return {
        "fourth_down_rows": float(len(scored)),
        "fourth_down_log_loss": float(-np.mean(np.log(np.clip(actual_probability, 1e-8, 1.0)))),
        "fourth_down_brier": float(np.mean(np.sum((model_matrix - one_hot) ** 2, axis=1))),
        "fourth_down_accuracy": float(np.mean(predicted == actual)),
        "heuristic_fourth_down_log_loss": float(
            -np.mean(np.log(np.clip(heuristic_probability, 1e-8, 1.0)))
        ),
        "heuristic_fourth_down_brier": float(
            np.mean(np.sum((heuristic_matrix - one_hot) ** 2, axis=1))
        ),
        "team_base_fourth_down_log_loss": float(
            -np.mean(np.log(np.clip(team_base_probability, 1e-8, 1.0)))
        ),
        "context_base_fourth_down_log_loss": float(
            -np.mean(np.log(np.clip(context_base_probability, 1e-8, 1.0)))
        ),
    }


def evaluate_termination_scores(scored: pd.DataFrame) -> dict[str, float]:
    if scored.empty:
        raise ValueError("Termination scoring requires at least one held-out scrimmage event")
    actual = pd.to_numeric(scored["actual_terminated"], errors="coerce").to_numpy(dtype=float)
    model = pd.to_numeric(scored["termination_probability"], errors="coerce").to_numpy(dtype=float)
    team_base = pd.to_numeric(scored["team_base_probability"], errors="coerce").to_numpy(dtype=float)
    context_base = pd.to_numeric(scored["context_base_probability"], errors="coerce").to_numpy(dtype=float)
    return {
        "termination_rows": float(len(scored)),
        "termination_log_loss": _binary_log_loss(actual, model),
        "termination_brier": _binary_brier(actual, model),
        "team_base_termination_log_loss": _binary_log_loss(actual, team_base),
        "context_base_termination_log_loss": _binary_log_loss(actual, context_base),
    }


def observed_fourth_down_team_games(pbp: pd.DataFrame) -> pd.DataFrame:
    decisions = extract_fourth_down_decisions(pbp)
    columns = [
        "game_id",
        "team",
        "fourth_down_decisions",
        "fourth_down_go_attempts",
    ]
    if decisions.empty:
        return pd.DataFrame(columns=columns)
    summary = (
        decisions.assign(go=decisions["action"].eq("GO").astype(float))
        .groupby(["game_id", "team"], dropna=False)
        .agg(fourth_down_decisions=("action", "size"), fourth_down_go_attempts=("go", "sum"))
        .reset_index()
    )
    return summary[columns]


def evaluate_fourth_down_team_draws(
    team_draws: pd.DataFrame,
    observed: pd.DataFrame,
) -> dict[str, float]:
    if team_draws.empty or observed.empty:
        return {}
    required = {
        "game_id",
        "team",
        "fourth_down_decisions",
        "fourth_down_go_attempts",
    }
    missing = required - set(team_draws)
    if missing:
        raise ValueError(f"Fourth-down team draws missing columns: {sorted(missing)}")
    predicted = (
        team_draws.groupby(["game_id", "team"], dropna=False)[
            ["fourth_down_decisions", "fourth_down_go_attempts"]
        ]
        .mean()
        .reset_index()
    )
    merged = predicted.merge(observed, on=["game_id", "team"], suffixes=("_pred", "_actual"))
    if merged.empty:
        return {}
    return {
        "decision_team_rows": float(len(merged)),
        "team_fourth_down_decisions_mae": float(
            np.mean(
                np.abs(
                    merged["fourth_down_decisions_pred"]
                    - merged["fourth_down_decisions_actual"]
                )
            )
        ),
        "team_fourth_down_go_attempts_mae": float(
            np.mean(
                np.abs(
                    merged["fourth_down_go_attempts_pred"]
                    - merged["fourth_down_go_attempts_actual"]
                )
            )
        ),
    }
