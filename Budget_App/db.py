"""SQLite data layer for Budget App."""

import sqlite3
import shutil
import os
from datetime import datetime
import pandas as pd

DB_PATH = "budget.db"

BASE_COLUMNS = [
    "Year",
    "MonthNum",
    "Month",
    "Stipendio",
    "Reddito aggiuntivo",
    "Alimentari",
    "Bancomat",
    "Carburante",
    "Cene, Pranzo",
    "Immobili (affitto, mutuo, tasse, assicurazione)",
    "Investimenti",
    "Medicinali",
    "PayPal + Abbonamenti",
    "Spese Straordinarie",
    "Trasporti",
    "Viaggi, Divertimento",
]

COMPUTED_COLUMNS = [
    "Totale Entrate",
    "Totale Uscite",
    "Reddito meno spese",
    "Risparmio %",
]

# All columns double-quoted so case and special chars are preserved exactly
_COLS_SQL = ",\n    ".join([f'    "{c}"' for c in BASE_COLUMNS])

SCHEMA_MONTHLY_BUDGET = f"""
CREATE TABLE IF NOT EXISTS monthly_budget (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    {_COLS_SQL},
    UNIQUE("Year", "MonthNum")
);
"""

SCHEMA_TRANSACTIONS = """
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    description TEXT,
    amount REAL NOT NULL,
    category TEXT,
    source TEXT,
    imported_at TEXT DEFAULT (datetime('now')),
    month_ref TEXT
);
"""

SCHEMA_BUDGET_TARGETS = """
CREATE TABLE IF NOT EXISTS budget_targets (
    category TEXT PRIMARY KEY,
    monthly_target REAL NOT NULL DEFAULT 0.0
);
"""


def get_connection() -> sqlite3.Connection:
    """Return connection with WAL mode and foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if not exists. Called on app startup."""
    conn = get_connection()
    conn.execute(SCHEMA_MONTHLY_BUDGET)
    conn.execute(SCHEMA_TRANSACTIONS)
    conn.execute(SCHEMA_BUDGET_TARGETS)
    conn.commit()
    conn.close()


def _backup_db():
    """Create a .bak backup of the DB before each save."""
    if os.path.exists(DB_PATH):
        shutil.copy2(DB_PATH, DB_PATH + ".bak")


def migrate_from_csv(csv_path="budget_database.csv", force=False):
    """One-time migration: read CSV, insert rows into monthly_budget.

    Args:
        csv_path: Path to the CSV file.
        force: If True, delete all existing data and re-import regardless.
               If False, skip if monthly_budget already has data.
    """
    if not os.path.exists(csv_path):
        return

    conn = get_connection()
    cursor = conn.execute("SELECT COUNT(*) FROM monthly_budget")
    count = cursor.fetchone()[0]

    if count > 0 and not force:
        conn.close()
        return

    if force:
        conn.execute("DELETE FROM monthly_budget")

    df = pd.read_csv(csv_path)

    cols_to_import = [c for c in BASE_COLUMNS if c in df.columns]
    places = ", ".join(["?" for _ in cols_to_import])
    cols_quoted = ", ".join([f'"{c}"' for c in cols_to_import])
    sql = f'INSERT OR REPLACE INTO monthly_budget ({cols_quoted}) VALUES ({places})'

    for _, row in df.iterrows():
        values = []
        for c in cols_to_import:
            val = row[c]
            if pd.isna(val):
                if c in ("Year", "MonthNum"):
                    val = 0
                elif c == "Month":
                    val = ""
                else:
                    val = 0.0
            values.append(val)
        conn.execute(sql, values)

    conn.commit()
    conn.close()


def load_data() -> pd.DataFrame:
    """Query monthly_budget, return DataFrame sorted by Year/MonthNum descending.
    Excludes 'id' and computed columns — calculate_metrics() adds those.
    """
    conn = get_connection()
    cols_quoted = ", ".join([f'"{c}"' for c in BASE_COLUMNS])
    df = pd.read_sql_query(
        f'SELECT {cols_quoted} FROM monthly_budget ORDER BY "Year" DESC, "MonthNum" DESC',
        conn,
    )
    conn.close()
    return df


