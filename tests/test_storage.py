"""
Tests for storage.SignalStore.

All tests use tempfile-based SQLite/CSV files only. The real project's
data/trade_genie.db and trade_genie_contrarian_signals.csv are never
opened.

Run with:  python3 -m unittest tests.test_storage -v
(run from the repository root).
"""

from __future__ import annotations

import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from storage import SIGNAL_COLUMNS, SignalStore  # noqa: E402


def _write_sqlite(path: Path, rows: list[dict]) -> None:
    frame = pd.DataFrame(rows, columns=SIGNAL_COLUMNS) if rows else pd.DataFrame(
        columns=SIGNAL_COLUMNS
    )
    with sqlite3.connect(path) as connection:
        frame.to_sql("signals", connection, if_exists="replace", index=False)


def _write_csv(path: Path, rows: list[dict]) -> None:
    frame = pd.DataFrame(rows, columns=SIGNAL_COLUMNS) if rows else pd.DataFrame(
        columns=SIGNAL_COLUMNS
    )
    frame.to_csv(path, index=False)


def _make_row(signal_id: str, status: str = "PENDING") -> dict:
    row = {column: None for column in SIGNAL_COLUMNS}
    row.update(
        {
            "signal_id": signal_id,
            "signal_timestamp": "2026-01-01T00:00:00Z",
            "asset": "TESTUSD=X",
            "asset_name": "TEST/USD",
            "direction": "BUY",
            "status": status,
            "outcome": "WIN" if status == "RESOLVED" else None,
        }
    )
    return row


class SignalStoreTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp_dir = Path(tempfile.mkdtemp(prefix="trade_genie_storage_test_"))
        self.db_path = self.tmp_dir / "signals.db"
        self.csv_path = self.tmp_dir / "signals.csv"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    # 1. Valid SQLite loads successfully -----------------------------------
    def test_valid_sqlite_loads_successfully(self) -> None:
        _write_sqlite(self.db_path, [_make_row("SQLITE_OK")])
        store = SignalStore(self.db_path, self.csv_path)

        frame = store.load_frame()

        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["signal_id"], "SQLITE_OK")
        self.assertListEqual(list(frame.columns), SIGNAL_COLUMNS)

    # 2. SQLite preferred over CSV when both exist with different data -----
    def test_sqlite_preferred_over_csv_when_both_exist(self) -> None:
        _write_sqlite(self.db_path, [_make_row("FROM_SQLITE")])
        _write_csv(self.csv_path, [_make_row("FROM_CSV")])
        store = SignalStore(self.db_path, self.csv_path)

        frame = store.load_frame()

        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["signal_id"], "FROM_SQLITE")

    # 3. Missing SQLite falls back to CSV -----------------------------------
    def test_missing_sqlite_falls_back_to_csv(self) -> None:
        # self.db_path deliberately never created.
        _write_csv(self.csv_path, [_make_row("FROM_CSV_FALLBACK")])
        store = SignalStore(self.db_path, self.csv_path)

        frame = store.load_frame()

        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["signal_id"], "FROM_CSV_FALLBACK")

    # 4. Corrupt SQLite falls back to CSV -----------------------------------
    def test_corrupt_sqlite_falls_back_to_csv(self) -> None:
        self.db_path.write_bytes(b"this is not a valid sqlite database file")
        _write_csv(self.csv_path, [_make_row("FROM_CSV_AFTER_CORRUPTION")])
        store = SignalStore(self.db_path, self.csv_path)

        frame = store.load_frame()

        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["signal_id"], "FROM_CSV_AFTER_CORRUPTION")

    # 5. Missing SQLite + missing CSV -> empty, correctly-shaped frame -----
    def test_missing_both_sources_returns_empty_correct_schema(self) -> None:
        # Neither self.db_path nor self.csv_path created.
        store = SignalStore(self.db_path, self.csv_path)

        frame = store.load_frame()

        self.assertTrue(frame.empty)
        self.assertListEqual(list(frame.columns), SIGNAL_COLUMNS)

    # 6. Empty SQLite table behaves correctly -------------------------------
    def test_empty_sqlite_table_returns_empty_correct_schema(self) -> None:
        _write_sqlite(self.db_path, [])  # creates the table with 0 rows
        store = SignalStore(self.db_path, self.csv_path)

        frame = store.load_frame()

        self.assertTrue(frame.empty)
        self.assertListEqual(list(frame.columns), SIGNAL_COLUMNS)

    # 6b. SQLite file exists but has no "signals" table at all -------------
    def test_sqlite_file_with_no_signals_table_falls_back_to_csv(self) -> None:
        # touch a valid-but-empty sqlite file (no tables at all)
        sqlite3.connect(self.db_path).close()
        _write_csv(self.csv_path, [_make_row("FROM_CSV_NO_TABLE")])
        store = SignalStore(self.db_path, self.csv_path)

        frame = store.load_frame()

        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["signal_id"], "FROM_CSV_NO_TABLE")

    # 7. Dashboard-required fields are present ------------------------------
    def test_dashboard_required_fields_present(self) -> None:
        _write_sqlite(self.db_path, [_make_row("HAS_FIELDS", status="RESOLVED")])
        store = SignalStore(self.db_path, self.csv_path)

        frame = store.load_frame()

        for required in ("signal_timestamp", "status", "outcome"):
            self.assertIn(required, frame.columns)
        self.assertEqual(frame.iloc[0]["status"], "RESOLVED")
        self.assertEqual(frame.iloc[0]["outcome"], "WIN")

    # Never writes anything ---------------------------------------------
    def test_load_frame_never_writes_to_either_file(self) -> None:
        _write_sqlite(self.db_path, [_make_row("READ_ONLY_CHECK")])
        db_mtime_before = self.db_path.stat().st_mtime_ns
        store = SignalStore(self.db_path, self.csv_path)

        store.load_frame()
        store.load_frame()

        self.assertFalse(self.csv_path.exists(), "load_frame() must not create the CSV file")
        self.assertEqual(
            self.db_path.stat().st_mtime_ns,
            db_mtime_before,
            "load_frame() must not modify the SQLite file",
        )


if __name__ == "__main__":
    unittest.main()
