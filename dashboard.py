
import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

BASE_DIR = Path(__file__).resolve().parent
DATABASE_FILE = BASE_DIR / "data" / "trade_genie.db"


st.set_page_config(
    page_title="Trade Genie Dashboard",
    layout="wide",
)

st.title("Trade Genie Operator Dashboard")
st_autorefresh(interval=10000, key="trade_genie_refresh")

def load_signals() -> pd.DataFrame:
    if not DATABASE_FILE.exists():
        return pd.DataFrame()

    with sqlite3.connect(DATABASE_FILE) as connection:
        return pd.read_sql_query(
            "SELECT * FROM signals ORDER BY signal_timestamp DESC",
            connection,
        )


signals = load_signals()


if signals.empty:
    st.warning("No signals found in the database.")
    st.stop()


outcomes = signals["outcome"].fillna("").astype(str).str.upper()

wins = int((outcomes == "WIN").sum())
losses = int((outcomes == "LOSS").sum())
pending = int((signals["status"].fillna("").astype(str).str.upper() == "PENDING").sum())
resolved = wins + losses
win_rate = (wins / resolved * 100) if resolved else 0.0


col1, col2, col3, col4, col5 = st.columns(5)

col1.metric("Total Signals", len(signals))
col2.metric("Pending", pending)
col3.metric("Wins", wins)
col4.metric("Losses", losses)
col5.metric("Win Rate", f"{win_rate:.1f}%")

st.subheader("System Health")

health_data = signals[
    outcomes.isin(["WIN", "LOSS"])
].copy()

if health_data.empty:
    st.info("Not enough resolved trades to calculate system health.")
else:
    health_data["reward_risk"] = pd.to_numeric(
        health_data["reward_risk"],
        errors="coerce",
    ).fillna(0.0)

    health_data["r_result"] = 0.0

    health_data.loc[
        health_data["outcome"].fillna("").astype(str).str.upper() == "WIN",
        "r_result",
    ] = health_data.loc[
        health_data["outcome"].fillna("").astype(str).str.upper() == "WIN",
        "reward_risk",
    ]

    health_data.loc[
        health_data["outcome"].fillna("").astype(str).str.upper() == "LOSS",
        "r_result",
    ] = -1.0

    gross_profit = health_data.loc[
        health_data["r_result"] > 0,
        "r_result",
    ].sum()

    gross_loss = abs(
        health_data.loc[
            health_data["r_result"] < 0,
            "r_result",
        ].sum()
    )

    health_profit_factor = (
        gross_profit / gross_loss
        if gross_loss > 0
        else float("inf")
    )

    health_expectancy = health_data["r_result"].mean()

    asset_health = (
        health_data.groupby("asset_name", dropna=False)["r_result"]
        .sum()
        .sort_values(ascending=False)
    )

    best_asset = (
        str(asset_health.index[0])
        if not asset_health.empty
        else "N/A"
    )

    worst_asset = (
        str(asset_health.index[-1])
        if not asset_health.empty
        else "N/A"
    )

    if resolved < 20:
        overall_grade = "EARLY DATA"
    elif win_rate >= 65 and health_profit_factor >= 2:
        overall_grade = "A"
    elif win_rate >= 55 and health_profit_factor >= 1.5:
        overall_grade = "B"
    elif health_profit_factor >= 1:
        overall_grade = "C"
    else:
        overall_grade = "D"

    score1, score2, score3, score4 = st.columns(4)

    score1.metric("Overall Grade", overall_grade)

    score2.metric(
        "Profit Factor",
        "∞"
        if health_profit_factor == float("inf")
        else f"{health_profit_factor:.2f}",
    )

    score3.metric(
        "Expectancy",
        f"{health_expectancy:+.2f}R",
    )

    score4.metric(
        "Resolved Trades",
        resolved,
    )

    score5, score6 = st.columns(2)

    score5.metric("Best Asset", best_asset)
    score6.metric("Worst Asset", worst_asset)

st.divider()

st.subheader("Active Signals")

pending_signals = signals[
    signals["status"].fillna("").astype(str).str.upper() == "PENDING"
]

if pending_signals.empty:
    st.info("No active signals.")
