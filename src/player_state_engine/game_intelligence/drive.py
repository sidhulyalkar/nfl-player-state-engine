from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

_DRIVE_CONTEXT_COLUMNS = ("score_state", "late_game", "play_family", "red_zone")
_PACE_TARGET = "seconds_to_next_play"


def _chronology(frame: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(frame["season"], errors="coerce") * 25 + pd.to_numeric(
        frame["week"], errors="coerce"
    )


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    valid = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not valid.any():
        return float("nan")
    return float(np.average(values[valid].astype(float), weights=weights[valid].astype(float)))


def _weighted_choice(
    values: np.ndarray,
    weights: np.ndarray,
    rng: np.random.Generator,
    *,
    default: float,
) -> float:
    valid = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not valid.any():
        return float(default)
    values = values[valid].astype(float)
    weights = weights[valid].astype(float)
    probability = weights / weights.sum()
    return float(values[int(rng.choice(np.arange(len(values)), p=probability))])


def _score_state(value: float) -> str:
    if value <= -8:
        return "trailing"
    if value >= 8:
        return "leading"
    return "neutral"


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


def _aligned_pace_target(frame: pd.DataFrame) -> pd.Series:
    """Return game-clock runoff after the current play, aligned within drive/offense."""
    if _PACE_TARGET in frame:
        return pd.to_numeric(frame[_PACE_TARGET], errors="coerce")
    required = {"game_id", "posteam", "game_seconds_remaining", "play_id"}
    missing = required - set(frame)
    if missing:
        raise ValueError(f"Aligned pace target missing columns: {sorted(missing)}")
    data = frame.copy()
    data["_drive_id"] = _derive_drive_id(data)
    data = data.sort_values(
        ["season", "week", "game_id", "_drive_id", "play_id"], kind="mergesort"
    )
    grouped = data.groupby(
        ["game_id", "_drive_id", "posteam"], sort=False
    )["game_seconds_remaining"]
    current = pd.to_numeric(data["game_seconds_remaining"], errors="coerce")
    target = (current - pd.to_numeric(grouped.shift(-1), errors="coerce")).clip(0, 90)
    return target.reindex(frame.index)


def _with_drive_context(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    score = pd.to_numeric(data.get("score_differential"), errors="coerce").fillna(0.0)
    clock = pd.to_numeric(data.get("game_seconds_remaining"), errors="coerce").fillna(3600.0)
    yardline = pd.to_numeric(data.get("yardline_100"), errors="coerce").fillna(75.0)
    data["score_state"] = np.select(
        [score <= -8, score >= 8],
        ["trailing", "leading"],
        default="neutral",
    )
    data["late_game"] = clock.le(900).astype(int)
    data["red_zone"] = yardline.le(20).astype(int)
    if "play_family" not in data:
        data["play_family"] = "UNKNOWN"
    data["play_family"] = data["play_family"].astype(str)
    data[_PACE_TARGET] = _aligned_pace_target(data)
    return data


def extract_drive_frame(play_frame: pd.DataFrame) -> pd.DataFrame:
    """Extract scrimmage-play drive summaries without using future games as features."""
    required = {
        "season",
        "week",
        "game_id",
        "play_id",
        "posteam",
        "defteam",
        "yardline_100",
        "game_seconds_remaining",
    }
    missing = required - set(play_frame)
    if missing:
        raise ValueError(f"Drive extraction missing columns: {sorted(missing)}")
    data = play_frame.copy()
    data["_drive_id"] = _derive_drive_id(data)
    data = data.sort_values(
        ["season", "week", "game_id", "_drive_id", "play_id"], kind="mergesort"
    )
    rows: list[dict[str, object]] = []
    for (season, week, game_id, drive_id, team), group in data.groupby(
        ["season", "week", "game_id", "_drive_id", "posteam"],
        sort=False,
        dropna=False,
    ):
        if group.empty:
            continue
        first = group.iloc[0]
        clocks = pd.to_numeric(group["game_seconds_remaining"], errors="coerce")
        start_clock = float(clocks.max())
        end_clock = float(clocks.min())
        start_yardline = pd.to_numeric(first["yardline_100"], errors="coerce")
        rows.append(
            {
                "season": int(season),
                "week": int(week),
                "game_id": str(game_id),
                "drive_id": str(drive_id),
                "team": str(team),
                "opponent": str(first["defteam"]),
                "start_yardline_100": float(start_yardline),
                "plays": float(len(group)),
                "drive_seconds_proxy": max(0.0, start_clock - end_clock),
            }
        )
    return pd.DataFrame(rows)


def observed_drive_volume(play_frame: pd.DataFrame) -> pd.DataFrame:
    """Observed per-team game volume on the same scrimmage-play basis as simulation."""
    data = _with_drive_context(play_frame)
    drives = extract_drive_frame(data)
    columns = [
        "game_id",
        "team",
        "drives",
        "plays_per_drive",
        "seconds_per_play",
        "mean_start_yardline_100",
    ]
    if drives.empty:
        return pd.DataFrame(columns=columns)
    drive_summary = (
        drives.groupby(["game_id", "team"], dropna=False)
        .agg(
            drives=("drive_id", "nunique"),
            plays=("plays", "sum"),
            mean_start_yardline_100=("start_yardline_100", "mean"),
        )
        .reset_index()
    )
    drive_summary["plays_per_drive"] = (
        drive_summary["plays"] / drive_summary["drives"].clip(lower=1)
    )
    pace = data[["game_id", "posteam", _PACE_TARGET]].copy()
    pace[_PACE_TARGET] = pd.to_numeric(pace[_PACE_TARGET], errors="coerce")
    pace = pace.loc[pace[_PACE_TARGET].between(1.0, 90.0)]
    pace_summary = (
        pace.groupby(["game_id", "posteam"], dropna=False)[_PACE_TARGET]
        .mean()
        .rename("seconds_per_play")
        .reset_index()
        .rename(columns={"posteam": "team"})
    )
    return drive_summary.merge(
        pace_summary,
        on=["game_id", "team"],
        how="left",
        validate="one_to_one",
    )[columns]


def permute_pace_targets_within_team_season(
    play_frame: pd.DataFrame,
    *,
    seed: int = 42,
) -> pd.DataFrame:
    """Preserve each team-season pace distribution while breaking its state mapping."""
    data = _with_drive_context(play_frame)
    rng = np.random.default_rng(seed)
    result = data[_PACE_TARGET].copy()
    for _, index in data.groupby(["season", "posteam"], sort=False).groups.items():
        labels = list(index)
        values = data.loc[labels, _PACE_TARGET].to_numpy(copy=True)
        rng.shuffle(values)
        result.loc[labels] = values
    data[_PACE_TARGET] = result
    return data


@dataclass(slots=True)
class DriveVolumeModel:
    """Hierarchical point-in-time pace and drive-start sampler.

    The model owns only mechanisms that v0.12 mixed into broader outcome/state logic:
    forward-aligned clock runoff and starting field position. Sparse pace context shrinks
    toward the offense's recent base distribution.
    """

    prior_strength: float = 24.0
    half_life_weeks: float = 6.0
    context_columns: tuple[str, ...] = _DRIVE_CONTEXT_COLUMNS
    model_source: str = "hierarchical_drive_volume_v013"
    fitted: bool = False
    train_max_season: int | None = None
    train_max_week: int | None = None
    pace_events: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)
    drive_starts: pd.DataFrame = field(default_factory=pd.DataFrame, repr=False)

    def fit(self, play_frame: pd.DataFrame) -> DriveVolumeModel:
        required = {
            "season",
            "week",
            "game_id",
            "play_id",
            "posteam",
            "defteam",
            "play_family",
            "game_seconds_remaining",
            "score_differential",
            "yardline_100",
        }
        missing = required - set(play_frame)
        if missing:
            raise ValueError(f"DriveVolumeModel missing columns: {sorted(missing)}")
        data = _with_drive_context(play_frame)
        pace = data[
            [
                "season",
                "week",
                "posteam",
                "defteam",
                _PACE_TARGET,
                *self.context_columns,
            ]
        ].copy()
        pace[_PACE_TARGET] = pd.to_numeric(pace[_PACE_TARGET], errors="coerce")
        pace = pace.loc[pace[_PACE_TARGET].between(1.0, 90.0)].copy()
        if len(pace) < 50:
            raise ValueError("DriveVolumeModel requires at least 50 aligned pace observations")

        latest = int(_chronology(pace).max())
        age = (latest - _chronology(pace)).clip(lower=0)
        pace["recency_weight"] = np.power(
            0.5,
            age / max(float(self.half_life_weeks), 0.25),
        )
        pace["team"] = pace["posteam"].astype(str)
        pace["opponent"] = pace["defteam"].astype(str)
        self.pace_events = pace.reset_index(drop=True)

        starts = extract_drive_frame(data)
        if starts.empty:
            raise ValueError("DriveVolumeModel requires observed drive starts")
        start_age = (int(_chronology(starts).max()) - _chronology(starts)).clip(lower=0)
        starts["recency_weight"] = np.power(
            0.5,
            start_age / max(float(self.half_life_weeks), 0.25),
        )
        starts["start_yardline_100"] = pd.to_numeric(
            starts["start_yardline_100"], errors="coerce"
        ).clip(1.0, 99.0)
        self.drive_starts = starts.dropna(subset=["start_yardline_100"]).reset_index(
            drop=True
        )

        cutoff = data[["season", "week"]].copy()
        cutoff["season"] = pd.to_numeric(cutoff["season"], errors="coerce")
        cutoff["week"] = pd.to_numeric(cutoff["week"], errors="coerce")
        cutoff = cutoff.dropna().sort_values(["season", "week"], kind="mergesort")
        if not cutoff.empty:
            last = cutoff.iloc[-1]
            self.train_max_season = int(last["season"])
            self.train_max_week = int(last["week"])
        self.fitted = True
        return self

    def _pace_pool(
        self,
        *,
        team: str,
        state: dict[str, float | str] | pd.Series,
        play_family: str,
        use_context: bool,
    ) -> tuple[pd.DataFrame, pd.DataFrame, float]:
        if not self.fitted:
            raise RuntimeError("DriveVolumeModel must be fitted before prediction")
        base = self.pace_events.loc[self.pace_events["team"].astype(str).eq(str(team))]
        if base.empty:
            base = self.pace_events
        if not use_context:
            return base, pd.DataFrame(), 0.0

        state_dict = state.to_dict() if isinstance(state, pd.Series) else dict(state)
        context = {
            "score_state": _score_state(float(state_dict.get("score_differential", 0.0))),
            "late_game": int(float(state_dict.get("game_seconds_remaining", 3600.0)) <= 900),
            "play_family": str(play_family),
            "red_zone": int(float(state_dict.get("yardline_100", 75.0)) <= 20),
        }
        contextual = base
        for column in self.context_columns:
            if column in contextual and column in context:
                contextual = contextual.loc[
                    contextual[column].astype(str).eq(str(context[column]))
                ]
        evidence = (
            float(
                pd.to_numeric(contextual["recency_weight"], errors="coerce")
                .fillna(0.0)
                .sum()
            )
            if not contextual.empty
            else 0.0
        )
        alpha = evidence / (evidence + max(float(self.prior_strength), 1e-6))
        return base, contextual, float(alpha)

    @staticmethod
    def _pace_arrays(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
        values = pd.to_numeric(frame[_PACE_TARGET], errors="coerce").to_numpy(dtype=float)
        weights = pd.to_numeric(frame["recency_weight"], errors="coerce").to_numpy(dtype=float)
        return values, weights

    def expected_seconds(
        self,
        *,
        team: str,
        state: dict[str, float | str] | pd.Series,
        play_family: str,
        use_context: bool = True,
    ) -> float:
        base, contextual, alpha = self._pace_pool(
            team=team,
            state=state,
            play_family=play_family,
            use_context=use_context,
        )
        base_mean = _weighted_mean(*self._pace_arrays(base))
        if not np.isfinite(base_mean):
            base_mean = 28.0
        if contextual.empty or alpha <= 0:
            return float(np.clip(base_mean, 8.0, 45.0))
        context_mean = _weighted_mean(*self._pace_arrays(contextual))
        if not np.isfinite(context_mean):
            return float(np.clip(base_mean, 8.0, 45.0))
        return float(np.clip((1.0 - alpha) * base_mean + alpha * context_mean, 8.0, 45.0))

    def sample_seconds(
        self,
        *,
        team: str,
        state: dict[str, float | str] | pd.Series,
        play_family: str,
        rng: np.random.Generator,
        use_context: bool = True,
        fallback_seconds: float = 28.0,
    ) -> float:
        base, contextual, alpha = self._pace_pool(
            team=team,
            state=state,
            play_family=play_family,
            use_context=use_context,
        )
        pool = contextual if not contextual.empty and rng.random() < alpha else base
        value = _weighted_choice(
            *self._pace_arrays(pool),
            rng,
            default=float(fallback_seconds),
        )
        return float(np.clip(value, 8.0, 45.0))

    def sample_start_yardline(
        self,
        *,
        team: str,
        opponent: str,
        rng: np.random.Generator,
        fallback_yardline_100: float = 75.0,
    ) -> float:
        if not self.fitted:
            raise RuntimeError("DriveVolumeModel must be fitted before prediction")
        offense = self.drive_starts.loc[self.drive_starts["team"].astype(str).eq(str(team))]
        defense = self.drive_starts.loc[
            self.drive_starts["opponent"].astype(str).eq(str(opponent))
        ]
        draw = float(rng.random())
        if draw < 0.60 and not offense.empty:
            pool = offense
        elif draw < 0.90 and not defense.empty:
            pool = defense
        else:
            pool = self.drive_starts
        value = _weighted_choice(
            pd.to_numeric(pool["start_yardline_100"], errors="coerce").to_numpy(dtype=float),
            pd.to_numeric(pool["recency_weight"], errors="coerce").to_numpy(dtype=float),
            rng,
            default=float(fallback_yardline_100),
        )
        return float(np.clip(value, 5.0, 95.0))

    def score_pace_events(
        self,
        play_frame: pd.DataFrame,
        *,
        use_context: bool = True,
    ) -> pd.DataFrame:
        data = _with_drive_context(play_frame)
        rows: list[dict[str, object]] = []
        for _, row in data.iterrows():
            actual = pd.to_numeric(row.get(_PACE_TARGET), errors="coerce")
            if pd.isna(actual) or not 1.0 <= float(actual) <= 90.0:
                continue
            state = {
                "score_differential": float(row.get("score_differential", 0.0)),
                "game_seconds_remaining": float(row.get("game_seconds_remaining", 3600.0)),
                "yardline_100": float(row.get("yardline_100", 75.0)),
            }
            candidate = self.expected_seconds(
                team=str(row["posteam"]),
                state=state,
                play_family=str(row["play_family"]),
                use_context=use_context,
            )
            baseline = self.expected_seconds(
                team=str(row["posteam"]),
                state=state,
                play_family=str(row["play_family"]),
                use_context=False,
            )
            rows.append(
                {
                    "season": int(row["season"]),
                    "week": int(row["week"]),
                    "game_id": str(row["game_id"]),
                    "team": str(row["posteam"]),
                    "actual_seconds": float(actual),
                    "predicted_seconds": float(candidate),
                    "baseline_seconds": float(baseline),
                }
            )
        return pd.DataFrame(rows)


def evaluate_pace_event_scores(scores: pd.DataFrame) -> dict[str, float]:
    if scores.empty:
        raise ValueError("No drive-volume pace events to evaluate")
    actual = pd.to_numeric(scores["actual_seconds"], errors="coerce")
    candidate = pd.to_numeric(scores["predicted_seconds"], errors="coerce")
    baseline = pd.to_numeric(scores["baseline_seconds"], errors="coerce")
    valid = actual.notna() & candidate.notna() & baseline.notna()
    if not valid.any():
        raise ValueError("No valid pace score rows")
    actual_values = actual.loc[valid].to_numpy(dtype=float)
    candidate_values = candidate.loc[valid].to_numpy(dtype=float)
    baseline_values = baseline.loc[valid].to_numpy(dtype=float)
    return {
        "pace_rows": float(len(actual_values)),
        "state_pace_mae": float(np.mean(np.abs(actual_values - candidate_values))),
        "team_base_pace_mae": float(np.mean(np.abs(actual_values - baseline_values))),
        "state_pace_bias": float(np.mean(candidate_values - actual_values)),
        "team_base_pace_bias": float(np.mean(baseline_values - actual_values)),
    }


def evaluate_drive_volume_draws(
    team_draws: pd.DataFrame,
    observed: pd.DataFrame,
) -> dict[str, float]:
    required = {
        "game_id",
        "team",
        "drives",
        "plays_per_drive",
        "seconds_per_play",
        "mean_start_yardline_100",
    }
    missing_draws = (required | {"simulation"}) - set(team_draws)
    missing_observed = required - set(observed)
    if missing_draws:
        raise ValueError(f"Drive-volume draws missing: {sorted(missing_draws)}")
    if missing_observed:
        raise ValueError(f"Observed drive volume missing: {sorted(missing_observed)}")
    medians = (
        team_draws.groupby(["game_id", "team"], dropna=False)
        .agg(
            drives=("drives", "median"),
            plays_per_drive=("plays_per_drive", "median"),
            seconds_per_play=("seconds_per_play", "median"),
            mean_start_yardline_100=("mean_start_yardline_100", "median"),
        )
        .reset_index()
    )
    joined = observed.merge(
        medians,
        on=["game_id", "team"],
        how="inner",
        suffixes=("_actual", "_pred"),
    )
    if joined.empty:
        raise ValueError("No overlapping drive-volume rows")

    def mae(column: str, *, nan_safe: bool = False) -> float:
        actual = pd.to_numeric(joined[f"{column}_actual"], errors="coerce")
        predicted = pd.to_numeric(joined[f"{column}_pred"], errors="coerce")
        values = np.abs(actual - predicted).to_numpy(dtype=float)
        return float(np.nanmean(values) if nan_safe else np.mean(values))

    return {
        "drive_team_rows": float(len(joined)),
        "team_drives_mae": mae("drives"),
        "team_plays_per_drive_mae": mae("plays_per_drive"),
        "team_seconds_per_play_mae": mae("seconds_per_play", nan_safe=True),
        "team_start_yardline_mae": mae("mean_start_yardline_100"),
    }
