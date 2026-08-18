from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

_DRIVE_CONTEXT_COLUMNS = ("score_state", "late_game", "play_family", "red_zone")


def _chronology(frame: pd.DataFrame) -> pd.Series:
    return pd.to_numeric(frame["season"], errors="coerce") * 25 + pd.to_numeric(
        frame["week"], errors="coerce"
    )


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    valid = np.isfinite(values) & np.isfinite(weights) & (weights > 0)
    if not valid.any():
        return float("nan")
    values = values[valid].astype(float)
    weights = weights[valid].astype(float)
    return float(np.average(values, weights=weights))


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
    return data


def _derive_drive_id(frame: pd.DataFrame) -> pd.Series:
    data = frame.sort_values(["season", "week", "game_id", "play_id"], kind="mergesort")
    if "drive" in data:
        drive = pd.to_numeric(data["drive"], errors="coerce")
        if drive.notna().any():
            fallback = (
                data.groupby("game_id", sort=False)["posteam"]
                .transform(lambda values: values.ne(values.shift()).cumsum())
                .astype(float)
            )
            return drive.fillna(fallback).reindex(frame.index)
    fallback = (
        data.groupby("game_id", sort=False)["posteam"]
        .transform(lambda values: values.ne(values.shift()).cumsum())
        .astype(float)
    )
    return fallback.reindex(frame.index)


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
        start_clock = float(
            pd.to_numeric(group["game_seconds_remaining"], errors="coerce").max()
        )
        end_clock = float(
            pd.to_numeric(group["game_seconds_remaining"], errors="coerce").min()
        )
        rows.append(
            {
                "season": int(season),
                "week": int(week),
                "game_id": str(game_id),
                "drive_id": str(drive_id),
                "team": str(team),
                "opponent": str(first["defteam"]),
                "start_yardline_100": float(
                    pd.to_numeric(first["yardline_100"], errors="coerce")
                ),
                "plays": float(len(group)),
                "drive_seconds_proxy": max(0.0, start_clock - end_clock),
            }
        )
    return pd.DataFrame(rows)


def observed_drive_volume(play_frame: pd.DataFrame) -> pd.DataFrame:
    """Observed per-team game volume diagnostics on the same scrimmage-play basis as simulation."""
    drives = extract_drive_frame(play_frame)
    if drives.empty:
        return pd.DataFrame(
            columns=[
                "game_id",
                "team",
                "drives",
                "plays_per_drive",
                "seconds_per_play",
                "mean_start_yardline_100",
            ]
        )
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
    pace = play_frame[["game_id", "posteam", "seconds_between_plays"]].copy()
    pace["seconds_between_plays"] = pd.to_numeric(
        pace["seconds_between_plays"], errors="coerce"
    )
    pace = pace.loc[pace["seconds_between_plays"].between(1.0, 90.0)]
    pace_summary = (
        pace.groupby(["game_id", "posteam"], dropna=False)["seconds_between_plays"]
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
    )[
        [
            "game_id",
            "team",
            "drives",
            "plays_per_drive",
            "seconds_per_play",
            "mean_start_yardline_100",
        ]
    ]


def permute_pace_targets_within_team_season(
    play_frame: pd.DataFrame,
    *,
    seed: int = 42,
) -> pd.DataFrame:
    """Negative control that preserves each team-season pace distribution but breaks state mapping."""
    data = play_frame.copy()
    if "seconds_between_plays" not in data:
        return data
    rng = np.random.default_rng(seed)
    result = data["seconds_between_plays"].copy()
    for _, index in data.groupby(["season", "posteam"], sort=False).groups.items():
        positions = np.asarray(list(index))
        values = data.loc[positions, "seconds_between_plays"].to_numpy(copy=True)
        rng.shuffle(values)
        result.loc[positions] = values
    data["seconds_between_plays"] = result
    return data