else:
    for _, trade in pending_signals.iterrows():
        st.markdown(
            f"""
            **{trade.get('asset_name', trade.get('asset', 'Unknown'))}**
            
            Direction: **{trade.get('direction', 'N/A')}**  
            Entry: **{trade.get('entry_price', 'N/A')}**  
            Stop Loss: **{trade.get('stop_loss', 'N/A')}**  
            Take Profit: **{trade.get('take_profit', 'N/A')}**  
            Grade: **{trade.get('signal_grade', 'N/A')}**  
            Status: **PENDING**
            """
        )
        st.divider()
st.subheader("Recent Signals")

display_columns = [
    column
    for column in [
        "signal_timestamp",
        "asset_name",
        "direction",
        "entry_price",
        "stop_loss",
        "take_profit",
        "signal_grade",
        "status",
        "outcome",
    ]
    if column in signals.columns
]

st.dataframe(
    signals[display_columns],
    width="stretch",
    hide_index=True,
)

st.divider()
st.subheader("Performance by Asset")

resolved_signals = signals[
    signals["outcome"].fillna("").astype(str).str.upper().isin(["WIN", "LOSS"])
].copy()

if resolved_signals.empty:
    st.info("No resolved WIN/LOSS signals available for analytics.")
else:
    asset_performance = (
        resolved_signals.assign(
            win=resolved_signals["outcome"]
            .fillna("")
            .astype(str)
            .str.upper()
            .eq("WIN")
            .astype(int),
            loss=resolved_signals["outcome"]
            .fillna("")
            .astype(str)
            .str.upper()
            .eq("LOSS")
            .astype(int),
        )
        .groupby("asset_name", dropna=False)
        .agg(
            trades=("signal_id", "count"),
            wins=("win", "sum"),
            losses=("loss", "sum"),
        )
        .reset_index()
    )

    asset_performance["win_rate"] = (
        asset_performance["wins"] / asset_performance["trades"] * 100
    ).round(1)

    st.dataframe(
        asset_performance.sort_values(
            ["win_rate", "trades"],
            ascending=[False, False],
        ),
        width="stretch",
        hide_index=True,
    )

st.subheader("Performance by Signal Grade")

if resolved_signals.empty:
    st.info("No resolved WIN/LOSS signals available for grade analytics.")
else:
    grade_performance = (
        resolved_signals.assign(
            signal_grade=resolved_signals["signal_grade"]
            .fillna("Unknown")
            .astype(str)
            .str.upper(),
            win=resolved_signals["outcome"]
            .fillna("")
            .astype(str)
            .str.upper()
            .eq("WIN")
            .astype(int),
            loss=resolved_signals["outcome"]
            .fillna("")
            .astype(str)
            .str.upper()
            .eq("LOSS")
            .astype(int),
        )
        .groupby("signal_grade", dropna=False)
        .agg(
            trades=("signal_id", "count"),
            wins=("win", "sum"),
            losses=("loss", "sum"),
        )
        .reset_index()
    )

    grade_performance["win_rate"] = (
        grade_performance["wins"] / grade_performance["trades"] * 100
    ).round(1)

    st.dataframe(
        grade_performance.sort_values(
            ["win_rate", "trades"],
            ascending=[False, False],
        ),
        width="stretch",
        hide_index=True,
    )

st.subheader("Performance by Market Structure")

if resolved_signals.empty:
    st.info("No resolved WIN/LOSS signals available for structure analytics.")
elif "market_structure" not in resolved_signals.columns:
    st.warning("The market_structure column is missing from the database.")
else:
    structure_performance = (
        resolved_signals.assign(
            market_structure=resolved_signals["market_structure"]
            .fillna("Unknown")
            .astype(str)
            .str.upper(),
            win=resolved_signals["outcome"]
            .fillna("")
            .astype(str)
            .str.upper()
            .eq("WIN")
            .astype(int),
            loss=resolved_signals["outcome"]
            .fillna("")
            .astype(str)
            .str.upper()
            .eq("LOSS")
            .astype(int),
        )
        .groupby("market_structure", dropna=False)
        .agg(
            trades=("signal_id", "count"),
            wins=("win", "sum"),
            losses=("loss", "sum"),
        )
        .reset_index()
    )

    structure_performance["win_rate"] = (
        structure_performance["wins"]
        / structure_performance["trades"]
        * 100
    ).round(1)

    st.dataframe(
        structure_performance.sort_values(
            ["win_rate", "trades"],
            ascending=[False, False],
        ),
        width="stretch",
        hide_index=True,
    )

