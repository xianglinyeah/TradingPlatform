"""Moving Average Strategy with Stop Loss/Take Profit"""
from typing import List, Optional, Dict
import logging

from .base import BaseStrategy
from ..data import BarData
from ..execution import Signal, Position

logger = logging.getLogger(__name__)


class MovingAverageStrategy(BaseStrategy):
    """
    Moving Average Strategy with Stop Loss/Take Profit

    Rules:
    - Calculate EMA(10)
    - If price falls 0.5% below EMA: BUY with stop loss/take profit
    - Stop Loss: -0.8% from entry price
    - Take Profit: +1.2% from entry price
    """

    def __init__(self, name: str = "MovingAverage", symbols: list = None,
                 exclude_symbols: list = None, params: dict = None):
        """
        Initialize strategy

        Args:
            name: Strategy name (default "MovingAverage")
            symbols: List of symbols this strategy trades (supports wildcards)
            exclude_symbols: List of symbols to exclude (supports wildcards)
            params: {
                'ema_period': int,  # EMA period (default 20)
                'buy_threshold': float,  # Buy when price < EMA * (1 + threshold)
                'stop_loss_pct': float,  # Stop loss percentage (default -0.03)
                'take_profit_pct': float,  # Take profit percentage (default 0.03)
            }
        """
        super().__init__(name=name, symbols=symbols or [],
                       exclude_symbols=exclude_symbols or [], params=params or {})

        self.ema_period = params.get('ema_period', 10)
        self.buy_threshold = params.get('buy_threshold', -0.005)  # -0.5% more sensitive
        self.stop_loss_pct = params.get('stop_loss_pct', -0.008)  # -0.8%
        self.take_profit_pct = params.get('take_profit_pct', 0.012)  # +1.2%

        # Per-symbol state for multi-symbol trading
        self.price_histories: Dict[str, List[float]] = {}  # Price history by symbol
        self.current_emas: Dict[str, Optional[float]] = {}  # Current EMA by symbol
        self.entry_prices: Dict[str, Optional[float]] = {}  # Entry price by symbol
        self.stop_loss_prices: Dict[str, Optional[float]] = {}  # Stop loss price by symbol
        self.take_profit_prices: Dict[str, Optional[float]] = {}  # Take profit price by symbol

        logger.info(
            f"Initialized MovingAverageStrategy: "
            f"EMA={self.ema_period}, buy_threshold={self.buy_threshold:.2%}, "
            f"stop_loss={self.stop_loss_pct:.2%}, take_profit={self.take_profit_pct:.2%}"
        )

    def _get_or_init_symbol_state(self, symbol: str):
        """Initialize state for a symbol if not exists"""
        if symbol not in self.price_histories:
            self.price_histories[symbol] = []
            self.current_emas[symbol] = None
            self.entry_prices[symbol] = None
            self.stop_loss_prices[symbol] = None
            self.take_profit_prices[symbol] = None

    def calculate_ema(self, symbol: str, new_price: float) -> float:
        """
        Calculate EMA with new price for a symbol

        Args:
            symbol: Stock symbol
            new_price: New closing price

        Returns:
            Current EMA value
        """
        self._get_or_init_symbol_state(symbol)

        price_history = self.price_histories[symbol]
        price_history.append(new_price)

        if len(price_history) < self.ema_period:
            # Not enough data, return SMA so far
            return sum(price_history) / len(price_history)

        if self.current_emas[symbol] is None:
            # First EMA: calculate SMA
            self.current_emas[symbol] = sum(price_history[-self.ema_period:]) / self.ema_period
        else:
            # Update EMA: EMA = (Close - EMA_prev) * multiplier + EMA_prev
            multiplier = 2 / (self.ema_period + 1)
            self.current_emas[symbol] = (new_price - self.current_emas[symbol]) * multiplier + self.current_emas[symbol]

        return self.current_emas[symbol]

    def on_bar(self, bar: BarData) -> Optional[List[Signal]]:
        """
        Process new bar and generate signals with stop loss/take profit

        Args:
            bar: OHLCV bar data

        Returns:
            List of signals (empty if no action)
        """
        self.bar_count += 1

        # Initialize state for this symbol if needed
        self._get_or_init_symbol_state(bar.symbol)

        # Calculate EMA for this symbol
        ema = self.calculate_ema(bar.symbol, bar.close)

        # Need at least EMA_PERIOD bars before trading
        if len(self.price_histories[bar.symbol]) < self.ema_period:
            logger.debug(
                f"[{bar.timestamp}] {bar.symbol} - Accumulating data: {len(self.price_histories[bar.symbol])}/{self.ema_period}"
            )
            return []

        # Calculate deviation from EMA
        deviation = (bar.close - ema) / ema

        # Generate signals
        signals = []

        # Get position for this symbol
        position = self.positions.get(bar.symbol, Position(bar.symbol))

        # Buy signal: price falls below EMA by threshold
        if deviation <= self.buy_threshold:
            logger.info(f"[BUY_CHECK] Bar: {bar.timestamp}, Close: {bar.close:.2f}, EMA: {ema:.2f}, Deviation: {deviation:.2%}, Position: {position.quantity}")
            if position.quantity == 0:  # Only buy if no position
                # Fixed order size: 100 shares per order
                quantity = 100

                signal = self.generate_signal(
                    symbol=bar.symbol,
                    signal_type='buy',
                    quantity=quantity,
                    reason=f"Price {deviation:.2%} below EMA({self.ema_period})"
                )

                signals.append(signal)

                # Set stop loss and take profit based on entry price
                self.entry_prices[bar.symbol] = bar.close
                self.stop_loss_prices[bar.symbol] = bar.close * (1 + self.stop_loss_pct)
                self.take_profit_prices[bar.symbol] = bar.close * (1 + self.take_profit_pct)

                logger.info(
                    f"[{bar.timestamp}] BUY signal: {bar.symbol} @ {bar.close:.2f}, "
                    f"EMA={ema:.2f}, deviation={deviation:.2%}, "
                    f"StopLoss={self.stop_loss_prices[bar.symbol]:.2f}, TakeProfit={self.take_profit_prices[bar.symbol]:.2f}"
                )

        # Check stop loss/take profit if we have a position
        elif position.quantity > 0 and self.stop_loss_prices[bar.symbol] is not None and self.take_profit_prices[bar.symbol] is not None:
            # Stop Loss: price falls to or below stop loss price
            if bar.low <= self.stop_loss_prices[bar.symbol]:
                quantity = position.quantity

                signal = self.generate_signal(
                    symbol=bar.symbol,
                    signal_type='sell',
                    quantity=quantity,
                    reason=f"Stop Loss triggered: {bar.close:.2f} <= {self.stop_loss_prices[bar.symbol]:.2f}"
                )

                logger.info(
                    f"[{bar.timestamp}] STOP LOSS: {bar.symbol} @ {bar.close:.2f}, "
                    f"StopLoss={self.stop_loss_prices[bar.symbol]:.2f}"
                )

                signals.append(signal)
                self.entry_prices[bar.symbol] = None
                self.stop_loss_prices[bar.symbol] = None
                self.take_profit_prices[bar.symbol] = None

            # Take Profit: price rises to or above take profit price
            elif bar.high >= self.take_profit_prices[bar.symbol]:
                quantity = position.quantity

                signal = self.generate_signal(
                    symbol=bar.symbol,
                    signal_type='sell',
                    quantity=quantity,
                    reason=f"Take Profit triggered: {bar.close:.2f} >= {self.take_profit_prices[bar.symbol]:.2f}"
                )

                logger.info(
                    f"[{bar.timestamp}] TAKE PROFIT: {bar.symbol} @ {bar.close:.2f}, "
                    f"TakeProfit={self.take_profit_prices[bar.symbol]:.2f}"
                )

                signals.append(signal)
                self.entry_prices[bar.symbol] = None
                self.stop_loss_prices[bar.symbol] = None
                self.take_profit_prices[bar.symbol] = None

        return signals

    def get_indicators(self) -> dict:
        """Get current indicator values"""
        return {
            'emas': self.current_emas,
            'price_history_lengths': {s: len(h) for s, h in self.price_histories.items()},
        }

    def reset(self):
        """Reset strategy state"""
        super().reset()
        self.price_histories.clear()
        self.current_emas.clear()
        self.entry_prices.clear()
        self.stop_loss_prices.clear()
        self.take_profit_prices.clear()
        logger.info("MovingAverageStrategy state has been reset")
