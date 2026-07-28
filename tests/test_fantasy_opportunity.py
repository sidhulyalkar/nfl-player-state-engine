import pandas as pd

from player_state_engine.fantasy.opportunity import rank_high_chance_opportunities


def test_vacated_opportunity_and_role_capture_drive_rank() -> None:
    frame = pd.DataFrame(
        {
            "player_id": ["a", "b"],
            "opportunity_active_probability": [0.95, 0.95],
            "opportunity_snap_share_q50": [0.75, 0.60],
            "opportunity_route_participation_q50": [0.80, 0.50],
            "opportunity_target_share_q50": [0.18, 0.12],
            "opportunity_carry_share_q50": [0.02, 0.02],
            "vacated_target_share": [0.20, 0.01],
            "teammate_absence_probability": [0.60, 0.05],
            "scheme_fit_score": [0.70, 0.50],
        }
    )
    ranked = rank_high_chance_opportunities(frame)
    assert ranked.iloc[0]["player_id"] == "a"
    assert ranked["breakout_probability"].between(0, 1).all()
    assert ranked.iloc[0]["opportunity_reasons"] != "monitor role evidence"
