"""MarketDataEvent model + JSON serialization.

The JSON shape MUST be byte-compatible with the C# version that StrategyService
is already consuming. Field order, types, and Symbol format ("600000.SH") match
the C# `MarketData.Replay.Models.MarketDataEvent`.

C# uses `System.Text.Json.JsonSerializer.Serialize` with default options:
- PascalCase property names (preserved verbatim)
- DateTime serialized as ISO 8601 with timezone offset
- `decimal` serialized as plain number

We reproduce that with a fixed key order and explicit float coercion.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# Canonical key order — must match C# property declaration order in
# MarketData.Replay/Models/MarketDataEvent.cs.
_EVENT_KEYS = (
    "Symbol",
    "EventTime",
    "ReplayTime",
    "Open",
    "High",
    "Low",
    "Close",
    "Volume",
    "Amount",
    "SessionId",
    "SequenceNumber",
    "Source",
)


@dataclass
class MarketDataEvent:
    Symbol: str
    EventTime: str
    ReplayTime: str
    Open: float
    High: float
    Low: float
    Close: float
    Volume: float
    Amount: float
    SessionId: str
    SequenceNumber: int
    Source: str

    def to_json(self) -> str:
        """Serialize to JSON with C#-compatible key order and types.

        Floats that are integral (e.g. 10000.0) render without a fractional
        part (matching C# `decimal` serialization of whole numbers).
        """
        payload: dict[str, Any] = {}
        for k in _EVENT_KEYS:
            v = getattr(self, k)
            if isinstance(v, float) and v.is_integer():
                # Emit as int ("10000" instead of "10000.0") to match C# decimal JSON output.
                payload[k] = int(v)
            else:
                payload[k] = v
        return json.dumps(payload, separators=(", ", ": "))


def from_gm_bar(
    bar: Any,
    *,
    symbol_converter,
    session_id: str,
    sequence_number: int,
    replay_time: datetime,
) -> MarketDataEvent:
    """Convert a GM SDK bar object to a MarketDataEvent.

    `symbol_converter` is `services.symbol_converter.from_gm` (injected here to
    avoid a hard import cycle, and to keep this module pure).
    """
    symbol = symbol_converter(getattr(bar, "symbol", ""))
    eob = getattr(bar, "eob", None)
    event_time_str = _format_datetime(eob)
    replay_time_str = _format_datetime(replay_time)

    return MarketDataEvent(
        Symbol=symbol,
        EventTime=event_time_str,
        ReplayTime=replay_time_str,
        Open=float(getattr(bar, "open", 0.0)),
        High=float(getattr(bar, "high", 0.0)),
        Low=float(getattr(bar, "low", 0.0)),
        Close=float(getattr(bar, "close", 0.0)),
        Volume=float(getattr(bar, "volume", 0.0)),
        Amount=float(getattr(bar, "amount", 0.0)),
        SessionId=session_id,
        SequenceNumber=int(sequence_number),
        Source="GM",
    )


def _format_datetime(dt: Any) -> str:
    """Format a datetime as ISO 8601 with timezone offset (C#-compatible).

    Mirrors `System.Text.Json` default DateTime serialization:
    - UTC aware → "2026-06-22T01:30:00Z"
    - Other aware → "2026-06-22T09:30:00+08:00" (offset as +HH:MM)
    - naive → assume Beijing local, append "+08:00"
    """
    if dt is None:
        return "0001-01-01T00:00:00"

    # Handle pandas.Timestamp without importing pandas
    if hasattr(dt, "to_pydatetime"):
        dt = dt.to_pydatetime()

    if not isinstance(dt, datetime):
        return str(dt)

    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.tzinfo is None:
        # Beijing time without tz info
        return base + "+08:00"

    # aware datetime
    offset = dt.utcoffset()
    if offset is None or offset.total_seconds() == 0:
        return base + "Z"
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hh = abs(total_minutes) // 60
    mm = abs(total_minutes) % 60
    return base + f"{sign}{hh:02d}:{mm:02d}"
