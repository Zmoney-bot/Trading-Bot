import html
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import altair as alt
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
    :root {
        --tg-bg:#080b12;
        --tg-card:#0d121c;
        --tg-card-2:#111724;
        --tg-border:rgba(148,163,184,.16);
        --tg-purple:#8b5cf6;
        --tg-purple-2:#6d28d9;
        --tg-muted:#94a3b8;
        --tg-text:#f8fafc;
        --tg-green:#4ade80;
        --tg-blue:#60a5fa;
        --tg-amber:#fbbf24;
    }
    .stApp {
        background:
            radial-gradient(circle at 78% -10%,rgba(109,40,217,.12),transparent 30rem),
            radial-gradient(circle at 5% 0%,rgba(76,29,149,.13),transparent 24rem),
            var(--tg-bg);
    }
    .block-container { max-width:1600px;padding:1.25rem 1.35rem 2rem; }

    /* Existing sidebar: layout and controls intentionally unchanged. */
    [data-testid="stSidebar"] { background:#090f1b;border-right:1px solid rgba(148,163,184,.18); }
    [data-testid="stSidebar"] .block-container { padding-top:1.2rem; }

    .tg-head { display:flex;justify-content:space-between;align-items:center;gap:1rem;margin:0 0 .85rem; }
    .tg-brand { color:var(--tg-text);font-size:1.48rem;font-weight:800;letter-spacing:-.03em; }
    .tg-sub { color:var(--tg-muted);font-size:.78rem;margin-top:.1rem; }
    .tg-badge { display:inline-flex;align-items:center;gap:.48rem;padding:.45rem .75rem;border:1px solid rgba(34,197,94,.30);border-radius:10px;color:#bbf7d0;background:rgba(34,197,94,.08);font-size:.71rem;font-weight:750;white-space:nowrap; }
    .tg-dot { width:8px;height:8px;border-radius:50%;background:#22c55e;box-shadow:0 0 12px #22c55e; }
    .tg-badge-stale { border-color:rgba(245,158,11,.35);color:#fde68a;background:rgba(245,158,11,.08); }
    .tg-dot-stale { background:#f59e0b;box-shadow:0 0 12px #f59e0b; }

    .tg-hero {
        display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:1rem;
        min-height:150px;margin:.2rem 0 1rem;padding:1.4rem 1.55rem;
        border:1px solid rgba(139,92,246,.38);border-radius:14px;
        background:
            radial-gradient(circle at 92% 25%,rgba(99,102,241,.20),transparent 13rem),
            linear-gradient(110deg,rgba(76,29,149,.14),rgba(17,24,39,.78));
        box-shadow:inset 0 1px 0 rgba(255,255,255,.025),0 12px 35px rgba(0,0,0,.18);
    }
    .tg-hero-title { color:var(--tg-text);font-size:1.42rem;font-weight:800;letter-spacing:-.025em; }
    .tg-hero-copy { color:#aeb8c8;font-size:.87rem;margin-top:.45rem;max-width:760px;line-height:1.55; }
    .tg-hero-chip { display:inline-flex;align-items:center;gap:.4rem;margin-top:.9rem;padding:.38rem .7rem;border:1px solid rgba(139,92,246,.38);border-radius:8px;background:rgba(109,40,217,.18);color:#ddd6fe;font-size:.7rem;font-weight:750;letter-spacing:.04em; }
    .tg-genie { font-size:4rem;filter:drop-shadow(0 0 18px rgba(124,58,237,.45));padding:0 1rem; }

    .tg-kpi-grid { display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:.8rem;margin:.15rem 0 1rem; }
    .tg-kpi { min-height:112px;padding:1rem;border:1px solid var(--tg-border);border-radius:13px;background:linear-gradient(145deg,rgba(17,24,39,.94),rgba(10,15,24,.96));box-shadow:inset 0 1px 0 rgba(255,255,255,.025); }
    .tg-kpi-top { display:flex;align-items:center;gap:.7rem;color:#b6c0cf;font-size:.76rem; }
    .tg-kpi-icon { display:grid;place-items:center;width:34px;height:34px;border-radius:50%;border:1px solid currentColor;background:rgba(139,92,246,.08);font-size:.95rem; }
    .tg-kpi-value { margin:.62rem 0 .1rem;color:var(--tg-text);font-size:1.52rem;font-weight:800;line-height:1;letter-spacing:-.035em; }
    .tg-kpi-note { color:var(--tg-muted);font-size:.7rem; }
    .tg-purple { color:#c084fc; }.tg-green { color:var(--tg-green); }.tg-blue { color:var(--tg-blue); }.tg-amber { color:var(--tg-amber); }

    div[data-testid="stVerticalBlockBorderWrapper"] { border-color:var(--tg-border)!important;background:linear-gradient(145deg,rgba(14,20,30,.94),rgba(9,14,22,.94));border-radius:13px!important; }
    div[data-testid="stVerticalBlockBorderWrapper"] h3 { font-size:1rem!important;margin:.1rem 0 .65rem!important; }
    div[data-testid="stMetric"] { min-height:92px;padding:.72rem .85rem;border:1px solid var(--tg-border);border-radius:13px;background:rgba(17,24,39,.86); }
    div[data-testid="stMetricLabel"] { color:var(--tg-muted);font-size:.78rem; }
    div[data-testid="stMetricValue"] { color:var(--tg-text);font-size:1.55rem; }
    div[data-testid="stDataFrame"] { border:1px solid var(--tg-border);border-radius:12px;overflow:hidden; }
    div[data-testid="stExpander"] { border-color:var(--tg-border);background:rgba(17,24,39,.48); }

    .tg-table-wrap { width:100%;overflow-x:auto;border:1px solid rgba(148,163,184,.12);border-radius:10px;background:#0a1019; }
    .tg-table { width:100%;border-collapse:collapse;font-size:.72rem; }
    .tg-table th { padding:.65rem .7rem;color:#7f8b9e;background:#0d141f;text-transform:uppercase;letter-spacing:.055em;font-size:.62rem;text-align:left;border-bottom:1px solid var(--tg-border);white-space:nowrap; }
    .tg-table td { padding:.68rem .7rem;color:#d6deea;border-bottom:1px solid rgba(148,163,184,.09);white-space:nowrap; }
    .tg-table tr:last-child td { border-bottom:0; }
    .tg-table tr:hover td { background:rgba(139,92,246,.055); }
    .tg-empty { display:grid;place-items:center;min-height:215px;color:var(--tg-muted);font-size:.82rem;text-align:center; }

    .tg-system { display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:0;margin:1rem 0;padding:.85rem 1rem;border:1px solid var(--tg-border);border-radius:13px;background:linear-gradient(145deg,rgba(14,20,30,.92),rgba(9,14,22,.94)); }
    .tg-system-item { display:flex;align-items:center;gap:.65rem;padding:.2rem .9rem;border-right:1px solid var(--tg-border); }
    .tg-system-item:last-child { border-right:0; }
    .tg-system-icon { font-size:1.08rem; }.tg-system-label { color:var(--tg-muted);font-size:.67rem; }.tg-system-value { color:#dbe4f0;font-size:.76rem;margin-top:.08rem;white-space:nowrap; }

    h1,h2,h3 { color:#e2e8f0!important;letter-spacing:-.02em; }
    h2 { font-size:1.15rem!important;margin:.4rem 0!important; }
    .stTabs [data-baseweb="tab-list"] { gap:.3rem;border-bottom:1px solid var(--tg-border); }
    .stTabs [data-baseweb="tab"] { height:2.4rem;padding:0 .85rem;border-radius:8px 8px 0 0;background:transparent; }
    .stTabs [aria-selected="true"] { color:#c084fc!important;background:rgba(139,92,246,.08)!important; }
    .stButton button { border:1px solid rgba(139,92,246,.42);background:linear-gradient(135deg,#6d28d9,#4c1d95);color:white;border-radius:9px;font-weight:700; }
    .stButton button:hover { border-color:#a78bfa;color:white; }
    #MainMenu,footer { visibility:hidden; }

    @media(max-width:1100px){.tg-kpi-grid{grid-template-columns:repeat(3,minmax(0,1fr))}.tg-system{grid-template-columns:repeat(2,minmax(0,1fr))}.tg-system-item{border-right:0;border-bottom:1px solid var(--tg-border);padding:.55rem}}
    @media(max-width:800px){.block-container{padding:.8rem}.tg-head{align-items:flex-start}.tg-brand{font-size:1.15rem}.tg-kpi-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.tg-hero{min-height:125px;padding:1rem}.tg-genie{font-size:3rem;padding:0}.tg-system{grid-template-columns:1fr}}
    @media(max-width:520px){.tg-kpi-grid{grid-template-columns:1fr}.tg-hero{grid-template-columns:1fr}.tg-genie{display:none}.tg-badge{font-size:.62rem}}
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


def compact_table(frame: pd.DataFrame, columns: list[tuple[str, str]], rows=7):
    """Render a compact dark table for the overview without changing stored data."""
    chosen = [(source, label) for source, label in columns if source in frame.columns]
    if frame.empty or not chosen:
        st.markdown('<div class="tg-empty">No signals found in this view.</div>', unsafe_allow_html=True)
        return
    view = frame[[source for source, _ in chosen]].head(rows).copy()
    view.columns = [label for _, label in chosen]
    for column in view.columns:
        view[column] = view[column].map(lambda value: "—" if pd.isna(value) or str(value).strip() == "" else str(value))
    table = view.to_html(index=False, classes="tg-table", border=0, escape=True)
    st.markdown(f'<div class="tg-table-wrap">{table}</div>', unsafe_allow_html=True)


def metric_card(icon: str, label: str, value: str, note: str, color: str):
    return f"""
    <div class="tg-kpi">
      <div class="tg-kpi-top"><span class="tg-kpi-icon {color}">{html.escape(icon)}</span><span>{html.escape(label)}</span></div>
      <div class="tg-kpi-value">{html.escape(value)}</div>
      <div class="tg-kpi-note {color}">{html.escape(note)}</div>
    </div>
    """


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
active = signals[signals["status_clean"].isin(["ACTIVE", "OPEN", "PENDING"])]
rejected = signals[signals["status_clean"].isin(["REJECT", "REJECTED", "NO TRADE", "NO_TRADE"]) | signals["outcome_clean"].isin(["REJECT", "REJECTED"])]
watching = signals[signals["status_clean"].isin(["WATCH", "WATCHING", "QUEUED"])]

if page == "Overview":
    hero_title = "Trade Genie is Monitoring" if data_is_fresh else "Trade Genie Needs Attention"
    hero_copy = (
        "The engine data is current. Review the latest setups and performance without changing production rules."
        if data_is_fresh else
        "Stored engine data is stale. The dashboard remains read-only; verify the scanner service before relying on new setups."
    )
    st.markdown(
        f"""
        <section class="tg-hero">
          <div>
            <div class="tg-hero-title">🪄 &nbsp;{hero_title}</div>
            <div class="tg-hero-copy">{hero_copy}</div>
            <div class="tg-hero-chip">◆ READ-ONLY OPERATOR VIEW</div>
          </div>
          <div class="tg-genie" aria-hidden="true">🧞‍♂️</div>
        </section>
        """,
        unsafe_allow_html=True,
    )

    latest = signals.iloc[0]
    latest_asset = str(safe_value(latest, "asset_name", safe_value(latest, "asset", "N/A")))
    latest_stamp = latest.get("signal_time")
    latest_note = latest_stamp.strftime("%b %d · %I:%M %p") if pd.notna(latest_stamp) else "No timestamp"
    pf_display = "∞" if profit_factor == float("inf") else f"{profit_factor:.2f}"
    cards = [
        metric_card("↗", "Total Signals", f"{len(signals):,}", "All time", "tg-purple"),
        metric_card("◎", "Win Rate", f"{win_rate:.1f}%", f"{wins} wins / {losses} losses", "tg-green"),
        metric_card("🏆", "Net R", f"{net_r:+.2f}R", f"{expectancy:+.2f}R expectancy", "tg-blue"),
        metric_card("▥", "Profit Factor", pf_display, "Resolved trades", "tg-amber"),
        metric_card("◷", "Last Signal", latest_asset, latest_note, "tg-purple"),
    ]
    st.markdown(f'<div class="tg-kpi-grid">{"".join(cards)}</div>', unsafe_allow_html=True)

    left, right = st.columns([1, 1.1], gap="medium")
    with left:
        with st.container(border=True):
            st.subheader("☷  Recent Signals")
            compact_table(
                signals,
                [
                    ("asset_name", "Asset"),
                    ("direction", "Side"),
                    ("signal_grade", "Grade"),
                    ("confirmation_score", "Score"),
                    ("status", "Status"),
                    ("outcome", "Result"),
                ],
                rows=7,
            )
    with right:
        with st.container(border=True):
            st.subheader("▥  Performance Overview")
            if resolved.empty:
                st.markdown('<div class="tg-empty">Performance data appears after the first resolved trade.</div>', unsafe_allow_html=True)
            else:
                curve = resolved.sort_values("signal_time").copy().reset_index(drop=True)
                curve["Trade"] = range(1, len(curve) + 1)
                curve["Cumulative R"] = curve["r_result"].cumsum()
                curve = pd.concat([pd.DataFrame({"Trade": [0], "Cumulative R": [0.0]}), curve[["Trade", "Cumulative R"]]], ignore_index=True)
                chart = (
                    alt.Chart(curve)
                    .mark_line(color="#8b5cf6", strokeWidth=2.5, interpolate="monotone")
                    .encode(
                        x=alt.X("Trade:Q", axis=alt.Axis(title=None, grid=False, labelColor="#7f8b9e", tickColor="#263244")),
                        y=alt.Y("Cumulative R:Q", axis=alt.Axis(title="Net R", titleColor="#7f8b9e", labelColor="#7f8b9e", gridColor="#1d2633")),
                        tooltip=[alt.Tooltip("Trade:Q", format=".0f"), alt.Tooltip("Cumulative R:Q", format="+.2f")],
                    )
                    .properties(height=218)
                    .configure_view(strokeOpacity=0)
                    .configure(background="transparent")
                )
                st.altair_chart(chart, width="stretch")

    age_short = "Unknown" if event_age_minutes is None else (f"{event_age_minutes:.0f} min" if event_age_minutes < 60 else f"{event_age_minutes / 60:.1f} hr")
    system_items = [
        ("●", "Bot Status", "Monitoring" if data_is_fresh else "Check Engine", "tg-green" if data_is_fresh else "tg-amber"),
        ("◷", "Market Feed", "Current" if data_is_fresh else "Stale", "tg-blue" if data_is_fresh else "tg-amber"),
        ("◇", "Mode", "Read-only", "tg-purple"),
        ("◴", "Event Age", age_short, "tg-amber"),
        ("▣", "Database", "Connected", "tg-green"),
    ]
    system_html = "".join(
        f'<div class="tg-system-item"><span class="tg-system-icon {color}">{icon}</span><div><div class="tg-system-label">{label}</div><div class="tg-system-value">{value}</div></div></div>'
        for icon, label, value, color in system_items
    )
    st.markdown(f'<div class="tg-system">{system_html}</div>', unsafe_allow_html=True)

    st.subheader("Signal Center")
    tab_active, tab_pending, tab_resolved, tab_rejected = st.tabs([
        f"Active ({len(active)})", f"Watching ({len(watching)})", f"Resolved ({len(resolved)})", f"Rejected ({len(rejected)})"
    ])
    for tab_item, data in [(tab_active, active), (tab_pending, watching), (tab_resolved, resolved), (tab_rejected, rejected)]:
        with tab_item:
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
    with tabs[0]:
        breakdown(signals, "asset_name", "Asset")
    with tabs[1]:
        breakdown(signals, "signal_grade", "Grade")
    with tabs[2]:
        breakdown(signals, "market_structure", "Market structure")
    with tabs[3]:
        hourly = resolved.dropna(subset=["signal_time"]).copy()
        if hourly.empty:
            st.info("No timestamped resolved trades available.")
        else:
            hourly["trading_hour"] = hourly["signal_time"].dt.hour.map(lambda hour: f"{hour:02d}:00")
            breakdown(hourly, "trading_hour", "Trading hour")
    with tabs[4]:
        monthly = resolved.dropna(subset=["signal_time"]).copy()
        if monthly.empty:
            st.info("No timestamped resolved trades available.")
        else:
            monthly["month"] = monthly["signal_time"].dt.strftime("%Y-%m")
            breakdown(monthly, "month", "Month")
    with tabs[5]:
        if resolved.empty:
            st.info("No resolved trades available.")
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
    if selected_asset != "All":
        journal = journal[series(journal, "asset_name").astype(str).eq(selected_asset)]
    if selected_outcome != "All":
        journal = journal[journal["outcome_clean"].eq(selected_outcome)]
    if search:
        journal = journal[journal.astype(str).apply(lambda col: col.str.contains(search, case=False, na=False)).any(axis=1)]
    display_table(journal, ["signal_timestamp", "asset_name", "strategy_name", "setup_family", "direction", "entry_price", "stop_loss", "take_profit", "signal_grade", "status", "outcome"], 380)
    with st.expander("Review trade details", expanded=False):
        for idx, row in journal.head(20).iterrows():
            trade_expander(row, f"journal-{idx}")

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
