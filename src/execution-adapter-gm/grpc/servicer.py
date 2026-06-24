"""gRPC service implementation.

Mirrors C# `execution_adapter_gm.Services.GMTradingGrpcService`. The five RPCs
match `proto/gm_trading.proto` byte-for-byte.

Threading model:
  PlaceOrder → enqueue job → block on Future (30s)
  CancelOrder → direct call (cross-thread safe per C#)
  GetCash/GetPosition/GetOrders → direct query calls
"""
from __future__ import annotations

import logging
import queue
from concurrent.futures import Future, TimeoutError as FutureTimeoutError
from datetime import datetime

import grpc

import sys
import os
# Make the proto stubs importable when this servicer is loaded.
_PROTO_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "protos")
if _PROTO_DIR not in sys.path:
    sys.path.insert(0, _PROTO_DIR)

import gm_trading_pb2 as pb  # noqa: E402
import gm_trading_pb2_grpc as pb_grpc  # noqa: E402

from broker import strategy as gm_strategy, order_enums  # noqa: E402
from utils import symbol_converter  # noqa: E402
from broker.order_queue import (  # noqa: E402
    PENDING_ORDERS,
    REQUEST_QUEUE,
    PlaceOrderJob,
)

logger = logging.getLogger("grpc_servicer")


