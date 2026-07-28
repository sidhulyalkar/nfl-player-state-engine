from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(slots=True)
class MatchupScenario:
    player_id: str
    scenario_name: str
    hypothesis: str
    evidence_strength: float
    model_action: str = "ablation_only"


def hypothesize_matchup_scenarios(row: pd.Series) -> list[MatchupScenario]:
    """Translate public-context features into testable, non-causal hypotheses.

    These scenarios are report annotations. They do not alter projections until
    a registered ablation demonstrates out-of-sample value.
    """

    player_id = str(row.get("player_id", "unknown"))
    strength = float(row.get("persona_evidence_strength", 0.0) or 0.0)
    scenarios: list[MatchupScenario] = []
    if float(row.get("persona_role_expectation", 0.0) or 0.0) >= 0.35:
        scenarios.append(
            MatchupScenario(
                player_id,
                "role_expansion_language",
                "Recent public statements contain explicit role or opportunity language; test whether snap/route priors should widen rather than automatically increase.",
                strength,
            )
        )
    if float(row.get("persona_matchup_specificity", 0.0) or 0.0) >= 0.35:
        scenarios.append(
            MatchupScenario(
                player_id,
                "matchup_specific_language",
                "The player discussed coverage, opponent, or game-plan specifics; test interaction only with objective matchup features.",
                strength,
            )
        )
    if float(row.get("persona_recovery_focus", 0.0) or 0.0) >= 0.35:
        scenarios.append(
            MatchupScenario(
                player_id,
                "recovery_language",
                "Recovery language is elevated; compare against official availability evidence and widen workload uncertainty if independently corroborated.",
                strength,
            )
        )
    return scenarios
