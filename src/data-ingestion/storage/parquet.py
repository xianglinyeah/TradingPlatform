"""Parquet storage for minute and daily bars (pyarrow).

Schema: trade_time | ts_code | open | close | high | low | volume | amount | adj_factor.

Minute bars use a per-year file layout backed by PG metadata; daily bars use
a single file per symbol. Both writers are idempotent (read → dedupe by
trade_time → sort → rewrite).
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Iterable, List, Tuple

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)


BAR_COLUMNS = [
    "trade_time", "ts_code", "open", "close", "high", "low",
    "volume", "amount", "adj_factor",
]

# Schema mirrors the existing on-disk Parquet files: timestamp[us, tz=UTC].
TS_TYPE = pa.timestamp("us", tz="UTC")


def gm_to_ts_code(gm_symbol: str) -> str:
    """`SHSE.600000` -> `600000.SH`."""
    parts = gm_symbol.split(".")
    if len(parts) != 2:
        return gm_symbol
    suffix = {"SHSE": "SH", "SZSE": "SZ"}.get(parts[0].upper(), parts[0])
    return f"{parts[1]}.{suffix}"


def ts_to_gm_code(ts_symbol: str) -> str:
    """Inverse of gm_to_ts_code: `600000.SH` -> `SHSE.600000`."""
    parts = ts_symbol.split(".")
    if len(parts) != 2:
        return ts_symbol
    full = {"SH": "SHSE", "SZ": "SZSE"}.get(parts[1].upper(), parts[1])
    return f"{full}.{parts[0]}"


def _to_utc(bob):
    """Normalize any datetime/Timestamp to a tz-aware UTC datetime.

    The C# version stored Beijing wall-clock instants labelled as UTC (it wrote
    the raw `bob` DateTime straight into Parquet). The Python gm SDK returns
    `pandas.Timestamp` with `+08:00` tz; to preserve byte-level compatibility
    we strip tz first (keeping the Beijing wall-clock) then re-label as UTC.
    """
    if bob is None:
        return None
    if isinstance(bob, pd.Timestamp):
        if bob.tzinfo is not None:
            bob = bob.tz_localize(None)
        return bob.to_pydatetime().replace(tzinfo=timezone.utc)
    if isinstance(bob, datetime):
        if bob.tzinfo is not None:
            return bob.astimezone(timezone.utc)
        return bob.replace(tzinfo=timezone.utc)
    # Fallback: let pandas coerce.
    ts = pd.Timestamp(bob)
    if ts.tzinfo is not None:
        ts = ts.tz_localize(None)
    return ts.to_pydatetime().replace(tzinfo=timezone.utc)


def _bars_to_table(bars: Iterable[dict], ts_code: str) -> pa.Table:
    trade_times, ts_codes = [], []
    opens, closes, highs, lows = [], [], [], []
    volumes, amounts, adjs = [], [], []

    for b in bars:
        bob = _to_utc(b.get("bob") or b.get("eob"))
        trade_times.append(bob)
        ts_codes.append(ts_code)
        opens.append(float(b.get("open", 0.0)))
        closes.append(float(b.get("close", 0.0)))
        highs.append(float(b.get("high", 0.0)))
        lows.append(float(b.get("low", 0.0)))
        volumes.append(float(b.get("volume", 0.0)))
        amounts.append(float(b.get("amount", 0.0)))
        adjs.append(1.0)

    return pa.table({
        "trade_time": pa.array(trade_times, type=TS_TYPE),
        "ts_code": pa.array(ts_codes, type=pa.string()),
        "open": pa.array(opens, type=pa.float64()),
        "close": pa.array(closes, type=pa.float64()),
        "high": pa.array(highs, type=pa.float64()),
        "low": pa.array(lows, type=pa.float64()),
        "volume": pa.array(volumes, type=pa.float64()),
        "amount": pa.array(amounts, type=pa.float64()),
        "adj_factor": pa.array(adjs, type=pa.float64()),
    })


def _table_to_bars(table: pa.Table) -> List[dict]:
    """Read parquet rows back into bar dicts (keyed by lowercase fields).

    Normalizes trade_time through `_to_utc` so bars read from disk share the
    same tz-aware UTC labeling as bars produced by `gm_api.history_bars`,
    enabling correct dedup/merge.
    """
    if table.num_rows == 0:
        return []
    cols = {name: table.column(name).to_pylist() for name in table.column_names}
    out: List[dict] = []
    n = table.num_rows
    for i in range(n):
        bob = _to_utc(cols["trade_time"][i])
        out.append({
            "bob": bob,
            "eob": bob,
            "open": cols["open"][i],
            "close": cols["close"][i],
            "high": cols["high"][i],
            "low": cols["low"][i],
            "volume": cols["volume"][i],
            "amount": cols["amount"][i],
        })
    return out


def _write_file(file_path: str, bars: List[dict], ts_code: str) -> None:
    table = _bars_to_table(bars, ts_code)
    pq.write_table(table, file_path, compression="snappy")


def _read_file(file_path: str) -> List[dict]:
    if not os.path.exists(file_path):
        return []
    table = pq.read_table(file_path)
    return _table_to_bars(table)


def _normalize_bars(bars: Iterable[dict]) -> List[dict]:
    """Ensure every bar's `bob`/`eob` is tz-aware UTC (matches existing file schema).

    Bars read from disk via `_table_to_bars` are already normalized; bars from
    `gm_api.history_bars` may be naive Beijing wall-clock or pandas Timestamps
    with +08:00 — both get coerced to the same tz-aware UTC labeling so dedup
    keys match.
    """
    out: List[dict] = []
    for b in bars:
        nb = dict(b)
        nb["bob"] = _to_utc(nb.get("bob") or nb.get("eob"))
        nb["eob"] = nb["bob"]
        out.append(nb)
    return out


def _dedup_merge(existing: List[dict], new: List[dict]) -> List[dict]:
    """Merge by `bob` timestamp; new wins on collision. Sorted ascending.

    Assumes both sides already passed through `_normalize_bars` (tz-aware UTC).
    """
    by_key = {}
    for b in existing:
        by_key[b["bob"]] = b
    for b in new:
        by_key[b["bob"]] = b
    return sorted(by_key.values(), key=lambda b: b["bob"])


class MinuteParquetStorage:
    """Per-year file layout: `<root>/<CODE>_<YEAR>.parquet`.

    Also maintains the `kline_min_metadata` table in PostgreSQL so the existing
    C#-era metadata stays consistent. Used by kline_incremental and kline_full.
    """

    def __init__(self, root_dir: str, pg_conn: dict = None):
        self.root_dir = root_dir
        os.makedirs(root_dir, exist_ok=True)
        self.pg_conn = pg_conn
        if pg_conn:
            self._ensure_metadata_table()

    def _ensure_metadata_table(self) -> None:
        """Create the kline_min_metadata table in PostgreSQL if it does not exist."""
        import psycopg2
        with psycopg2.connect(**self.pg_conn) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS kline_min_metadata (
                        symbol VARCHAR(20) NOT NULL,
                        trade_date DATE,
                        year INTEGER NOT NULL,
                        month INTEGER,
                        file_path VARCHAR(500),
                        file_size BIGINT,
                        row_count INTEGER,
                        first_time TIMESTAMP,
                        last_time TIMESTAMP,
                        status VARCHAR(20) DEFAULT 'pending',
                        error_message TEXT,
                        retry_count INTEGER DEFAULT 0,
                        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        days_collected INTEGER,
                        PRIMARY KEY (symbol, year)
                    );
                    CREATE INDEX IF NOT EXISTS idx_kline_min_metadata_symbol
                        ON kline_min_metadata(symbol);
                    CREATE INDEX IF NOT EXISTS idx_kline_min_metadata_date
                        ON kline_min_metadata(trade_date);
                    CREATE INDEX IF NOT EXISTS idx_kline_min_metadata_status
                        ON kline_min_metadata(status);
                """)
            conn.commit()

    def save_bars(self, gm_symbol: str, year: int, bars: List[dict]) -> str:
        """Overwrite-write. Returns file path. Used by kline_full."""
        if not bars:
            return ""
        ts_code = gm_to_ts_code(gm_symbol)
        file_path = os.path.join(self.root_dir, f"{ts_code}_{year}.parquet")
        _write_file(file_path, bars, ts_code)
        self._upsert_metadata(gm_symbol, ts_code, year, len(bars), file_path, bars)
        return file_path

    def append_bars(self, gm_symbol: str, year: int, new_bars: List[dict]) -> Tuple[str, int]:
        """Read-merge-dedupe-rewrite. Returns (file_path, net_new_rows). Used by incremental."""
        if not new_bars:
            return "", 0
        ts_code = gm_to_ts_code(gm_symbol)
        file_path = os.path.join(self.root_dir, f"{ts_code}_{year}.parquet")
        existing = _read_file(file_path)
        new_normalized = _normalize_bars(new_bars)
        before = len(existing)
        merged = _dedup_merge(existing, new_normalized)
        added = len(merged) - before
        _write_file(file_path, merged, ts_code)
        self._upsert_metadata(gm_symbol, ts_code, year, len(merged), file_path, merged)
        logger.info("Minute appended %d new rows (total %d) to %s",
                    added, len(merged), file_path)
        return file_path, added

    def _upsert_metadata(self, gm_symbol: str, ts_code: str, year: int,
                         count: int, file_path: str, bars: List[dict]) -> None:
        if not self.pg_conn:
            return
        import psycopg2
        size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        first = min(b["bob"] for b in bars)
        last = max(b["bob"] for b in bars)
        with psycopg2.connect(**self.pg_conn) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO kline_min_metadata
                        (symbol, trade_date, year, month, file_path, file_size,
                         row_count, first_time, last_time, status)
                    VALUES (%(symbol)s, %(trade_date)s, %(year)s, 1, %(file_path)s,
                            %(file_size)s, %(row_count)s, %(first_time)s, %(last_time)s, 'completed')
                    ON CONFLICT (symbol, year) DO UPDATE SET
                        file_path = EXCLUDED.file_path,
                        file_size = EXCLUDED.file_size,
                        row_count = EXCLUDED.row_count,
                        first_time = EXCLUDED.first_time,
                        last_time = EXCLUDED.last_time,
                        status = EXCLUDED.status,
                        updated_at = CURRENT_TIMESTAMP
                """, {
                    "symbol": ts_code,
                    "trade_date": f"{year}-01-01",
                    "year": year,
                    "file_path": file_path,
                    "file_size": size,
                    "row_count": count,
                    "first_time": first,
                    "last_time": last,
                })
            conn.commit()


class DailyParquetStorage:
    """Single file per symbol: `<root>/<CODE>.parquet` (no year suffix)."""

    def __init__(self, root_dir: str):
        self.root_dir = root_dir
        os.makedirs(root_dir, exist_ok=True)

    def save_bars_all(self, gm_symbol: str, bars: List[dict]) -> str:
        """Overwrite-write all daily bars for a symbol. Returns file path."""
        if not bars:
            return ""
        ts_code = gm_to_ts_code(gm_symbol)
        file_path = os.path.join(self.root_dir, f"{ts_code}.parquet")
        _write_file(file_path, bars, ts_code)
        return file_path

    def append_bars_all(self, gm_symbol: str, new_bars: List[dict]) -> Tuple[str, int]:
        """Read-merge-dedupe-rewrite daily bars. Returns (file_path, net_new_rows)."""
        if not new_bars:
            return "", 0
        ts_code = gm_to_ts_code(gm_symbol)
        file_path = os.path.join(self.root_dir, f"{ts_code}.parquet")
        existing = _read_file(file_path)
        new_normalized = _normalize_bars(new_bars)
        before = len(existing)
        merged = _dedup_merge(existing, new_normalized)
        added = len(merged) - before
        _write_file(file_path, merged, ts_code)
        logger.info("Daily appended %d new rows (total %d) to %s",
                    added, len(merged), file_path)
        return file_path, added
