from __future__ import annotations

ALLOWED_SIGNAL_NAMES = {
    "training_focus",
    "recovery_focus",
    "competitive_language",
    "team_orientation",
    "leadership_language",
    "matchup_specificity",
    "role_expectation",
    "media_visibility",
    "commercial_content",
}

PROHIBITED_INFERENCES = {
    "race",
    "ethnicity",
    "religion",
    "sexual_orientation",
    "political_affiliation",
    "medical_diagnosis",
    "mental_health_diagnosis",
    "substance_use",
    "financial_status",
    "family_private_life",
}

COLLECTION_RULES = (
    "Collect only public, athlete-authored posts or explicitly licensed/official media.",
    "Never bypass login walls, CAPTCHAs, robots.txt, rate limits, or access controls.",
    "Do not collect private messages, follower identity lists, precise location, or deleted content.",
    "Use official platform APIs where available and credentials are authorized.",
    "Store timestamps, URLs, extraction version, and evidence for every derived feature.",
    "Do not infer sensitive personal attributes or clinical/psychological diagnoses.",
)