@dataclass(slots=True)
class DriveVolumeModel:
    """Hierarchical point-in-time pace and drive-start sampler.

    The model intentionally owns only two mechanisms that the v0.12 outcome sampler mixed
    with play efficiency: clock runoff and starting field position. It can therefore be
    enabled or disabled independently in frozen replay.
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
            "seconds_between_plays",
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
                "seconds_between_plays",
                *self.context_columns,
            ]
        ].copy()
        pace["seconds_between_plays"] = pd.to_numeric(
            pace["seconds_between_plays"], errors="coerce"
        )
        pace = pace.loc[pace["seconds_between_plays"].between(1.0, 90.0)].copy()
        if len(pace) < 50:
            raise ValueError("DriveVolumeModel requires at least 50 valid pace observations")

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
        start_latest = int(_chronology(starts).max())
        start_age = (start_latest - _chronology(starts)).clip(lower=0)
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
        score_value = float(state_dict.get("score_differential", 0.0))
        clock = float(state_dict.get("game_seconds_remaining", 3600.0))
        yardline = float(state_dict.get("yardline_100", 75.0))
        context = {
            "score_state": _score_state(score_value),
            "late_game": int(clock <= 900),
            "play_family": str(play_family),
            "red_zone": int(yardline <= 20),
        }
        contextual = base
        for column in self.context_columns:
            if column not in contextual or column not in context:
                continue
            contextual = contextual.loc[
                contextual[column].astype(str).eq(str(context[column]))
            ]
        evidence = (
            float(
                pd.to_numeric(contextual.get("recency_weight"), errors="coerce")
                .fillna(0.0)
                .sum()
            )
            if not contextual.empty
            else 0.0
        )
        alpha = evidence / (evidence + max(float(self.prior_strength), 1e-6))
        return base, contextual, float(alpha)

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
        base_mean = _weighted_mean(
            pd.to_numeric(base["seconds_between_plays"], errors="coerce").to_numpy(dtype=float),
            pd.to_numeric(base["recency_weight"], errors="coerce").to_numpy(dtype=float),
        )
        if not np.isfinite(base_mean):
            base_mean = 28.0
        if contextual.empty or alpha <= 0:
            return float(np.clip(base_mean, 8.0, 45.0))
        context_mean = _weighted_mean(
            pd.to_numeric(
                contextual["seconds_between_plays"], errors="coerce"
            ).to_numpy(dtype=float),
            pd.to_numeric(contextual["recency_weight"], errors="coerce").to_numpy(dtype=float),
        )
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
            pd.to_numeric(pool["seconds_between_plays"], errors="coerce").to_numpy(dtype=float),
            pd.to_numeric(pool["recency_weight"], errors="coerce").to_numpy(dtype=float),
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
            actual = pd.to_numeric(row.get("seconds_between_plays"), errors="coerce")
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
    actual = actual.loc[valid].to_numpy(dtype=float)
    candidate = candidate.loc[valid].to_numpy(dtype=float)
    baseline = baseline.loc[valid].to_numpy(dtype=float)
    return {
        "pace_rows": float(len(actual)),
        "state_pace_mae": float(np.mean(np.abs(actual - candidate))),
        "team_base_pace_mae": float(np.mean(np.abs(actual - baseline))),
        "state_pace_bias": float(np.mean(candidate - actual)),
        "team_base_pace_bias": float(np.mean(baseline - actual)),
    }


def evaluate_drive_volume_draws(
    team_draws: pd.DataFrame,
    observed: pd.DataFrame,
) -> dict[str, float]:
    required_draws = {
        "game_id",
        "simulation",
        "team",
        "drives",
        "plays_per_drive",
        "seconds_per_play",
        "mean_start_yardline_100",
    }
    required_observed = {
        "game_id",
        "team",
        "drives",
        "plays_per_drive",
        "seconds_per_play",
        "mean_start_yardline_100",
    }
    missing_draws = required_draws - set(team_draws)
    missing_observed = required_observed - set(observed)
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
    return {
        "drive_team_rows": float(len(joined)),
        "team_drives_mae": float(
            np.mean(
                np.abs(
                    pd.to_numeric(joined["drives_actual"], errors="coerce")
                    - pd.to_numeric(joined["drives_pred"], errors="coerce")
                )
            )
        ),
        "team_plays_per_drive_mae": float(
            np.mean(
                np.abs(
                    pd.to_numeric(joined["plays_per_drive_actual"], errors="coerce")
                    - pd.to_numeric(joined["plays_per_drive_pred"], errors="coerce")
                )
            )
        ),
        "team_seconds_per_play_mae": float(
            np.nanmean(
                np.abs(
                    pd.to_numeric(joined["seconds_per_play_actual"], errors="coerce")
                    - pd.to_numeric(joined["seconds_per_play_pred"], errors="coerce")
                )
            )
        ),
        "team_start_yardline_mae": float(
            np.mean(
                np.abs(
                    pd.to_numeric(
                        joined["mean_start_yardline_100_actual"], errors="coerce"
                    )
                    - pd.to_numeric(
                        joined["mean_start_yardline_100_pred"], errors="coerce"
                    )
                )
            )
        ),
    }
