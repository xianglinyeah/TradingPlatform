"""ClickHouse storage for k-line bars (clickhouse-connect HTTP client).

Tables `kline_1min` and `kline_daily` live in the configured database
(default: market_data). Beijing wall-clock instants are stored as naive
DateTime values (e.g. 09:30 stays 09:30); `_strip_tz` enforces this before
sending values to ClickHouse.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import clickhouse_connect

logger = logging.getLogger(__name__)


TABLE_1MIN = "kline_1min"
TABLE_DAILY = "kline_daily"

INSERT_COLUMNS = [
    "trade_time", "ts_code", "open", "close", "high", "low",
    "volume", "amount", "adj_factor",
]


def _strip_tz(v):
    """If v is a tz-aware datetime, return the same wall-clock as naive.
    Required for ClickHouse DateTime columns (which are timezone-naive)."""
    if v is None:
        return None
    if hasattr(v, "tzinfo") and v.tzinfo is not None:
        return v.replace(tzinfo=None)
    return v


class ClickHouseStorage:
    """ClickHouse client for k-line bar storage (insert, delete-range, last-bar lookup)."""

    def __init__(self, host: str = "localhost", port: int = 32123,
                 user: str = "dev_user", password: str = "dev_pass",
                 database: str = "market_data"):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.database = database

    def _client(self) -> "clickhouse_connect.driver.Client":
        """Create a short-lived ClickHouse HTTP client."""
        return clickhouse_connect.get_client(
            host=self.host, port=self.port,
            username=self.user, password=self.password,
            database=self.database,
        )

    def _fq(self, table: str) -> str:
        return f"{self.database}.{table}"

    def get_last_bar_time(self, table: str, ts_code: str) -> Optional[datetime]:
        sql = f"SELECT max(trade_time) FROM {self._fq(table)} WHERE ts_code = %(ts)s"
        with self._client() as c:
            res = c.query(sql, parameters={"ts": ts_code})
        if not res.result_rows:
            return None
        val = res.result_rows[0][0]
        if val is None:
            return None
        # clickhouse-connect may return datetime or pandas.Timestamp
        if hasattr(val, "to_pydatetime"):
            val = val.to_pydatetime()
        return val

    def delete_range(self, table: str, ts_code: str,
                     from_dt: datetime, to_dt: datetime) -> None:
        sql = (
            f"ALTER TABLE {self._fq(table)} "
            "DELETE WHERE ts_code = %(ts)s "
            "AND trade_time >= %(from)s AND trade_time <= %(to)s "
            "SETTINGS mutations_sync = 2"
        )
        with self._client() as c:
            c.command(sql, parameters={
                "ts": ts_code,
                "from": _strip_tz(from_dt),
                "to": _strip_tz(to_dt),
            })
        logger.info("CH deleted %s/%s range [%s, %s]", table, ts_code, from_dt, to_dt)

    def insert_bars(self, table: str, bars: List[dict], ts_code: str) -> int:
        """Insert bars into ClickHouse. Returns number of rows inserted."""
        if not bars:
            logger.info("CH insert skipped: %s/%s has 0 bars", table, ts_code)
            return 0

        def _f(b, k):
            v = b.get(k)
            return 0.0 if v is None else float(v)

        rows = [
            (
                _strip_tz(b.get("bob") or b.get("eob")),
                ts_code,
                _f(b, "open"),
                _f(b, "close"),
                _f(b, "high"),
                _f(b, "low"),
                _f(b, "volume"),
                _f(b, "amount"),
                1.0,
            )
            for b in bars
        ]
        with self._client() as c:
            c.insert(self._fq(table), rows, column_names=INSERT_COLUMNS)
        logger.info("CH inserted %d rows into %s/%s", len(rows), table, ts_code)
        return len(rows)

    def delete_ranges_batch(self, table: str,
                            ranges: List[tuple]) -> int:
        """Delete multiple (ts_code, from_dt, to_dt) ranges in one ALTER TABLE.
        Combining N ranges into one mutation is faster than N separate
        `ALTER TABLE ... DELETE` calls (ClickHouse mutation has fixed overhead).

        Returns the number of ranges included.
        """
        if not ranges:
            return 0

        import re
        # ts_code is interpolated into the SQL string below. The regex check
        # before interpolation allows only "6 digits + dot + 2 uppercase letters"
        # (e.g. "600000.SH"), which is too restrictive to carry an injection
        # payload. ClickHouse.Client parameterized placeholders are not supported
        # for ALTER TABLE ... DELETE WHERE, so f-string with strict validation
        # is the only viable approach here.
        ts_code_re = re.compile(r"^\d{6}\.[A-Z]{2}$")
        or_clauses = []
        for ts_code, from_dt, to_dt in ranges:
            if not ts_code_re.match(ts_code):
                raise ValueError(f"invalid ts_code format: {ts_code!r}")
            from_str = _strip_tz(from_dt).strftime("%Y-%m-%d %H:%M:%S")
            to_str = _strip_tz(to_dt).strftime("%Y-%m-%d %H:%M:%S")
            or_clauses.append(
                f"(ts_code = '{ts_code}' "
                f"AND trade_time >= '{from_str}' "
                f"AND trade_time <= '{to_str}')"
            )

        sql = (
            f"ALTER TABLE {self._fq(table)} "
            f"DELETE WHERE {' OR '.join(or_clauses)} "
            "SETTINGS mutations_sync = 2"
        )
        with self._client() as c:
            c.command(sql)
        logger.info("CH batch deleted %d ranges from %s", len(ranges), table)
        return len(ranges)

    def insert_bars_batch(self, table: str,
                          bars_by_tscode: dict) -> int:
        """Insert bars for multiple ts_codes in one INSERT call.

        `bars_by_tscode` maps ts_code -> [bar_dicts, ...]. Returns the total
        number of rows inserted.
        """
        def _f(b, k):
            v = b.get(k)
            return 0.0 if v is None else float(v)

        all_rows = []
        for ts_code, bars in bars_by_tscode.items():
            for b in bars:
                all_rows.append((
                    _strip_tz(b.get("bob") or b.get("eob")),
                    ts_code,
                    _f(b, "open"),
                    _f(b, "close"),
                    _f(b, "high"),
                    _f(b, "low"),
                    _f(b, "volume"),
                    _f(b, "amount"),
                    1.0,
                ))

        if not all_rows:
            return 0

        with self._client() as c:
            c.insert(self._fq(table), all_rows, column_names=INSERT_COLUMNS)
        logger.info("CH batch inserted %d rows into %s (%d symbols)",
                    len(all_rows), table, len(bars_by_tscode))
        return len(all_rows)
