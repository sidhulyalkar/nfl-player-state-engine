import pandas as pd

from player_state_engine.features.prospect import build_prospect_features


def test_prospect_features_include_combine_draft_and_college() -> None:
    combine = pd.DataFrame(
        {
            "player_name": ["Alpha Back", "Beta Back", "Gamma Back"],
            "season": [2025, 2025, 2025],
            "pos": ["RB", "RB", "RB"],
            "forty": [4.40, 4.55, 4.62],
            "weight": [215, 220, 205],
            "vertical": [38, 32, 30],
            "broad_jump": [125, 115, 110],
            "cone": [7.0, 7.2, 7.3],
            "shuttle": [4.2, 4.3, 4.4],
            "bench": [20, 18, 14],
            "height": [71, 72, 70],
        }
    )
    draft = pd.DataFrame(
        {
            "pfr_player_name": ["Alpha Back", "Beta Back", "Gamma Back"],
            "season": [2025, 2025, 2025],
            "position": ["RB", "RB", "RB"],
            "round": [1, 3, 7],
            "pick": [20, 80, 230],
            "team": ["AAA", "BBB", "CCC"],
        }
    )
    college = pd.DataFrame(
        {
            "player_name": ["Alpha Back", "Beta Back", "Gamma Back"],
            "draft_year": [2025, 2025, 2025],
            "position": ["RB", "RB", "RB"],
            "dominator_rating": [0.35, 0.25, 0.15],
            "college_rush_share": [0.65, 0.45, 0.30],
            "breakout_age": [19, 21, 22],
            "early_declare": [1, 0, 0],
        }
    )
    result = build_prospect_features(combine, draft, college)
    assert "prospect_prior_score" in result
    assert "college_production_position_z" in result
    assert (
        result.sort_values("prospect_prior_score", ascending=False).iloc[0]["player_name"]
        == "Alpha Back"
    )