def save_data(df):
    """Upsert DataFrame into monthly_budget. Only saves base columns.
    Creates a .bak backup before writing.
    """
    _backup_db()

    conn = get_connection()
    cols_to_save = [c for c in BASE_COLUMNS if c in df.columns]

    if not cols_to_save:
        conn.close()
        return

    places = ", ".join(["?" for _ in cols_to_save])
    cols_quoted = ", ".join([f'"{c}"' for c in cols_to_save])
    sql = f'INSERT OR REPLACE INTO monthly_budget ({cols_quoted}) VALUES ({places})'

    for _, row in df.iterrows():
        values = []
        for c in cols_to_save:
            val = row[c]
            if pd.isna(val):
                if c in ("Year", "MonthNum"):
                    val = 0
                elif c == "Month":
                    val = ""
                else:
                    val = 0.0
            values.append(val)
        conn.execute(sql, values)

    conn.commit()
    conn.close()

    try:
        import streamlit as st
        st.toast("Dati salvati con successo!", icon="✅")
        st.cache_data.clear()
    except ImportError:
        pass


def export_to_csv(filepath="budget_database.csv"):
    """Export current DB to CSV (for backward compatibility / cloud sync)."""
    conn = get_connection()
    cols_quoted = ", ".join([f'"{c}"' for c in BASE_COLUMNS])
    df = pd.read_sql_query(
        f'SELECT {cols_quoted} FROM monthly_budget ORDER BY "Year" DESC, "MonthNum" DESC',
        conn,
    )
    conn.close()
    df.to_csv(filepath, index=False)


def save_transactions(records):
    """Atomically replace ALL transactions with the provided records.

    Each record is a dict with keys: date, description, amount, category,
    source, month_ref. Runs in a single transaction (delete + insert).
    Returns the number of inserted rows.
    """
    rows = [
        (
            str(r.get("date", "")),
            str(r.get("description", "")),
            float(r.get("amount", 0.0)),
            r.get("category"),
            r.get("source"),
            r.get("month_ref"),
        )
        for r in records
    ]

    conn = get_connection()
    try:
        conn.execute("DELETE FROM transactions")
        conn.executemany(
            "INSERT INTO transactions (date, description, amount, category, source, month_ref) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    try:
        import streamlit as st
        st.cache_data.clear()
    except ImportError:
        pass

    return len(rows)


def load_transactions(month_ref=None):
    """Return transactions as a DataFrame, optionally filtered by month_ref."""
    conn = get_connection()
    if month_ref:
        df = pd.read_sql_query(
            'SELECT * FROM transactions WHERE month_ref = ? ORDER BY "date"',
            conn,
            params=(month_ref,),
        )
    else:
        df = pd.read_sql_query('SELECT * FROM transactions ORDER BY "date"', conn)
    conn.close()
    return df


def get_budget_targets():
    """Return saved budget targets as a dict {category: monthly_target}."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT category, monthly_target FROM budget_targets"
        ).fetchall()
    except sqlite3.OperationalError:
        conn.execute(SCHEMA_BUDGET_TARGETS)
        conn.commit()
        rows = []
    conn.close()
    return {r["category"]: r["monthly_target"] for r in rows}


def save_budget_targets(targets):
    """Replace all budget targets. `targets` is a dict {category: monthly_target}."""
    conn = get_connection()
    conn.execute(SCHEMA_BUDGET_TARGETS)
    try:
        conn.execute("DELETE FROM budget_targets")
        conn.executemany(
            "INSERT OR REPLACE INTO budget_targets (category, monthly_target) VALUES (?, ?)",
            [(str(k), float(v)) for k, v in targets.items()],
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    try:
        import streamlit as st
        st.cache_data.clear()
    except ImportError:
        pass


def get_db_info() -> dict:
    """Return info: db_path, db_size_kb, row_count, last_backup_time."""
    info = {
        "db_path": os.path.abspath(DB_PATH),
        "db_size_kb": 0.0,
        "row_count": 0,
        "last_backup_time": None,
    }

    if os.path.exists(DB_PATH):
        info["db_size_kb"] = os.path.getsize(DB_PATH) / 1024.0

    bak_path = DB_PATH + ".bak"
    if os.path.exists(bak_path):
        info["last_backup_time"] = datetime.fromtimestamp(
            os.path.getmtime(bak_path)
        ).strftime("%Y-%m-%d %H:%M:%S")

    conn = get_connection()
    try:
        cursor = conn.execute("SELECT COUNT(*) FROM monthly_budget")
        info["row_count"] = cursor.fetchone()[0]
    except sqlite3.OperationalError:
        info["row_count"] = 0
    conn.close()

    return info
