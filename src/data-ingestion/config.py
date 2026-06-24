"""Configuration loader for data_ingestion.

Mirrors the C# data_ingestion Config/IngestionConfig.cs layout 1:1. YAML keys
use underscore_naming (matching YamlDotNet's UnderscoredNamingConvention).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import yaml


@dataclass
class GmConfig:
    token: str = ""
    address: str = "127.0.0.1:7001"


@dataclass
class StorageConfig:
    parquet_path: str = ""
    connection_string: str = ""


@dataclass
class MarketScopeConfig:
    scope_type: str = "SSE50"
    custom_symbols: List[str] = field(default_factory=list)


@dataclass
class DataConfig:
    frequency: str = "60s"
    start_year: int = 2016
    end_year: int = 2026


@dataclass
class ProcessingConfig:
    batch_size: int = 100
    retry_count: int = 3
    delay_between_requests: int = 100


@dataclass
class ClickHouseConfig:
    host: str = "localhost"
    port: int = 32123
    user: str = "dev_user"
    password: str = "dev_pass"
    database: str = "market_data"


@dataclass
class FundamentalsConfig:
    start_date: str = "2005-01-01"
    end_date: Optional[str] = None
    symbol_source: str = "CSI_ALL"
    symbols: List[str] = field(default_factory=list)
    daily_dir: str = r"D:\TradingPlatform\data\daily"
    symbols_cache_file: str = "symbols_cache.txt"
    request_delay_ms: int = 200
    retry_count: int = 2
    rpt_type: int = 0
    data_type: int = 0

    @property
    def symbol_filter(self) -> List[str]:
        return self.symbols


@dataclass
class FundamentalsIncrementalConfig:
    daily_lookback_days: int = 7
    quarterly_lookback_days: int = 30
    safety_buffer_days: int = 2
    max_gap_days: int = 180
    start_date: str = ""
    end_date: str = ""
    symbol_source: str = "CSI_ALL"
    symbols: List[str] = field(default_factory=list)
    symbol_filter: List[str] = field(default_factory=list)
    daily_dir: str = r"D:\TradingPlatform\data\daily"
    symbols_cache_file: str = "symbols_cache.txt"
    request_delay_ms: int = 200
    retry_count: int = 2
    rpt_type: int = 0
    data_type: int = 0


@dataclass
class KlineIncrementalConfig:
    minute_lookback_days: int = 7
    daily_lookback_days: int = 10
    safety_buffer_days: int = 1
    max_gap_days: int = 30
    symbol_source: str = "CSI_ALL"
    symbols: List[str] = field(default_factory=list)
    symbol_filter: List[str] = field(default_factory=list)
    daily_dir: str = r"D:\TradingPlatform\data\daily"
    minute_dir: str = r"D:\TradingPlatform\data\minute\1min"
    symbols_cache_file: str = "symbols_cache_kline.txt"
    request_delay_ms: int = 200
    retry_count: int = 2
    clickhouse: ClickHouseConfig = field(default_factory=ClickHouseConfig)


@dataclass
class IngestionConfig:
    gm: GmConfig = field(default_factory=GmConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    market_scope: MarketScopeConfig = field(default_factory=MarketScopeConfig)
    data: DataConfig = field(default_factory=DataConfig)
    processing: ProcessingConfig = field(default_factory=ProcessingConfig)
    fundamentals: FundamentalsConfig = field(default_factory=FundamentalsConfig)
    fundamentals_incremental: FundamentalsIncrementalConfig = field(default_factory=FundamentalsIncrementalConfig)
    kline_incremental: KlineIncrementalConfig = field(default_factory=KlineIncrementalConfig)


def _coerce_section(cls, data: dict):
    """Instantiate a dataclass from a dict, silently ignoring unknown keys.

    Recursively coerces nested dataclass-typed fields (e.g. KlineIncrementalConfig.clickhouse).
    """
    if data is None:
        return cls()
    known = cls.__dataclass_fields__
    kwargs = {}
    for k, v in data.items():
        if k not in known:
            continue
        ftype = known[k].type
        # Resolve string annotations (e.g. "ClickHouseConfig" or "Optional[str]").
        if isinstance(ftype, str):
            ftype = globals().get(ftype) or _resolve_type_hint(cls, ftype)
        if isinstance(v, dict) and ftype and hasattr(ftype, "__dataclass_fields__"):
            kwargs[k] = _coerce_section(ftype, v)
        else:
            kwargs[k] = v
    return cls(**kwargs)


def _resolve_type_hint(cls, name: str):
    """Try to resolve a string type annotation to a class in this module."""
    if name in globals():
        return globals()[name]
    return None


def load_config(config_path: str = "config.yaml") -> IngestionConfig:
    import os

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    cfg = IngestionConfig()
    cfg.gm = _coerce_section(GmConfig, raw.get("gm"))
    cfg.storage = _coerce_section(StorageConfig, raw.get("storage"))
    cfg.market_scope = _coerce_section(MarketScopeConfig, raw.get("market_scope"))
    cfg.data = _coerce_section(DataConfig, raw.get("data"))
    cfg.processing = _coerce_section(ProcessingConfig, raw.get("processing"))
    cfg.fundamentals = _coerce_section(FundamentalsConfig, raw.get("fundamentals"))
    cfg.fundamentals_incremental = _coerce_section(
        FundamentalsIncrementalConfig, raw.get("fundamentals_incremental")
    )
    cfg.kline_incremental = _coerce_section(KlineIncrementalConfig, raw.get("kline_incremental"))

    # Secret overrides: env vars take precedence over yaml so secrets are not
    # committed to source control. YAML can leave them empty or use a placeholder.
    gm_token_env = os.getenv("GM_TOKEN")
    if gm_token_env:
        cfg.gm.token = gm_token_env

    return cfg


def parse_pg_conn(conn_str: str) -> dict:
    """Parse a Npgsql-style 'Host=...;Port=...;Username=...;Password=...;Database=...' string."""
    parts = {}
    for token in (conn_str or "").split(";"):
        token = token.strip()
        if not token or "=" not in token:
            continue
        k, v = token.split("=", 1)
        parts[k.strip().lower()] = v.strip()
    return {
        "host": parts.get("host", "localhost"),
        "port": int(parts.get("port", "5432")),
        "user": parts.get("username") or parts.get("user", ""),
        "password": parts.get("password", ""),
        "dbname": parts.get("database") or parts.get("dbname", ""),
    }
