"""Base Strategy Class"""
from abc import ABC, abstractmethod
from typing import List, Optional, Dict, TYPE_CHECKING
from datetime import datetime
import logging

from ..data import BarData
from ..execution import Order, Position, Signal
from .. import metrics

if TYPE_CHECKING:
    from ..context import Context

logger = logging.getLogger(__name__)


class BaseStrategy(ABC):
    """Abstract Base Class for Trading Strategies"""

    # Metadata for hot-loading UI. Subclasses override these.
    # PARAMS_SCHEMA entries follow the shape consumed by Dashboard.Web's
    # dynamic form renderer: {key, label, type, default, min, max, step?}
    PARAMS_SCHEMA: List[dict] = []
    DISPLAY_NAME: str = ""
    DESCRIPTION: str = ""

    def __init__(self, name: str, symbols: Optional[List[str]] = None,
                 exclude_symbols: Optional[List[str]] = None, params: Optional[dict] = None):
        """
        Initialize strategy

        Args:
            name: Strategy name (used as strategy_id)
            symbols: List of symbols this strategy trades (optional, supports wildcards)
            exclude_symbols: List of symbols to exclude (optional, supports wildcards)
            params: Strategy parameters (optional)
        """
        self.name = name
        self.symbols = symbols or []  # Symbols this strategy trades
        self.exclude_symbols = exclude_symbols or []  # Symbols to exclude
        self.params = params or {}
        self.positions: Dict[str, Position] = {}  # Positions by symbol (support multi-symbol trading)
        self.signals: List[Signal] = []  # Pending signals
        self.trades: List[dict] = []  # Trade history
        self.bar_count = 0  # Number of bars processed

        # Context for historical data access (optional, for strategies that need daily data)
        self.context: Optional[Context] = None

    @abstractmethod
    def on_bar(self, bar: BarData) -> Optional[List[Signal]]:
        """
        Handle new bar data

        Args:
            bar: OHLCV bar data

        Returns:
            List of trading signals (empty list if no action)
        """
        pass

    def on_order_filled(self, order: Order):
        """
        Called when an order is filled

        Args:
            order: Filled order
        """
        logger.info(f"[on_order_filled] Order filled: {order.side.upper()} {order.quantity} {order.symbol} @ {order.avg_price:.2f}")

        # Get or create position for this symbol
        if order.symbol not in self.positions:
            self.positions[order.symbol] = Position(symbol=order.symbol)

        position = self.positions[order.symbol]

        # Update position
        if order.side == 'buy':
            position.add(order.quantity, order.avg_price)
            logger.info(f"[on_order_filled] Position updated: BUY {order.symbol} qty={position.quantity}")
        else:  # sell
            position.reduce(order.quantity, order.avg_price)
            logger.info(f"[on_order_filled] Position updated: SELL {order.symbol} qty={position.quantity}")

        # Record trade
        self.trades.append({
            'timestamp': order.filled_time,
            'symbol': order.symbol,
            'side': order.side,
            'quantity': order.quantity,
            'price': order.avg_price,
            'commission': order.commission
        })

    def on_position_changed(self, position: Position):
        """
        Called when position changes

        Args:
            position: New position
        """
        # Update position for the symbol
        self.positions[position.symbol] = position

    def get_pending_signals(self) -> List[Signal]:
        """Get pending signals and clear the list"""
        signals = self.signals.copy()
        self.signals.clear()
        return signals

    def generate_signal(
        self,
        symbol: str,
        signal_type: str,
        quantity: int,
        price: Optional[float] = None,
        reason: str = ""
    ) -> Signal:
        """
        Generate a trading signal

        Args:
            symbol: Stock symbol
            signal_type: 'buy' or 'sell'
            quantity: Quantity to trade
            price: Limit price (None for market order)
            reason: Signal reason (for logging)

        Returns:
            Signal object
        """
        signal = Signal(
            symbol=symbol,
            signal_type=signal_type,
            quantity=quantity,
            price=price,
            reason=reason,
            timestamp=datetime.now(),
            strategy_id=self.name
        )
        self.signals.append(signal)
        metrics.signals_generated.labels(
            strategy_name=self.name, symbol=symbol, side=signal_type
        ).inc()
        return signal

    def get_trade_history(self) -> List[dict]:
        """Get trade history"""
        return self.trades.copy()

    def set_context(self, context: Optional['Context']) -> None:
        """
        Set context for historical data access.

        Args:
            context: Context object with HistoryStore, or None to disable
        """
        self.context = context
        logger.info(f"{self.name}: Context set (context={context is not None})")

    def reset(self):
        """Reset strategy state"""
        self.positions.clear()
        self.signals.clear()
        self.trades.clear()
        self.bar_count = 0
