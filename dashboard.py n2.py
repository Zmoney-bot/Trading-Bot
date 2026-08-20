import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from streamlit_autorefresh import st_autorefresh

from storage import SignalStore


BASE_DIR = Path(__file__).resolve().parent
RUNTIME_DIR = Path(os.getenv("TRADE_GENIE_DATA_DIR", str(BASE_DIR))).expanduser()
DATABASE_FILE = RUNTIME_DIR / "trade_genie.db"
SIGNALS_BACKUP = RUNTIME_DIR / "trade_genie_contrarian_signals.csv"
SIGNAL_STORE = SignalStore(DATABASE_FILE, SIGNALS_BACKUP)
ET = ZoneInfo("America/New_York")

st.set_page_config(
    page_title="Trade Genie | Command Center",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root { --card:#111827; --border:rgba(148,163,184,.18); --muted:#94a3b8; }
    .stApp { background:radial-gradient(circle at 5% 0%,rgba(126,34,206,.2),transparent 28rem),#080d17; }
    .block-container { max-width:1600px; padding:1.1rem 1.5rem 2rem; }
    [data-testid="stSidebar"] { background:#090f1b; border-right:1px solid var(--border); }
    [data-testid="stSidebar"] .block-container { padding-top:1.2rem; }
    .tg-head { display:flex;justify-content:space-between;align-items:center;gap:1rem;margin:0 0 .65rem; }
    .tg-brand { color:#f8fafc;font-size:1.45rem;font-weight:800;letter-spacing:-.025em; }
    .tg-sub { color:var(--muted);font-size:.78rem;margin-top:.08rem; }
    .tg-badge { display:inline-flex;align-items:center;gap:.45rem;padding:.35rem .7rem;border:1px solid rgba(34,197,94,.3);border-radius:999px;color:#bbf7d0;background:rgba(34,197,94,.09);font-size:.72rem;font-weight:750; }
    .tg-dot { width:7px;height:7px;border-radius:50%;background:#22c55e;box-shadow:0 0 10px #22c55e; }
    .tg-badge-stale { border-color:rgba(245,158,11,.35);color:#fde68a;background:rgba(245,158,11,.09); }
    .tg-dot-stale { background:#f59e0b;box-shadow:0 0 10px #f59e0b; }
    div[data-testid="stMetric"] { min-height:92px;padding:.72rem .85rem;border:1px solid var(--border);border-radius:13px;background:rgba(17,24,39,.86); }
    div[data-testid="stMetricLabel"] { color:var(--muted);font-size:.78rem; }
    div[data-testid="stMetricValue"] { color:#f8fafc;font-size:1.55rem; }
    div[data-testid="stDataFrame"] { border:1px solid var(--border);border-radius:12px;overflow:hidden; }
    div[data-testid="stExpander"] { border-color:var(--border);background:rgba(17,24,39,.48); }
    div[data-testid="stVerticalBlockBorderWrapper"] { border-color:var(--border);background:rgba(17,24,39,.38); }
    h1,h2,h3 { color:#e2e8f0!important;letter-spacing:-.02em; }
    h2 { font-size:1.15rem!important;margin:.4rem 0!important; }
    .stTabs [data-baseweb="tab-list"] { gap:.25rem; }
    .stTabs [data-baseweb="tab"] { height:2.35rem;padding:0 .85rem;border-radius:8px;background:#111827; }
    #MainMenu,footer { visibility:hidden; }
    @media(max-width:800px){.block-container{padding:.8rem}.tg-head{align-items:flex-start}.tg-brand{font-size:1.15rem}}
    </style>
    """,
    unsafe_allow_html=True,
)


def series(frame: pd.DataFrame, name: str, default="") -> pd.Series:
    if name in frame.columns:
        return frame[name]
    return pd.Series(default, index=frame.index)


@st.cache_data(ttl=8, show_spinner=False)
def load_signals() -> pd.DataFrame:
    frame = SIGNAL_STORE.load_frame()
    if frame.empty:
        return frame
    frame = frame.copy()
    frame["signal_time"] = pd.to_datetime(series(frame, "signal_timestamp"), format="mixed", errors="coerce")
    frame["resolved_time"] = pd.to_datetime(series(frame, "resolved_timestamp"), format="mixed", errors="coerce")
    frame["outcome_clean"] = series(frame, "outcome").fillna("").astype(str).str.upper()
    frame["status_clean"] = series(frame, "status").fillna("").astype(str).str.upper()
    frame["reward_risk_num"] = pd.to_numeric(series(frame, "reward_risk", 0), errors="coerce").fillna(0.0)
    frame["r_result"] = 0.0
    frame.loc[frame["outcome_clean"].eq("WIN"), "r_result"] = frame.loc[frame["outcome_clean"].eq("WIN"), "reward_risk_num"]
    frame.loc[frame["outcome_clean"].eq("LOSS"), "r_result"] = -1.0
    return frame.sort_values("signal_time", ascending=False, na_position="last")


def resolved_rows(frame: pd.DataFrame) -> pd.DataFrame:
    return frame[frame["outcome_clean"].isin(["WIN", "LOSS"])].copy()


def safe_value(row, name, fallback="N/A"):
    value = row.get(name, fallback)
    return fallback if pd.isna(value) or str(value).strip() == "" else value


def display_table(frame: pd.DataFrame, columns: list[str], height=310):
    chosen = [column for column in columns if column in frame.columns]
    if frame.empty:
        st.info("No records in this view.")
    elif chosen:
        st.dataframe(frame[chosen], width="stretch", hide_index=True, height=height)


def parse_confirmations(value) -> list[tuple[str, str]]:
    if value is None or pd.isna(value):
        return []
    results = []
    for line in str(value).replace(";", "\n").splitlines():
        line = line.strip(" •-\t")
        if not line:
            continue
        if ":" in line:
            name, result = line.rsplit(":", 1)
        elif "=" in line:
            name, result = line.rsplit("=", 1)
        else:
            name, result = line, "INFO"
        results.append((name.strip(), result.strip().upper()))
    return results


def trade_expander(row, prefix="trade"):
    asset = safe_value(row, "asset_name", safe_value(row, "asset", "Unknown"))
    direction = safe_value(row, "direction")
    grade = safe_value(row, "signal_grade", "—")
    score = safe_value(row, "confirmation_score", "—")
    status = safe_value(row, "status", safe_value(row, "outcome", "Unknown"))
    stamp = row.get("signal_time")
    stamp_text = stamp.strftime("%b %d · %I:%M %p") if pd.notna(stamp) else "Time unavailable"
    with st.expander(f"{asset}  ·  {direction}  ·  {grade}  ·  {score}/5  ·  {status}  ·  {stamp_text}"):
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Entry", safe_value(row, "entry_price"))
        c2.metric("Stop", safe_value(row, "stop_loss"))
        c3.metric("Target", safe_value(row, "take_profit"))
        c4.metric("R:R", f"1:{safe_value(row, 'reward_risk', '—')}")
        confirmations = parse_confirmations(row.get("confirmation_details"))
        if confirmations:
            passed = [name for name, result in confirmations if any(word in result for word in ("PASS", "TRUE", "YES", "✓"))]
            failed = [name for name, result in confirmations if any(word in result for word in ("FAIL", "FALSE", "NO", "✕", "X"))]
            pcol, fcol = st.columns(2)
            with pcol:
                st.caption("CONFIRMED")
                st.markdown("\n".join(f"- ✅ {item}" for item in passed) or "—")
            with fcol:
                st.caption("NOT CONFIRMED")
                st.markdown("\n".join(f"- ❌ {item}" for item in failed) or "—")
        else:
            st.caption("No stored confirmation breakdown for this signal.")


def breakdown(frame: pd.DataFrame, group: str, label: str):
    data = resolved_rows(frame)
    if data.empty or group not in data.columns:
        st.info(f"No resolved {label.lower()} data available.")
        return
    result = data.assign(win=data["outcome_clean"].eq("WIN").astype(int)).groupby(group, dropna=False).agg(
        trades=("outcome_clean", "size"), wins=("win", "sum"), net_r=("r_result", "sum")
    ).reset_index()
    result["losses"] = result["trades"] - result["wins"]
    result["win_rate"] = (result["wins"] / result["trades"] * 100).round(1)
    result["net_r"] = result["net_r"].round(2)
    st.dataframe(result.sort_values(["net_r", "win_rate"], ascending=False), width="stretch", hide_index=True, height=300)


signals = load_signals()
with st.sidebar:
    st.markdown("### 🧠 Trade Genie")
    st.caption("OPERATOR CONSOLE")
    page = st.radio("Navigate", ["Overview", "Analytics", "Strategies", "Journal", "System Health", "Settings"], label_visibility="collapsed")
    st.divider()
    auto_refresh = st.toggle("Auto-refresh", value=True)
    refresh_seconds = st.select_slider("Refresh interval", options=[10, 15, 30, 60], value=15, disabled=not auto_refresh)
    st.caption(f"Data: {DATABASE_FILE.name}")

if auto_refresh:
    st_autorefresh(interval=refresh_seconds * 1000, key="trade_genie_refresh")

now = datetime.now(ET)
newest_event = signals["signal_time"].max() if not signals.empty else pd.NaT
if pd.notna(newest_event):
    # SignalStore currently contains naïve ET timestamps. Localize them before
    # comparing with the timezone-aware dashboard clock.
    newest_event_et = newest_event.tz_localize(ET) if newest_event.tzinfo is None else newest_event.tz_convert(ET)
    event_age_minutes = max(0.0, (pd.Timestamp.now(tz=ET) - newest_event_et).total_seconds() / 60)
else:
    newest_event_et = pd.NaT
    event_age_minutes = None

data_is_fresh = event_age_minutes is not None and event_age_minutes <= max(refresh_seconds * 3 / 60, 45)
badge_text = "ENGINE DATA CURRENT" if data_is_fresh else "ENGINE DATA STALE"
badge_class = "tg-badge" if data_is_fresh else "tg-badge tg-badge-stale"
dot_class = "tg-dot" if data_is_fresh else "tg-dot tg-dot-stale"
st.markdown(
    f'<div class="tg-head"><div><div class="tg-brand">{page}</div><div class="tg-sub">Trade Genie command center · {now:%b %d, %Y · %I:%M:%S %p ET}</div></div><div class="{badge_class}"><span class="{dot_class}"></span> {badge_text}</div></div>',
    unsafe_allow_html=True,
)

if signals.empty:
    st.warning("No signals found yet. The dashboard is connected and will populate after the engine stores its first scan or signal.")
    st.stop()

resolved = resolved_rows(signals)
wins = int(resolved["outcome_clean"].eq("WIN").sum())
losses = int(resolved["outcome_clean"].eq("LOSS").sum())
win_rate = wins / len(resolved) * 100 if len(resolved) else 0.0
gross_profit = resolved.loc[resolved["r_result"] > 0, "r_result"].sum()
gross_loss = abs(resolved.loc[resolved["r_result"] < 0, "r_result"].sum())
profit_factor = gross_profit / gross_loss if gross_loss else (float("inf") if gross_profit else 0.0)
net_r = float(resolved["r_result"].sum())
expectancy = float(resolved["r_result"].mean()) if not resolved.empty else 0.0
active = signals[signals["status_clean"].isin(["ACTIVE", "OPEN"])]
rejected = signals[signals["status_clean"].isin(["REJECT", "REJECTED", "NO TRADE", "NO_TRADE"]) | signals["outcome_clean"].isin(["REJECT", "REJECTED"])]
pending = signals[signals["status_clean"].isin(["PENDING", "WATCH", "WATCHING", "QUEUED"])]

if page == "Overview":
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Win Rate", f"{win_rate:.1f}%")
    k2.metric("Profit Factor", "∞" if profit_factor == float("inf") else f"{profit_factor:.2f}")
    k3.metric("Net R", f"{net_r:+.2f}R")
    k4.metric("Expectancy", f"{expectancy:+.2f}R")
    k5.metric("Open", len(active))
    k6.metric("Total Signals", len(signals))

    left, right = st.columns([1.35, 1], gap="medium")
    with left:
        st.subheader("Performance")
        if resolved.empty:
            st.info("Equity curve appears after the first resolved trade.")
        else:
            curve = resolved.sort_values("signal_time").copy()
            curve["cumulative_r"] = curve["r_result"].cumsum()
            curve = pd.concat([pd.DataFrame({"cumulative_r": [0.0]}, index=[0]), curve.set_index(pd.RangeIndex(1, len(curve) + 1))[["cumulative_r"]]])
            st.line_chart(curve, height=260)
    with right:
        st.subheader("Live Scanner")
        scanner = signals.drop_duplicates(subset=["asset_name"] if "asset_name" in signals.columns else None).head(12).copy()
        scanner_cols = ["asset_name", "direction", "confirmation_score", "signal_grade", "market_structure", "status"]
        display_table(scanner, scanner_cols, height=260)

    st.subheader("Signal Center")
    tab_active, tab_pending, tab_resolved, tab_rejected = st.tabs([
        f"Active ({len(active)})", f"Pending ({len(pending)})", f"Resolved ({len(resolved)})", f"Rejected ({len(rejected)})"
    ])
    for tab, data in [(tab_active, active), (tab_pending, pending), (tab_resolved, resolved), (tab_rejected, rejected)]:
        with tab:
            if data.empty:
                st.info("No signals in this state.")
            else:
                display_table(data.head(12), ["signal_timestamp", "asset_name", "strategy_name", "direction", "entry_price", "signal_grade", "confirmation_score", "status", "outcome"], 260)
                with st.expander("Signal drill-down", expanded=False):
                    for idx, row in data.head(10).iterrows():
                        trade_expander(row, str(idx))

elif page == "Analytics":
    st.subheader("Performance Analytics")
    a1, a2, a3, a4 = st.columns(4)
    a1.metric("Resolved Trades", len(resolved))
    a2.metric("Wins / Losses", f"{wins} / {losses}")
    a3.metric("Net R", f"{net_r:+.2f}R")
    a4.metric("Avg R", f"{expectancy:+.2f}R")
    tabs = st.tabs(["Asset", "Grade", "Structure", "Trading Hour", "Monthly", "Drawdown"])
    with tabs[0]: breakdown(signals, "asset_name", "Asset")
    with tabs[1]: breakdown(signals, "signal_grade", "Grade")
    with tabs[2]: breakdown(signals, "market_structure", "Market structure")
    with tabs[3]:
        hourly = resolved.dropna(subset=["signal_time"]).copy()
        if hourly.empty: st.info("No timestamped resolved trades available.")
        else:
            hourly["trading_hour"] = hourly["signal_time"].dt.hour.map(lambda hour: f"{hour:02d}:00")
            breakdown(hourly, "trading_hour", "Trading hour")
    with tabs[4]:
        monthly = resolved.dropna(subset=["signal_time"]).copy()
        if monthly.empty: st.info("No timestamped resolved trades available.")
        else:
            monthly["month"] = monthly["signal_time"].dt.strftime("%Y-%m")
            breakdown(monthly, "month", "Month")
    with tabs[5]:
        if resolved.empty: st.info("No resolved trades available.")
        else:
            dd = resolved.sort_values("signal_time").copy()
            dd["equity"] = dd["r_result"].cumsum()
            dd["drawdown"] = dd["equity"] - dd["equity"].cummax().clip(lower=0)
            st.metric("Maximum Drawdown", f"{dd['drawdown'].min():.2f}R")
            st.area_chart(dd.reset_index(drop=True)[["drawdown"]], height=300)

elif page == "Strategies":
    st.subheader("Strategy and Rule Performance")
    s1, s2 = st.tabs(["Strategy Results", "Confirmation Rules"])
    with s1:
        group = "strategy_name" if "strategy_name" in signals.columns else "setup_family"
        breakdown(signals, group, "Strategy")
    with s2:
        records = []
        for _, row in resolved.iterrows():
            for rule, result in parse_confirmations(row.get("confirmation_details")):
                records.append({"rule": rule, "result": result, "outcome": row["outcome_clean"], "r_result": row["r_result"]})
        rules = pd.DataFrame(records)
        if rules.empty:
            st.info("No parseable confirmation details are stored yet.")
        else:
            rules["win"] = rules["outcome"].eq("WIN").astype(int)
            summary = rules.groupby(["rule", "result"]).agg(trades=("outcome", "size"), wins=("win", "sum"), net_r=("r_result", "sum")).reset_index()
            summary["win_rate"] = (summary["wins"] / summary["trades"] * 100).round(1)
            st.dataframe(summary.sort_values(["net_r", "trades"], ascending=False), width="stretch", hide_index=True, height=430)
            st.caption("Use larger samples before changing production rules. This view is observational only.")

elif page == "Journal":
    st.subheader("Trade Journal")
    f1, f2, f3 = st.columns(3)
    asset_options = ["All"] + sorted(series(signals, "asset_name").dropna().astype(str).unique().tolist())
    outcome_options = ["All"] + sorted(series(signals, "outcome_clean").dropna().astype(str).unique().tolist())
    selected_asset = f1.selectbox("Asset", asset_options)
    selected_outcome = f2.selectbox("Outcome", outcome_options)
    search = f3.text_input("Search")
    journal = signals.copy()
    if selected_asset != "All": journal = journal[series(journal, "asset_name").astype(str).eq(selected_asset)]
    if selected_outcome != "All": journal = journal[journal["outcome_clean"].eq(selected_outcome)]
    if search:
        journal = journal[journal.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False)).any(axis=1)]
    display_table(journal, ["signal_timestamp", "asset_name", "strategy_name", "setup_family", "direction", "entry_price", "stop_loss", "take_profit", "signal_grade", "status", "outcome"], 380)
    with st.expander("Review trade details", expanded=False):
        for idx, row in journal.head(20).iterrows(): trade_expander(row, f"journal-{idx}")

elif page == "System Health":
    if event_age_minutes is None:
        age_label = "Unknown"
    elif event_age_minutes < 60:
        age_label = f"{event_age_minutes:.0f} min"
    elif event_age_minutes < 1440:
        age_label = f"{event_age_minutes / 60:.1f} hr"
    else:
        age_label = f"{event_age_minutes / 1440:.1f} days"
    h1, h2, h3, h4 = st.columns(4)
    h1.metric("Database", "Connected")
    h2.metric("Last Stored Event", newest_event_et.strftime("%b %d · %I:%M %p") if pd.notna(newest_event_et) else "Unknown")
    h3.metric("Event Age", age_label)
    h4.metric("Telegram", "Isolated")
    if not data_is_fresh:
        st.warning("Stored engine data is stale. Confirm the scanner service is running before relying on this dashboard.")
    st.caption("Dashboard access is read-only. Telegram delivery and production strategy rules remain isolated from this interface.")
    st.subheader("Recent Engine Records")
    records = signals.head(30).rename(columns={
        "signal_timestamp": "Time", "signal_id": "Signal ID", "asset_name": "Asset",
        "strategy_name": "Strategy", "confirmation_score": "Score", "signal_grade": "Grade",
        "status": "Status", "outcome": "Outcome",
    })
    display_table(records, ["Time", "Signal ID", "Asset", "Strategy", "Score", "Grade", "Status", "Outcome"], 400)

else:
    st.subheader("Dashboard Settings")
    st.caption("Simulation controls affect dashboard estimates only; they do not alter production risk or broker balances.")
    c1, c2 = st.columns(2)
    with c1:
        starting_balance = st.number_input("Starting balance ($)", min_value=100.0, value=float(os.getenv("ACCOUNT_STARTING_BALANCE", "10000")), step=500.0)
        risk_percent = st.number_input("Risk per trade (%)", min_value=.05, max_value=5.0, value=float(os.getenv("ACCOUNT_RISK_PERCENT", ".5")), step=.05)
    with c2:
        profit_target = st.number_input("Profit target (%)", min_value=1.0, value=float(os.getenv("ACCOUNT_PROFIT_TARGET_PERCENT", "10")), step=1.0)
        daily_limit = st.number_input("Daily loss limit (%)", min_value=.5, value=float(os.getenv("ACCOUNT_DAILY_LOSS_LIMIT_PERCENT", "5")), step=.5)
    risk_dollars = starting_balance * risk_percent / 100
    balance = starting_balance + net_r * risk_dollars
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Estimated Balance", f"${balance:,.2f}")
    m2.metric("Risk / Trade", f"${risk_dollars:,.2f}")
    m3.metric("Target", f"${starting_balance * profit_target / 100:,.2f}")
    m4.metric("Daily Limit", f"-${starting_balance * daily_limit / 100:,.2f}")
    st.warning("Production strategy, market, alert, and execution settings remain intentionally read-only here.")
