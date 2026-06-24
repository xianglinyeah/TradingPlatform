"""Configuration loader for market-data-gm (Python).

Mirrors the C# `GMConfig` from `appsettings.json` section `GM` 1:1.
YAML keys use the same names as the C# properties, lowercased per YAML convention.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

import yaml


@dataclass
class GmConfig:
    token: str = ""
    address: str = "127.0.0.1:7001"
    symbols: List[str] = field(default_factory=list)
    frequency: str = "60s"


@dataclass
class KafkaConfig:
    bootstrap_servers: str = "localhost:9092"
    market_data_topic: str = "market.data"
    control_topic: str = "replay.control"
    client_id: str = "gm-market-data-realtime"


@dataclass
class LoggingConfig:
    level: str = "INFO"
    dir: str = "logs/marketdata-gm"


@dataclass
class MarketDataConfig:
    gm: GmConfig = field(default_factory=GmConfig)
    kafka: KafkaConfig = field(default_factory=KafkaConfig)
    session_id_prefix: str = "gm-realtime"
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def _coerce(cls, data: dict):
    """Instantiate a dataclass from a dict, silently ignoring unknown keys."""
    if data is None:
        return cls()
    known = cls.__dataclass_fields__
    kwargs = {k: v for k, v in data.items() if k in known}
    return cls(**kwargs)


def load_config(config_path: str = "config.yaml") -> MarketDataConfig:
    import os

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    cfg = MarketDataConfig()
    cfg.gm = _coerce(GmConfig, raw.get("gm"))
    cfg.kafka = _coerce(KafkaConfig, raw.get("kafka"))
    cfg.logging = _coerce(LoggingConfig, raw.get("logging"))
    if "session_id_prefix" in raw:
        cfg.session_id_prefix = raw["session_id_prefix"]

    # Secret overrides: env vars take precedence so secrets are not committed.
    gm_token_env = os.getenv("GM_TOKEN")
    if gm_token_env:
        cfg.gm.token = gm_token_env

    return cfg
