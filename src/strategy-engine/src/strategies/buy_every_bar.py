"""Buy Every Bar Strategy - Simple test strategy

This strategy is used to test the entire trading pipeline:
- Immediately place a buy order when new minute bar data is received
- Used to verify the complete workflow from market data to order execution
"""
from typing import List, Optional

from .base import BaseStrategy
from ..data import BarData
from ..execution import Signal


class BuyEveryBarStrategy(BaseStrategy):
    """Buy on every minute bar strategy - for testing end-to-end trading pipeline"""

    def __init__(self, name: str = "buy_every_bar", symbols: list = None,
                 exclude_symbols: list = None, params: dict = None):
        """
        Initialize strategy

        Args:
            name: Strategy name
            symbols: List of symbols to trade (supports wildcards)
            exclude_symbols: List of symbols to exclude (supports wildcards)
            params: Strategy parameters
                - quantity: Quantity to buy each time (default 100 shares)
                - max_position: Maximum position quantity (default 1000 shares, prevents infinite buying)
        """
        super().__init__(
            name=name,
            symbols=symbols or [],
            exclude_symbols=exclude_symbols or [],
            params=params or {}
        )
        self.quantity = params.get('quantity', 100)  # Buy 100 shares each time
        self.max_position = params.get('max_position', 1000)  # Maximum 1000 shares position

    def on_bar(self, bar: BarData) -> Optional[List[Signal]]:
        """
        Process new bar data - place buy order every time

        Args:
            bar: OHLCV bar data

        Returns:
            List of trading signals
        """
        self.bar_count += 1

        # Get current position for this symbol
        position = self.positions.get(bar.symbol)
        current_quantity = position.quantity if position else 0

        # Check if maximum position limit is reached
        if current_quantity >= self.max_position:
            print(f"[BuyEveryBar] {bar.symbol} reached maximum position limit {self.max_position}, stop buying")
            return None

        # Generate buy signal
        signal = self.generate_signal(
            symbol=bar.symbol,
            signal_type='buy',
            quantity=self.quantity,
            price=None,  # Market order
            reason=f"BuyEveryBar strategy triggered {self.bar_count} times"
        )

        print(f"[BuyEveryBar] Received {bar.symbol} bar ({bar.timestamp}), placing buy order {self.quantity} shares @ market")

        return [signal]

    def __str__(self):
        return f"BuyEveryBarStrategy(quantity={self.quantity}, max_position={self.max_position})"