st.subheader("Performance by Trading Hour")

if resolved_signals.empty:
    st.info("No resolved WIN/LOSS signals available for hourly analytics.")
else:
    hourly = resolved_signals.copy()

    hourly["signal_timestamp"] = pd.to_datetime(
        hourly["signal_timestamp"],
        format="mixed",
        errors="coerce",
    )

    hourly = hourly.dropna(subset=["signal_timestamp"])

    hourly["hour"] = hourly["signal_timestamp"].dt.hour
    hourly["win"] = (
        hourly["outcome"]
        .fillna("")
        .astype(str)
        .str.upper()
        .eq("WIN")
        .astype(int)
    )
    hourly["loss"] = (
        hourly["outcome"]
        .fillna("")
        .astype(str)
        .str.upper()
        .eq("LOSS")
        .astype(int)
    )

    hour_performance = (
        hourly.groupby("hour", dropna=False)
        .agg(
            trades=("signal_id", "count"),
            wins=("win", "sum"),
            losses=("loss", "sum"),
        )
        .reset_index()
    )

    hour_performance["win_rate"] = (
        hour_performance["wins"]
        / hour_performance["trades"]
        * 100
    ).round(1)

    hour_performance["hour_label"] = pd.to_datetime(
        hour_performance["hour"],
        format="%H",
    ).dt.strftime("%-I %p")

    st.dataframe(
        hour_performance[
            ["hour_label", "trades", "wins", "losses", "win_rate"]
        ].sort_values("hour_label"),
        width="stretch",
        hide_index=True,
    )

st.subheader("Equity Curve")

equity_data = resolved_signals.copy()

if equity_data.empty:
    st.info("No resolved trades available for the equity curve.")
else:
    equity_data["signal_timestamp"] = pd.to_datetime(
        equity_data["signal_timestamp"],
        format="mixed",
        errors="coerce",
    )

    equity_data["reward_risk"] = pd.to_numeric(
        equity_data["reward_risk"],
        errors="coerce",
    ).fillna(0.0)

    equity_data = (
        equity_data
        .dropna(subset=["signal_timestamp"])
        .sort_values("signal_timestamp")
        .reset_index(drop=True)
    )

    equity_data["outcome_clean"] = (
        equity_data["outcome"]
        .fillna("")
        .astype(str)
        .str.upper()
    )

    equity_data["r_result"] = 0.0

    win_mask = equity_data["outcome_clean"].eq("WIN")
    loss_mask = equity_data["outcome_clean"].eq("LOSS")

    equity_data.loc[win_mask, "r_result"] = equity_data.loc[
        win_mask, "reward_risk"
    ]

    equity_data.loc[loss_mask, "r_result"] = -1.0

    equity_data["cumulative_r"] = equity_data["r_result"].cumsum()
    equity_data["trade_number"] = range(1, len(equity_data) + 1)

    current_r = equity_data["cumulative_r"].iloc[-1]
    peak_r = equity_data["cumulative_r"].max()

    col1, col2 = st.columns(2)
    col1.metric("Current Net R", f"{current_r:+.2f}R")
    col2.metric("Peak Net R", f"{peak_r:+.2f}R")

    chart_data = equity_data.set_index("trade_number")[["cumulative_r"]]
    chart_data = pd.concat(
        [
            pd.DataFrame({"cumulative_r": [0.0]}, index=[0]),
            chart_data,
        ]
    )

    st.line_chart(
        chart_data,
        x_label="Trade Number",
        y_label="Cumulative R",
    )

    st.caption(
        "This curve uses R-multiples: wins add the stored reward/risk, "
        "and losses subtract 1R."
    )

st.subheader("Drawdown Analysis")

if equity_data.empty:
    st.info("No resolved trades available for drawdown analysis.")
