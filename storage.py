"""
storage.py

Minimal, read-only storage abstraction for the Trade Genie dashboard.

Architecture (approved): SQLite is the canonical operational datastore;
the CSV backup file is a read fallback used ONLY when SQLite is missing,
unreadable, or corrupt. This module never writes to either file -- it
exists purely so dashboard.py can read signal history without embedding
SQL/pandas plumbing directly, and without ever risking turning a corrupt
SQLite database into new "canonical" state by writing CSV data back into
it (that direction of sync does not exist here).

Schema note -- why SIGNAL_COLUMNS is duplicated here rather than
imported from trade_genie_contrarian.py: importing that module would
execute its module-level side effects just to read a list of column
names -- load_dotenv(), building MARKET_PROFILES, reading (and
implicitly depending on the layout of) the runtime stats file via
`stats = load_stats()`, creating the data/ directory, and pulling in
yfinance/requests as hard import-time dependencies for a Streamlit
process that never needs them. That coupling is worse than the
duplication. SIGNAL_COLUMNS in trade_genie_contrarian.py remains the
source of truth; if it changes, this list needs updating to match.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pandas as pd

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


class SignalStore:
    """Read-only accessor for Trade Genie's signal history.

    SQLite (`database_file`) is canonical. The CSV file
    (`signals_backup_csv`) is read only as a fallback when SQLite can't
    be read at all. A successful CSV read is never written back into
    SQLite, and neither file is ever written to by this class -- it is
    a reader, not a synchronizer.
    """

    def __init__(self, database_file: Path, signals_backup_csv: Path) -> None:
        self.database_file = Path(database_file)
        self.signals_backup_csv = Path(signals_backup_csv)

    def load_frame(self) -> pd.DataFrame:
        """Return the current signal history as a DataFrame.

        Order: SQLite (canonical) -> CSV backup (fallback) -> empty,
        correctly-columned DataFrame. Never returns None and never
        raises for a missing/corrupt/empty source -- failures are
        logged to stdout and the next fallback is tried instead.
        """
        frame = self._load_from_sqlite()
        if frame is not None:
            return frame

        frame = self._load_from_csv()
        if frame is not None:
            return frame

        return pd.DataFrame(columns=SIGNAL_COLUMNS)

    def _load_from_sqlite(self) -> pd.DataFrame | None:
        if not self.database_file.exists():
            return None

        try:
            with sqlite3.connect(self.database_file) as connection:
                frame = pd.read_sql_query("SELECT * FROM signals", connection)
        except (sqlite3.Error, pd.errors.DatabaseError) as error:
            print(
                "[storage] Canonical SQLite read failed "
                f"({self.database_file.name}): {type(error).__name__}: "
                f"{error}. Falling back to CSV backup."
            )
            return None

        return self._normalize(frame)

    def _load_from_csv(self) -> pd.DataFrame | None:
        if not self.signals_backup_csv.exists():
            return None

        try:
            frame = pd.read_csv(self.signals_backup_csv)
        except (pd.errors.EmptyDataError, OSError) as error:
            print(
                "[storage] CSV backup read failed "
                f"({self.signals_backup_csv.name}): "
                f"{type(error).__name__}: {error}."
            )
            return None

        return self._normalize(frame)

    @staticmethod
    def _normalize(frame: pd.DataFrame) -> pd.DataFrame:
        """Guarantee every expected column is present, in order.

        Missing columns are added as all-None rather than raising, so a
        source with an older/partial schema still renders instead of
        crashing the dashboard.
        """
        for column in SIGNAL_COLUMNS:
            if column not in frame.columns:
                frame[column] = None
        return frame[SIGNAL_COLUMNS]
