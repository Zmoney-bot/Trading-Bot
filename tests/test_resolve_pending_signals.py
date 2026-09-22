"""
Regression tests for the P0 fix in resolve_pending_signals().

Bug (fixed in commit d9e399c on main): the TRADE CLOSED Telegram
notification block inside resolve_pending_signals() referenced undefined
variables (row, asset_name, entry_price). Every time a signal resolved,
that raised NameError, which was silently swallowed by the per-symbol
try/except in run_scan_cycle() -- so save_signal_log() and save_stats(),
both positioned after the broken block, never ran. Resolved signals stayed
correct in memory for the life of the process but were never persisted,
so a process restart reverted any resolved signal back to PENDING.

These tests exercise resolve_pending_signals() directly against temporary,
throwaway SQLite/CSV/stats files -- never the real project database -- and
prove the bug stays fixed:

  1. A PENDING signal that hits its target becomes RESOLVED/WIN.
  2. A PENDING signal that hits its stop becomes RESOLVED/LOSS.
  3. The resolution is persisted to the canonical SQLite store.
  4. Reloading after a simulated process restart returns the resolved
     state, not PENDING (this is the exact failure mode of the original bug).
  5. The CSV backup/export reflects the resolved state too.
  6. Two signals resolving in the same cycle do not corrupt one another
     (the original block also leaked loop variables across iterations;
     this proves both signals end up with their own correct outcome).
  7. A failing/raising Telegram call cannot prevent persistence, because
     resolve_pending_signals() no longer depends on Telegram at all.

Run with:  python3 -m unittest tests/test_resolve_pending_signals.py -v
(run from the repository root, using the project's own virtualenv so
pandas/yfinance/python-dotenv are available -- these tests do not touch
the network; yfinance is only imported by the module under test, never
called).
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path

import pandas as pd

# Import the module under test from the repository root, regardless of
# where these tests are invoked from.
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

# trade_genie_contrarian.py imports yfinance at module level, but nothing
# these tests exercise (resolve_pending_signals, load/save_signal_log)
# ever calls into it -- yfinance is only used by download_market_data(),
# which is never invoked here. If the real package isn't installed in the
# test environment, install a harmless empty stub purely so the import
# succeeds; this changes nothing about the module under test and is never
# used for anything except letting `import trade_genie_contrarian` work.
try:
    import yfinance  # noqa: F401
except ImportError:
    sys.modules["yfinance"] = types.ModuleType("yfinance")

import trade_genie_contrarian as tg  # noqa: E402


UTC = "UTC"


def make_candles(rows: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    """rows: list of (iso_timestamp, open, high, low, close)."""
    index = pd.to_datetime([r[0] for r in rows], utc=True)
    data = {
        "Open": [r[1] for r in rows],
        "High": [r[2] for r in rows],
        "Low": [r[3] for r in rows],
        "Close": [r[4] for r in rows],
    }
    return pd.DataFrame(data, index=index)


def make_pending_signal(
    signal_id: str,
    symbol: str,
    direction: str,
    entry_price: float,
    stop_loss: float,
    take_profit: float,
    signal_timestamp: str,
    expiry_hours: float = 72.0,
) -> dict:
    ts = pd.Timestamp(signal_timestamp, tz=UTC)
    row = {column: None for column in tg.SIGNAL_COLUMNS}
    row.update(
        {
            "signal_id": signal_id,
            "signal_timestamp": ts,
            "asset": symbol,
            "asset_name": symbol,
            "direction": direction,
            "entry_price": entry_price,
            "entry_rsi": 50.0,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "risk_distance": abs(entry_price - stop_loss),
            "reward_risk": 2.5,
            "confirmation_score": 3,
            "signal_grade": "B",
            "confirmation_details": "test fixture",
            "market_structure": "BEARISH",
            "support_resistance": entry_price,
            "expiry_timestamp": ts + pd.Timedelta(hours=expiry_hours),
            "status": "PENDING",
            "exit_price": None,
            "outcome": None,
            "resolved_timestamp": None,
        }
    )
    return row


class ResolvePendingSignalsTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="trade_genie_test_"))

        # Redirect every persistence path to throwaway files for this test
        # only. The real project's data/trade_genie.db,
        # trade_genie_contrarian_signals.csv and
        # trade_genie_contrarian_stats.json are never opened by these tests.
        self._orig_database_file = tg.DATABASE_FILE
        self._orig_signals_file = tg.SIGNALS_FILE
        self._orig_stats_file = tg.STATS_FILE
        self._orig_stats = tg.stats

        tg.DATABASE_FILE = self.tmp_dir / "test_trade_genie.db"
        tg.SIGNALS_FILE = self.tmp_dir / "test_signals.csv"
        tg.STATS_FILE = self.tmp_dir / "test_stats.json"
        tg.stats = tg.default_stats()

    def tearDown(self) -> None:
        tg.DATABASE_FILE = self._orig_database_file
        tg.SIGNALS_FILE = self._orig_signals_file
        tg.STATS_FILE = self._orig_stats_file
        tg.stats = self._orig_stats
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # 1. Target hit -> WIN ----------------------------------------------
    def test_signal_hits_target_becomes_win(self) -> None:
        signal_log = pd.DataFrame(
            [
                make_pending_signal(
                    "TEST_BUY_WIN",
                    "TESTUSD=X",
                    "BUY",
                    entry_price=100.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    signal_timestamp="2026-01-01T00:00:00Z",
                )
            ]
        )
        candles = make_candles(
            [
                ("2026-01-01T00:15:00Z", 100, 105, 99, 104),
                ("2026-01-01T00:30:00Z", 104, 111, 100, 110),  # target hit here
                ("2026-01-01T00:45:00Z", 110, 112, 109, 111),  # trailing "in progress" candle
            ]
        )

        result = tg.resolve_pending_signals("TESTUSD=X", candles, signal_log)

        row = result.iloc[0]
        self.assertEqual(row["status"], "RESOLVED")
        self.assertEqual(row["outcome"], "WIN")
        self.assertAlmostEqual(float(row["exit_price"]), 110.0)

    # 2. Stop hit -> LOSS -------------------------------------------------
    def test_signal_hits_stop_becomes_loss(self) -> None:
        signal_log = pd.DataFrame(
            [
                make_pending_signal(
                    "TEST_BUY_LOSS",
                    "TESTUSD=X",
                    "BUY",
                    entry_price=100.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    signal_timestamp="2026-01-01T00:00:00Z",
                )
            ]
        )
        candles = make_candles(
            [
                ("2026-01-01T00:15:00Z", 100, 102, 96, 101),
                ("2026-01-01T00:30:00Z", 101, 103, 94, 95),  # stop hit here
                ("2026-01-01T00:45:00Z", 95, 97, 93, 96),  # trailing "in progress" candle
            ]
        )

        result = tg.resolve_pending_signals("TESTUSD=X", candles, signal_log)

        row = result.iloc[0]
        self.assertEqual(row["status"], "RESOLVED")
        self.assertEqual(row["outcome"], "LOSS")
        self.assertAlmostEqual(float(row["exit_price"]), 95.0)

    # 3. Persists to canonical SQLite -------------------------------------
    def test_resolution_persists_to_canonical_sqlite(self) -> None:
        signal_log = pd.DataFrame(
            [
                make_pending_signal(
                    "TEST_SQLITE_PERSIST",
                    "TESTUSD=X",
                    "BUY",
                    entry_price=100.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    signal_timestamp="2026-01-01T00:00:00Z",
                )
            ]
        )
        candles = make_candles(
            [
                ("2026-01-01T00:15:00Z", 100, 111, 99, 110),  # target hit
                ("2026-01-01T00:30:00Z", 110, 112, 109, 111),  # trailing candle
            ]
        )

        tg.resolve_pending_signals("TESTUSD=X", candles, signal_log)

        self.assertTrue(tg.DATABASE_FILE.exists(), "canonical SQLite file was never written")
        with sqlite3.connect(tg.DATABASE_FILE) as connection:
            persisted = pd.read_sql_query("SELECT * FROM signals", connection)

        self.assertEqual(len(persisted), 1)
        self.assertEqual(persisted.iloc[0]["status"], "RESOLVED")
        self.assertEqual(persisted.iloc[0]["outcome"], "WIN")

    # 4. Restart-safety: reload after "process restart" returns RESOLVED --
    def test_reload_after_restart_returns_resolved_not_pending(self) -> None:
        signal_log = pd.DataFrame(
            [
                make_pending_signal(
                    "TEST_RESTART_SAFE",
                    "TESTUSD=X",
                    "SELL",
                    entry_price=100.0,
                    stop_loss=105.0,
                    take_profit=90.0,
                    signal_timestamp="2026-01-01T00:00:00Z",
                )
            ]
        )
        candles = make_candles(
            [
                ("2026-01-01T00:15:00Z", 100, 101, 89, 90),  # target hit (low <= 90)
                ("2026-01-01T00:30:00Z", 90, 92, 88, 91),  # trailing candle
            ]
        )

        tg.resolve_pending_signals("TESTUSD=X", candles, signal_log)

        # Simulate a full process restart: this is exactly the code path
        # main() calls once at startup. Under the original bug, this would
        # come back PENDING because the save was skipped by the crash.
        reloaded = tg.load_signal_log()

        matching = reloaded[reloaded["signal_id"] == "TEST_RESTART_SAFE"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching.iloc[0]["status"], "RESOLVED")
        self.assertEqual(matching.iloc[0]["outcome"], "WIN")

    # 5. CSV backup/export reflects the resolved state ---------------------
    def test_csv_backup_reflects_resolved_state(self) -> None:
        signal_log = pd.DataFrame(
            [
                make_pending_signal(
                    "TEST_CSV_BACKUP",
                    "TESTUSD=X",
                    "BUY",
                    entry_price=100.0,
                    stop_loss=95.0,
                    take_profit=110.0,
                    signal_timestamp="2026-01-01T00:00:00Z",
                )
            ]
        )
        candles = make_candles(
            [
                ("2026-01-01T00:15:00Z", 100, 111, 99, 110),
                ("2026-01-01T00:30:00Z", 110, 112, 109, 111),
            ]
        )

        tg.resolve_pending_signals("TESTUSD=X", candles, signal_log)

        self.assertTrue(tg.SIGNALS_FILE.exists(), "CSV backup/export was never written")
        csv_content = pd.read_csv(tg.SIGNALS_FILE)
        matching = csv_content[csv_content["signal_id"] == "TEST_CSV_BACKUP"]
        self.assertEqual(len(matching), 1)
        self.assertEqual(matching.iloc[0]["status"], "RESOLVED")
        self.assertEqual(matching.iloc[0]["outcome"], "WIN")

    # 6. Two signals resolving in the same cycle don't corrupt each other --
    def test_two_signals_resolve_same_cycle_independently(self) -> None:
        # Deliberately DIFFERENT stop/target geometry per signal, so each
        # one's outcome is determined independently by its own risk levels
        # rather than both hitting the same trigger by coincidence (an
        # earlier version of this fixture gave both signals identical
        # entry/stop/target, which meant they were mathematically
        # guaranteed to resolve identically -- that tested nothing about
        # per-signal isolation). Both signals are evaluated against the
        # SAME candle series inside the SAME resolve_pending_signals() call
        # and BOTH resolve on the SAME candle, which is the strongest
        # available check that each loop iteration reads its own signal's
        # fields fresh rather than leaking state from the other iteration
        # (exactly the class of bug the original loop-variable leak had).
        signal_log = pd.DataFrame(
            [
                make_pending_signal(
                    "TEST_MULTI_WIN",
                    "TESTUSD=X",
                    "BUY",
                    entry_price=100.0,
                    stop_loss=90.0,   # far away -> should NOT be hit
                    take_profit=106.0,  # close -> should be hit first
                    signal_timestamp="2026-01-01T00:00:00Z",
                ),
                make_pending_signal(
                    "TEST_MULTI_LOSS",
                    "TESTUSD=X",
                    "BUY",
                    entry_price=100.0,
                    stop_loss=97.0,   # close -> should be hit
                    take_profit=130.0,  # far away -> should NOT be reachable
                    signal_timestamp="2026-01-01T00:00:00Z",
                ),
            ]
        )
        candles = make_candles(
            [
                # Single candle simultaneously: hits TEST_MULTI_WIN's target
                # (high >= 106, its stop at 90 is not touched by low=95) AND
                # hits TEST_MULTI_LOSS's stop (low <= 97, its target at 130
                # is nowhere near high=107).
                ("2026-01-01T00:15:00Z", 100, 107, 95, 106),
                ("2026-01-01T00:30:00Z", 106, 108, 105, 107),  # trailing candle
            ]
        )

        result = tg.resolve_pending_signals("TESTUSD=X", candles, signal_log)

        win_row = result[result["signal_id"] == "TEST_MULTI_WIN"].iloc[0]
        loss_row = result[result["signal_id"] == "TEST_MULTI_LOSS"].iloc[0]

        self.assertEqual(win_row["status"], "RESOLVED")
        self.assertEqual(win_row["outcome"], "WIN")
        self.assertAlmostEqual(float(win_row["exit_price"]), 106.0)

        self.assertEqual(loss_row["status"], "RESOLVED")
        self.assertEqual(loss_row["outcome"], "LOSS")
        self.assertAlmostEqual(float(loss_row["exit_price"]), 97.0)

    # 7. A failing Telegram call cannot prevent persistence ----------------
    def test_telegram_failure_cannot_prevent_persistence(self) -> None:
        def raising_telegram(*args, **kwargs):
            raise RuntimeError("simulated Telegram outage")

        original_send = tg.send_telegram_message
        tg.send_telegram_message = raising_telegram
        try:
            signal_log = pd.DataFrame(
                [
                    make_pending_signal(
                        "TEST_TELEGRAM_DOWN",
                        "TESTUSD=X",
                        "BUY",
                        entry_price=100.0,
                        stop_loss=95.0,
                        take_profit=110.0,
                        signal_timestamp="2026-01-01T00:00:00Z",
                    )
                ]
            )
            candles = make_candles(
                [
                    ("2026-01-01T00:15:00Z", 100, 111, 99, 110),
                    ("2026-01-01T00:30:00Z", 110, 112, 109, 111),
                ]
            )

            # Must not raise, and must still persist, even though Telegram
            # is broken -- resolve_pending_signals() no longer calls
            # send_telegram_message() at all after the P0 fix.
            result = tg.resolve_pending_signals("TESTUSD=X", candles, signal_log)

            self.assertEqual(result.iloc[0]["status"], "RESOLVED")
            self.assertTrue(tg.DATABASE_FILE.exists())
        finally:
            tg.send_telegram_message = original_send


if __name__ == "__main__":
    unittest.main()