else:
    drawdown_data = equity_data.copy()

    drawdown_data["equity_peak"] = (
        drawdown_data["cumulative_r"]
        .cummax()
        .clip(lower=0.0)
    )

    drawdown_data["drawdown_r"] = (
        drawdown_data["cumulative_r"]
        - drawdown_data["equity_peak"]
    )

    current_drawdown = drawdown_data["drawdown_r"].iloc[-1]
    max_drawdown = drawdown_data["drawdown_r"].min()
    average_drawdown = drawdown_data.loc[
        drawdown_data["drawdown_r"] < 0,
        "drawdown_r",
    ].mean()

    if pd.isna(average_drawdown):
        average_drawdown = 0.0

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Current Drawdown",
        f"{current_drawdown:.2f}R",
    )

    col2.metric(
        "Maximum Drawdown",
        f"{max_drawdown:.2f}R",
    )

    col3.metric(
        "Average Drawdown",
        f"{average_drawdown:.2f}R",
    )

    drawdown_chart = drawdown_data.set_index(
        "trade_number"
    )[["drawdown_r"]]

    drawdown_chart = pd.concat(
        [
            pd.DataFrame(
                {"drawdown_r": [0.0]},
                index=[0],
            ),
            drawdown_chart,
        ]
    )

    st.line_chart(
        drawdown_chart,
        x_label="Trade Number",
        y_label="Drawdown R",
    )

    st.caption(
        "Drawdown measures how far the equity curve is below its previous peak."
    )

st.subheader("Win and Loss Streaks")

if equity_data.empty:
    st.info("No resolved trades available for streak analysis.")
else:
    streak_data = equity_data.copy()

    outcomes = streak_data["outcome_clean"].tolist()

    current_outcome = None
    current_length = 0
    current_win_streak = 0
    current_loss_streak = 0
    longest_win_streak = 0
    longest_loss_streak = 0

    for outcome in outcomes:
        if outcome == current_outcome:
            current_length += 1
        else:
            current_outcome = outcome
            current_length = 1

        if outcome == "WIN":
            longest_win_streak = max(longest_win_streak, current_length)
        elif outcome == "LOSS":
            longest_loss_streak = max(longest_loss_streak, current_length)

    if outcomes:
        if outcomes[-1] == "WIN":
            current_win_streak = current_length
        elif outcomes[-1] == "LOSS":
            current_loss_streak = current_length

    col1, col2, col3, col4 = st.columns(4)

    col1.metric("Current Win Streak", current_win_streak)
    col2.metric("Current Loss Streak", current_loss_streak)
    col3.metric("Longest Win Streak", longest_win_streak)
    col4.metric("Longest Loss Streak", longest_loss_streak)

st.subheader("Monthly Performance")

if equity_data.empty:
    st.info("No resolved trades available for monthly analysis.")
else:
    monthly_data = equity_data.copy()

    monthly_data["month"] = (
        monthly_data["signal_timestamp"]
        .dt.to_period("M")
        .astype(str)
    )

    monthly_performance = (
        monthly_data.groupby("month", dropna=False)
        .agg(
            trades=("signal_id", "count"),
            wins=("outcome_clean", lambda values: (values == "WIN").sum()),
            losses=("outcome_clean", lambda values: (values == "LOSS").sum()),
            net_r=("r_result", "sum"),
        )
        .reset_index()
    )

    monthly_performance["win_rate"] = (
        monthly_performance["wins"]
        / monthly_performance["trades"]
        * 100
    ).round(1)

    monthly_performance["net_r"] = monthly_performance["net_r"].round(2)

    st.dataframe(
        monthly_performance[
            ["month", "trades", "wins", "losses", "win_rate", "net_r"]
        ].sort_values("month"),
        width="stretch",
        hide_index=True,
    )

st.subheader("Trade Duration Analytics")

if resolved_signals.empty:
    st.info("No resolved trades available.")
