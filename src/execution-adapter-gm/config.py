"""Configuration loader for execution-adapter-gm (Python).

Mirrors the C# `GMSettings` from `appsettings.json` section `GM` 1:1, plus
gRPC Kestrel config (now under `grpc`) and schedule tunables.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import yaml


@dataclass
class GmConfig:
    token: str = ""
    address: str = "127.0.0.1:7001"
    strategy_id: str = "gm-trading-adaptor"
    paper_account_id: str = ""
    live_account_id: str = ""


@dataclass
class GrpcConfig:
    listen: str = "0.0.0.0:5005"
    workers: int = 4


@dataclass
class ScheduleConfig:
    poll_frequency_ms: int = 200
    session_start: str = "09:15"
    session_end: str = "15:30"


@dataclass
class OrderConfig:
    default_timeout_seconds: int = 30


@dataclass
class LoggingConfig:
    level: str = "INFO"
    dir: str = "logs/execution-adapters-gm"


@dataclass
class AdapterConfig:
    gm: GmConfig = field(default_factory=GmConfig)
    grpc: GrpcConfig = field(default_factory=GrpcConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    order: OrderConfig = field(default_factory=OrderConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)


def _coerce(cls, data: dict):
    """Instantiate a dataclass from a dict, silently ignoring unknown keys."""
    if data is None:
        return cls()
    known = cls.__dataclass_fields__
    kwargs = {k: v for k, v in data.items() if k in known}
    return cls(**kwargs)


def load_config(config_path: str = "config.yaml") -> AdapterConfig:
    import os

    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    cfg = AdapterConfig()
    cfg.gm = _coerce(GmConfig, raw.get("gm"))
    cfg.grpc = _coerce(GrpcConfig, raw.get("grpc"))
    cfg.schedule = _coerce(ScheduleConfig, raw.get("schedule"))
    cfg.order = _coerce(OrderConfig, raw.get("order"))
    cfg.logging = _coerce(LoggingConfig, raw.get("logging"))

    # Secret overrides: env vars take precedence so secrets are not committed.
    gm_token_env = os.getenv("GM_TOKEN")
    if gm_token_env:
        cfg.gm.token = gm_token_env
    paper_acct_env = os.getenv("GM_PAPER_ACCOUNT_ID")
    if paper_acct_env:
        cfg.gm.paper_account_id = paper_acct_env
    live_acct_env = os.getenv("GM_LIVE_ACCOUNT_ID")
    if live_acct_env:
        cfg.gm.live_account_id = live_acct_env

    return cfg
