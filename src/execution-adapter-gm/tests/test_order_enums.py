"""Unit tests for ``broker.enums``.

Validates the Proto <-> GM SDK integer mappings documented at the top of
``broker/enums.py``. The expected integer values are taken directly from
the installed ``gm.api`` module so the tests stay correct even if the SDK
ships different constants on another platform.

Proto side (gm_trading.proto):
  Side:        0=Buy, 1=Sell
  OrderType:   0=Market, 1=Limit, 2=Stop

GM SDK side:
  OrderSide:   1=Buy, 2=Sell
  OrderType:   2=Market, 1=Limit, 3=Stop
"""
import pytest

# The gm SDK is required to read canonical Side/OrderType constants.
# In environments without gm installed (e.g. CI running the shared
# strategy-engine venv), skip the entire module instead of erroring
# during collection.
gm = pytest.importorskip("gm")
from gm.api import (  # noqa: E402
    OrderSide_Buy,
    OrderSide_Sell,
    OrderType_Limit,
    OrderType_Market,
    OrderType_Stop,
)

from broker.enums import (
    ProtoOrderStatus,
    ProtoOrderType,
    ProtoSide,
    gm_status_to_proto,
    is_gm_status_final,
    position_effect_open,
    proto_order_type_to_gm,
    proto_side_to_gm,
)


# ---------- proto_side_to_gm ----------

def test_buy_side_mapping():
    """Proto Side.BUY (0) -> GM OrderSide_Buy (1)."""
    assert proto_side_to_gm(ProtoSide.BUY) == OrderSide_Buy
    assert proto_side_to_gm(ProtoSide.BUY) == 1


def test_sell_side_mapping():
    """Proto Side.SELL (1) -> GM OrderSide_Sell (2)."""
    assert proto_side_to_gm(ProtoSide.SELL) == OrderSide_Sell
    assert proto_side_to_gm(ProtoSide.SELL) == 2


def test_proto_side_unknown_raises():
    """An unmapped side must raise ValueError, not silently return 0."""
    with pytest.raises(ValueError, match="Unknown order side"):
        proto_side_to_gm(99)


# ---------- proto_order_type_to_gm ----------

def test_market_order_type():
    """Proto OrderType.MARKET (0) -> GM OrderType_Market (2)."""
    assert proto_order_type_to_gm(ProtoOrderType.MARKET) == OrderType_Market
    assert proto_order_type_to_gm(ProtoOrderType.MARKET) == 2


def test_limit_order_type():
    """Proto OrderType.LIMIT (1) -> GM OrderType_Limit (1)."""
    assert proto_order_type_to_gm(ProtoOrderType.LIMIT) == OrderType_Limit
    assert proto_order_type_to_gm(ProtoOrderType.LIMIT) == 1


def test_stop_order_type():
    """Proto OrderType.STOP (2) -> GM OrderType_Stop (3)."""
    assert proto_order_type_to_gm(ProtoOrderType.STOP) == OrderType_Stop
    assert proto_order_type_to_gm(ProtoOrderType.STOP) == 3


def test_proto_order_type_unknown_raises():
    """An unmapped order type must raise ValueError."""
    with pytest.raises(ValueError, match="Unknown order type"):
        proto_order_type_to_gm(42)


# ---------- gm_status_to_proto (bonus coverage) ----------

def test_gm_status_filled_to_proto():
    """GM Filled -> Proto FILLED."""
    from gm.api import OrderStatus_Filled
    assert gm_status_to_proto(OrderStatus_Filled) == ProtoOrderStatus.FILLED


def test_gm_status_rejected_to_proto():
    """GM Rejected -> Proto REJECTED."""
    from gm.api import OrderStatus_Rejected
    assert gm_status_to_proto(OrderStatus_Rejected) == ProtoOrderStatus.REJECTED


def test_gm_status_canceled_to_proto():
    """GM Canceled -> Proto CANCELLED."""
    from gm.api import OrderStatus_Canceled
    assert gm_status_to_proto(OrderStatus_Canceled) == ProtoOrderStatus.CANCELLED


def test_gm_status_partially_filled_to_proto():
    """GM PartiallyFilled -> Proto PARTIAL."""
    from gm.api import OrderStatus_PartiallyFilled
    assert gm_status_to_proto(OrderStatus_PartiallyFilled) == ProtoOrderStatus.PARTIAL


def test_gm_status_new_to_proto_pending():
    """GM New (accepted by broker) -> Proto PENDING (not yet final)."""
    from gm.api import OrderStatus_New
    assert gm_status_to_proto(OrderStatus_New) == ProtoOrderStatus.PENDING


def test_gm_status_unknown_to_proto_pending():
    """GM Unknown -> Proto PENDING."""
    from gm.api import OrderStatus_Unknown
    assert gm_status_to_proto(OrderStatus_Unknown) == ProtoOrderStatus.PENDING


def test_gm_status_unmapped_defaults_to_pending():
    """An unmapped GM status defaults to PENDING (safe fallthrough)."""
    assert gm_status_to_proto(999) == ProtoOrderStatus.PENDING


# ---------- is_gm_status_final ----------

def test_is_gm_status_final_true():
    """Filled / Canceled / Rejected are final."""
    from gm.api import OrderStatus_Canceled, OrderStatus_Filled, OrderStatus_Rejected
    assert is_gm_status_final(OrderStatus_Filled) is True
    assert is_gm_status_final(OrderStatus_Canceled) is True
    assert is_gm_status_final(OrderStatus_Rejected) is True


def test_is_gm_status_final_false():
    """Unknown / New / PartiallyFilled are NOT final."""
    from gm.api import (
        OrderStatus_New,
        OrderStatus_PartiallyFilled,
        OrderStatus_Unknown,
    )
    assert is_gm_status_final(OrderStatus_Unknown) is False
    assert is_gm_status_final(OrderStatus_New) is False
    assert is_gm_status_final(OrderStatus_PartiallyFilled) is False


# ---------- position_effect_open ----------

def test_position_effect_open_returns_int():
    """position_effect_open() returns the GM PositionEffect_Open constant."""
    from gm.api import PositionEffect_Open
    assert position_effect_open() == PositionEffect_Open
    assert isinstance(position_effect_open(), int)