else:
    duration_data = resolved_signals.copy()

    duration_data["signal_timestamp"] = pd.to_datetime(
        duration_data["signal_timestamp"],
        format="mixed",
        errors="coerce",
    )

    duration_data["resolved_timestamp"] = pd.to_datetime(
        duration_data["resolved_timestamp"],
        format="mixed",
        errors="coerce",
    )

    duration_data = duration_data.dropna(
        subset=["signal_timestamp", "resolved_timestamp"]
    )

    duration_data["duration_minutes"] = (
        duration_data["resolved_timestamp"]
        - duration_data["signal_timestamp"]
    ).dt.total_seconds() / 60

    duration_data["outcome_clean"] = (
        duration_data["outcome"]
        .fillna("")
        .astype(str)
        .str.upper()
    )

    avg_minutes = duration_data["duration_minutes"].mean()

    win_minutes = duration_data.loc[
        duration_data["outcome_clean"] == "WIN",
        "duration_minutes",
    ]

    loss_minutes = duration_data.loc[
        duration_data["outcome_clean"] == "LOSS",
        "duration_minutes",
    ]

    col1, col2, col3 = st.columns(3)

    col1.metric(
        "Average Duration",
        f"{avg_minutes:.0f} min",
    )

    col2.metric(
        "Average Win",
        f"{win_minutes.mean():.0f} min",
    )

    col3.metric(
        "Average Loss",
        f"{loss_minutes.mean():.0f} min",
    )

    duration_data["trade_label"] = (
        duration_data["asset_name"].fillna("Unknown").astype(str)
        + " "
        + duration_data["outcome_clean"]
    )

    duration_chart = duration_data[
        ["trade_label", "duration_minutes"]
    ].copy()

    duration_chart["trade_label"] = (
        duration_chart["trade_label"]
        + " #"
        + (duration_chart.index + 1).astype(str)
    )

    st.bar_chart(
        duration_chart.set_index("trade_label")[["duration_minutes"]]
    )


st.subheader("Core Performance Metrics")

if equity_data.empty:
    st.info("No resolved trades available for performance metrics.")
else:
    metric_data = equity_data.copy()

    winning_r = metric_data.loc[
        metric_data["r_result"] > 0,
        "r_result",
    ]

    losing_r = metric_data.loc[
        metric_data["r_result"] < 0,
        "r_result",
    ]

    gross_profit_r = winning_r.sum()
    gross_loss_r = abs(losing_r.sum())

    profit_factor = (
        gross_profit_r / gross_loss_r
        if gross_loss_r > 0
        else float("inf")
    )

    expectancy_r = metric_data["r_result"].mean()

    average_win_r = (
        winning_r.mean()
        if not winning_r.empty
        else 0.0
    )

    average_loss_r = (
        losing_r.mean()
        if not losing_r.empty
        else 0.0
    )

    recovery_factor = (
        current_r / abs(max_drawdown)
        if max_drawdown < 0
        else float("inf")
    )

    col1, col2, col3 = st.columns(3)
    col4, col5 = st.columns(2)

    col1.metric(
        "Profit Factor",
        "∞" if profit_factor == float("inf") else f"{profit_factor:.2f}",
    )

    col2.metric(
        "Expectancy per Trade",
        f"{expectancy_r:+.2f}R",
    )

    col3.metric(
        "Average Winner",
        f"{average_win_r:+.2f}R",
    )

    col4.metric(
        "Average Loser",
        f"{average_loss_r:.2f}R",
    )

    col5.metric(
        "Recovery Factor",
        "∞" if recovery_factor == float("inf") else f"{recovery_factor:.2f}",
    )

    st.caption(
        "Profit factor compares gross winning R to gross losing R. "
        "Expectancy estimates the average R earned per completed trade."
    )

st.subheader("Trade Review")

if resolved_signals.empty:
    st.info("No resolved trades available for review.")
