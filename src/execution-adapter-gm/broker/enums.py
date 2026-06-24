"""Proto ↔ GM SDK enum mapping.

Mirrors C# `execution_adapter_gm.Utils.OrderEnums.cs`. The integer values
on the wire are the **Proto** values; the GM SDK uses its own ints.

Proto side (gm_trading.proto):
  Side:        0=Buy, 1=Sell
  OrderType:   0=Market, 1=Limit, 2=Stop
  OrderStatus: 0=Pending, 1=Filled, 2=Rejected, 3=Cancelled, 4=Partial, 5=Expired

GM SDK side:
  OrderSide:   1=Buy, 2=Sell, 0=Unknown
  OrderType:   2=Market, 1=Limit, 3=Stop, 0=Unknown
  OrderStatus: 0=Unknown, 1=Submitted/New, 2=PartiallyFilled, 3=Filled,
               4=Cancelled, 5=Rejected (plus extras not used here)
"""
from __future__ import annotations

from gm.api import (
    OrderSide_Buy,
    OrderSide_Sell,
    OrderType_Limit,
    OrderType_Market,
    OrderType_Stop,
    OrderStatus_Canceled,
    OrderStatus_Filled,
    OrderStatus_New,
    OrderStatus_PartiallyFilled,
    OrderStatus_Rejected,
    OrderStatus_Unknown,
    PositionEffect_Open,
)


# ---------- Proto constants ----------

class ProtoSide:
    BUY = 0
    SELL = 1


class ProtoOrderType:
    MARKET = 0
    LIMIT = 1
    STOP = 2


class ProtoOrderStatus:
    PENDING = 0
    FILLED = 1
    REJECTED = 2
    CANCELLED = 3
    PARTIAL = 4
    EXPIRED = 5


# ---------- Proto → GM SDK ----------

_PROTO_SIDE_TO_GM = {
    ProtoSide.BUY: OrderSide_Buy,
    ProtoSide.SELL: OrderSide_Sell,
}

_PROTO_TYPE_TO_GM = {
    ProtoOrderType.MARKET: OrderType_Market,
    ProtoOrderType.LIMIT: OrderType_Limit,
    ProtoOrderType.STOP: OrderType_Stop,
}


def proto_side_to_gm(side: int) -> int:
    """Map a Proto Side int to a GM SDK OrderSide int."""
    if side not in _PROTO_SIDE_TO_GM:
        raise ValueError(f"Unknown order side: {side}")
    return _PROTO_SIDE_TO_GM[side]


def proto_order_type_to_gm(order_type: int) -> int:
    """Map a Proto OrderType int to a GM SDK OrderType int."""
    if order_type not in _PROTO_TYPE_TO_GM:
        raise ValueError(f"Unknown order type: {order_type}")
    return _PROTO_TYPE_TO_GM[order_type]


def position_effect_open() -> int:
    """Default position effect for buy/sell of stocks."""
    return PositionEffect_Open


# ---------- GM SDK → Proto ----------

_GM_STATUS_TO_PROTO = {
    OrderStatus_Unknown: ProtoOrderStatus.PENDING,
    OrderStatus_New: ProtoOrderStatus.PENDING,
    # Submitted in C# == OrderStatus_New in Python SDK (both mean "accepted by broker")
    OrderStatus_PartiallyFilled: ProtoOrderStatus.PARTIAL,
    OrderStatus_Filled: ProtoOrderStatus.FILLED,
    OrderStatus_Canceled: ProtoOrderStatus.CANCELLED,
    OrderStatus_Rejected: ProtoOrderStatus.REJECTED,
}


def gm_status_to_proto(status: int) -> int:
    """Map a GM SDK OrderStatus int to a Proto OrderStatus int.

    Unknown values default to PENDING (matches C# fallthrough for safety).
    """
    if status in _GM_STATUS_TO_PROTO:
        return _GM_STATUS_TO_PROTO[status]
    # Unknown statuses (PendingCancel, PendingReplace, Suspended, etc.) are
    # not final — return PENDING so PlaceOrder keeps waiting.
    return ProtoOrderStatus.PENDING


def is_gm_status_final(status: int) -> bool:
    """Match `IsOrderFinal` in C#: Filled / Cancelled / Rejected."""
    return status in (OrderStatus_Filled, OrderStatus_Canceled, OrderStatus_Rejected)
