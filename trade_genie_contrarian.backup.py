#!/usr/bin/env python3
"""
Trade Genie Contrarian Reversal Bot

Core strategy:
- Bearish overextension/reversal -> BUY
- Bullish overextension/reversal -> SELL
- Minimum 3 of 5 confirmations
- No single confirmation is mandatory
- Closed-candle-only analysis
- Paper forward testing, CSV journaling, Telegram alerts
- One pending signal per market
- Daily loss and signal limits
- Trading-session and economic-news blackout filters
- Historical backtest mode
- Separate Gold and NASDAQ parameters

Usage:
    python3 trade_genie_contrarian.py
    python3 trade_genie_contrarian.py --once
    python3 trade_genie_contrarian.py --backtest
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, time as clock_time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf
import sqlite3
from dotenv import load_dotenv


# ============================================================
# CENTRAL CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
EASTERN = ZoneInfo("America/New_York")

SYMBOLS = {
    "USDJPY=X": "USD/JPY",
    "EURUSD=X": "EUR/USD",
    "GBPUSD=X": "GBP/USD",
    "GC=F": "Gold",
    "^NDX": "NASDAQ-100",
}

CHART_SYMBOLS = {
    "USDJPY=X": "OANDA:USDJPY",
    "EURUSD=X": "OANDA:EURUSD",
    "GBPUSD=X": "OANDA:GBPUSD",
    "GC=F": "OANDA:XAUUSD",
    "^NDX": "NASDAQ:NDX",
}

# Strategy settings
MIN_CONFIRMATIONS = 3
REWARD_RISK_RATIO = 2.5
RSI_PERIOD = 14
FAST_EMA_PERIOD = 50
SLOW_EMA_PERIOD = 200
ATR_PERIOD = 14
SWING_WINDOW = 2
MIN_EMA_SPREAD_ATR = 0.15
MAX_HOLD_HOURS = 72

# Bot controls
SCAN_INTERVAL_SECONDS = 60
MAX_SIGNALS_PER_DAY = 5
DAILY_LOSS_LIMIT = 2
ONE_PENDING_SIGNAL_PER_MARKET = True
CLOSED_CANDLES_ONLY = True

# Filters
TRADING_SESSION_FILTER_ENABLED = True
NEWS_FILTER_ENABLED = True
NEWS_BLACKOUT_MINUTES_BEFORE = 30
NEWS_BLACKOUT_MINUTES_AFTER = 30

# Backtest
BACKTEST_LOOKBACK_DAYS = 60
BACKTEST_MAX_BARS = 2500
BACKTEST_OUTPUT_FILE = BASE_DIR / "trade_genie_backtest_results.csv"

# Persistent files
SIGNALS_FILE = BASE_DIR / "trade_genie_contrarian_signals.csv"
STATS_FILE = BASE_DIR / "trade_genie_contrarian_stats.json"
NEWS_FILE = BASE_DIR / "economic_news_blackouts.csv"
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DATABASE_FILE = DATA_DIR / "trade_genie.db"
SIGNAL_COLUMNS = [
    "signal_id",
    "signal_timestamp",
    "asset",
    "asset_name",
    "direction",
    "entry_price",
    "entry_rsi",
    "stop_loss",
    "take_profit",
    "risk_distance",
    "reward_risk",
    "confirmation_score",
    "signal_grade",
    "confirmation_details",
    "market_structure",
    "support_resistance",
    "expiry_timestamp",
    "status",
    "exit_price",
    "outcome",
    "resolved_timestamp",
]


@dataclass(frozen=True)
class MarketProfile:
    support_resistance_atr_distance: float
    stop_atr_buffer: float
    rsi_oversold: float
    rsi_overbought: float
    session_start: clock_time
    session_end: clock_time
    allowed_weekdays: tuple[int, ...] = (0, 1, 2, 3, 4)


# Separate profiles for FX, Gold, and NASDAQ.
MARKET_PROFILES = {
    "USDJPY=X": MarketProfile(
        support_resistance_atr_distance=1.35,
        stop_atr_buffer=0.25,
        rsi_oversold=38.0,
        rsi_overbought=62.0,
        session_start=clock_time(3, 0),
        session_end=clock_time(17, 0),
    ),
    "EURUSD=X": MarketProfile(
        support_resistance_atr_distance=1.35,
        stop_atr_buffer=0.25,
        rsi_oversold=38.0,
        rsi_overbought=62.0,
        session_start=clock_time(3, 0),
        session_end=clock_time(17, 0),
    ),
    "GBPUSD=X": MarketProfile(
        support_resistance_atr_distance=1.50,
        stop_atr_buffer=0.30,
        rsi_oversold=37.0,
        rsi_overbought=63.0,
        session_start=clock_time(3, 0),
        session_end=clock_time(17, 0),
    ),
    "GC=F": MarketProfile(
        support_resistance_atr_distance=1.85,
        stop_atr_buffer=0.40,
        rsi_oversold=35.0,
        rsi_overbought=65.0,
        session_start=clock_time(6, 0),
        session_end=clock_time(17, 0),
    ),
    "^NDX": MarketProfile(
        support_resistance_atr_distance=2.00,
        stop_atr_buffer=0.50,
        rsi_oversold=35.0,
        rsi_overbought=65.0,
        session_start=clock_time(9, 30),
        session_end=clock_time(16, 0),
    ),
}


# ============================================================
# ENVIRONMENT / TELEGRAM
# ============================================================

load_dotenv()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


def send_telegram_message(
    message: str,
    button_text: str | None = None,
    button_url: str | None = None,
) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram not configured. Signal saved locally only.")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload: dict[str, Any] = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    if button_text and button_url:
        payload["reply_markup"] = {
            "inline_keyboard": [[{"text": button_text, "url": button_url}]]
        }

    try:
        response = requests.post(url, json=payload, timeout=20)
        response.raise_for_status()
        return True
    except requests.RequestException as error:
        print(f"Telegram error: {error}")
        return False


# ============================================================
# STATS / JOURNAL
# ============================================================

def default_stats() -> dict[str, Any]:
    return {
        "total_cycles": 0,
        "total_scans": 0,
        "total_signals": 0,
        "total_resolved": 0,
        "wins": 0,
        "losses": 0,
        "expired": 0,
        "scans_by_symbol": {},
        "signals_by_symbol": {},
    }


def load_stats() -> dict[str, Any]:
    if not STATS_FILE.exists():
        return default_stats()

    try:
        with STATS_FILE.open("r", encoding="utf-8") as file:
            saved = json.load(file)
        loaded = default_stats()
        loaded.update(saved)
        return loaded
    except (json.JSONDecodeError, OSError) as error:
        print(f"Could not read stats file: {error}")
        return default_stats()


def save_stats(stats_data: dict[str, Any]) -> None:
    try:
        with STATS_FILE.open("w", encoding="utf-8") as file:
            json.dump(stats_data, file, indent=4)
    except OSError as error:
        print(f"Could not save stats: {error}")


stats = load_stats()


def count_scan(symbol: str) -> None:
    stats["total_scans"] += 1
    symbol_scans = stats["scans_by_symbol"]
    symbol_scans[symbol] = symbol_scans.get(symbol, 0) + 1
    save_stats(stats)


def count_signal(symbol: str) -> None:
    stats["total_signals"] += 1
    symbol_signals = stats["signals_by_symbol"]
    symbol_signals[symbol] = symbol_signals.get(symbol, 0) + 1
    save_stats(stats)


def load_signal_log() -> pd.DataFrame:
    if not SIGNALS_FILE.exists():
        return pd.DataFrame(columns=SIGNAL_COLUMNS)

    try:
        signal_log = pd.read_csv(SIGNALS_FILE)
    except (pd.errors.EmptyDataError, OSError) as error:
        print(f"Could not read signal journal: {error}")
        return pd.DataFrame(columns=SIGNAL_COLUMNS)

    for column in SIGNAL_COLUMNS:
        if column not in signal_log.columns:
            signal_log[column] = None

    return signal_log[SIGNAL_COLUMNS]

  def save_signal_log(signal_log: pd.DataFrame) -> None:
    try:
        signal_log.to_csv(SIGNALS_FILE, index=False)

        if signal_log.empty:
            print("Signal journal is empty. Database overwrite skipped.")
            return

        with sqlite3.connect(DATABASE_FILE) as connection:
            signal_log.to_sql(
                "signals",
                connection,
                if_exists="replace",
                index=False,
            )

    except (OSError, sqlite3.Error, ValueError) as error:
        print(f"Could not save signal journal: {error}")

        


def completed_trade_count(signal_log: pd.DataFrame) -> int:
    if signal_log.empty:
        return 0
    outcomes = signal_log["outcome"].astype(str).str.upper()
    return int(outcomes.isin(["WIN", "LOSS"]).sum())


def print_stats() -> None:
    complete = stats["wins"] + stats["losses"]
    win_rate = (stats["wins"] / complete * 100) if complete else 0.0

    print()
    print("=" * 68)
    print("TRADE GENIE CONTRARIAN + 2.5R STATS")
    print("=" * 68)
    print(f"Full scan cycles:   {stats['total_cycles']}")
    print(f"Market scans:       {stats['total_scans']}")
    print(f"Signals sent:       {stats['total_signals']}")
    print(f"Resolved signals:   {stats['total_resolved']}")
    print(f"Wins:               {stats['wins']}")
    print(f"Losses:             {stats['losses']}")
    print(f"Expired:            {stats['expired']}")
    print(f"Win rate:           {win_rate:.2f}%")
    print()

    for symbol, asset_name in SYMBOLS.items():
        scans = stats["scans_by_symbol"].get(symbol, 0)
        signals = stats["signals_by_symbol"].get(symbol, 0)
        print(f"{asset_name:<12} Scans: {scans:<6} Signals: {signals}")

    print("=" * 68)
    print()


# ============================================================
# MARKET DATA / INDICATORS
# ============================================================

def clean_downloaded_data(data: pd.DataFrame) -> pd.DataFrame:
    if data.empty:
        return data

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    required = ["Open", "High", "Low", "Close"]
    missing = [column for column in required if column not in data.columns]
    if missing:
        raise RuntimeError(f"Missing market columns: {missing}")

    data = data.dropna(subset=required).copy()
    if "Volume" not in data.columns:
        data["Volume"] = 0.0

    if getattr(data.index, "tz", None) is not None:
        data.index = data.index.tz_convert(None)

    return data


def download_market_data(
    symbol: str,
    interval: str,
    period: str,
    quiet: bool = False,
) -> pd.DataFrame:
    if not quiet:
        print(f"Downloading {symbol} | interval={interval} | period={period}")

    data = yf.download(
        tickers=symbol,
        interval=interval,
        period=period,
        auto_adjust=False,
        progress=False,
        threads=False,
    )
    data = clean_downloaded_data(data)

    if data.empty:
        raise RuntimeError(f"No {interval} data returned for {symbol}")

    return data


def calculate_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    average_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    average_loss = loss.ewm(alpha=1 / period, adjust=False).mean()

    relative_strength = average_gain / average_loss.replace(0, pd.NA)
    rsi = 100 - (100 / (1 + relative_strength))
    return rsi.fillna(50.0)


def calculate_atr(data: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    previous_close = data["Close"].shift(1)
    true_range = pd.concat(
        [
            data["High"] - data["Low"],
            (data["High"] - previous_close).abs(),
            (data["Low"] - previous_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return true_range.ewm(alpha=1 / period, adjust=False).mean()


def add_indicators(data: pd.DataFrame) -> pd.DataFrame:
    data = data.copy()
    data[f"EMA_{FAST_EMA_PERIOD}"] = data["Close"].ewm(
        span=FAST_EMA_PERIOD,
        adjust=False,
    ).mean()
    data[f"EMA_{SLOW_EMA_PERIOD}"] = data["Close"].ewm(
        span=SLOW_EMA_PERIOD,
        adjust=False,
    ).mean()
    data[f"RSI_{RSI_PERIOD}"] = calculate_rsi(data["Close"])
    data[f"ATR_{ATR_PERIOD}"] = calculate_atr(data)
    return data.dropna()


def get_market_data(symbol: str, quiet: bool = False) -> dict[str, pd.DataFrame]:
    fifteen_minute = add_indicators(
        download_market_data(symbol, "15m", "60d", quiet=quiet)
    )

    hourly_raw = download_market_data(symbol, "1h", "60d", quiet=quiet)
    hourly = add_indicators(hourly_raw)

    four_hour_raw = (
        hourly_raw.resample("4h")
        .agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )
        .dropna()
    )
    four_hour = add_indicators(four_hour_raw)

    daily = add_indicators(
        download_market_data(symbol, "1d", "2y", quiet=quiet)
    )

    return {
        "15m": fifteen_minute,
        "1h": hourly,
        "4h": four_hour,
        "1d": daily,
    }


# ============================================================
# STRUCTURE / PRICE ACTION
# ============================================================

def completed_candles(data: pd.DataFrame) -> pd.DataFrame:
    if not CLOSED_CANDLES_ONLY or len(data) < 3:
        return data.copy()
    return data.iloc[:-1].copy()


def find_swing_points(
    data: pd.DataFrame,
    window: int = SWING_WINDOW,
) -> tuple[list[tuple[pd.Timestamp, float]], list[tuple[pd.Timestamp, float]]]:
    highs: list[tuple[pd.Timestamp, float]] = []
    lows: list[tuple[pd.Timestamp, float]] = []

    if len(data) < (window * 2) + 1:
        return highs, lows

    high_series = data["High"]
    low_series = data["Low"]

    for position in range(window, len(data) - window):
        high_window = high_series.iloc[position - window : position + window + 1]
        low_window = low_series.iloc[position - window : position + window + 1]

        current_high = float(high_series.iloc[position])
        current_low = float(low_series.iloc[position])
        timestamp = pd.Timestamp(data.index[position])

        if current_high >= float(high_window.max()):
            highs.append((timestamp, current_high))
        if current_low <= float(low_window.min()):
            lows.append((timestamp, current_low))

    return highs, lows


def detect_market_structure(data: pd.DataFrame) -> str:
    highs, lows = find_swing_points(data)
    if len(highs) < 2 or len(lows) < 2:
        return "NEUTRAL"

    previous_high, latest_high = highs[-2][1], highs[-1][1]
    previous_low, latest_low = lows[-2][1], lows[-1][1]

    if latest_high > previous_high and latest_low > previous_low:
        return "BULLISH"
    if latest_high < previous_high and latest_low < previous_low:
        return "BEARISH"
    return "NEUTRAL"


def trend_direction(data: pd.DataFrame) -> str:
    latest = data.iloc[-1]
    fast = float(latest[f"EMA_{FAST_EMA_PERIOD}"])
    slow = float(latest[f"EMA_{SLOW_EMA_PERIOD}"])
    close = float(latest["Close"])
    atr = float(latest[f"ATR_{ATR_PERIOD}"])

    if atr <= 0:
        return "NEUTRAL"

    spread_ok = abs(fast - slow) >= atr * MIN_EMA_SPREAD_ATR
    if close > fast > slow and spread_ok:
        return "BULLISH"
    if close < fast < slow and spread_ok:
        return "BEARISH"
    return "NEUTRAL"


def latest_swing_low(data: pd.DataFrame) -> float:
    _, lows = find_swing_points(data)
    return float(lows[-1][1]) if lows else float(data["Low"].tail(20).min())


def latest_swing_high(data: pd.DataFrame) -> float:
    highs, _ = find_swing_points(data)
    return float(highs[-1][1]) if highs else float(data["High"].tail(20).max())


def nearest_support(data: pd.DataFrame) -> float:
    latest = data.iloc[-1]
    price = float(latest["Close"])
    ema = float(latest[f"EMA_{FAST_EMA_PERIOD}"])
    swing = latest_swing_low(data)
    candidates = [level for level in (swing, ema) if level <= price]
    return max(candidates) if candidates else swing


def nearest_resistance(data: pd.DataFrame) -> float:
    latest = data.iloc[-1]
    price = float(latest["Close"])
    ema = float(latest[f"EMA_{FAST_EMA_PERIOD}"])
    swing = latest_swing_high(data)
    candidates = [level for level in (swing, ema) if level >= price]
    return min(candidates) if candidates else swing


def bullish_reversal_candle(data: pd.DataFrame) -> bool:
    current = data.iloc[-1]
    previous = data.iloc[-2]

    current_open = float(current["Open"])
    current_high = float(current["High"])
    current_low = float(current["Low"])
    current_close = float(current["Close"])
    previous_open = float(previous["Open"])
    previous_high = float(previous["High"])
    previous_close = float(previous["Close"])

    body = max(abs(current_close - current_open), 1e-12)
    lower_wick = min(current_open, current_close) - current_low

    engulfing = (
        current_close > current_open
        and previous_close < previous_open
        and current_open <= previous_close
        and current_close >= previous_open
    )
    rejection = current_close > current_open and lower_wick >= body * 1.5
    break_up = (
        current_close > current_open
        and current_close > previous_high
        and current_high > previous_high
    )
    return bool(engulfing or rejection or break_up)


def bearish_reversal_candle(data: pd.DataFrame) -> bool:
    current = data.iloc[-1]
    previous = data.iloc[-2]

    current_open = float(current["Open"])
    current_high = float(current["High"])
    current_low = float(current["Low"])
    current_close = float(current["Close"])
    previous_open = float(previous["Open"])
    previous_low = float(previous["Low"])
    previous_close = float(previous["Close"])

    body = max(abs(current_close - current_open), 1e-12)
    upper_wick = current_high - max(current_open, current_close)

    engulfing = (
        current_close < current_open
        and previous_close > previous_open
        and current_open >= previous_close
        and current_close <= previous_open
    )
    rejection = current_close < current_open and upper_wick >= body * 1.5
    break_down = (
        current_close < current_open
        and current_close < previous_low
        and current_low < previous_low
    )
    return bool(engulfing or rejection or break_down)


# ============================================================
# FILTERS
# ============================================================

def timestamp_to_eastern(timestamp: pd.Timestamp) -> pd.Timestamp:
    timestamp = pd.Timestamp(timestamp)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC").tz_convert(EASTERN)
    return timestamp.tz_convert(EASTERN)


def session_is_open(symbol: str, timestamp: pd.Timestamp) -> bool:
    if not TRADING_SESSION_FILTER_ENABLED:
        return True

    profile = MARKET_PROFILES[symbol]
    eastern = timestamp_to_eastern(timestamp)

    if eastern.weekday() not in profile.allowed_weekdays:
        return False

    current_time = eastern.time().replace(tzinfo=None)
    return profile.session_start <= current_time <= profile.session_end


def ensure_news_template() -> None:
    if NEWS_FILE.exists():
        return

    template = pd.DataFrame(
        columns=["start", "end", "impact", "symbols", "title"]
    )
    template.to_csv(NEWS_FILE, index=False)


def load_news_blackouts() -> pd.DataFrame:
    ensure_news_template()

    try:
        events = pd.read_csv(NEWS_FILE)
    except (pd.errors.EmptyDataError, OSError):
        return pd.DataFrame(columns=["start", "end", "impact", "symbols", "title"])

    required = {"start", "end", "impact", "symbols", "title"}
    if not required.issubset(events.columns):
        print(
            f"News file ignored. Required columns: {sorted(required)}"
        )
        return pd.DataFrame(columns=sorted(required))

    events = events.copy()
    events["start"] = pd.to_datetime(events["start"], errors="coerce", utc=True)
    events["end"] = pd.to_datetime(events["end"], errors="coerce", utc=True)
    return events.dropna(subset=["start", "end"])


def news_blackout_active(
    symbol: str,
    timestamp: pd.Timestamp,
    events: pd.DataFrame,
) -> tuple[bool, str]:
    if not NEWS_FILTER_ENABLED or events.empty:
        return False, ""

    current = pd.Timestamp(timestamp)
    if current.tzinfo is None:
        current = current.tz_localize("UTC")
    else:
        current = current.tz_convert("UTC")

    before = pd.Timedelta(minutes=NEWS_BLACKOUT_MINUTES_BEFORE)
    after = pd.Timedelta(minutes=NEWS_BLACKOUT_MINUTES_AFTER)

    for _, event in events.iterrows():
        event_symbols = {
            item.strip()
            for item in str(event["symbols"]).split(",")
            if item.strip()
        }
        applies = "*" in event_symbols or symbol in event_symbols
        if not applies:
            continue

        start = pd.Timestamp(event["start"]) - before
        end = pd.Timestamp(event["end"]) + after
        if start <= current <= end:
            title = str(event.get("title", "Economic event"))
            impact = str(event.get("impact", "unknown"))
            return True, f"{title} ({impact})"

    return False, ""


def utc_day_bounds(timestamp: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    current = pd.Timestamp(timestamp)
    if current.tzinfo is None:
        current = current.tz_localize("UTC")
    else:
        current = current.tz_convert("UTC")

    start = current.normalize()
    end = start + pd.Timedelta(days=1)
    return start, end


def daily_limits_allow_signal(
    signal_log: pd.DataFrame,
    timestamp: pd.Timestamp,
) -> tuple[bool, str]:
    if signal_log.empty:
        return True, ""

    start, end = utc_day_bounds(timestamp)
    signal_times = pd.to_datetime(
        signal_log["signal_timestamp"],
        errors="coerce",
        utc=True,
    )
    today_mask = (signal_times >= start) & (signal_times < end)
    today = signal_log.loc[today_mask]

    if len(today) >= MAX_SIGNALS_PER_DAY:
        return False, f"Maximum {MAX_SIGNALS_PER_DAY} signals reached today"

    today_losses = (
        today["outcome"].astype(str).str.upper() == "LOSS"
    ).sum()
    if int(today_losses) >= DAILY_LOSS_LIMIT:
        return False, f"Daily loss limit of {DAILY_LOSS_LIMIT} reached"

    return True, ""


def pending_signal_exists(signal_log: pd.DataFrame, symbol: str) -> bool:
    if not ONE_PENDING_SIGNAL_PER_MARKET or signal_log.empty:
        return False

    return bool(
        (
            (signal_log["asset"].astype(str) == symbol)
            & (signal_log["status"].astype(str).str.upper() == "PENDING")
        ).any()
    )


# ============================================================
# CONTRARIAN STRATEGY
# ============================================================

def signal_grade(score: int) -> str:
    return {5: "A+", 4: "A", 3: "B"}.get(score, "REJECT")


def analyze_market(
    symbol: str,
    market_data: dict[str, pd.DataFrame],
) -> dict[str, Any]:
    profile = MARKET_PROFILES[symbol]

    fifteen = completed_candles(market_data["15m"])
    hourly = completed_candles(market_data["1h"])
    four_hour = completed_candles(market_data["4h"])
    daily = completed_candles(market_data["1d"])

    if len(fifteen) < SLOW_EMA_PERIOD:
        raise RuntimeError(
            f"Not enough completed 15-minute candles for {symbol}: "
            f"{len(fifteen)}/{SLOW_EMA_PERIOD}"
        )

    latest = fifteen.iloc[-1]
    previous = fifteen.iloc[-2]

    latest_price = float(latest["Close"])
    latest_rsi = float(latest[f"RSI_{RSI_PERIOD}"])
    previous_rsi = float(previous[f"RSI_{RSI_PERIOD}"])
    atr = float(latest[f"ATR_{ATR_PERIOD}"])

    structure = detect_market_structure(fifteen)
    support = nearest_support(fifteen)
    resistance = nearest_resistance(fifteen)

    timeframe_trends = {
        "1D": trend_direction(daily),
        "4H": trend_direction(four_hour),
        "1H": trend_direction(hourly),
    }
    bullish_votes = sum(
        trend == "BULLISH" for trend in timeframe_trends.values()
    )
    bearish_votes = sum(
        trend == "BEARISH" for trend in timeframe_trends.values()
    )

    near_support = (
        0 <= latest_price - support
        <= atr * profile.support_resistance_atr_distance
    )
    near_resistance = (
        0 <= resistance - latest_price
        <= atr * profile.support_resistance_atr_distance
    )

    # Reversal requirement: RSI must be extreme and beginning to turn.
    oversold_turning_up = (
        latest_rsi <= profile.rsi_oversold
        and latest_rsi > previous_rsi
    )
    overbought_turning_down = (
        latest_rsi >= profile.rsi_overbought
        and latest_rsi < previous_rsi
    )

    # BEARISH OVEREXTENSION / REVERSAL -> BUY
    buy_confirmations = {
        "Bearish structure / downside extension": structure == "BEARISH",
        "RSI oversold and turning upward": oversold_turning_up,
        "Price near support": near_support,
        "Higher-timeframe bearish extension": bearish_votes >= 2,
        "Bullish reversal candle": bullish_reversal_candle(fifteen),
    }

    # BULLISH OVEREXTENSION / REVERSAL -> SELL
    sell_confirmations = {
        "Bullish structure / upside extension": structure == "BULLISH",
        "RSI overbought and turning downward": overbought_turning_down,
        "Price near resistance": near_resistance,
        "Higher-timeframe bullish extension": bullish_votes >= 2,
        "Bearish reversal candle": bearish_reversal_candle(fifteen),
    }

    buy_score = int(sum(buy_confirmations.values()))
    sell_score = int(sum(sell_confirmations.values()))

    direction = "NO TRADE"
    confirmations: dict[str, bool]
    score: int
    zone_level: float
    stop_loss = 0.0
    take_profit = 0.0
    risk_distance = 0.0

    # Score-only model: no individual confirmation is mandatory.
    if buy_score >= MIN_CONFIRMATIONS and buy_score > sell_score:
        direction = "BUY"
        confirmations = buy_confirmations
        score = buy_score
        zone_level = support

        stop_anchor = min(latest_swing_low(fifteen), support)
        stop_loss = stop_anchor - atr * profile.stop_atr_buffer
        risk_distance = latest_price - stop_loss
        take_profit = latest_price + risk_distance * REWARD_RISK_RATIO

    elif sell_score >= MIN_CONFIRMATIONS and sell_score > buy_score:
        direction = "SELL"
        confirmations = sell_confirmations
        score = sell_score
        zone_level = resistance

        stop_anchor = max(latest_swing_high(fifteen), resistance)
        stop_loss = stop_anchor + atr * profile.stop_atr_buffer
        risk_distance = stop_loss - latest_price
        take_profit = latest_price - risk_distance * REWARD_RISK_RATIO

    else:
        if buy_score >= sell_score:
            confirmations = buy_confirmations
            score = buy_score
            zone_level = support
        else:
            confirmations = sell_confirmations
            score = sell_score
            zone_level = resistance

    valid_risk = (
        direction == "NO TRADE"
        or (
            risk_distance > 0
            and stop_loss > 0
            and take_profit > 0
        )
    )
    if not valid_risk:
        direction = "NO TRADE"

    return {
        "symbol": symbol,
        "asset_name": SYMBOLS[symbol],
        "timestamp": pd.Timestamp(fifteen.index[-1]),
        "entry_price": latest_price,
        "entry_rsi": latest_rsi,
        "atr": atr,
        "structure": structure,
        "timeframe_trends": timeframe_trends,
        "support": support,
        "resistance": resistance,
        "zone_level": zone_level,
        "confirmations": confirmations,
        "score": score,
        "grade": signal_grade(score),
        "direction": direction,
        "stop_loss": stop_loss,
        "take_profit": take_profit,
        "risk_distance": risk_distance,
        "reward_risk": REWARD_RISK_RATIO,
        "qualified": direction in {"BUY", "SELL"},
    }


# ============================================================
# SIGNAL CREATION
# ============================================================

def create_signal_if_qualified(
    setup: dict[str, Any],
    signal_log: pd.DataFrame,
    news_events: pd.DataFrame,
) -> pd.DataFrame:
    symbol = setup["symbol"]
    timestamp = pd.Timestamp(setup["timestamp"])
    confirmations = setup["confirmations"]
    score = int(setup["score"])
    direction = setup["direction"]

    count_scan(symbol)

    print()
    print(
        f"[{symbol}] Decision: {direction} | "
        f"Structure={setup['structure']} | "
        f"RSI={setup['entry_rsi']:.2f} | "
        f"Score={score}/5 | Grade={setup['grade']}"
    )
    print(
        f"    MTF: {setup['timeframe_trends']} | "
        f"Support={setup['support']:.5f} | "
        f"Resistance={setup['resistance']:.5f}"
    )

    for name, passed in confirmations.items():
        print(f"    {name}: {'PASS' if passed else 'FAIL'}")

    if not setup["qualified"]:
        failed = [name for name, passed in confirmations.items() if not passed]
        print(
            f"[{symbol}] No signal. Needs {MIN_CONFIRMATIONS}/5. "
            f"No confirmation is individually mandatory. "
            f"Failed: {', '.join(failed)}"
        )
        return signal_log

    if not session_is_open(symbol, timestamp):
        print(f"[{symbol}] Signal blocked: outside configured session.")
        return signal_log

    blackout, reason = news_blackout_active(symbol, timestamp, news_events)
    if blackout:
        print(f"[{symbol}] Signal blocked by news filter: {reason}")
        return signal_log

    limits_ok, limit_reason = daily_limits_allow_signal(signal_log, timestamp)
    if not limits_ok:
        print(f"[{symbol}] Signal blocked: {limit_reason}")
        return signal_log

    if pending_signal_exists(signal_log, symbol):
        print(f"[{symbol}] Signal already pending. Duplicate skipped.")
        return signal_log

    signal_id = f"{symbol}_{direction}_{timestamp:%Y%m%d_%H%M%S}"
    existing_ids = signal_log["signal_id"].astype(str).tolist()
    if signal_id in existing_ids:
        print(f"[{symbol}] Closed candle already evaluated: {timestamp}")
        return signal_log

    expiry = timestamp + pd.Timedelta(hours=MAX_HOLD_HOURS)
    details = " | ".join(
        f"{name}: {'PASS' if passed else 'FAIL'}"
        for name, passed in confirmations.items()
    )

    new_signal = {
        "signal_id": signal_id,
        "signal_timestamp": timestamp,
        "asset": symbol,
        "asset_name": SYMBOLS[symbol],
        "direction": direction,
        "entry_price": setup["entry_price"],
        "entry_rsi": setup["entry_rsi"],
        "stop_loss": setup["stop_loss"],
        "take_profit": setup["take_profit"],
        "risk_distance": setup["risk_distance"],
        "reward_risk": setup["reward_risk"],
        "confirmation_score": score,
        "signal_grade": setup["grade"],
        "confirmation_details": details,
        "market_structure": setup["structure"],
        "support_resistance": setup["zone_level"],
        "expiry_timestamp": expiry,
        "status": "PENDING",
        "exit_price": None,
        "outcome": None,
        "resolved_timestamp": None,
    }

    signal_log = pd.concat(
        [signal_log, pd.DataFrame([new_signal])],
        ignore_index=True,
    )
    save_signal_log(signal_log)
    count_signal(symbol)

    eastern_timestamp = timestamp_to_eastern(timestamp)
    formatted_time = eastern_timestamp.strftime("%Y-%m-%d %I:%M:%S %p %Z")
    direction_icon = "📈" if direction == "BUY" else "📉"
    chart_symbol = CHART_SYMBOLS.get(symbol, symbol)
    chart_url = (
        "https://www.tradingview.com/chart/"
        f"?symbol={chart_symbol.replace(':', '%3A')}"
    )

    message = (
        "🧞‍♂️ <b>TRADE GENIE CONTRARIAN SIGNAL</b>\n\n"
        f"📊 <b>Asset:</b> {SYMBOLS[symbol]}\n"
        "⏱ <b>Entry timeframe:</b> M15 closed candle\n"
        f"🕒 <b>Signal time:</b> {formatted_time}\n\n"
        f"{direction_icon} <b>Direction:</b> {direction}\n"
        f"🎯 <b>Entry:</b> {setup['entry_price']:.5f}\n"
        f"🛑 <b>Stop:</b> {setup['stop_loss']:.5f}\n"
        f"✅ <b>Target:</b> {setup['take_profit']:.5f}\n"
        f"⚖️ <b>Reward/Risk:</b> 1:{REWARD_RISK_RATIO:.1f}\n\n"
        f"<b>Signal grade:</b> {setup['grade']}\n"
        f"<b>Score:</b> {score}/5\n"
        f"<b>Structure:</b> {setup['structure']}\n\n"
        "<i>Contrarian rule: bearish reversal buys; "
        "bullish reversal sells.</i>\n"
        "<i>Paper forward test only. No real trade was placed.</i>"
    )

    send_telegram_message(
        message,
        button_text=f"OPEN {direction} CHART",
        button_url=chart_url,
    )

    print(f"[{symbol}] SIGNAL SENT: {signal_id}")
    return signal_log


# ============================================================
# AUTOMATIC WIN / LOSS RESOLUTION
# ============================================================

def resolve_pending_signals(
    symbol: str,
    fifteen_minute_data: pd.DataFrame,
    signal_log: pd.DataFrame,
) -> pd.DataFrame:
    if signal_log.empty:
        return signal_log

    completed_data = completed_candles(fifteen_minute_data)
    pending_mask = (
        (signal_log["status"].astype(str).str.upper() == "PENDING")
        & (signal_log["asset"].astype(str) == symbol)
    )
    pending_indices = signal_log.index[pending_mask].tolist()
    if not pending_indices:
        return signal_log

    latest_timestamp = pd.Timestamp(completed_data.index[-1])
    latest_price = float(completed_data.iloc[-1]["Close"])
    changed = False

    for index in pending_indices:
        signal_timestamp = pd.Timestamp(
            signal_log.at[index, "signal_timestamp"]
        )
        expiry_timestamp = pd.Timestamp(
            signal_log.at[index, "expiry_timestamp"]
        )
        direction = str(signal_log.at[index, "direction"]).upper()
        stop_loss = float(signal_log.at[index, "stop_loss"])
        take_profit = float(signal_log.at[index, "take_profit"])

        future = completed_data[completed_data.index > signal_timestamp]

        outcome: str | None = None
        exit_price: float | None = None
        resolved_timestamp: pd.Timestamp | None = None

        for candle_timestamp, candle in future.iterrows():
            candle_high = float(candle["High"])
            candle_low = float(candle["Low"])

            if direction == "BUY":
                stop_hit = candle_low <= stop_loss
                target_hit = candle_high >= take_profit
            else:
                stop_hit = candle_high >= stop_loss
                target_hit = candle_low <= take_profit

            # Conservative assumption: if both occur in one bar, stop first.
            if stop_hit:
                outcome = "LOSS"
                exit_price = stop_loss
                resolved_timestamp = pd.Timestamp(candle_timestamp)
                break

            if target_hit:
                outcome = "WIN"
                exit_price = take_profit
                resolved_timestamp = pd.Timestamp(candle_timestamp)
                break

        if outcome is None and latest_timestamp >= expiry_timestamp:
            outcome = "EXPIRED"
            exit_price = latest_price
            resolved_timestamp = latest_timestamp

        if outcome is None:
            continue

        signal_log.at[index, "status"] = "RESOLVED"
        signal_log.at[index, "exit_price"] = exit_price
        signal_log.at[index, "outcome"] = outcome
        signal_log.at[index, "resolved_timestamp"] = resolved_timestamp

        stats["total_resolved"] += 1
        if outcome == "WIN":
            stats["wins"] += 1
        elif outcome == "LOSS":
            stats["losses"] += 1
        elif outcome == "EXPIRED":
            stats["expired"] += 1

        changed = True
        print(
            f"[{symbol}] Signal resolved: {outcome} | "
            f"Exit={exit_price:.5f} | Time={resolved_timestamp}"
        )

    if changed:
        save_signal_log(signal_log)
        save_stats(stats)

    return signal_log


# ============================================================
# BACKTEST MODE
# ============================================================

def slice_market_data_for_timestamp(
    market_data: dict[str, pd.DataFrame],
    timestamp: pd.Timestamp,
) -> dict[str, pd.DataFrame]:
    result: dict[str, pd.DataFrame] = {}
    for timeframe, frame in market_data.items():
        result[timeframe] = frame[frame.index <= timestamp].copy()
    return result


def resolve_historical_trade(
    direction: str,
    entry_timestamp: pd.Timestamp,
    stop_loss: float,
    take_profit: float,
    future_data: pd.DataFrame,
) -> tuple[str, float, pd.Timestamp]:
    expiry = entry_timestamp + pd.Timedelta(hours=MAX_HOLD_HOURS)
    future = future_data[
        (future_data.index > entry_timestamp)
        & (future_data.index <= expiry)
    ]

    for timestamp, candle in future.iterrows():
        high = float(candle["High"])
        low = float(candle["Low"])

        if direction == "BUY":
            stop_hit = low <= stop_loss
            target_hit = high >= take_profit
        else:
            stop_hit = high >= stop_loss
            target_hit = low <= take_profit

        if stop_hit:
            return "LOSS", stop_loss, pd.Timestamp(timestamp)
        if target_hit:
            return "WIN", take_profit, pd.Timestamp(timestamp)

    if not future.empty:
        last = future.iloc[-1]
        return "EXPIRED", float(last["Close"]), pd.Timestamp(future.index[-1])

    return "EXPIRED", float("nan"), expiry


def run_backtest() -> None:
    print("Starting historical contrarian backtest...")
    all_results: list[dict[str, Any]] = []

    for symbol, asset_name in SYMBOLS.items():
        print(f"\nBacktesting {asset_name} ({symbol})")
        market_data = get_market_data(symbol, quiet=True)
        fifteen = market_data["15m"]

        start_index = max(SLOW_EMA_PERIOD + 5, len(fifteen) - BACKTEST_MAX_BARS)
        last_signal_timestamp: pd.Timestamp | None = None

        for position in range(start_index, len(fifteen) - 2):
            timestamp = pd.Timestamp(fifteen.index[position])

            # Evaluate once per completed historical candle.
            if last_signal_timestamp is not None and timestamp <= last_signal_timestamp:
                continue

            sliced = slice_market_data_for_timestamp(market_data, timestamp)
            if any(len(frame) < 5 for frame in sliced.values()):
                continue

            try:
                setup = analyze_market(symbol, sliced)
            except (RuntimeError, IndexError, KeyError):
                continue

            if not setup["qualified"]:
                continue
            if not session_is_open(symbol, setup["timestamp"]):
                continue

            outcome, exit_price, resolved_time = resolve_historical_trade(
                direction=setup["direction"],
                entry_timestamp=pd.Timestamp(setup["timestamp"]),
                stop_loss=float(setup["stop_loss"]),
                take_profit=float(setup["take_profit"]),
                future_data=fifteen,
            )

            all_results.append(
                {
                    "asset": symbol,
                    "asset_name": asset_name,
                    "signal_timestamp": setup["timestamp"],
                    "direction": setup["direction"],
                    "entry_price": setup["entry_price"],
                    "stop_loss": setup["stop_loss"],
                    "take_profit": setup["take_profit"],
                    "score": setup["score"],
                    "grade": setup["grade"],
                    "outcome": outcome,
                    "exit_price": exit_price,
                    "resolved_timestamp": resolved_time,
                }
            )
            last_signal_timestamp = pd.Timestamp(setup["timestamp"])

    results = pd.DataFrame(all_results)
    results.to_csv(BACKTEST_OUTPUT_FILE, index=False)

    if results.empty:
        print("\nBacktest complete: no qualifying historical setups.")
        print(f"Results file: {BACKTEST_OUTPUT_FILE}")
        return

    wins = int((results["outcome"] == "WIN").sum())
    losses = int((results["outcome"] == "LOSS").sum())
    expired = int((results["outcome"] == "EXPIRED").sum())
    completed = wins + losses
    win_rate = (wins / completed * 100) if completed else 0.0

    print("\n" + "=" * 68)
    print("BACKTEST RESULTS")
    print("=" * 68)
    print(f"Signals:   {len(results)}")
    print(f"Wins:      {wins}")
    print(f"Losses:    {losses}")
    print(f"Expired:   {expired}")
    print(f"Win rate:  {win_rate:.2f}%")
    print(f"Saved to:  {BACKTEST_OUTPUT_FILE}")
    print("=" * 68)


# ============================================================
# STARTUP / MAIN LOOP
# ============================================================

def print_startup_message() -> None:
    telegram_status = (
        "CONNECTED"
        if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
        else "NOT CONFIGURED"
    )

    print()
    print("=" * 68)
    print("TRADE GENIE CONTRARIAN REVERSAL BOT")
    print("=" * 68)
    print("BEARISH overextension/reversal -> BUY")
    print("BULLISH overextension/reversal -> SELL")
    print(f"Qualification: {MIN_CONFIRMATIONS}/5, score only")
    print("No individual confirmation is mandatory")
    print(f"Reward/Risk target: 1:{REWARD_RISK_RATIO:.1f}")
    print(f"Daily loss limit: {DAILY_LOSS_LIMIT}")
    print(f"Maximum signals/day: {MAX_SIGNALS_PER_DAY}")
    print(f"Closed candles only: {CLOSED_CANDLES_ONLY}")
    print(f"One pending signal/market: {ONE_PENDING_SIGNAL_PER_MARKET}")
    print(f"Trading-session filter: {TRADING_SESSION_FILTER_ENABLED}")
    print(f"News blackout filter: {NEWS_FILTER_ENABLED}")
    print(f"Scan interval: {SCAN_INTERVAL_SECONDS} seconds")
    print(f"Telegram: {telegram_status}")
    print("Markets: " + ", ".join(SYMBOLS.values()))
    print("=" * 68)
    print()


def run_scan_cycle(
    signal_log: pd.DataFrame,
    news_events: pd.DataFrame,
) -> pd.DataFrame:
    stats["total_cycles"] += 1
    save_stats(stats)

    print()
    print(
        f"Starting scan cycle #{stats['total_cycles']} at "
        f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    )
    print("-" * 68)

    for symbol, asset_name in SYMBOLS.items():
        print(f"\nScanning {asset_name} ({symbol})")

        try:
            market_data = get_market_data(symbol)

            signal_log = resolve_pending_signals(
                symbol=symbol,
                fifteen_minute_data=market_data["15m"],
                signal_log=signal_log,
            )

            setup = analyze_market(symbol, market_data)
            signal_log = create_signal_if_qualified(
                setup=setup,
                signal_log=signal_log,
                news_events=news_events,
            )

        except Exception as error:
            print(
                f"[{symbol}] Scan error: "
                f"{type(error).__name__}: {error}"
            )

    pending_count = 0
    resolved_count = 0
    if not signal_log.empty:
        pending_count = int(
            (
                signal_log["status"].astype(str).str.upper()
                == "PENDING"
            ).sum()
        )
        resolved_count = int(
            (
                signal_log["status"].astype(str).str.upper()
                == "RESOLVED"
            ).sum()
        )

    print(
        f"\nScan complete | Pending: {pending_count} | "
        f"Resolved: {resolved_count}"
    )
    print_stats()
    return signal_log


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Trade Genie contrarian reversal paper bot"
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one live scan cycle and exit.",
    )
    parser.add_argument(
        "--backtest",
        action="store_true",
        help="Run historical backtest mode and exit.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.backtest:
        run_backtest()
        return

    print_startup_message()
    ensure_news_template()
    news_events = load_news_blackouts()
    signal_log = load_signal_log()

    send_telegram_message(
        "🧞‍♂️ <b>TRADE GENIE CONTRARIAN BOT</b>\n\n"
        "🟢 <b>STATUS:</b> ONLINE\n"
        "Bearish reversal buys and bullish reversal sells are active."
    )

    while True:
        try:
            signal_log = run_scan_cycle(signal_log, news_events)

            if args.once:
                break

            print(
                f"Waiting approximately {SCAN_INTERVAL_SECONDS} seconds..."
            )
            time.sleep(SCAN_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            print("\nTrade Genie stopped by user.")
            break

        except Exception as error:
            print(
                f"Main loop error: {type(error).__name__}: {error}"
            )
            print("Retrying in 60 seconds...")
            time.sleep(60)


if __name__ == "__main__":
    main()