else:
    review_data = resolved_signals.copy()

    review_data["signal_timestamp"] = pd.to_datetime(
        review_data["signal_timestamp"],
        format="mixed",
        errors="coerce",
    )

    review_data["resolved_timestamp"] = pd.to_datetime(
        review_data["resolved_timestamp"],
        format="mixed",
        errors="coerce",
    )

    review_data["review_label"] = (
        review_data["asset_name"].fillna("Unknown").astype(str)
        + " | "
        + review_data["direction"].fillna("N/A").astype(str)
        + " | "
        + review_data["outcome"].fillna("N/A").astype(str)
        + " | "
        + review_data["signal_timestamp"].dt.strftime("%Y-%m-%d %I:%M %p")
    )

    selected_label = st.selectbox(
        "Select a trade",
        review_data["review_label"].tolist(),
    )

    selected_trade = review_data.loc[
        review_data["review_label"] == selected_label
    ].iloc[0]

    col1, col2, col3 = st.columns(3)

    col1.metric("Asset", selected_trade.get("asset_name", "N/A"))
    col2.metric("Direction", selected_trade.get("direction", "N/A"))
    col3.metric("Outcome", selected_trade.get("outcome", "N/A"))

    col4, col5, col6 = st.columns(3)

    col4.metric(
        "Entry",
        f"{float(selected_trade.get('entry_price', 0)):.5f}",
    )

    col5.metric(
        "Stop Loss",
        f"{float(selected_trade.get('stop_loss', 0)):.5f}",
    )

    col6.metric(
        "Take Profit",
        f"{float(selected_trade.get('take_profit', 0)):.5f}",
    )

    col7, col8, col9 = st.columns(3)

    col7.metric(
        "Signal Grade",
        selected_trade.get("signal_grade", "N/A"),
    )

    col8.metric(
        "Market Structure",
        selected_trade.get("market_structure", "N/A"),
    )

    col9.metric(
        "Reward/Risk",
        f"1:{float(selected_trade.get('reward_risk', 0)):.1f}",
    )

    st.metric(
        "Confirmation Score",
        f"{int(selected_trade.get('confirmation_score', 0))}/5",
    )

    confirmation_details = str(
        selected_trade.get("confirmation_details", "")
    ).strip()

    if confirmation_details:
        st.write("**Confirmation Details:**")

        detail_items = [
            item.strip()
            for item in confirmation_details.split("|")
            if item.strip()
        ]

        for item in detail_items:
            if item.endswith(": PASS"):
                st.success(item)
            elif item.endswith(": FAIL"):
                st.error(item)
            else:
                st.write(item)

    if pd.notna(selected_trade["signal_timestamp"]):
        st.write(
            "**Signal Time:**",
            selected_trade["signal_timestamp"].strftime(
                "%Y-%m-%d %I:%M %p"
            ),
        )

    if pd.notna(selected_trade["resolved_timestamp"]):
        st.write(
            "**Resolved Time:**",
            selected_trade["resolved_timestamp"].strftime(
                "%Y-%m-%d %I:%M %p"
            ),
        )

        duration_minutes = (
            selected_trade["resolved_timestamp"]
            - selected_trade["signal_timestamp"]
        ).total_seconds() / 60

        st.write(
            "**Trade Duration:**",
            f"{duration_minutes:.0f} minutes",
        )

    st.write(
        "**Signal ID:**",
        selected_trade.get("signal_id", "N/A"),
    )

st.subheader("Advanced Asset Performance")

if equity_data.empty:
    st.info("No resolved trades available for advanced asset analytics.")
