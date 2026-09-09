"""SQLite data layer for Budget App."""

import sqlite3
import shutil
import os
import json
from datetime import datetime
import pandas as pd
from pydantic import BaseModel, ConfigDict

from agents.merchant_utils import normalize_merchant

# Percorsi assoluti: il DB, il seed e il CSV devono restare accanto a questo
# modulo, indipendentemente dalla directory da cui viene lanciata l'app.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "budget.db")
SEED_PATH = os.path.join(BASE_DIR, "merchant_seed.json")
DEFAULT_CSV_PATH = os.path.join(BASE_DIR, "budget_database.csv")


def _resolve_csv_path(csv_path):
    """Risolve un percorso CSV relativo contro BASE_DIR (export/migrate).

    Così ``export_to_csv``/``migrate_from_csv`` scrivono/leggono sempre in
    Budget_App anche se il processo è avviato da un'altra directory.
    """
    if os.path.isabs(csv_path):
        return csv_path
    return os.path.join(BASE_DIR, csv_path)

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

SCHEMA_MERCHANT_CATEGORIES = """
CREATE TABLE IF NOT EXISTS merchant_categories (
    merchant_normalized TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'llm',
    confidence REAL DEFAULT 0.8,
    times_seen INTEGER DEFAULT 1,
    first_seen TEXT,
    last_seen TEXT
);
"""


class MerchantEntry(BaseModel):
    """Voce della mappatura negozio -> categoria.

    Modello congelato (frozen): una volta creata, la voce non può essere
    mutata accidentalmente. Questo protegge in particolare le correzioni
    manuali (source='manual'), che hanno priorità assoluta.
    """

    model_config = ConfigDict(frozen=True)

    merchant: str
    category: str
    source: str
    confidence: float
    times_seen: int
    first_seen: str | None = None
    last_seen: str | None = None


def get_connection() -> sqlite3.Connection:
    """Return connection with WAL mode and foreign keys enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    """Create tables if not exists. Called on app startup.

    Ritorna il numero di voci seed importate automaticamente (0 se la tabella
    era già popolata o il file seed è assente). L'import è idempotente e non
    sovrascrive mai voci esistenti/manuali.
    """
    conn = get_connection()
    conn.execute(SCHEMA_MONTHLY_BUDGET)
    conn.execute(SCHEMA_TRANSACTIONS)
    conn.execute(SCHEMA_BUDGET_TARGETS)
    conn.execute(SCHEMA_MERCHANT_CATEGORIES)
    conn.commit()
    conn.close()

    # Seed automatico: se la mappatura è vuota e merchant_seed.json esiste
    # accanto a questo modulo, la importa una tantum.
    return seed_merchants_from_json(SEED_PATH)


def _backup_db():
    """Create a .bak backup of the DB before each save."""
    if os.path.exists(DB_PATH):
        shutil.copy2(DB_PATH, DB_PATH + ".bak")


def migrate_from_csv(csv_path=DEFAULT_CSV_PATH, force=False):
    """One-time migration: read CSV, insert rows into monthly_budget.

    Args:
        csv_path: Path to the CSV file.
        force: If True, delete all existing data and re-import regardless.
               If False, skip if monthly_budget already has data.
    """
    csv_path = _resolve_csv_path(csv_path)
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


def export_to_csv(filepath=DEFAULT_CSV_PATH):
    """Export current DB to CSV (for backward compatibility / cloud sync)."""
    filepath = _resolve_csv_path(filepath)
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


# ---------------------------------------------------------------------------
# Mappatura negozi -> categorie (merchant_categories)
# ---------------------------------------------------------------------------
def _ensure_merchant_table(conn):
    """Create merchant_categories table if missing (idempotent)."""
    conn.execute(SCHEMA_MERCHANT_CATEGORIES)


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def get_merchant_map() -> dict[str, MerchantEntry]:
    """Ritorna l'intera mappatura {merchant_normalized: MerchantEntry}.

    Non crea la tabella: se non esiste ritorna un dict vuoto (l'import userà
    l'LLM per tutto). Usata anche dal flusso di import come lookup.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT merchant_normalized, category, source, confidence, "
            "times_seen, first_seen, last_seen FROM merchant_categories"
        ).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return {}
    conn.close()
    return {
        r["merchant_normalized"]: MerchantEntry(
            merchant=r["merchant_normalized"],
            category=r["category"],
            source=r["source"],
            confidence=r["confidence"],
            times_seen=r["times_seen"],
            first_seen=r["first_seen"],
            last_seen=r["last_seen"],
        )
        for r in rows
    }


