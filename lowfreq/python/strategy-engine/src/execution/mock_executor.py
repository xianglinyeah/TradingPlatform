"""Mock Executor for Local Backtesting"""
from typing import List, Dict, Optional, Tuple
from datetime import datetime, date
from collections import defaultdict
import logging

from .common import Signal, Order, Position

logger = logging.getLogger(__name__)


class MockExecutor:
    """Mock executor for simulation"""

    def __init__(self, initial_capital: float = 1_000_000, commission_rate: float = 0.0003):
        """
        Initialize mock executor

        Args:
            initial_capital: Initial cash
            commission_rate: Commission rate (default 0.03%)
        """
        self.initial_capital = initial_capital
        self.cash = initial_capital
        self.commission_rate = commission_rate

        self.positions: Dict[str, Position] = defaultdict(Position)
        self.orders: List[Order] = []
        self.trade_history: List[dict] = []

        # Performance tracking
        self.total_pnl = 0.0
        self.total_commission = 0.0
        self.total_trades = 0

    def execute_signals(self, signals: List[Signal], current_bar) -> List[Order]:
        """
        Execute trading signals with market rules validation

        Args:
            signals: List of signals to execute
            current_bar: Current bar data (for price and timestamp)

        Returns:
            List of filled orders
        """
        filled_orders = []

        for signal in signals:
            try:
                # Market rules validation BEFORE execution
                validation_result = self._validate_market_rules(signal, current_bar)
                if not validation_result[0]:  # (passed, reason)
                    logger.warning(
                        f"Signal rejected by market rules: {signal.symbol} {signal.signal_type} "
                        f"{signal.quantity} - {validation_result[1]}"
                    )
                    continue  # Skip this signal

                order = self._create_order(signal, current_bar)
                filled_order = self._fill_order(order, current_bar)
                filled_orders.append(filled_order)

                logger.info(
                    f"Executed: {filled_order.side.upper()} {filled_order.quantity} "
                    f"{signal.symbol} @ {current_bar.close:.2f}"
                )

            except Exception as e:
                logger.error(f"Failed to execute signal {signal}: {e}")

        return filled_orders

    def _validate_market_rules(self, signal: Signal, bar) -> Tuple[bool, str]:
        """
        Validate signal against market rules (T+1, no naked short)

        Args:
            signal: Trading signal to validate
            bar: Current bar data

        Returns:
            Tuple of (passed: bool, reason: str)
        """
        # Only validate sell signals
        if signal.signal_type != 'sell':
            return True, ""

        position = self.positions.get(signal.symbol, Position())
        trade_date = bar.timestamp.date() if hasattr(bar.timestamp, 'date') else date.today()

        # Rule 1: No naked short (cannot sell without position)
        if signal.quantity > position.quantity:
            return False, f"No naked short: position={position.quantity}, request={signal.quantity}"

        # Rule 2: T+1 rule (cannot sell stocks bought today)
        sellable_qty = position.get_sellable_quantity(trade_date)
        if signal.quantity > sellable_qty:
            today_bought = position.quantity - sellable_qty
            return False, f"T+1 restriction: sellable={sellable_qty}, today_bought={today_bought}, request={signal.quantity}"

        return True, ""

    def _create_order(self, signal: Signal, bar) -> Order:
        """Create order from signal"""
        return Order(
            symbol=signal.symbol,
            side=signal.signal_type,
            quantity=signal.quantity,
            price=signal.price,
            strategy_id=signal.strategy_id  # Track which strategy generated this order
        )

    def _fill_order(self, order: Order, bar) -> Order:
        """
        Fill order at bar's close price

        Args:
            order: Order to fill
            bar: Current bar data

        Returns:
            Filled order
        """
        # Use close price for simplicity
        fill_price = bar.close
        commission = abs(order.quantity * fill_price * self.commission_rate)

        # Update cash
        if order.side == 'buy':
            required_cash = order.quantity * fill_price + commission
            if required_cash > self.cash:
                raise ValueError(
                    f"Insufficient cash: need {required_cash:.2f}, have {self.cash:.2f}"
                )
            self.cash -= required_cash
        else:  # sell
            self.cash += order.quantity * fill_price - commission

        # Update position
        position = self.positions[order.symbol]
        trade_date = bar.timestamp.date() if hasattr(bar.timestamp, 'date') else date.today()

        if order.side == 'buy':
            position.add(order.quantity, fill_price, trade_date)
        else:  # sell
            position.reduce(order.quantity, fill_price, trade_date)

        # Fill order
        order.fill(fill_price, order.quantity, commission)

        # Track
        self.orders.append(order)
        self.trade_history.append({
            'timestamp': bar.timestamp,
            'symbol': order.symbol,
            'side': order.side,
            'quantity': order.quantity,
            'price': fill_price,
            'commission': commission
        })

        self.total_commission += commission
        self.total_trades += 1

        return order

    def calculate_pnl(self, current_prices: Dict[str, float]) -> Dict:
        """
        Calculate total PnL

        Args:
            current_prices: Current market prices by symbol

        Returns:
            PnL statistics
        """
        total_position_value = 0.0
        total_unrealized_pnl = 0.0

        for symbol, position in self.positions.items():
            if symbol in current_prices:
                current_price = current_prices[symbol]
                position_value = position.market_value(current_price)
                unrealized_pnl = position.unrealized_pnl(current_price)

                total_position_value += position_value
                total_unrealized_pnl += unrealized_pnl

        total_realized_pnl = sum(pos.realized_pnl for pos in self.positions.values())
        total_equity = self.cash + total_position_value
        total_pnl = total_equity - self.initial_capital

        return {
            'cash': self.cash,
            'position_value': total_position_value,
            'total_equity': total_equity,
            'realized_pnl': total_realized_pnl,
            'unrealized_pnl': total_unrealized_pnl,
            'total_pnl': total_pnl,
            'total_commission': self.total_commission,
            'total_trades': self.total_trades,
            'return_pct': (total_pnl / self.initial_capital * 100) if self.initial_capital > 0 else 0.0
        }

    def get_position(self, symbol: str) -> Position:
        """Get position for symbol"""
        return self.positions.get(symbol, Position())

    def get_all_positions(self) -> Dict[str, Position]:
        """Get all positions"""
        return dict(self.positions)

    def get_trade_history(self) -> List[dict]:
        """Get trade history"""
        return self.trade_history.copy()

    def reset(self):
        """Reset executor state"""
        self.cash = self.initial_capital
        self.positions.clear()
        self.orders.clear()
        self.trade_history.clear()
        self.total_pnl = 0.0
        self.total_commission = 0.0
        self.total_trades = 0