else:
    asset_data = equity_data.copy()

    asset_data["signal_timestamp"] = pd.to_datetime(
        asset_data["signal_timestamp"],
        format="mixed",
        errors="coerce",
    )

    asset_data["resolved_timestamp"] = pd.to_datetime(
        asset_data["resolved_timestamp"],
        format="mixed",
        errors="coerce",
    )

    asset_data = asset_data.dropna(
        subset=["signal_timestamp", "resolved_timestamp"]
    )

    asset_data["duration_minutes"] = (
        asset_data["resolved_timestamp"]
        - asset_data["signal_timestamp"]
    ).dt.total_seconds() / 60

    def asset_profit_factor(group):
        gross_profit = group.loc[
            group["r_result"] > 0,
            "r_result",
        ].sum()

        gross_loss = abs(
            group.loc[
                group["r_result"] < 0,
                "r_result",
            ].sum()
        )

        if gross_loss == 0:
            return float("inf")

        return gross_profit / gross_loss

    advanced_asset = (
        asset_data.groupby("asset_name", dropna=False)
        .agg(
            trades=("signal_id", "count"),
            wins=("outcome_clean", lambda values: (values == "WIN").sum()),
            losses=("outcome_clean", lambda values: (values == "LOSS").sum()),
            net_r=("r_result", "sum"),
            avg_r=("r_result", "mean"),
            avg_duration=("duration_minutes", "mean"),
        )
        .reset_index()
    )

    profit_factors = (
        asset_data.groupby("asset_name", dropna=False)
        .apply(asset_profit_factor)
        .rename("profit_factor")
        .reset_index()
    )

    advanced_asset = advanced_asset.merge(
        profit_factors,
        on="asset_name",
        how="left",
    )

    advanced_asset["win_rate"] = (
        advanced_asset["wins"]
        / advanced_asset["trades"]
        * 100
    ).round(1)

    advanced_asset["net_r"] = advanced_asset["net_r"].round(2)
    advanced_asset["avg_r"] = advanced_asset["avg_r"].round(2)
    advanced_asset["avg_duration"] = advanced_asset[
        "avg_duration"
    ].round(0)

    advanced_asset["profit_factor"] = advanced_asset[
        "profit_factor"
    ].apply(
        lambda value: "∞"
        if value == float("inf")
        else f"{value:.2f}"
    )

    st.dataframe(
        advanced_asset[
            [
                "asset_name",
                "trades",
                "wins",
                "losses",
                "win_rate",
                "net_r",
                "avg_r",
                "avg_duration",
                "profit_factor",
            ]
        ].sort_values(
            ["net_r", "win_rate"],
            ascending=[False, False],
        ),
        width="stretch",
        hide_index=True,
    )

st.subheader("Confirmation Rule Analytics")

if resolved_signals.empty:
    st.info("No resolved trades available for confirmation analytics.")
else:
    rule_rows = []

    for _, trade in resolved_signals.iterrows():
        outcome = str(trade.get("outcome", "")).upper()
        details = str(trade.get("confirmation_details", "")).strip()

        if not details:
            continue

        for item in details.split("|"):
            item = item.strip()

            if ": " not in item:
                continue

            rule_name, rule_result = item.rsplit(": ", 1)

            rule_rows.append(
                {
                    "rule": rule_name.strip(),
                    "rule_result": rule_result.strip().upper(),
                    "trade_outcome": outcome,
                }
            )

    rule_data = pd.DataFrame(rule_rows)

    if rule_data.empty:
        st.info("No confirmation-rule details were available.")
    else:
        rule_data["win"] = (
            rule_data["trade_outcome"].eq("WIN").astype(int)
        )

        rule_summary = (
            rule_data.groupby(
                ["rule", "rule_result"],
                dropna=False,
            )
            .agg(
                trades=("trade_outcome", "count"),
                wins=("win", "sum"),
            )
            .reset_index()
        )

        rule_summary["losses"] = (
            rule_summary["trades"] - rule_summary["wins"]
        )

        rule_summary["win_rate"] = (
            rule_summary["wins"]
            / rule_summary["trades"]
            * 100
        ).round(1)

        minimum_trades = st.slider(
            "Minimum sample size",
            min_value=1,
            max_value=20,
            value=3,
            step=1,
        )

        filtered_rules = rule_summary[
            rule_summary["trades"] >= minimum_trades
        ]

        st.dataframe(
            filtered_rules[
                [
                    "rule",
                    "rule_result",
                    "trades",
                    "wins",
                    "losses",
                    "win_rate",
                ]
            ].sort_values(
                ["win_rate", "trades"],
                ascending=[False, False],
            ),
            width="stretch",
            hide_index=True,
        )

        st.caption(
            "This table compares how trades performed when each confirmation "
            "rule passed or failed."
        )

st.subheader("Strategy Optimizer")

if resolved_signals.empty:
    st.info("No resolved trades available for strategy optimization.")
