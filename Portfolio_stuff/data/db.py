"""
Base de datos SQLite centralizada para precios históricos.
Proporciona una interfaz única para leer/escribir datos de todos los módulos.
"""
import re
import sqlite3
import pandas as pd
from pathlib import Path
from typing import List, Tuple, Optional
from contextlib import contextmanager

DB_PATH = Path(__file__).parent / "market_data.db"


def normalize_symbol(symbol: str) -> str:
    return symbol.strip().upper()


def symbol_to_table_name(symbol: str) -> str:
    symbol = normalize_symbol(symbol)
    sanitized = re.sub(r"[^A-Z0-9]+", "_", symbol)
    sanitized = re.sub(r"_+", "_", sanitized).strip("_")
    return f"price_{sanitized}"


@contextmanager
def get_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db():
    with get_connection() as conn:
        conn.execute("""
        CREATE TABLE IF NOT EXISTS symbol_registry (
            symbol TEXT PRIMARY KEY,
            table_name TEXT NOT NULL UNIQUE
        )
        """)
        conn.commit()
        if legacy_price_data_table_exists(conn):
            migrate_price_data_table(conn)


def legacy_price_data_table_exists(conn) -> bool:
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='price_data'"
    )
    return cursor.fetchone() is not None


def migrate_price_data_table(conn):
    cursor = conn.execute(
        "SELECT symbol, date, open, high, low, close, volume, adj_close FROM price_data ORDER BY symbol, date"
    )
    rows = cursor.fetchall()
    if not rows:
        conn.execute("DROP TABLE IF EXISTS price_data")
        conn.commit()
        return

    records_by_symbol = {}
    for row in rows:
        symbol = normalize_symbol(row["symbol"])
        records_by_symbol.setdefault(symbol, []).append({
            "date": row["date"],
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": row["volume"],
            "adj_close": row["adj_close"],
        })

    for symbol, records in records_by_symbol.items():
        table_name = ensure_symbol_table(symbol, conn)
        insert_stmt = f"""
            INSERT INTO {table_name} (date, open, high, low, close, volume, adj_close)
            VALUES (:date, :open, :high, :low, :close, :volume, :adj_close)
            ON CONFLICT(date) DO UPDATE SET
                open = COALESCE(excluded.open, open),
                high = COALESCE(excluded.high, high),
                low = COALESCE(excluded.low, low),
                close = excluded.close,
                volume = COALESCE(excluded.volume, volume),
                adj_close = COALESCE(excluded.adj_close, adj_close)
        """
        conn.executemany(insert_stmt, records)
    conn.execute("DROP TABLE IF EXISTS price_data")
    conn.commit()


def get_registered_table(symbol: str, conn) -> Optional[str]:
    normalized = normalize_symbol(symbol)
    cursor = conn.execute(
        "SELECT table_name FROM symbol_registry WHERE symbol = ?",
        (normalized,),
    )
    row = cursor.fetchone()
    return row["table_name"] if row else None