def _format_dt_iso(dt) -> str:
    """Format a datetime as ISO 8601 (C# round-trip "o" format-compatible)."""
    if dt is None:
        return ""
    if hasattr(dt, "to_pydatetime"):
        dt = dt.to_pydatetime()
    if not isinstance(dt, datetime):
        return str(dt)
    if dt.tzinfo is None:
        # Treat as Beijing local time
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "+08:00"
    offset = dt.utcoffset()
    if offset is None or offset.total_seconds() == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%S") + "Z"
    total = int(offset.total_seconds() // 60)
    sign = "+" if total >= 0 else "-"
    hh = abs(total) // 60
    mm = abs(total) % 60
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + f"{sign}{hh:02d}:{mm:02d}"


class GMTradingServicer(pb_grpc.GMTradingServicer):
    """Implementation of the five RPCs in gm_trading.proto."""

    def __init__(self, *, default_timeout_seconds: int = 30) -> None:
        self._default_timeout = default_timeout_seconds

    # ---------- PlaceOrder ----------

    def PlaceOrder(self, request, context):
        logger.info(
            "[GRPC] Received order request: %s %s side=%d type=%d qty=%s @ %s account=%s",
            request.order_id,
            request.symbol,
            request.side,
            request.order_type,
            request.quantity,
            request.price,
            request.account_id,
        )
        try:
            gm_symbol = symbol_converter.to_gm(request.symbol)
            gm_side = order_enums.proto_side_to_gm(request.side)
            gm_type = order_enums.proto_order_type_to_gm(request.order_type)
        except ValueError as ex:
            return self._place_order_rejected(request.order_id, str(ex))

        future: Future = Future()
        # Mark the future as pending so that if the queue stalls past the
        # timeout we don't leave a dangling Future in PENDING_ORDERS.
        job = PlaceOrderJob(
            order_id=request.order_id,
            gm_symbol=gm_symbol,
            gm_side=gm_side,
            gm_order_type=gm_type,
            quantity=int(request.quantity),
            price=float(request.price),
            account=request.account_id,
            future=future,
        )
        try:
            REQUEST_QUEUE.put(job, timeout=5)
        except queue.Full:
            logger.error("[GRPC] Request queue full (GM SDK stalled?). Rejecting order %s", request.order_id)
            return self._place_order_rejected(request.order_id, "request queue full — GM SDK consumer stalled")

        try:
            order = future.result(timeout=self._default_timeout)
        except FutureTimeoutError:
            return self._place_order_timeout(request.order_id)
        except Exception as ex:
            logger.exception("[GRPC] Order placement exception")
            return self._place_order_rejected(request.order_id, f"exception: {ex}")

        return self._build_place_order_success(request.order_id, order)

    def _build_place_order_success(self, order_id: str, order) -> pb.PlaceOrderResponse:
        status = order_enums.gm_status_to_proto(int(getattr(order, "status", 0)))
        return pb.PlaceOrderResponse(
            success=True,
            message="Order placed successfully",
            order_id=order_id,
            status=status,
            filled_quantity=float(getattr(order, "filled_volume", 0.0) or 0.0),
            fill_price=float(getattr(order, "price", 0.0) or 0.0),
            commission=0.0,
            filled_at=_format_dt_iso(getattr(order, "updated_at", None)),
        )

    def _place_order_rejected(self, order_id: str, msg: str) -> pb.PlaceOrderResponse:
        return pb.PlaceOrderResponse(
            success=False,
            message=msg,
            order_id=order_id,
            status=order_enums.ProtoOrderStatus.REJECTED,
        )

    def _place_order_timeout(self, order_id: str) -> pb.PlaceOrderResponse:
        # Mirror C# behaviour: after timeout, do a best-effort query for the
        # final status. If found, use it; otherwise return Rejected.
        try:
            orders = gm_strategy.query_orders() or []
            for o in orders:
                if getattr(o, "cl_ord_id", None) == order_id:
                    status = order_enums.gm_status_to_proto(int(getattr(o, "status", 0)))
                    return pb.PlaceOrderResponse(
                        success=(status == order_enums.ProtoOrderStatus.FILLED),
                        message=f"Order query after timeout: status={status}",
                        order_id=order_id,
                        status=status,
                        filled_quantity=float(getattr(o, "filled_volume", 0.0) or 0.0),
                        fill_price=float(getattr(o, "price", 0.0) or 0.0),
                        commission=0.0,
                        filled_at=_format_dt_iso(getattr(o, "updated_at", None)),
                    )
        except Exception as ex:
            logger.exception("[GRPC] Timeout fallback query failed: %s", ex)
        return pb.PlaceOrderResponse(
            success=False,
            message="Order wait timeout and query failed",
            order_id=order_id,
            status=order_enums.ProtoOrderStatus.REJECTED,
        )

    # ---------- CancelOrder ----------

    def CancelOrder(self, request, context):
        logger.info("[GRPC] Cancel order: order_id=%s account=%s",
                    request.order_id, request.account_id)
        try:
            result = gm_strategy.cancel_order(request.order_id, request.account_id)
            success = (result == 0)
            msg = "Order cancellation successful" if success else \
                  f"Order cancellation failed (code={result})"
            logger.info("[GRPC] Cancel result: %s (%s)", success, msg)
            return pb.CancelOrderResponse(success=success, message=msg)
        except Exception as ex:
            logger.exception("[GRPC] Cancel exception")
            return pb.CancelOrderResponse(success=False, message=f"exception: {ex}")

    # ---------- GetCash ----------

    def GetCash(self, request, context):
        logger.info("[GRPC] Query cash: account=%s", request.account_id)
        try:
            cash_list = gm_strategy.query_cash(request.account_id) or []
            response = pb.GetCashResponse(success=True, message="Query successful")
            for cash in cash_list:
                response.cash_list.add(
                    account_id=getattr(cash, "account_id", "") or "",
                    available=float(getattr(cash, "available", 0.0) or 0.0),
                    total=float(getattr(cash, "balance", 0.0) or 0.0),
                    realized_pnl=0.0,
                )
            logger.info("[GRPC] Cash query: count=%d", len(response.cash_list))
            return response
        except Exception as ex:
            logger.exception("[GRPC] Cash query exception")
            return pb.GetCashResponse(success=False, message=f"exception: {ex}")

    # ---------- GetPosition ----------

    def GetPosition(self, request, context):
        logger.info("[GRPC] Query position: account=%s", request.account_id)
        try:
            positions = gm_strategy.query_position(request.account_id) or []
            response = pb.GetPositionResponse(success=True, message="Query successful")
            for pos in positions:
                gm_sym = getattr(pos, "symbol", "")
                response.positions.add(
                    symbol=symbol_converter.from_gm(gm_sym),
                    quantity=float(getattr(pos, "volume", 0.0) or 0.0),
                    available=float(getattr(pos, "available", 0.0) or 0.0),
                    avg_price=float(getattr(pos, "price", 0.0) or 0.0),
                    cost=float(getattr(pos, "cost", 0.0) or 0.0),
                    unrealized_pnl=0.0,
                    realized_pnl=0.0,
                )
            logger.info("[GRPC] Position query: count=%d", len(response.positions))
            return response
        except Exception as ex:
            logger.exception("[GRPC] Position query exception")
            return pb.GetPositionResponse(success=False, message=f"exception: {ex}")

    # ---------- GetOrders ----------

    def GetOrders(self, request, context):
        logger.info("[GRPC] Query orders: account=%s", request.account_id)
        try:
            orders = gm_strategy.query_orders() or []
            response = pb.GetOrdersResponse(success=True, message="Query successful")
            account_id = request.account_id
            for o in orders:
                # Filter by account if specified (SDK returns all account orders)
                if account_id and getattr(o, "account_id", "") != account_id:
                    continue
                gm_sym = getattr(o, "symbol", "")
                response.orders.add(
                    order_id=getattr(o, "cl_ord_id", "") or "",
                    symbol=symbol_converter.from_gm(gm_sym),
                    side=int(getattr(o, "side", 0)),
                    order_type=int(getattr(o, "order_type", 0)),
                    quantity=float(getattr(o, "volume", 0.0) or 0.0),
                    price=float(getattr(o, "price", 0.0) or 0.0),
                    status=order_enums.gm_status_to_proto(int(getattr(o, "status", 0))),
                    filled_quantity=float(getattr(o, "filled_volume", 0.0) or 0.0),
                    fill_price=float(getattr(o, "price", 0.0) or 0.0),
                    created_at=_format_dt_iso(getattr(o, "created_at", None)),
                    updated_at=_format_dt_iso(getattr(o, "updated_at", None)),
                )
            logger.info("[GRPC] Orders query: count=%d", len(response.orders))
            return response
        except Exception as ex:
            logger.exception("[GRPC] Orders query exception")
            return pb.GetOrdersResponse(success=False, message=f"exception: {ex}")