def get_merchant_list() -> list[MerchantEntry]:
    """Ritorna le voci della mappatura come lista (per la UI), ordinate."""
    return sorted(get_merchant_map().values(), key=lambda e: e.merchant)


def get_merchant_count() -> int:
    """Numero di voci presenti nella mappatura (0 se la tabella non esiste)."""
    conn = get_connection()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM merchant_categories"
        ).fetchone()[0]
    except sqlite3.OperationalError:
        conn.close()
        return 0
    conn.close()
    return count


def upsert_merchant(merchant, category, source="llm", confidence=0.8) -> bool:
    """Inserisce/aggiorna una mappatura negozio -> categoria.

    NON sovrascrive MAI una voce manuale: se la entry esistente ha
    source='manual', l'upsert viene ignorato (priorità assoluta alla
    correzione manuale). Per voci non-manual: incrementa times_seen, aggiorna
    last_seen, e aggiorna category/source/confidence.

    Ritorna False se ignorato (entry manuale esistente), True altrimenti.
    """
    key = normalize_merchant(merchant)
    if not key:
        return False

    now = _now_iso()
    conn = get_connection()
    try:
        _ensure_merchant_table(conn)
        existing = conn.execute(
            "SELECT source FROM merchant_categories WHERE merchant_normalized = ?",
            (key,),
        ).fetchone()
        if existing is not None and existing["source"] == "manual":
            return False

        conn.execute(
            """
            INSERT INTO merchant_categories
                (merchant_normalized, category, source, confidence,
                 times_seen, first_seen, last_seen)
            VALUES (?, ?, ?, ?, 1, ?, ?)
            ON CONFLICT(merchant_normalized) DO UPDATE SET
                category = excluded.category,
                source = excluded.source,
                confidence = excluded.confidence,
                times_seen = merchant_categories.times_seen + 1,
                last_seen = excluded.last_seen
            WHERE merchant_categories.source != 'manual'
            """,
            (key, str(category), source, float(confidence), now, now),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def set_merchant_manual(merchant, category) -> bool:
    """Imposta (o sovrascrive) una correzione manuale: source='manual',
    confidence=1.0. Priorità assoluta: nessun upsert LLM/seed la toccherà."""
    key = normalize_merchant(merchant)
    if not key:
        return False

    now = _now_iso()
    conn = get_connection()
    try:
        _ensure_merchant_table(conn)
        conn.execute(
            """
            INSERT INTO merchant_categories
                (merchant_normalized, category, source, confidence,
                 times_seen, first_seen, last_seen)
            VALUES (?, ?, 'manual', 1.0, 1, ?, ?)
            ON CONFLICT(merchant_normalized) DO UPDATE SET
                category = excluded.category,
                source = 'manual',
                confidence = 1.0,
                times_seen = merchant_categories.times_seen + 1,
                last_seen = excluded.last_seen
            """,
            (key, str(category), now, now),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def delete_merchant(merchant) -> bool:
    """Elimina una voce dalla mappatura. Ritorna True se eliminata."""
    key = normalize_merchant(merchant)
    if not key:
        return False

    conn = get_connection()
    try:
        _ensure_merchant_table(conn)
        cursor = conn.execute(
            "DELETE FROM merchant_categories WHERE merchant_normalized = ?",
            (key,),
        )
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def seed_merchants_from_json(path) -> int:
    """Carica il seed negozi->categoria UNA TANTUM.

    Carica solo se la tabella è vuota (comportamento sicuro e idempotente).
    Le chiavi vengono normalizzate con normalize_merchant così da restare
    coerenti con il lookup dell'import. Non sovrascrive mai voci manuali
    (difensivo). Ritorna il numero di voci inserite.
    """
    if not os.path.isabs(path):
        path = os.path.join(BASE_DIR, path)
    if not os.path.exists(path):
        return 0

    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)

    conn = get_connection()
    try:
        _ensure_merchant_table(conn)
        count = conn.execute(
            "SELECT COUNT(*) FROM merchant_categories"
        ).fetchone()[0]
        if count > 0:
            return 0

        now = _now_iso()
        inserted = 0
        for entry in data:
            merchant = normalize_merchant(entry.get("merchant", ""))
            category = str(entry.get("category", "") or "")
            source = str(entry.get("source", "seeded") or "seeded")
            confidence = float(entry.get("confidence", 0.6))
            if not merchant or not category:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO merchant_categories
                    (merchant_normalized, category, source, confidence,
                     times_seen, first_seen, last_seen)
                VALUES (?, ?, ?, ?, 1, ?, ?)
                """,
                (merchant, category, source, confidence, now, now),
            )
            inserted += 1
        conn.commit()
        return inserted
    finally:
        conn.close()