def ensure_symbol_table(symbol: str, conn) -> str:
    normalized = normalize_symbol(symbol)
    table_name = get_registered_table(normalized, conn)
    if table_name:
        return table_name

    table_name = symbol_to_table_name(normalized)
    base_table_name = table_name
    suffix = 1
    while conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
        (table_name,),
    ).fetchone():
        table_name = f"{base_table_name}_{suffix}"
        suffix += 1

    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL UNIQUE,
            open REAL,
            high REAL,
            low REAL,
            close REAL NOT NULL,
            volume INTEGER,
            adj_close REAL
        )
    """)
    conn.execute(
        "INSERT INTO symbol_registry (symbol, table_name) VALUES (?, ?)",
        (normalized, table_name),
    )
    conn.commit()
    return table_name


def insert_or_update_price(
    symbol: str,
    date: str,
    close: float,
    open: Optional[float] = None,
    high: Optional[float] = None,
    low: Optional[float] = None,
    volume: Optional[int] = None,
    adj_close: Optional[float] = None,
) -> bool:
    with get_connection() as conn:
        table_name = ensure_symbol_table(symbol, conn)
        cursor = conn.cursor()
        cursor.execute(
            f"""
            INSERT INTO {table_name} (date, open, high, low, close, volume, adj_close)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                open = COALESCE(excluded.open, open),
                high = COALESCE(excluded.high, high),
                low = COALESCE(excluded.low, low),
                close = excluded.close,
                volume = COALESCE(excluded.volume, volume),
                adj_close = COALESCE(excluded.adj_close, adj_close)
            """,
            (date, open, high, low, close, volume, adj_close),
        )
        conn.commit()
        return cursor.rowcount > 0


def insert_or_update_prices_batch(records: List[dict]) -> int:
    total = 0
    with get_connection() as conn:
        cursor = conn.cursor()
        for rec in records:
            symbol = rec.get("symbol") or ""
            table_name = ensure_symbol_table(symbol, conn)
            cursor.execute(
                f"""
                INSERT INTO {table_name} (date, open, high, low, close, volume, adj_close)
                VALUES (:date, :open, :high, :low, :close, :volume, :adj_close)
                ON CONFLICT(date) DO UPDATE SET
                    open = COALESCE(excluded.open, open),
                    high = COALESCE(excluded.high, high),
                    low = COALESCE(excluded.low, low),
                    close = excluded.close,
                    volume = COALESCE(excluded.volume, volume),
                    adj_close = COALESCE(excluded.adj_close, adj_close)
                """,
                rec,
            )
            total += 1
        conn.commit()
    return total


def get_price_data(
    symbol: Optional[str] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
) -> pd.DataFrame:
    if symbol:
        with get_connection() as conn:
            table_name = get_registered_table(symbol, conn)
            if not table_name:
                return pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume", "adj_close"])
            query = f"SELECT date, open, high, low, close, volume, adj_close FROM {table_name} WHERE 1=1"
            params = []
            if start_date:
                query += " AND date >= ?"
                params.append(start_date)
            if end_date:
                query += " AND date <= ?"
                params.append(end_date)
            query += " ORDER BY date"
            df = pd.read_sql_query(query, conn, params=params)
            if not df.empty:
                df["date"] = pd.to_datetime(df["date"])
                df["close"] = pd.to_numeric(df["close"], errors="coerce")
                df["symbol"] = normalize_symbol(symbol)
            return df

    symbols = get_all_symbols()
    frames = []
    for sym in symbols:
        frames.append(get_price_data(sym, start_date=start_date, end_date=end_date))
    if frames:
        result = pd.concat(frames, ignore_index=True)
    else:
        result = pd.DataFrame(columns=["symbol", "date", "open", "high", "low", "close", "volume", "adj_close"])
    return result


def get_latest_close(symbol: str) -> Optional[Tuple[str, float]]:
    with get_connection() as conn:
        table_name = get_registered_table(symbol, conn)
        if not table_name:
            return None
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT date, close FROM {table_name} ORDER BY date DESC LIMIT 1"
        )
        row = cursor.fetchone()
    return (row["date"], row["close"]) if row else None


def get_latest_data_date(ignore_symbols: Optional[List[str]] = None) -> Optional[str]:
    ignore_set = {normalize_symbol(s) for s in (ignore_symbols or [])}
    latest_date = None
    for symbol in get_all_symbols():
        if normalize_symbol(symbol) in ignore_set:
            continue
        latest = get_latest_close(symbol)
        if latest:
            date_str, _ = latest
            if latest_date is None or date_str > latest_date:
                latest_date = date_str
    return latest_date


def needs_data_update(ignore_symbols: Optional[List[str]] = None) -> bool:
    if ignore_symbols is None:
        ignore_symbols = ["ALL"]

    latest_date = get_latest_data_date(ignore_symbols=ignore_symbols)
    if latest_date is None:
        return True

    latest_ts = pd.to_datetime(latest_date).normalize()
    today = pd.Timestamp.now().normalize()
    while today.weekday() >= 5:
        today -= pd.Timedelta(days=1)

    return latest_ts < today


def get_all_symbols() -> List[str]:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT symbol FROM symbol_registry ORDER BY symbol")
        symbols = [row["symbol"] for row in cursor.fetchall()]
    return symbols


def delete_symbol_data(symbol: str) -> int:
    with get_connection() as conn:
        table_name = get_registered_table(symbol, conn)
        if not table_name:
            return 0
        conn.execute(f"DROP TABLE IF EXISTS {table_name}")
        conn.execute("DELETE FROM symbol_registry WHERE symbol = ?", (normalize_symbol(symbol),))
        conn.commit()
        return 1


def export_to_csv(output_path: str, symbol: Optional[str] = None):
    df = get_price_data(symbol=symbol)
    df.to_csv(output_path, index=False)


def get_consolidated_data() -> pd.DataFrame:
    df = get_price_data()
    if df.empty:
        return pd.DataFrame(columns=["Symbol", "Date", "Close"])
    return df[["symbol", "date", "close"]].rename(
        columns={"symbol": "Symbol", "date": "Date", "close": "Close"}
    )


# Inicializar BD al importar
init_db()
