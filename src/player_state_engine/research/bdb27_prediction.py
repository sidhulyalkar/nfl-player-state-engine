"""Point-in-time, research-only Combine-to-rookie prediction experiments.

This module intentionally cannot ingest an unrestricted game-frame table as a
pre-draft feature. No model promotion, cognitive score, or injury-risk claims.
All output is private; unqualified/insufficient cohorts fail closed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

_ALLOWED = frozenset({"DB", "WR", "TE", "OL", "DL"})
_RESERVED = frozenset({"player_id", "nfl_id", "draft_year", "season", "position", "outcome",
                       "numerator", "denominator", "target", "rookie", "game_id", "play_id",
                       "pressure_allowed", "time_to_pressure", "separation_at_pass_forward",
                       "draft_pick", "draft_round", "career_success"})


@dataclass(frozen=True)
class StudyDesign:
    position: str
    drill: str
    outcome: str
    baseline_features: tuple[str, ...]
    train_years: tuple[int, ...] = (2023, 2024)
    test_year: int = 2025
    min_train: int = 25
    min_test: int = 12
    min_opportunities: int = 20
    ridge_alpha: float = 10.0
    seed: int = 2027
    bootstrap_samples: int = 500
    permutations: int = 200
    opportunity_weight_cap: int = 150
    # Only use abs signed turns until source handedness is independently verified.
    candidate_feature: str = "abs_asymmetry_pct"

    def __post_init__(self) -> None:
        if self.position not in _ALLOWED or not self.drill or not self.outcome:
            raise ValueError("position, drill, and endpoint must be prespecified")
        if self.train_years != (2023, 2024) or self.test_year != 2025:
            raise ValueError("only the frozen 2023/24 train -> 2025 holdout is supported")
        if not self.baseline_features or len(set(self.baseline_features)) != len(self.baseline_features):
            raise ValueError("nonempty unique explicit baseline features required")
        if any(not v.isidentifier() or v.lower() in _RESERVED or v.startswith("tracking_") or
               v.startswith("nfl_") or v.startswith("rookie_") for v in self.baseline_features):
            raise ValueError("potentially post-draft or ambiguous baseline feature")
        if self.candidate_feature != "abs_asymmetry_pct":
            raise ValueError("signed asymmetry is not qualified for cross-source modeling")
        if self.min_train < 20 or self.min_test < 10 or self.min_opportunities < 1:
            raise ValueError("minimum independent player/opportunity thresholds too low")
        if self.permutations < 100 or self.bootstrap_samples < 200:
            raise ValueError("insufficient uncertainty or negative-control repetitions")
        if not np.isfinite(self.ridge_alpha) or self.ridge_alpha <= 0:
            raise ValueError("regularization must be positive")
        if self.opportunity_weight_cap < self.min_opportunities:
            raise ValueError("weight cap must not undercut opportunity threshold")

    def digest(self) -> str:
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


def design_from_file(path: Path) -> StudyDesign:
    if not path.is_file() or path.is_symlink():
        raise ValueError("missing or symlinked preregistration")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if raw.get("schema_version") != 1 or raw.get("authority") != "RESEARCH_ONLY_NO_PROMOTION":
        raise ValueError("unsupported research design authority/version")
    keys = set(StudyDesign.__dataclass_fields__)
    if set(raw) - (keys | {"schema_version", "authority", "notes"}):
        raise ValueError("unrecognized research design fields")
    raw.pop("schema_version")
    raw.pop("authority")
    raw.pop("notes", None)
    if "baseline_features" in raw:
        raw["baseline_features"] = tuple(raw["baseline_features"])
    if "train_years" in raw:
        raw["train_years"] = tuple(raw["train_years"])
    return StudyDesign(**raw)


def _unique(table: pd.DataFrame, columns: list[str], label: str) -> None:
    if not set(columns).issubset(table.columns):
        raise ValueError(f"{label} lacks columns {sorted(set(columns)-set(table.columns))}")
    if table[columns].isna().any().any() or table.duplicated(columns).any():
        raise ValueError(f"{label} missing or duplicate identity {columns}")


def _numeric(df: pd.DataFrame, cols: list[str], *, allow_nan: bool = False) -> pd.DataFrame:
    out = df.copy()
    for col in cols:
        out[col] = pd.to_numeric(out[col], errors="coerce")
        x = out[col].to_numpy(dtype=float)
        if np.isinf(x).any() or (not allow_nan and not np.isfinite(x).all()):
            raise ValueError(f"invalid numeric {col}")
    return out


def movement_features(events: pd.DataFrame, profiles: pd.DataFrame, *, drill: str) -> pd.DataFrame:
    """One row per player; trials rather than detected events get equal weight.

    Simple tracking quantities are not interpreted as perception, gaze, or loading.
    A player without qualified signed asymmetry remains unestimated and excluded
    from the three-model paired comparison rather than silently imputed.
    """
    required = {"source_kind", "source_id", "player_id", "independent_trial_id",
                "entry_speed_yd_s", "speed_retention", "turn"}
    if not required.issubset(events.columns):
        raise ValueError("tracking events lack source/attempt/kinematic fields")
    e = events.loc[events.source_kind.eq("combine") & events.source_id.eq(drill)].copy()
    if e.empty:
        return pd.DataFrame(columns=["player_id", "tracking_entry_speed", "tracking_retention",
                                     "abs_asymmetry_pct", "candidate_status", "attempt_count"])
    if not e.turn.isin(["left", "right"]).all():
        raise ValueError("invalid movement direction")
    e = _numeric(e, ["entry_speed_yd_s", "speed_retention"])
    if (e.entry_speed_yd_s <= 0).any() or (e.speed_retention <= 0).any():
        raise ValueError("invalid tracking kinematics")
    _unique(profiles.loc[profiles.source_kind.eq("combine") &
                         profiles.source_id.eq(drill)], ["player_id", "source_id"], "drill profiles")
    # Event-rich fragments may not outweigh a single complete drill attempt.
    by_attempt = e.groupby(["player_id", "independent_trial_id"], sort=True).agg(
        entry_speed=("entry_speed_yd_s", "median"),
        retention=("speed_retention", "median"),
    ).reset_index()
    aggregate = by_attempt.groupby("player_id", as_index=False).agg(
        tracking_entry_speed=("entry_speed", "median"),
        tracking_retention=("retention", "median"),
        attempt_count=("independent_trial_id", "nunique"),
    )
    p = profiles.loc[profiles.source_kind.eq("combine") & profiles.source_id.eq(drill),
                     ["player_id", "status", "asymmetry_pct"]].copy()
    p = p.rename(columns={"status": "candidate_status"})
    p["abs_asymmetry_pct"] = pd.to_numeric(p.asymmetry_pct, errors="coerce").abs()
    p.loc[p.candidate_status.ne("estimated"), "abs_asymmetry_pct"] = np.nan
    return aggregate.merge(p.drop(columns="asymmetry_pct"), how="left", on="player_id", validate="one_to_one")


def build_panel(players: pd.DataFrame, results: pd.DataFrame, events: pd.DataFrame,
                profiles: pd.DataFrame, outcomes: pd.DataFrame, design: StudyDesign) -> tuple[pd.DataFrame, dict]:
    """Build one population, with explicit attrition and only pre-draft predictors.

    `outcomes`: independently qualified rookie REG aggregate with fields
    player_id, position, season, outcome_name, numerator, denominator,
    season_type. `numerator` is event count; denominator opportunities.
    No outcome columns are ever admitted as candidate features.
    """
    _unique(players, ["nfl_id"], "players")
    _unique(results, ["nfl_id"], "Combine results")
    _unique(outcomes, ["player_id", "position", "season", "outcome_name"], "rookie outcomes")
    p_required = {"nfl_id", "combine_position", "draft_year"}
    o_required = {"player_id", "position", "season", "outcome_name", "numerator",
                  "denominator", "season_type"}
    if not p_required.issubset(players) or not o_required.issubset(outcomes):
        raise ValueError("required player/rookie endpoint metadata missing")
    if not set(design.baseline_features).issubset(results.columns):
        raise ValueError("baseline Combine columns absent; source mapping not qualified")
    p = players[["nfl_id", "combine_position", "draft_year"]].copy()
    p["nfl_id"] = p.nfl_id.astype(str)
    p["draft_year"] = pd.to_numeric(p.draft_year, errors="raise").astype(int)
    p = p.loc[p.combine_position.eq(design.position) & p.draft_year.isin((*design.train_years, design.test_year))]
    p = p.rename(columns={"nfl_id": "player_id", "combine_position": "position"})
    b = results[["nfl_id", *design.baseline_features]].copy()
    b["nfl_id"] = b.nfl_id.astype(str)
    b = _numeric(b, list(design.baseline_features), allow_nan=True)
    b = b.rename(columns={"nfl_id": "player_id"})
    f = movement_features(events, profiles, drill=design.drill)
    out = outcomes.loc[outcomes.outcome_name.eq(design.outcome) &
                       outcomes.position.eq(design.position)].copy()
    if not out.season_type.eq("REG").all():
        raise ValueError("rookie outcomes include nonregular season")
    out = _numeric(out, ["numerator", "denominator"])
    if ((out.numerator < 0).any() or (out.numerator > out.denominator).any()
            or (out.denominator % 1 != 0).any() or (out.numerator % 1 != 0).any()):
        raise ValueError("outcomes must be event counts within opportunity counts")
    if out.player_id.isna().any():
        raise ValueError("missing rookie player identity")
    out["player_id"] = out.player_id.astype(str)
    raw_n = len(p)
    panel = p.merge(b, on="player_id", how="left", validate="one_to_one")
    panel = panel.merge(f, on="player_id", how="left", validate="one_to_one")
    out["rookie_rate"] = out.numerator / out.denominator.replace(0, np.nan)
    out = out[["player_id", "season", "rookie_rate", "denominator"]].rename(
        columns={"season": "outcome_season", "denominator": "opportunities"})
    panel = panel.merge(out, on="player_id", how="left", validate="one_to_many")
    # More than one outcome season for a cohort player is not silently collapsed.
    if panel.player_id.duplicated().any():
        raise ValueError("multiple rookie outcomes for one player; ambiguous observation horizon")
    if (panel.outcome_season.notna() & panel.outcome_season.ne(panel.draft_year)).any():
        raise ValueError("non-rookie season outcome leakage")
    panel["candidate_eligible"] = (panel.candidate_status.eq("estimated") &
                                    panel.abs_asymmetry_pct.notna() &
                                    panel.rookie_rate.notna() &
                                    panel.opportunities.ge(design.min_opportunities))
    # Missing baseline values are imputed using only training data, never test.
    counts = {"position_players": raw_n,
              "with_eligible_outcomes": int((panel.rookie_rate.notna() &
                panel.opportunities.ge(design.min_opportunities)).sum()),
              "with_combine_tracking": int(panel.attempt_count.notna().sum()),
              "with_estimated_asymmetry": int(panel.abs_asymmetry_pct.notna().sum()),
              "complete_paired_population": int(panel.candidate_eligible.sum()),
              "paired_by_year": {str(y): int(panel.loc[panel.draft_year.eq(y), "candidate_eligible"].sum())
                                 for y in (*design.train_years, design.test_year)},
              "cohort_coverage": {str(y): {
                  "players": int(panel.draft_year.eq(y).sum()),
                  "rookie_outcomes_with_minimum_opportunity": int((panel.draft_year.eq(y) &
                      panel.opportunities.ge(design.min_opportunities) & panel.rookie_rate.notna()).sum()),
                  "simple_tracking_available": int((panel.draft_year.eq(y) &
                      panel.tracking_retention.notna() & panel.tracking_entry_speed.notna()).sum()),
                  "candidate_eligible": int((panel.draft_year.eq(y) & panel.candidate_eligible).sum()),
              } for y in (*design.train_years, design.test_year)}}
    return panel, counts


def _estimator(alpha: float) -> Pipeline:
    return Pipeline([("impute", SimpleImputer(strategy="median", keep_empty_features=True)),
                     ("scale", StandardScaler()), ("ridge", Ridge(alpha=alpha))])


def _mae(y: np.ndarray, p: np.ndarray, w: np.ndarray | None = None) -> float:
    return float(np.average(np.abs(y-p), weights=w))


def _rmse(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.sqrt(np.mean((y-p) ** 2)))



def evaluate_tracking_baseline(panel: pd.DataFrame, design: StudyDesign) -> dict:
    """Broader-population A/B check independent of bilateral-estimate eligibility.

    Prevents an artificially attractive three-model comparison from hiding that
    only a highly selected subset of prospects have qualified asymmetry scores.
    """
    mask = (panel.rookie_rate.notna() &
            panel.opportunities.ge(design.min_opportunities) &
            panel.tracking_entry_speed.notna() & panel.tracking_retention.notna())
    subset = panel.loc[mask]
    train = subset.loc[subset.draft_year.isin(design.train_years)]
    test = subset.loc[subset.draft_year.eq(design.test_year)]
    audit = {"status": "insufficient_evidence", "train_players": len(train),
             "test_players": len(test), "population": len(subset)}
    if len(train) < design.min_train or len(test) < design.min_test:
        return audit
    conventional = list(design.baseline_features)
    tracking = [*conventional, "tracking_entry_speed", "tracking_retention"]
    for col in tracking:
        if not np.isfinite(train[col].to_numpy(dtype=float)).any():
            raise ValueError(f"no observed training feature {col}")
    y_train = train.rookie_rate.to_numpy(dtype=float)
    y_test = test.rookie_rate.to_numpy(dtype=float)
    w_train = np.minimum(train.opportunities.to_numpy(dtype=float), design.opportunity_weight_cap)
    w_test = np.minimum(test.opportunities.to_numpy(dtype=float), design.opportunity_weight_cap)
    predictions = {}
    for name, features in (("conventional", conventional), ("simple_tracking", tracking)):
        model = _estimator(design.ridge_alpha)
        model.fit(train[features], y_train, ridge__sample_weight=w_train)
        predictions[name] = model.predict(test[features])
    audit.update({"status": "evaluated_research_only",
                  "conventional_weighted_mae": _mae(y_test, predictions["conventional"], w_test),
                  "simple_tracking_weighted_mae": _mae(y_test, predictions["simple_tracking"], w_test),
                  "same_players_in_both_models": True,
                  "conditional_population": "players with observed simple tracking AND qualified rookie rate"})
    return audit


def evaluate_panel(panel: pd.DataFrame, design: StudyDesign) -> tuple[dict, pd.DataFrame]:
    """Frozen cohort holdout. Equal player population for all model comparisons.

    A passing synthetic test does not establish real-world performance.
    Results require prior choice of endpoint, eligibility, and features.
    """
    required = {"player_id", "position", "draft_year", "rookie_rate", "opportunities",
                "candidate_eligible", "tracking_entry_speed", "tracking_retention",
                design.candidate_feature, *design.baseline_features}
    if not required.issubset(panel.columns):
        raise ValueError("missing frozen design columns")
    if panel.player_id.isna().any() or panel.player_id.duplicated().any():
        raise ValueError("player-level holdout requires distinct identified players")
    if not panel.position.eq(design.position).all() or not panel.draft_year.isin(
            (*design.train_years, design.test_year)).all():
        raise ValueError("mismatched position or unexpected cohort")
    selected = panel.loc[panel.candidate_eligible].copy()
    train = selected.loc[selected.draft_year.isin(design.train_years)].copy()
    test = selected.loc[selected.draft_year.eq(design.test_year)].copy()
    report = {"authority": "RESEARCH_ONLY_NO_PROMOTION", "design_sha256": design.digest(),
              "broader_tracking_baseline": evaluate_tracking_baseline(panel, design),
              "train_years": list(design.train_years), "test_year": design.test_year,
              "population_players": len(panel), "eligible_players": len(selected),
              "train_players": len(train), "test_players": len(test),
              "status": "insufficient_evidence"}
    if len(train) < design.min_train or len(test) < design.min_test:
        return report, pd.DataFrame()
    track = ["tracking_entry_speed", "tracking_retention"]
    feature_sets = {"conventional": list(design.baseline_features),
                    "simple_tracking": [*design.baseline_features, *track],
                    "directional": [*design.baseline_features, *track, design.candidate_feature]}
    for name in feature_sets["directional"]:
        if not np.isfinite(train[name].to_numpy(dtype=float)).any():
            raise ValueError(f"no observed training feature for {name}")
    if not np.isfinite(selected[["rookie_rate", "opportunities", *track,
                                 design.candidate_feature]].to_numpy(dtype=float)).all():
        raise ValueError("selected players have invalid tracking/endpoint observations")
    # All baselines use the exact same athletes, weights, and held-out endpoints.
    y_train = train.rookie_rate.to_numpy(dtype=float)
    y_test = test.rookie_rate.to_numpy(dtype=float)
    w_train = np.minimum(train.opportunities.to_numpy(dtype=float), design.opportunity_weight_cap)
    w_test = np.minimum(test.opportunities.to_numpy(dtype=float), design.opportunity_weight_cap)
    preds: dict[str, np.ndarray] = {}
    for name, features in feature_sets.items():
        model = _estimator(design.ridge_alpha)
        model.fit(train[features], y_train, ridge__sample_weight=w_train)
        preds[name] = model.predict(test[features])
    model_metrics = {name: {"mae": _mae(y_test, val),
                            "weighted_mae": _mae(y_test, val, w_test),
                            "rmse": _rmse(y_test, val)} for name, val in preds.items()}
    main = np.abs(y_test-preds["directional"]) - np.abs(y_test-preds["simple_tracking"])
    rng = np.random.default_rng(design.seed)
    ci = []
    for _ in range(design.bootstrap_samples):
        indices = rng.integers(0, len(test), len(test))
        ci.append(float(np.average(main[indices], weights=w_test[indices])))
    lo, hi = np.quantile(ci, [0.025, 0.975])
    observed = float(np.average(main, weights=w_test))
    # Negative control: break ONLY player-asymmetry correspondence within
    # each year; preserve all stopwatch, tracking, outcome and cohort fields.
    placebo_deltas = []
    for _ in range(design.permutations):
        perm_train = train.copy()
        perm_test = test.copy()
        for year in design.train_years:
            mask = perm_train.draft_year.eq(year)
            values = perm_train.loc[mask, design.candidate_feature].to_numpy(dtype=float)
            perm_train.loc[mask, design.candidate_feature] = rng.permutation(values)
        vals = perm_test[design.candidate_feature].to_numpy(dtype=float)
        perm_test[design.candidate_feature] = rng.permutation(vals)
        model = _estimator(design.ridge_alpha)
        model.fit(perm_train[feature_sets["directional"]], y_train,
                  ridge__sample_weight=w_train)
        err = np.abs(y_test-model.predict(perm_test[feature_sets["directional"]]))
        placebo_deltas.append(float(np.average(
            err-np.abs(y_test-preds["simple_tracking"]), weights=w_test)))
    p_value = float((1+sum(v <= observed for v in placebo_deltas)) /
                    (1+len(placebo_deltas)))
    report.update({"status": "evaluated_research_only",
                   "model_metrics": model_metrics,
                   "directional_minus_tracking_weighted_mae": observed,
                   "paired_player_bootstrap_95ci": [float(lo), float(hi)],
                   "negative_control_permutation_p": p_value,
                   "permutations": len(placebo_deltas),
                   "decision": "provisional_gain_requires_independent_replication"
                   if hi < 0 and p_value < 0.05 else "reject_or_inconclusive",
                   "interpretation": "Prediction differences, not demonstrated awareness, loading, injury, or causality"})
    predictions = test[["player_id", "draft_year", "opportunities", "rookie_rate"]].copy()
    for name, val in preds.items():
        predictions[f"pred_{name}"] = val
    return report, predictions


def write_private_report(output_dir: Path, report: dict, predictions: pd.DataFrame) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "evaluation_RESEARCH_ONLY.json").write_text(json.dumps(report, indent=2)+"\n")
    if not predictions.empty:
        predictions.to_csv(output_dir / "heldout_player_predictions_PRIVATE.csv", index=False)
