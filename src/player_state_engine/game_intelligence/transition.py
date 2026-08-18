from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

_TRANSITION_TYPES = (
    "TOUCHDOWN",
    "TURNOVER",
    "PUNT",
    "FIELD_GOAL_GOOD",
    "FIELD_GOAL_MISSED",
    "DOWNS",
    "HALFTIME",
    "OTHER",
)


def _numeric(frame: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in frame:
        return pd.Series(default, index=frame.index, dtype=float)
    return pd.to_numeric(frame[column], errors="coerce").fillna(default)


def _normalize_game_id(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    if "game_id" not in out and "nflverse_game_id" in out:
        out["game_id"] = out["nflverse_game_id"]
    if "game_id" not in out:
        raise ValueError("Transition evidence requires game_id or nflverse_game_id")
    return out


def _chronology(frame: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(frame["season"], errors="coerce") * 25 + pd.to_numeric(
        frame["week"], errors="coerce"
    )


def _scrimmage_mask(frame: pd.DataFrame) -> pd.Series:
    pass_signal = (
        _numeric(frame, "pass_attempt")
        + _numeric(frame, "qb_dropback")
        + _numeric(frame, "sack")
        + _numeric(frame, "qb_scramble")
    )
    rush_signal = _numeric(frame, "rush_attempt")
    return (pass_signal + rush_signal).gt(0) & frame.get(
        "posteam", pd.Series(index=frame.index, dtype=object)
    ).notna()


def _string(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame:
        return pd.Series("", index=frame.index, dtype="string")
    return frame[column].astype("string").fillna("").str.lower()


def _field_goal_mask(frame: pd.DataFrame) -> pd.Series:
    return _numeric(frame, "field_goal_attempt").gt(0) | _string(frame, "play_type").eq(
        "field_goal"
    )


def _punt_mask(frame: pd.DataFrame) -> pd.Series:
    return _numeric(frame, "punt_attempt").gt(0) | _string(frame, "play_type").eq("punt")


def _field_goal_made(frame: pd.DataFrame) -> pd.Series:
    result = _string(frame, "field_goal_result")
    made_text = result.isin({"good", "made", "successful"})
    no_good_text = result.isin({"missed", "blocked", "no good", "failed"})
    score = _numeric(frame, "field_goal_result_numeric", np.nan)
    inferred = score.eq(1.0)
    return made_text | (~no_good_text & inferred)


def _distance_bucket(distance: float) -> str:
    value = float(distance)
    if value <= 35:
        return "short"
    if value <= 45:
        return "medium"
    if value <= 55:
        return "long"
    return "very_long"


def _source_zone(yardline_100: float) -> str:
    value = float(yardline_100)
    if value <= 20:
        return "red_zone"
    if value <= 40:
        return "plus_40"
    if value <= 60:
        return "midfield"
    if value <= 80:
        return "own_40"
    return "backed_up"


def _weighted_mean(values: pd.Series, weights: pd.Series) -> float:
    x = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    w = pd.to_numeric(weights, errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(x) & np.isfinite(w) & (w > 0)
    if not valid.any():
        return float("nan")
    return float(np.average(x[valid], weights=w[valid]))


def _weighted_choice(
    values: pd.Series,
    weights: pd.Series,
    rng: np.random.Generator,
    *,
    default: float,
) -> float:
    x = pd.to_numeric(values, errors="coerce").to_numpy(dtype=float)
    w = pd.to_numeric(weights, errors="coerce").to_numpy(dtype=float)
    valid = np.isfinite(x) & np.isfinite(w) & (w > 0)
    if not valid.any():
        return float(default)
    x = x[valid]
    w = w[valid]
    probability = w / w.sum()
    return float(x[int(rng.choice(np.arange(len(x)), p=probability))])


def extract_field_goal_attempts(pbp: pd.DataFrame) -> pd.DataFrame:
    """Normalize field-goal attempts for point-in-time calibration."""
    data = _normalize_game_id(pbp)
    required = {"season", "week", "play_id"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"Field-goal extraction missing columns: {sorted(missing)}")
    attempts = data.loc[_field_goal_mask(data)].copy()
    columns = [
        "season",
        "week",
        "game_id",
        "play_id",
        "team",
        "kick_distance",
        "distance_bucket",
        "made",
    ]
    if attempts.empty:
        return pd.DataFrame(columns=columns)
    attempts["team"] = attempts.get("posteam", "").astype(str)
    kick_distance = pd.to_numeric(attempts.get("kick_distance"), errors="coerce")
    yardline = pd.to_numeric(attempts.get("yardline_100"), errors="coerce")
    attempts["kick_distance"] = kick_distance.fillna(yardline + 17.0).clip(15.0, 75.0)
    attempts["distance_bucket"] = attempts["kick_distance"].map(_distance_bucket)
    attempts["made"] = _field_goal_made(attempts).astype(int)
    return attempts.loc[:, columns].reset_index(drop=True)


def _classify_transition(window: pd.DataFrame, last_scrimmage: pd.Series) -> str:
    turnover = bool(
        float(last_scrimmage.get("interception", 0.0) or 0.0) >= 0.5
        or float(last_scrimmage.get("fumble_lost", 0.0) or 0.0) >= 0.5
    )
    touchdown = bool(float(last_scrimmage.get("touchdown", 0.0) or 0.0) >= 0.5)
    if touchdown:
        return "TOUCHDOWN"
    if turnover:
        return "TURNOVER"
    field_goals = window.loc[_field_goal_mask(window)]
    if not field_goals.empty:
        return "FIELD_GOAL_GOOD" if bool(_field_goal_made(field_goals).iloc[-1]) else "FIELD_GOAL_MISSED"
    if _punt_mask(window).any():
        return "PUNT"
    qtr = float(last_scrimmage.get("qtr", 0.0) or 0.0)
    next_qtr = pd.to_numeric(window.get("qtr"), errors="coerce").dropna()
    if qtr <= 2 and not next_qtr.empty and float(next_qtr.iloc[-1]) >= 3:
        return "HALFTIME"
    down = float(last_scrimmage.get("down", 0.0) or 0.0)
    first_down = float(last_scrimmage.get("first_down", 0.0) or 0.0)
    if down >= 4 and first_down < 0.5:
        return "DOWNS"
    return "OTHER"


def _terminal_row(window: pd.DataFrame, transition_type: str) -> pd.Series:
    if transition_type.startswith("FIELD_GOAL"):
        rows = window.loc[_field_goal_mask(window)]
        if not rows.empty:
            return rows.iloc[-1]
    if transition_type == "PUNT":
        rows = window.loc[_punt_mask(window)]
        if not rows.empty:
            return rows.iloc[-1]
    return window.iloc[0]


def build_possession_transition_frame(pbp: pd.DataFrame) -> pd.DataFrame:
    """Build drive-ending transition labels from raw PBP, including special-teams rows.

    A transition starts at the terminal event of one offensive possession and targets the
    first scrimmage play of the next offensive possession. This prevents punt/field-goal
    timing and field position from being inferred from the preceding scrimmage play.
    """
    data = _normalize_game_id(pbp)
    required = {"season", "week", "play_id", "posteam", "yardline_100"}
    missing = required - set(data)
    if missing:
        raise ValueError(f"Transition extraction missing columns: {sorted(missing)}")
    data = data.sort_values(["season", "week", "game_id", "play_id"], kind="mergesort").copy()
    data["_raw_order"] = np.arange(len(data), dtype=int)
    rows: list[dict[str, object]] = []

    for game_id, game in data.groupby("game_id", sort=False):
        scrimmage = game.loc[_scrimmage_mask(game)].copy()
        scrimmage = scrimmage.loc[scrimmage["posteam"].notna()]
        if len(scrimmage) < 2:
            continue
        scrimmage["_possession_id"] = scrimmage["posteam"].astype(str).ne(
            scrimmage["posteam"].astype(str).shift()
        ).cumsum()
        groups = [group for _, group in scrimmage.groupby("_possession_id", sort=False)]
        for current, following in zip(groups[:-1], groups[1:], strict=True):
            previous_team = str(current["posteam"].iloc[-1])
            next_team = str(following["posteam"].iloc[0])
            if previous_team == next_team:
                continue
            last = current.iloc[-1]
            first_next = following.iloc[0]
            start_order = int(last["_raw_order"])
            end_order = int(first_next["_raw_order"])
            window = game.loc[
                game["_raw_order"].between(start_order, end_order, inclusive="both")
            ].copy()
            transition_type = _classify_transition(window, last)
            terminal = _terminal_row(window, transition_type)
            terminal_clock = pd.to_numeric(
                pd.Series([terminal.get("game_seconds_remaining", np.nan)]), errors="coerce"
            ).iloc[0]
            next_clock = pd.to_numeric(
                pd.Series([first_next.get("game_seconds_remaining", np.nan)]), errors="coerce"
            ).iloc[0]
            seconds = float("nan")
            if np.isfinite(terminal_clock) and np.isfinite(next_clock):
                seconds = float(np.clip(terminal_clock - next_clock, 0.0, 90.0))
            source_yardline = pd.to_numeric(
                pd.Series([terminal.get("yardline_100", last.get("yardline_100", np.nan))]),
                errors="coerce",
            ).iloc[0]
            next_start = pd.to_numeric(
                pd.Series([first_next.get("yardline_100", np.nan)]), errors="coerce"
            ).iloc[0]
            rows.append(
                {
                    "season": int(last["season"]),
                    "week": int(last["week"]),
                    "game_id": str(game_id),
                    "terminal_play_id": terminal.get("play_id"),
                    "next_play_id": first_next.get("play_id"),
                    "previous_team": previous_team,
                    "next_offense": next_team,
                    "transition_type": transition_type,
                    "source_yardline_100": float(source_yardline),
                    "source_zone": _source_zone(float(source_yardline)),
                    "next_start_yardline_100": float(next_start),
                    "transition_seconds": seconds,
                }
            )
    columns = [
        "season",
        "week",
        "game_id",
        "terminal_play_id",
        "next_play_id",
        "previous_team",
        "next_offense",
        "transition_type",
        "source_yardline_100",
        "source_zone",
        "next_start_yardline_100",
        "transition_seconds",
    ]
    return pd.DataFrame(rows, columns=columns)


def permute_transition_targets_within_type_season(
    transitions: pd.DataFrame,
    *,
    seed: int = 42,
) -> pd.DataFrame:
    """Preserve transition-type/season marginals while destroying contextual mapping."""
    required = {
        "season",
        "transition_type",
        "next_start_yardline_100",
        "transition_seconds",
    }
    missing = required - set(transitions)
    if missing:
        raise ValueError(f"Transition permutation missing columns: {sorted(missing)}")
    result = transitions.copy()
    rng = np.random.default_rng(seed)
    for _, index in result.groupby(["season", "transition_type"], sort=False).groups.items():
        labels = list(index)
        for column in ("next_start_yardline_100", "transition_seconds"):
            values = result.loc[labels, column].to_numpy(copy=True)
            rng.shuffle(values)
            result.loc[labels, column] = values
    return result


def permute_field_goal_results_within_distance_season(
    attempts: pd.DataFrame,
    *,
    seed: int = 42,
) -> pd.DataFrame:
    """Preserve season/distance make rates while breaking team-level calibration signal."""
    required = {"season", "distance_bucket", "made"}
    missing = required - set(attempts)
    if missing:
        raise ValueError(f"Field-goal permutation missing columns: {sorted(missing)}")
    result = attempts.copy()
    rng = np.random.default_rng(seed)
    for _, index in result.groupby(["season", "distance_bucket"], sort=False).groups.items():
        labels = list(index)
        values = result.loc[labels, "made"].to_numpy(copy=True)
        rng.shuffle(values)
        result.loc[labels, "made"] = values
    return result


@dataclass(slots=True)
class PossessionTransitionModel:
    """Hierarchical point-in-time model for drive-ending transitions and field goals."""

    prior_strength: float = 18.0
    half_life_weeks: float = 8.0
    field_goal_prior_strength: float = 30.0
    model_source: str = "hierarchical_possession_transition_v014"
    fitted: bool = False
    train_max_season: int | None = None
    train_max_week: int | None = None
    transitions: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)
    field_goals: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)

    def fit(self, pbp: pd.DataFrame) -> PossessionTransitionModel:
        return self.fit_frames(
            build_possession_transition_frame(pbp),
            extract_field_goal_attempts(pbp),
        )

    def fit_frames(
        self,
        transitions: pd.DataFrame,
        field_goals: pd.DataFrame,
    ) -> PossessionTransitionModel:
        required = {
            "season",
            "week",
            "transition_type",
            "next_offense",
            "source_zone",
            "next_start_yardline_100",
            "transition_seconds",
        }
        missing = required - set(transitions)
        if missing:
            raise ValueError(f"PossessionTransitionModel missing columns: {sorted(missing)}")
        usable = transitions.copy()
        usable = usable.loc[usable["transition_type"].isin(_TRANSITION_TYPES)].copy()
        usable["next_start_yardline_100"] = pd.to_numeric(
            usable["next_start_yardline_100"], errors="coerce"
        ).clip(1.0, 99.0)
        usable["transition_seconds"] = pd.to_numeric(
            usable["transition_seconds"], errors="coerce"
        ).clip(0.0, 90.0)
        usable = usable.dropna(subset=["next_start_yardline_100"])
        if len(usable) < 30:
            raise ValueError("PossessionTransitionModel requires at least 30 transition rows")
        latest = int(_chronology(usable).max())
        age = (latest - _chronology(usable)).clip(lower=0)
        usable["recency_weight"] = np.power(
            0.5,
            age / max(float(self.half_life_weeks), 0.25),
        )
        self.transitions = usable.reset_index(drop=True)

        goals = field_goals.copy()
        if not goals.empty:
            required_goals = {"season", "week", "team", "distance_bucket", "made"}
            missing_goals = required_goals - set(goals)
            if missing_goals:
                raise ValueError(f"Field-goal frame missing columns: {sorted(missing_goals)}")
            latest_goal = int(_chronology(goals).max())
            goal_age = (latest_goal - _chronology(goals)).clip(lower=0)
            goals["recency_weight"] = np.power(
                0.5,
                goal_age / max(float(self.half_life_weeks), 0.25),
            )
            goals["made"] = pd.to_numeric(goals["made"], errors="coerce").clip(0, 1)
            goals = goals.dropna(subset=["made"]).reset_index(drop=True)
        self.field_goals = goals

        cutoff = usable[["season", "week"]].copy()
        cutoff = cutoff.sort_values(["season", "week"], kind="mergesort")
        last = cutoff.iloc[-1]
        self.train_max_season = int(last["season"])
        self.train_max_week = int(last["week"])
        self.fitted = True
        return self

    def _transition_pools(
        self,
        *,
        transition_type: str,
        next_offense: str,
        source_yardline_100: float,
    ) -> tuple[pd.DataFrame, pd.DataFrame, float]:
        if not self.fitted:
            raise RuntimeError("PossessionTransitionModel must be fitted before prediction")
        kind = str(transition_type)
        base = self.transitions.loc[self.transitions["transition_type"].astype(str).eq(kind)]
        if base.empty:
            base = self.transitions
        zone = _source_zone(source_yardline_100)
        contextual = base.loc[
            base["next_offense"].astype(str).eq(str(next_offense))
            & base["source_zone"].astype(str).eq(zone)
        ]
        if contextual.empty:
            contextual = base.loc[base["source_zone"].astype(str).eq(zone)]
        evidence = float(
            pd.to_numeric(contextual.get("recency_weight"), errors="coerce").fillna(0.0).sum()
        ) if not contextual.empty else 0.0
        alpha = evidence / (evidence + max(float(self.prior_strength), 1e-6))
        return base, contextual, float(alpha)

    def expected_next_start_yardline(
        self,
        *,
        transition_type: str,
        next_offense: str,
        source_yardline_100: float,
    ) -> float:
        base, contextual, alpha = self._transition_pools(
            transition_type=transition_type,
            next_offense=next_offense,
            source_yardline_100=source_yardline_100,
        )
        base_mean = _weighted_mean(base["next_start_yardline_100"], base["recency_weight"])
        if not np.isfinite(base_mean):
            base_mean = 75.0
        if contextual.empty or alpha <= 0:
            return float(np.clip(base_mean, 1.0, 99.0))
        context_mean = _weighted_mean(
            contextual["next_start_yardline_100"], contextual["recency_weight"]
        )
        if not np.isfinite(context_mean):
            context_mean = base_mean
        return float(np.clip((1.0 - alpha) * base_mean + alpha * context_mean, 1.0, 99.0))

    def sample_next_start_yardline(
        self,
        *,
        transition_type: str,
        next_offense: str,
        source_yardline_100: float,
        rng: np.random.Generator,
        fallback_yardline_100: float = 75.0,
    ) -> float:
        base, contextual, alpha = self._transition_pools(
            transition_type=transition_type,
            next_offense=next_offense,
            source_yardline_100=source_yardline_100,
        )
        pool = contextual if not contextual.empty and rng.random() < alpha else base
        value = _weighted_choice(
            pool["next_start_yardline_100"],
            pool["recency_weight"],
            rng,
            default=float(fallback_yardline_100),
        )
        return float(np.clip(value, 1.0, 99.0))

    def expected_transition_seconds(
        self,
        *,
        transition_type: str,
        next_offense: str,
        source_yardline_100: float,
    ) -> float:
        base, contextual, alpha = self._transition_pools(
            transition_type=transition_type,
            next_offense=next_offense,
            source_yardline_100=source_yardline_100,
        )
        base_seconds = base.dropna(subset=["transition_seconds"])
        if base_seconds.empty:
            return 8.0
        base_mean = _weighted_mean(base_seconds["transition_seconds"], base_seconds["recency_weight"])
        contextual = contextual.dropna(subset=["transition_seconds"])
        if contextual.empty or alpha <= 0:
            return float(np.clip(base_mean, 0.0, 45.0))
        context_mean = _weighted_mean(
            contextual["transition_seconds"], contextual["recency_weight"]
        )
        if not np.isfinite(context_mean):
            context_mean = base_mean
        return float(np.clip((1.0 - alpha) * base_mean + alpha * context_mean, 0.0, 45.0))

    def sample_transition_seconds(
        self,
        *,
        transition_type: str,
        next_offense: str,
        source_yardline_100: float,
        rng: np.random.Generator,
        fallback_seconds: float = 8.0,
    ) -> float:
        base, contextual, alpha = self._transition_pools(
            transition_type=transition_type,
            next_offense=next_offense,
            source_yardline_100=source_yardline_100,
        )
        pool = contextual if not contextual.empty and rng.random() < alpha else base
        pool = pool.dropna(subset=["transition_seconds"])
        if pool.empty:
            return float(fallback_seconds)
        value = _weighted_choice(
            pool["transition_seconds"],
            pool["recency_weight"],
            rng,
            default=float(fallback_seconds),
        )
        return float(np.clip(value, 0.0, 45.0))

    def field_goal_make_probability(
        self,
        *,
        team: str,
        yardline_100: float,
        kick_distance: float | None = None,
    ) -> float:
        if not self.fitted:
            raise RuntimeError("PossessionTransitionModel must be fitted before prediction")
        if self.field_goals.empty:
            distance = float(kick_distance or (yardline_100 + 17.0))
            return float(np.clip(0.96 - max(distance - 30.0, 0.0) * 0.012, 0.25, 0.98))
        distance = float(kick_distance or (yardline_100 + 17.0))
        bucket = _distance_bucket(distance)
        league = self.field_goals
        bucket_rows = league.loc[league["distance_bucket"].astype(str).eq(bucket)]
        if bucket_rows.empty:
            bucket_rows = league
        base = _weighted_mean(bucket_rows["made"], bucket_rows["recency_weight"])
        team_rows = bucket_rows.loc[bucket_rows["team"].astype(str).eq(str(team))]
        evidence = float(
            pd.to_numeric(team_rows.get("recency_weight"), errors="coerce").fillna(0.0).sum()
        ) if not team_rows.empty else 0.0
        if team_rows.empty:
            return float(np.clip(base, 0.02, 0.995))
        team_rate = _weighted_mean(team_rows["made"], team_rows["recency_weight"])
        alpha = evidence / (evidence + max(float(self.field_goal_prior_strength), 1e-6))
        return float(np.clip((1.0 - alpha) * base + alpha * team_rate, 0.02, 0.995))

    def score_transition_events(self, pbp: pd.DataFrame) -> pd.DataFrame:
        events = build_possession_transition_frame(pbp)
        if events.empty:
            return events
        rows: list[dict[str, object]] = []
        for _, row in events.iterrows():
            base_pool = self.transitions.loc[
                self.transitions["transition_type"].astype(str).eq(str(row["transition_type"]))
            ]
            if base_pool.empty:
                base_pool = self.transitions
            base_start = _weighted_mean(
                base_pool["next_start_yardline_100"], base_pool["recency_weight"]
            )
            base_seconds_pool = base_pool.dropna(subset=["transition_seconds"])
            base_seconds = _weighted_mean(
                base_seconds_pool["transition_seconds"], base_seconds_pool["recency_weight"]
            ) if not base_seconds_pool.empty else 8.0
            rows.append(
                {
                    **row.to_dict(),
                    "predicted_start_yardline_100": self.expected_next_start_yardline(
                        transition_type=str(row["transition_type"]),
                        next_offense=str(row["next_offense"]),
                        source_yardline_100=float(row["source_yardline_100"]),
                    ),
                    "type_base_start_yardline_100": float(base_start),
                    "predicted_transition_seconds": self.expected_transition_seconds(
                        transition_type=str(row["transition_type"]),
                        next_offense=str(row["next_offense"]),
                        source_yardline_100=float(row["source_yardline_100"]),
                    ),
                    "type_base_transition_seconds": float(base_seconds),
                }
            )
        return pd.DataFrame(rows)

    def score_field_goals(self, pbp: pd.DataFrame) -> pd.DataFrame:
        attempts = extract_field_goal_attempts(pbp)
        if attempts.empty:
            return attempts
        league_rate = _weighted_mean(self.field_goals["made"], self.field_goals["recency_weight"])
        rows: list[dict[str, object]] = []
        for _, row in attempts.iterrows():
            bucket = str(row["distance_bucket"])
            bucket_rows = self.field_goals.loc[
                self.field_goals["distance_bucket"].astype(str).eq(bucket)
            ]
            base_probability = (
                _weighted_mean(bucket_rows["made"], bucket_rows["recency_weight"])
                if not bucket_rows.empty
                else league_rate
            )
            rows.append(
                {
                    **row.to_dict(),
                    "predicted_make_probability": self.field_goal_make_probability(
                        team=str(row["team"]),
                        yardline_100=max(float(row["kick_distance"]) - 17.0, 1.0),
                        kick_distance=float(row["kick_distance"]),
                    ),
                    "distance_base_probability": float(base_probability),
                }
            )
        return pd.DataFrame(rows)


def evaluate_transition_event_scores(scores: pd.DataFrame) -> dict[str, float]:
    required = {
        "next_start_yardline_100",
        "predicted_start_yardline_100",
        "type_base_start_yardline_100",
        "transition_seconds",
        "predicted_transition_seconds",
        "type_base_transition_seconds",
    }
    missing = required - set(scores)
    if missing:
        raise ValueError(f"Transition score frame missing columns: {sorted(missing)}")
    if scores.empty:
        raise ValueError("No transition events to score")
    actual_start = pd.to_numeric(scores["next_start_yardline_100"], errors="coerce")
    pred_start = pd.to_numeric(scores["predicted_start_yardline_100"], errors="coerce")
    base_start = pd.to_numeric(scores["type_base_start_yardline_100"], errors="coerce")
    start_valid = actual_start.notna() & pred_start.notna() & base_start.notna()
    actual_seconds = pd.to_numeric(scores["transition_seconds"], errors="coerce")
    pred_seconds = pd.to_numeric(scores["predicted_transition_seconds"], errors="coerce")
    base_seconds = pd.to_numeric(scores["type_base_transition_seconds"], errors="coerce")
    seconds_valid = actual_seconds.notna() & pred_seconds.notna() & base_seconds.notna()
    if not start_valid.any():
        raise ValueError("No valid transition start-field rows")
    return {
        "transition_rows": float(len(scores)),
        "transition_start_rows": float(start_valid.sum()),
        "transition_start_yardline_mae": float(
            np.abs(actual_start[start_valid] - pred_start[start_valid]).mean()
        ),
        "type_base_start_yardline_mae": float(
            np.abs(actual_start[start_valid] - base_start[start_valid]).mean()
        ),
        "transition_seconds_rows": float(seconds_valid.sum()),
        "transition_seconds_mae": float(
            np.abs(actual_seconds[seconds_valid] - pred_seconds[seconds_valid]).mean()
        ) if seconds_valid.any() else float("nan"),
        "type_base_transition_seconds_mae": float(
            np.abs(actual_seconds[seconds_valid] - base_seconds[seconds_valid]).mean()
        ) if seconds_valid.any() else float("nan"),
    }


def evaluate_field_goal_scores(scores: pd.DataFrame) -> dict[str, float]:
    required = {"made", "predicted_make_probability", "distance_base_probability"}
    missing = required - set(scores)
    if missing:
        raise ValueError(f"Field-goal score frame missing columns: {sorted(missing)}")
    if scores.empty:
        raise ValueError("No field-goal attempts to score")
    y = pd.to_numeric(scores["made"], errors="coerce").to_numpy(dtype=float)
    p = np.clip(
        pd.to_numeric(scores["predicted_make_probability"], errors="coerce").to_numpy(dtype=float),
        1e-6,
        1 - 1e-6,
    )
    base = np.clip(
        pd.to_numeric(scores["distance_base_probability"], errors="coerce").to_numpy(dtype=float),
        1e-6,
        1 - 1e-6,
    )
    valid = np.isfinite(y) & np.isfinite(p) & np.isfinite(base)
    if not valid.any():
        raise ValueError("No valid field-goal score rows")
    y = y[valid]
    p = p[valid]
    base = base[valid]
    return {
        "field_goal_rows": float(len(y)),
        "field_goal_log_loss": float(-(y * np.log(p) + (1.0 - y) * np.log(1.0 - p)).mean()),
        "field_goal_brier": float(np.mean((p - y) ** 2)),
        "field_goal_base_log_loss": float(
            -(y * np.log(base) + (1.0 - y) * np.log(1.0 - base)).mean()
        ),
        "field_goal_base_brier": float(np.mean((base - y) ** 2)),
    }


def observed_transition_team_games(pbp: pd.DataFrame) -> pd.DataFrame:
    """Observed team-game possession-ending counts for full-simulation diagnostics."""
    transitions = build_possession_transition_frame(pbp)
    columns = [
        "game_id",
        "team",
        "punts",
        "field_goal_attempts",
        "field_goals_made",
        "turnovers",
        "turnovers_on_downs",
    ]
    if transitions.empty:
        return pd.DataFrame(columns=columns)
    rows = transitions.copy()
    rows["team"] = rows["previous_team"].astype(str)
    rows["punts"] = rows["transition_type"].eq("PUNT").astype(float)
    rows["field_goal_attempts"] = rows["transition_type"].isin(
        ["FIELD_GOAL_GOOD", "FIELD_GOAL_MISSED"]
    ).astype(float)
    rows["field_goals_made"] = rows["transition_type"].eq("FIELD_GOAL_GOOD").astype(float)
    rows["turnovers"] = rows["transition_type"].eq("TURNOVER").astype(float)
    rows["turnovers_on_downs"] = rows["transition_type"].eq("DOWNS").astype(float)
    return (
        rows.groupby(["game_id", "team"], dropna=False)[columns[2:]]
        .sum()
        .reset_index()
    )


def evaluate_transition_team_draws(
    team_draws: pd.DataFrame,
    observed: pd.DataFrame,
) -> dict[str, float]:
    required = {
        "game_id",
        "simulation",
        "team",
        "punts",
        "field_goal_attempts",
        "field_goals_made",
        "turnovers",
        "turnovers_on_downs",
    }
    missing = required - set(team_draws)
    if missing:
        raise ValueError(f"Transition team draws missing columns: {sorted(missing)}")
    missing_observed = (required - {"simulation"}) - set(observed)
    if missing_observed:
        raise ValueError(f"Observed transition teams missing columns: {sorted(missing_observed)}")
    metrics = [
        "punts",
        "field_goal_attempts",
        "field_goals_made",
        "turnovers",
        "turnovers_on_downs",
    ]
    medians = (
        team_draws.groupby(["game_id", "team"], dropna=False)[metrics]
        .median()
        .reset_index()
    )
    joined = observed.merge(medians, on=["game_id", "team"], suffixes=("_actual", "_pred"))
    if joined.empty:
        raise ValueError("No overlapping transition team rows")
    result = {"transition_team_rows": float(len(joined))}
    for metric in metrics:
        result[f"team_{metric}_mae"] = float(
            np.abs(joined[f"{metric}_actual"] - joined[f"{metric}_pred"]).mean()
        )
    return result