else:
    optimizer_rows = []

    optimizer_data = resolved_signals.copy()

    optimizer_data["reward_risk"] = pd.to_numeric(
        optimizer_data["reward_risk"],
        errors="coerce",
    ).fillna(0.0)

    optimizer_data["outcome_clean"] = (
        optimizer_data["outcome"]
        .fillna("")
        .astype(str)
        .str.upper()
    )

    optimizer_data["r_result"] = 0.0

    optimizer_data.loc[
        optimizer_data["outcome_clean"] == "WIN",
        "r_result",
    ] = optimizer_data.loc[
        optimizer_data["outcome_clean"] == "WIN",
        "reward_risk",
    ]

    optimizer_data.loc[
        optimizer_data["outcome_clean"] == "LOSS",
        "r_result",
    ] = -1.0

    for _, trade in optimizer_data.iterrows():
        details = str(
            trade.get("confirmation_details", "")
        ).strip()

        if not details:
            continue

        for item in details.split("|"):
            item = item.strip()

            if ": " not in item:
                continue

            rule_name, rule_result = item.rsplit(": ", 1)

            optimizer_rows.append(
                {
                    "rule": rule_name.strip(),
                    "rule_result": rule_result.strip().upper(),
                    "r_result": float(trade["r_result"]),
                }
            )

    optimizer_rules = pd.DataFrame(optimizer_rows)

    if optimizer_rules.empty:
        st.info("No confirmation data available for optimization.")
    else:
        optimizer_summary = (
            optimizer_rules.groupby(
                ["rule", "rule_result"],
                dropna=False,
            )
            .agg(
                trades=("r_result", "count"),
                average_r=("r_result", "mean"),
            )
            .reset_index()
        )

        optimizer_pivot = optimizer_summary.pivot(
            index="rule",
            columns="rule_result",
            values=["trades", "average_r"],
        )

        optimizer_pivot.columns = [
            f"{metric}_{result}".lower()
            for metric, result in optimizer_pivot.columns
        ]

        optimizer_pivot = optimizer_pivot.reset_index()

        for column in [
            "trades_pass",
            "trades_fail",
            "average_r_pass",
            "average_r_fail",
        ]:
            if column not in optimizer_pivot.columns:
                optimizer_pivot[column] = 0.0

        optimizer_pivot["expectancy_impact"] = (
            optimizer_pivot["average_r_pass"]
            - optimizer_pivot["average_r_fail"]
        )

        optimizer_pivot[
            ["average_r_pass", "average_r_fail", "expectancy_impact"]
        ] = optimizer_pivot[
            ["average_r_pass", "average_r_fail", "expectancy_impact"]
        ].round(2)

        optimizer_pivot[
            ["trades_pass", "trades_fail"]
        ] = optimizer_pivot[
            ["trades_pass", "trades_fail"]
        ].fillna(0).astype(int)

        optimizer_minimum = st.slider(
            "Optimizer minimum samples per side",
            min_value=1,
            max_value=20,
            value=3,
            step=1,
        )

        optimizer_filtered = optimizer_pivot[
            (optimizer_pivot["trades_pass"] >= optimizer_minimum)
            & (optimizer_pivot["trades_fail"] >= optimizer_minimum)
        ].copy()

        st.dataframe(
            optimizer_filtered[
                [
                    "rule",
                    "trades_pass",
                    "trades_fail",
                    "average_r_pass",
                    "average_r_fail",
                    "expectancy_impact",
                ]
            ].sort_values(
                "expectancy_impact",
                ascending=False,
            ),
            width="stretch",
            hide_index=True,
        )

        if optimizer_filtered.empty:
            st.info(
                "No rules currently meet the selected sample requirement "
                "on both PASS and FAIL sides."
            )
        else:
            strongest_rule = optimizer_filtered.sort_values(
                "expectancy_impact",
                ascending=False,
            ).iloc[0]

            weakest_rule = optimizer_filtered.sort_values(
                "expectancy_impact",
                ascending=True,
            ).iloc[0]

            col1, col2 = st.columns(2)

            col1.metric(
                "Strongest Rule",
                strongest_rule["rule"],
                f"{strongest_rule['expectancy_impact']:+.2f}R impact",
            )

            col2.metric(
                "Weakest Rule",
                weakest_rule["rule"],
                f"{weakest_rule['expectancy_impact']:+.2f}R impact",
            )

        st.caption(
            "Expectancy impact equals average R when a rule passes minus "
            "average R when it fails. Positive values suggest the rule helps."
        )
