"""
Forging Line — Piece Travel Time Dashboard

Displays processed pieces with predicted bath time and per-stage
timing detail.

Usage:
    uv run streamlit run app/streamlit_app.py
"""

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from vaultech_analysis.inference import Predictor

GOLD_FILE = PROJECT_ROOT / "data" / "gold" / "pieces.parquet"

# Column definitions — process order
PARTIAL_COLS = [
    "partial_furnace_to_2nd_strike_s",
    "partial_2nd_to_3rd_strike_s",
    "partial_3rd_to_4th_strike_s",
    "partial_4th_strike_to_auxiliary_press_s",
    "partial_auxiliary_press_to_bath_s",
]
PARTIAL_LABELS = [
    "Furnace → 2nd strike",
    "2nd strike → 3rd strike",
    "3rd strike → 4th strike",
    "4th strike → Aux. press",
    "Aux. press → Bath",
]
CUMULATIVE_COLS = [
    "lifetime_2nd_strike_s",
    "lifetime_3rd_strike_s",
    "lifetime_4th_strike_s",
    "lifetime_auxiliary_press_s",
    "lifetime_bath_s",
]
CUMULATIVE_LABELS = [
    "2nd strike (1st op)",
    "3rd strike (2nd op)",
    "4th strike (drill)",
    "Auxiliary press",
    "Bath",
]


@st.cache_resource
def load_predictor():
    return Predictor(model_dir=PROJECT_ROOT / "models", gold_file=GOLD_FILE)


@st.cache_data
def load_data():
    predictor = load_predictor()
    df = pd.read_parquet(GOLD_FILE)
    df["predicted_bath_s"] = predictor.predict_batch(df)
    df["prediction_error_s"] = df["predicted_bath_s"] - df["lifetime_bath_s"]
    return df


@st.cache_data
def get_reference(df):
    return df.groupby("die_matrix")[PARTIAL_COLS + CUMULATIVE_COLS].median()


# ── Page config ──
st.set_page_config(page_title="Forging Line Dashboard", layout="wide")
st.title("Forging Line — Piece Travel Time Dashboard")

# Load data
df = load_data()
reference = get_reference(df)

# ── Sidebar filters ──
st.sidebar.header("Filters")

matrices = sorted(df["die_matrix"].unique())
selected_matrices = st.sidebar.multiselect("Die Matrix", matrices, default=matrices)

date_min = df["timestamp"].dt.date.min()
date_max = df["timestamp"].dt.date.max()
date_range = st.sidebar.date_input("Date range", value=(date_min, date_max), min_value=date_min, max_value=date_max)

show_slow_only = st.sidebar.checkbox("Show only slow pieces (> p90)")

# Apply filters
filtered = df[df["die_matrix"].isin(selected_matrices)].copy()
if len(date_range) == 2:
    filtered = filtered[
        (filtered["timestamp"].dt.date >= date_range[0])
        & (filtered["timestamp"].dt.date <= date_range[1])
    ]

if show_slow_only:
    p90 = df.groupby("die_matrix")["lifetime_bath_s"].quantile(0.90)
    filtered = filtered[filtered["lifetime_bath_s"] > filtered["die_matrix"].map(p90)]

# ── Summary metrics ──
col1, col2, col3, col4 = st.columns(4)
col1.metric("Total Pieces", f"{len(filtered):,}")
col2.metric("Median Bath Time", f"{filtered['lifetime_bath_s'].median():.1f}s")
col3.metric("Median Predicted", f"{filtered['predicted_bath_s'].median():.1f}s")
col4.metric("MAE", f"{filtered['prediction_error_s'].abs().mean():.2f}s")

# ── Pieces table ──
st.subheader("Pieces")

display_cols = [
    "timestamp", "piece_id", "die_matrix", "lifetime_bath_s",
    "predicted_bath_s", "prediction_error_s", "oee_cycle_time_s",
]
table_df = filtered[display_cols].copy()
table_df["timestamp"] = table_df["timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
table_df = table_df.round(2)

selection = st.dataframe(
    table_df,
    use_container_width=True,
    hide_index=True,
    on_select="rerun",
    selection_mode="single-row",
    height=400,
)

# ── Piece detail panel ──
selected_rows = selection.selection.rows if selection.selection else []

if selected_rows:
    idx = selected_rows[0]
    piece = filtered.iloc[idx]

    st.subheader(f"Piece Detail — {piece['piece_id']} (Matrix {int(piece['die_matrix'])})")

    matrix_ref = reference.loc[int(piece["die_matrix"])]

    # Cumulative times vs reference
    st.markdown("**Cumulative travel times vs reference**")
    cum_data = []
    for col, label in zip(CUMULATIVE_COLS, CUMULATIVE_LABELS):
        actual = piece[col]
        ref_val = matrix_ref[col]
        if pd.notna(actual) and pd.notna(ref_val):
            dev = actual - ref_val
            cum_data.append({
                "Stage": label,
                "Actual (s)": round(actual, 2),
                "Reference (s)": round(ref_val, 2),
                "Deviation (s)": round(dev, 2),
            })
    st.dataframe(pd.DataFrame(cum_data), use_container_width=True, hide_index=True)

    # Partial times vs reference
    st.markdown("**Partial times between stages vs reference**")
    partial_data = []
    for col, label in zip(PARTIAL_COLS, PARTIAL_LABELS):
        actual = piece[col]
        ref_val = matrix_ref[col]
        if pd.notna(actual) and pd.notna(ref_val):
            dev = actual - ref_val
            status = "OK" if dev <= 1.0 else "SLOW"
            partial_data.append({
                "Segment": label,
                "Actual (s)": round(actual, 2),
                "Reference (s)": round(ref_val, 2),
                "Deviation (s)": round(dev, 2),
                "Status": status,
            })
    st.dataframe(pd.DataFrame(partial_data), use_container_width=True, hide_index=True)

    # Bar chart: actual vs reference partial times (process synoptic)
    st.markdown("**Process synoptic — actual vs reference partial times**")
    chart_data = []
    for row in partial_data:
        chart_data.append({"Segment": row["Segment"], "Time (s)": row["Actual (s)"], "Type": "Actual"})
        chart_data.append({"Segment": row["Segment"], "Time (s)": row["Reference (s)"], "Type": "Reference"})

    chart_df = pd.DataFrame(chart_data)
    chart = (
        alt.Chart(chart_df)
        .mark_bar()
        .encode(
            x=alt.X("Segment:N", sort=[r["Segment"] for r in partial_data], title="Process Segment"),
            y=alt.Y("Time (s):Q", title="Time (seconds)"),
            color=alt.Color("Type:N", scale=alt.Scale(domain=["Actual", "Reference"], range=["#ff7f0e", "#1f77b4"])),
            xOffset="Type:N",
            tooltip=["Segment", "Type", "Time (s)"],
        )
        .properties(width=600, height=350)
    )
    st.altair_chart(chart, use_container_width=True)

else:
    st.info("Select a piece from the table above to see its per-stage timing detail.")
