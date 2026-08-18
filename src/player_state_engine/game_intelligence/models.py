from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


_DEFAULT_PLAY_CALL_FEATURES = (
    "down",
    "ydstogo",
    "yardline_100",
    "qtr",
    "game_seconds_remaining",
    "score_differential",
    "neutral_score_state",
    "late_game",
    "red_zone",
    "goal_to_go_state",
    "distance_bucket",
    "field_zone",
    "pregame_pass_rate",
    "neutral_pass_rate",
    "early_down_pass_rate",
    "red_zone_pass_rate",
    "third_down_pass_rate",
    "epa_per_play",
    "defense_epa_allowed",
    "explosive_rate",
    "defense_explosive_allowed",
    "home_spread",
    "game_total",
)


@dataclass(slots=True)
class PlayCallModel:
    feature_columns: tuple[str, ...] = _DEFAULT_PLAY_CALL_FEATURES
    model_source: str = "logistic_play_call_v010"
    fitted: bool = False
    train_max_season: int | None = None
    train_max_week: int | None = None
    pipeline: Pipeline = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.pipeline = Pipeline(
            [
                ("imputer", SimpleImputer(strategy="median", add_indicator=True)),
                ("scale", StandardScaler()),
                ("model", LogisticRegression(max_iter=1000, C=0.7)),
            ]
        )

    def _features(self, frame: pd.DataFrame) -> pd.DataFrame:
        data = pd.DataFrame(index=frame.index)
        for column in self.feature_columns:
            if column in frame:
                data[column] = pd.to_numeric(frame[column], errors="coerce")
            else:
                data[column] = np.nan
        return data

    def fit(self, frame: pd.DataFrame) -> PlayCallModel:
        if "is_dropback" not in frame:
            raise ValueError("PlayCallModel requires is_dropback labels")
        target = pd.to_numeric(frame["is_dropback"], errors="coerce")
        valid = target.isin([0, 1])
        if valid.sum() < 50 or target.loc[valid].nunique() < 2:
            raise ValueError("PlayCallModel requires at least 50 labeled run/dropback plays")
        self.pipeline.fit(self._features(frame.loc[valid]), target.loc[valid].astype(int))
        if "season" in frame:
            self.train_max_season = int(
                pd.to_numeric(frame.loc[valid, "season"], errors="coerce").max()
            )
        if "week" in frame:
            self.train_max_week = int(
                pd.to_numeric(frame.loc[valid, "week"], errors="coerce").max()
            )
        self.fitted = True
        return self

    def predict_pass_probability(self, frame: pd.DataFrame) -> np.ndarray:
        if not self.fitted:
            raise RuntimeError("PlayCallModel must be fitted before prediction")
        return self.pipeline.predict_proba(self._features(frame))[:, 1]


class EmpiricalPlayOutcomeModel:
    """Hierarchical empirical outcome sampler conditioned on play family and game state."""

    def __init__(self, *, min_stratum_plays: int = 30) -> None:
        self.min_stratum_plays = int(min_stratum_plays)
        self.strata: dict[tuple[object, ...], pd.DataFrame] = {}
        self.family: dict[str, pd.DataFrame] = {}
        self.fitted = False
        self.model_source = "hierarchical_empirical_play_outcomes_v010"

    def fit(self, frame: pd.DataFrame) -> EmpiricalPlayOutcomeModel:
        required = {
            "play_family",
            "down",
            "distance_bucket",
            "field_zone",
            "yards_gained",
            "touchdown",
            "turnover",
        }
        missing = required - set(frame)
        if missing:
            raise ValueError(f"Outcome model missing: {sorted(missing)}")
        columns = [
            column
            for column in (
                "yards_gained",
                "touchdown",
                "first_down",
                "turnover",
                "interception",
                "fumble_lost",
                "complete_pass",
                "seconds_between_plays",
            )
            if column in frame
        ]
        for family, family_group in frame.groupby("play_family", sort=False):
            self.family[str(family)] = family_group.loc[:, columns].reset_index(drop=True)
            for key, group in family_group.groupby(
                ["down", "distance_bucket", "field_zone"], sort=False
            ):
                if len(group) >= self.min_stratum_plays:
                    self.strata[(str(family), *tuple(key))] = group.loc[:, columns].reset_index(
                        drop=True
                    )
        self.fitted = True
        return self

    def sample(
        self,
        *,
        play_family: str,
        down: int,
        distance_bucket: int,
        field_zone: int,
        rng: np.random.Generator,
    ) -> dict[str, float]:
        if not self.fitted:
            raise RuntimeError("EmpiricalPlayOutcomeModel must be fitted before sampling")
        pool = self.strata.get((str(play_family), int(down), int(distance_bucket), int(field_zone)))
        if pool is None or pool.empty:
            pool = self.family.get(str(play_family))
        if pool is None or pool.empty:
            raise ValueError(f"No outcome samples available for {play_family}")
        row = pool.iloc[int(rng.integers(0, len(pool)))]
        sampled: dict[str, float] = {}
        for column in pool.columns:
            value = pd.to_numeric(row[column], errors="coerce")
            sampled[column] = 0.0 if pd.isna(value) else float(value)
        return sampled
