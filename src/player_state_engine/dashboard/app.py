from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from player_state_engine.data.io import read_table

st.set_page_config(page_title="NFL Player State Engine", layout="wide")
st.title("NFL Player State Engine")
st.caption("Leakage-safe weekly distributions, not crystal-ball point guesses.")

path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("artifacts/predictions/predictions.parquet")
if not path.exists():
    st.warning(f"Prediction file not found: {path}")
    st.stop()

predictions = read_table(path)
targets = sorted(
    {column.rsplit("_q", 1)[0] for column in predictions.columns if column.endswith("_q50")}
)
if not targets:
    st.error("No *_q50 columns were found.")
    st.stop()

target = st.selectbox("Projection target", targets)
positions = sorted(predictions.get("position", pd.Series(dtype=str)).dropna().unique())
selected_positions = st.multiselect("Positions", positions, default=positions)
team_values = sorted(predictions.get("recent_team", pd.Series(dtype=str)).dropna().unique())
selected_teams = st.multiselect("Teams", team_values, default=team_values)

filtered = predictions.copy()
if selected_positions and "position" in filtered:
    filtered = filtered.loc[filtered["position"].isin(selected_positions)]
if selected_teams and "recent_team" in filtered:
    filtered = filtered.loc[filtered["recent_team"].isin(selected_teams)]

q10, q50, q90 = f"{target}_q10", f"{target}_q50", f"{target}_q90"
show = [
    c
    for c in ("player_name", "position", "recent_team", "opponent_team", q10, q50, q90)
    if c in filtered
]
filtered = filtered.sort_values(q50, ascending=False)
st.dataframe(filtered[show], use_container_width=True, hide_index=True)

chart_frame = filtered.head(30).set_index("player_name")[[q10, q50, q90]]
st.bar_chart(chart_frame)

st.markdown(
    "**Interpretation:** q10 and q90 define an approximate 80% model interval. "
    "They measure model uncertainty under the available inputs, not every source of real-world uncertainty."
)
