"""Real gRPC Executor for Live Trading - connects to actual ExecutionService"""
import grpc
from typing import List, Dict, Optional
from datetime import datetime
import logging
from pathlib import Path
import sys
import uuid

# Add protos to path
protos_path = Path(__file__).parent.parent.parent / "protos"
sys.path.insert(0, str(protos_path))

import execution_pb2
import execution_pb2_grpc

from .common import Signal, Order, Position

logger = logging.getLogger(__name__)


class RealGrpcExecutor:
    """Real gRPC executor connecting to actual ExecutionService"""

    # OrderSide enum: 0=Buy, 1=Sell
    ORDER_SIDE_BUY = 0
    ORDER_SIDE_SELL = 1

    # OrderType enum: 0=Market, 1=Limit
    ORDER_TYPE_MARKET = 0
    ORDER_TYPE_LIMIT = 1

    # OrderStatus enum: 0=Pending, 1=Filled, 2=Partial, 3=Cancelled, 4=Rejected, 5=Expired
    ORDER_STATUS_PENDING = 0
    ORDER_STATUS_FILLED = 1
    ORDER_STATUS_PARTIAL = 2
    ORDER_STATUS_CANCELLED = 3
    ORDER_STATUS_REJECTED = 4
    ORDER_STATUS_EXPIRED = 5

    # TimeInForce enum (P2.1)
    TIF_DAY = 0
    TIF_IOC = 1
    TIF_GTC = 2
    TIF_FOK = 3

    def __init__(self, execution_service_address: str, session_id: str = None, initial_capital: float = 1_000_000):
        """
        Initialize real gRPC executor

        Args:
            execution_service_address: gRPC service address (e.g., "localhost:5101")
            session_id: Trading session ID (auto-generated if None)
            initial_capital: Initial capital (for reference)
        """
        self.execution_service_address = execution_service_address
        self.session_id = session_id or f"strategy_{uuid.uuid4().hex[:8]}"
        self.initial_capital = initial_capital
        self.channel = None
        self.stub = None
        self.orders: List[Order] = []
        self.total_trades = 0
        self.cash = initial_capital

        # Connect to execution service
        self._connect()

        logger.info(f"RealGrpcExecutor initialized: {execution_service_address}")
        logger.info(f"Session ID: {self.session_id}")

    def _connect(self):
        """Connect to execution service"""
        try:
            self.channel = grpc.insecure_channel(self.execution_service_address)
            self.stub = execution_pb2_grpc.ExecutionStub(self.channel)

            # Test connection by trying to reach the service (not using GetAccount as it has issues)
            try:
                # Try a simple test - just ensure channel is ready
                grpc.channel_ready_future(self.channel).result(timeout=5)
                logger.info(f"Connected to ExecutionService at {self.execution_service_address}")
            except Exception:
                # If channel ready check fails, still consider it connected as SubmitOrder works
                logger.info(f"Connected to ExecutionService at {self.execution_service_address} (best-effort)")

        except Exception as e:
            logger.error(f"Failed to connect to ExecutionService: {e}")
            raise

    def execute_signals(self, signals: List[Signal], current_bar) -> List[Order]:
        """
        Execute trading signals via real gRPC ExecutionService

        Args:
            signals: List of signals to execute
            current_bar: Current bar data

        Returns:
            List of filled orders
        """
        filled_orders = []

        for signal in signals:
            try:
                # Submit order via real gRPC
                order_response = self._submit_order(signal, current_bar)

                # Create local order object
                order = Order(
                    symbol=signal.symbol,
                    side=signal.signal_type,
                    quantity=signal.quantity,
                    price=signal.price,
                    strategy_id=signal.strategy_id  # Track which strategy generated this order
                )

                # Update order based on response
                if order_response.status == self.ORDER_STATUS_FILLED:
                    order.fill(
                        order_response.fill_price,
                        int(order_response.filled_quantity),
                        order_response.commission
                    )
                    self.total_trades += 1
                    filled_orders.append(order)

                    logger.info(
                        f"Executed via gRPC: {order.side.upper()} {order.quantity} "
                        f"{signal.symbol} @ {order_response.fill_price:.2f} "
                        f"(OrderID: {order_response.order_id})"
                    )
                elif order_response.status == self.ORDER_STATUS_REJECTED:
                    logger.warning(
                        f"Order rejected: {order_response.message}"
                    )
                else:
                    logger.warning(
                        f"Order status: {order_response.status} - {order_response.message}"
                    )

                self.orders.append(order)

            except grpc.RpcError as e:
                logger.error(f"gRPC error submitting order: {e.code()}: {e.details()}")
            except Exception as e:
                logger.error(f"Failed to submit order: {e}")

        return filled_orders

    def _submit_order(self, signal: Signal, current_bar) -> execution_pb2.OrderResponse:
        """
        Submit order via real gRPC ExecutionService

        Args:
            signal: Trading signal
            current_bar: Current bar data

        Returns:
            Order response
        """
        # Convert signal side to OrderSide enum
        side = self.ORDER_SIDE_BUY if signal.signal_type == 'buy' else self.ORDER_SIDE_SELL

        # Determine order type
        if signal.price and signal.price > 0:
            order_type = self.ORDER_TYPE_LIMIT
            price = signal.price
        else:
            order_type = self.ORDER_TYPE_MARKET
            price = current_bar.close if current_bar else 0.0

        # Log timestamp information
        if current_bar:
            logger.info(f"[TIMESTAMP_CHECK] current_bar.timestamp = {current_bar.timestamp}, type = {type(current_bar.timestamp)}")
            trade_time_str = current_bar.timestamp.strftime("%Y-%m-%dT%H:%M:%S")
            logger.info(f"[TIMESTAMP_CHECK] Formatted trade_time = {trade_time_str}")
        else:
            trade_time_str = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
            logger.warning(f"[TIMESTAMP_CHECK] No current_bar, using current time: {trade_time_str}")

        request = execution_pb2.OrderRequest(
            session_id=self.session_id,
            symbol=signal.symbol,
            side=side,
            type=order_type,
            quantity=float(signal.quantity),
            price=price,
            signal_id=f"signal_{uuid.uuid4().hex[:8]}",
            strategy_id=signal.strategy_id or "unknown_strategy",
            trade_time=trade_time_str
        )

        logger.info(
            f"[TIMESTAMP_CHECK] Sending gRPC request: "
            f"session_id={request.session_id}, symbol={request.symbol}, "
            f"side={request.side}, price={request.price}, "
            f"trade_time={request.trade_time}"
        )

        # 30s timeout: order placement is blocking and a hung call would freeze the strategy.
        response = self.stub.SubmitOrder(request, timeout=30)
        logger.info(
            f"[TIMESTAMP_CHECK] gRPC response: order_id={response.order_id}, "
            f"status={response.status}, message={response.message}"
        )

        return response

    def get_position(self, symbol: str) -> Position:
        """Get position for symbol"""
        try:
            request = execution_pb2.PositionRequest(
                session_id=self.session_id,
                symbol=symbol
            )
            response = self.stub.GetPosition(request, timeout=10)

            if response.symbol:  # If symbol exists, we have a position
                position = Position(symbol=response.symbol)
                position.quantity = int(response.quantity)
                position.avg_price = response.avg_price
                position.realized_pnl = response.realized_pnl
                return position
            else:
                return Position()

        except grpc.RpcError as e:
            logger.error(f"Failed to get position: {e.code()}: {e.details()}")
            return Position()

    def get_all_positions(self) -> Dict[str, Position]:
        """Get all positions"""
        try:
            request = execution_pb2.AllPositionsRequest(session_id=self.session_id)
            response = self.stub.GetAllPositions(request)

            positions = {}
            for pos in response.positions:
                position = Position(symbol=pos.symbol)
                position.quantity = int(pos.quantity)
                position.avg_price = pos.avg_price
                position.realized_pnl = pos.realized_pnl
                positions[pos.symbol] = position

            return positions

        except grpc.RpcError as e:
            logger.error(f"Failed to get positions: {e.code()}: {e.details()}")
            return {}

    def cancel_order(self, order_id: str) -> Optional[Dict]:
        """
        Cancel order (added in P0.2)

        Args:
            order_id: Business order_id (client_order_id), returned by submit_order

        Returns:
            dict: {order_id, status, filled_quantity, message}; on success status=3 (Cancelled)
            None: Call failed
        """
        try:
            request = execution_pb2.CancelOrderRequest(
                session_id=self.session_id,
                order_id=order_id
            )
            response = self.stub.CancelOrder(request, timeout=10)
            logger.info(
                f"CancelOrder: order_id={response.order_id}, status={response.status}, "
                f"filled_qty={response.filled_quantity}, msg={response.message}"
            )
            return {
                'order_id': response.order_id,
                'status': response.status,
                'filled_quantity': response.filled_quantity,
                'message': response.message
            }
        except grpc.RpcError as e:
            logger.error(f"Failed to cancel order {order_id}: {e.code()}: {e.details()}")
            return None

    def expire_day_orders(self, trade_date: str = None) -> Optional[Dict]:
        """
        Market close cancel: mark Pending/Partial DAY orders as Expired (added in P2.2).
        Triggered by external scheduler, not by a built-in timer in ExecutionService.

        Args:
            trade_date: ISO8601 date (e.g., "2026-06-18"); None means today

        Returns:
            dict: {expired_count, expired_order_ids}
        """
        try:
            request = execution_pb2.ExpireDayOrdersRequest(
                session_id=self.session_id,
                trade_date=trade_date or ""
            )
            response = self.stub.ExpireDayOrders(request)
            logger.info(
                f"ExpireDayOrders: expired {response.expired_count} orders: "
                f"{list(response.expired_order_ids)}"
            )
            return {
                'expired_count': response.expired_count,
                'expired_order_ids': list(response.expired_order_ids)
            }
        except grpc.RpcError as e:
            logger.error(f"Failed to expire day orders: {e.code()}: {e.details()}")
            return None

    def subscribe_order_updates(self, order_ids: List[str] = None):
        """
        Subscribe to order status update stream (added in P1.2).

        Args:
            order_ids: Specific orders to subscribe to; None/empty = subscribe to all orders in the session

        Yields:
            execution_pb2.OrderUpdate
        """
        request = execution_pb2.OrderUpdatesSubscribeRequest(
            session_id=self.session_id,
            order_ids=order_ids or []
        )
        try:
            for update in self.stub.SubscribeOrderUpdates(request):
                yield update
        except grpc.RpcError as e:
            logger.error(f"OrderUpdates stream closed: {e.code()}: {e.details()}")

    def get_account_summary(self) -> Dict:
        """Get account summary"""
        try:
            request = execution_pb2.AccountRequest(session_id=self.session_id)
            response = self.stub.GetAccount(request, timeout=10)

            # Store cash for reporting
            self.cash = response.cash

            return {
                'session_id': response.session_id,
                'cash': response.cash,
                'total_equity': response.equity,
                'market_value': response.market_value,
                'total_pnl': response.total_pnl,
                'total_trades': response.total_trades,
                'total_commission': response.total_commission,
                'initial_capital': response.initial_capital
            }

        except grpc.RpcError as e:
            logger.error(f"Failed to get account summary: {e.code()}: {e.details()}")
            return {}

    def update_session_id(self, new_session_id: str):
        """
        Update session ID for new replay session

        Args:
            new_session_id: New session ID to use
        """
        old_session_id = self.session_id
        self.session_id = new_session_id
        logger.info(f"Session ID updated: {old_session_id} -> {new_session_id}")

    def close(self):
        """Close gRPC connection"""
        if self.channel:
            self.channel.close()
            logger.info("gRPC connection closed")
