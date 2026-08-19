from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from player_state_engine.state_graph.types import RegimeState

BOUNDARY_COLUMNS: tuple[str, ...] = (
    "qb_starter_change",
    "play_caller_change",
    "head_coach_change",
    "major_ol_change",
    "team_change",
    "rookie_transition",
    "major_role_injury",
    "scheme_change",
    "season_boundary",
)


@dataclass(slots=True)
class RegimeDetector:
    """Explicit non-stationarity state with gradual prior-to-regime handoff."""

    maturity_half_life_weeks: float = 3.5
    high_maturity_weeks: int = 7

    def detect(
        self,
        events: pd.DataFrame,
        *,
        team: str,
        season: int,
        week: int,
    ) -> RegimeState:
        if events.empty:
            return RegimeState(
                team=str(team),
                season=int(season),
                week=int(week),
                regime_id=f"{team}:{season}:W1",
                weeks_since_boundary=max(int(week) - 1, 0),
                evidence_weight=0.0,
                maturity="LOW",
                active_boundaries=("season_boundary",),
                prior_weight=1.0,
                current_regime_weight=0.0,
            )

        data = events.copy()
        data["season"] = pd.to_numeric(data["season"], errors="coerce")
        data["week"] = pd.to_numeric(data["week"], errors="coerce")
        data = data.loc[data["team"].astype(str).eq(str(team))]
        cutoff = data["season"].lt(int(season)) | (
            data["season"].eq(int(season)) & data["week"].lt(int(week))
        )
        data = data.loc[cutoff].sort_values(["season", "week"], kind="mergesort")

        boundary_rows: list[tuple[int, int, tuple[str, ...]]] = []
        for _, row in data.iterrows():
            boundaries = tuple(
                column
                for column in BOUNDARY_COLUMNS
                if column in row and bool(row[column]) and not pd.isna(row[column])
            )
            if boundaries:
                boundary_rows.append((int(row["season"]), int(row["week"]), boundaries))

        if not boundary_rows or boundary_rows[-1][0] < int(season):
            latest_season = int(season)
            latest_week = 1
            boundaries = ("season_boundary",)
        else:
            latest_season, latest_week, boundaries = boundary_rows[-1]

        if latest_season == int(season):
            weeks_since = max(int(week) - latest_week, 0)
        else:
            weeks_since = max(int(week) - 1, 0)

        half_life = max(float(self.maturity_half_life_weeks), 0.5)
        current_weight = float(1.0 - np.power(0.5, weeks_since / half_life))
        prior_weight = float(1.0 - current_weight)
        if weeks_since <= 2:
            maturity = "LOW"
        elif weeks_since < int(self.high_maturity_weeks):
            maturity = "MEDIUM"
        else:
            maturity = "HIGH"

        regime_id = f"{team}:{latest_season}:W{latest_week}:{'+'.join(boundaries)}"
        return RegimeState(
            team=str(team),
            season=int(season),
            week=int(week),
            regime_id=regime_id,
            weeks_since_boundary=weeks_since,
            evidence_weight=current_weight,
            maturity=maturity,
            active_boundaries=boundaries,
            prior_weight=prior_weight,
            current_regime_weight=current_weight,
        )

    @staticmethod
    def blend_prior(current_value: float, prior_value: float, state: RegimeState) -> float:
        return float(
            state.current_regime_weight * float(current_value)
            + state.prior_weight * float(prior_value)
        )
