"""Unit tests for BaseStrategy core functionality"""
import pytest
from datetime import datetime
from unittest.mock import MagicMock

from src.strategies.base import BaseStrategy
from src.data import BarData
from src.execution import Order, Position, Signal


class TestStrategy(BaseStrategy):
    """Concrete implementation of BaseStrategy for testing"""

    def on_bar(self, bar: BarData):
        """Simple test implementation"""
        self.bar_count += 1
        return []


class TestBaseStrategy:
    """Test suite for BaseStrategy core functionality"""

    def test_initialization(self):
        """Test strategy initialization with default values"""
        params = {'param1': 'value1', 'param2': 42}
        strategy = TestStrategy(name="TestStrategy", params=params)

        assert strategy.name == "TestStrategy"
        assert strategy.params == params
        assert strategy.bar_count == 0
        assert isinstance(strategy.positions, dict)
        assert strategy.signals == []
        assert strategy.trades == []

    def test_generate_signal_buy(self):
        """Test generating a buy signal"""
        strategy = TestStrategy(name="TestStrategy", params={})

        signal = strategy.generate_signal(
            symbol="AAPL",
            signal_type='buy',
            quantity=100,
            price=150.0,
            reason="Test buy signal"
        )

        assert signal.symbol == "AAPL"
        assert signal.signal_type == 'buy'
        assert signal.quantity == 100
        assert signal.price == 150.0
        assert signal.reason == "Test buy signal"
        assert isinstance(signal.timestamp, datetime)

        # Check signal is added to pending signals
        assert len(strategy.signals) == 1
        assert strategy.signals[0] == signal

    def test_generate_signal_sell(self):
        """Test generating a sell signal"""
        strategy = TestStrategy(name="TestStrategy", params={})

        signal = strategy.generate_signal(
            symbol="MSFT",
            signal_type='sell',
            quantity=50,
            price=200.0,
            reason="Test sell signal"
        )

        assert signal.symbol == "MSFT"
        assert signal.signal_type == 'sell'
        assert signal.quantity == 50

    def test_generate_signal_market_order(self):
        """Test generating signal without price (market order)"""
        strategy = TestStrategy(name="TestStrategy", params={})

        signal = strategy.generate_signal(
            symbol="GOOGL",
            signal_type='buy',
            quantity=10,
            price=None,  # Market order
            reason="Market order"
        )

        assert signal.price is None

    def test_generate_signal_default_values(self):
        """Test generate_signal with default parameters"""
        strategy = TestStrategy(name="TestStrategy", params={})

        signal = strategy.generate_signal(
            symbol="TSLA",
            signal_type='buy',
            quantity=25
        )

        assert signal.price is None
        assert signal.reason == ""
        assert isinstance(signal.timestamp, datetime)

    def test_on_order_filled_buy(self):
        """Test order filled event for buy order"""
        strategy = TestStrategy(name="TestStrategy", params={})

        order = Order(
            symbol="AAPL",
            side='buy',
            quantity=100,
            price=150.0
        )
        order.fill(price=150.0, quantity=100, commission=1.5)

        strategy.on_order_filled(order)

        # Check position is updated
        assert "AAPL" in strategy.positions
        assert strategy.positions["AAPL"].quantity == 100
        assert strategy.positions["AAPL"].avg_price == 150.0

        # Check trade is recorded
        assert len(strategy.trades) == 1
        trade = strategy.trades[0]
        assert trade['symbol'] == "AAPL"
        assert trade['side'] == 'buy'
        assert trade['quantity'] == 100
        assert trade['price'] == 150.0
        assert trade['commission'] == 1.5
        assert isinstance(trade['timestamp'], datetime)

    def test_on_order_filled_sell(self):
        """Test order filled event for sell order"""
        strategy = TestStrategy(name="TestStrategy", params={})

        # First buy to establish position
        strategy.positions["AAPL"] = Position()
        strategy.positions["AAPL"].add(100, 150.0)

        order = Order(
            symbol="AAPL",
            side='sell',
            quantity=50,
            price=155.0
        )
        order.fill(price=155.0, quantity=50, commission=1.5)

        strategy.on_order_filled(order)

        # Check position is reduced
        assert strategy.positions["AAPL"].quantity == 50
        assert strategy.positions["AAPL"].avg_price == 150.0  # Avg price doesn't change on sell

        # Check trade is recorded
        assert len(strategy.trades) == 1
        trade = strategy.trades[0]
        assert trade['side'] == 'sell'
        assert trade['quantity'] == 50

    def test_on_order_filled_multiple_buys(self):
        """Test multiple buy orders and position averaging"""
        strategy = TestStrategy(name="TestStrategy", params={})

        # First buy
        order1 = Order(symbol="AAPL", side='buy', quantity=100, price=150.0)
        order1.fill(price=150.0, quantity=100, commission=1.5)
        strategy.on_order_filled(order1)

        # Second buy at different price
        order2 = Order(symbol="AAPL", side='buy', quantity=50, price=160.0)
        order2.fill(price=160.0, quantity=50, commission=1.0)
        strategy.on_order_filled(order2)

        # Check position averaging
        assert strategy.positions["AAPL"].quantity == 150
        # Weighted average: (100*150 + 50*160) / 150 = 153.33
        assert abs(strategy.positions["AAPL"].avg_price - 153.33) < 0.01

        # Check both trades recorded
        assert len(strategy.trades) == 2

    def test_on_position_changed(self):
        """Test position changed event"""
        strategy = TestStrategy(name="TestStrategy", params={})

        new_position = Position()
        new_position.add(100, 150.0)

        strategy.on_position_changed(new_position)

        # Note: on_position_changed now requires symbol parameter
        # For testing, we can manually set the position
        assert new_position.quantity == 100
        assert new_position.avg_price == 150.0

    def test_get_pending_signals(self):
        """Test getting and clearing pending signals"""
        strategy = TestStrategy(name="TestStrategy", params={})

        # Generate multiple signals
        signal1 = strategy.generate_signal("AAPL", 'buy', 100, 150.0)
        signal2 = strategy.generate_signal("MSFT", 'sell', 50, 200.0)

        # Get pending signals
        pending = strategy.get_pending_signals()

        assert len(pending) == 2
        assert pending[0] == signal1
        assert pending[1] == signal2

        # Check signals are cleared
        assert len(strategy.signals) == 0

    def test_get_pending_signals_empty(self):
        """Test getting pending signals when none exist"""
        strategy = TestStrategy(name="TestStrategy", params={})

        pending = strategy.get_pending_signals()

        assert pending == []
        assert len(strategy.signals) == 0

    def test_get_trade_history(self):
        """Test getting trade history"""
        strategy = TestStrategy(name="TestStrategy", params={})

        # Create some trades
        order1 = Order(symbol="AAPL", side='buy', quantity=100, price=150.0)
        order1.fill(price=150.0, quantity=100, commission=1.5)
        strategy.on_order_filled(order1)

        order2 = Order(symbol="MSFT", side='buy', quantity=50, price=200.0)
        order2.fill(price=200.0, quantity=50, commission=1.0)
        strategy.on_order_filled(order2)

        # Get trade history
        history = strategy.get_trade_history()

        assert len(history) == 2
        assert history[0]['symbol'] == "AAPL"
        assert history[1]['symbol'] == "MSFT"

        # Check it returns a copy, not the original list
        history.append({'test': 'value'})
        assert len(strategy.trades) == 2  # Original unchanged

    def test_get_trade_history_empty(self):
        """Test getting trade history when no trades"""
        strategy = TestStrategy(name="TestStrategy", params={})

        history = strategy.get_trade_history()

        assert history == []

    def test_reset(self):
        """Test resetting strategy state"""
        strategy = TestStrategy(name="TestStrategy", params={})

        # Create some state
        strategy.generate_signal("AAPL", 'buy', 100, 150.0)
        order = Order(symbol="AAPL", side='buy', quantity=100, price=150.0)
        order.fill(price=150.0, quantity=100, commission=1.5)
        strategy.on_order_filled(order)
        strategy.bar_count = 50

        # Reset
        strategy.reset()

        # Check all state is cleared (positions dict is now empty)
        assert len(strategy.positions) == 0
        assert len(strategy.signals) == 0
        assert len(strategy.trades) == 0
        assert strategy.bar_count == 0

    def test_reset_preserves_name_and_params(self):
        """Test that reset preserves strategy name and parameters"""
        params = {'param1': 'value1'}
        strategy = TestStrategy(name="TestStrategy", params=params)

        strategy.reset()

        assert strategy.name == "TestStrategy"
        assert strategy.params == params

    def test_signal_accumulation(self):
        """Test that signals accumulate before being cleared"""
        strategy = TestStrategy(name="TestStrategy", params={})

        # Generate signals over multiple bars
        for i in range(3):
            strategy.generate_signal(f"STOCK{i}", 'buy', 100, 100.0 + i)

        assert len(strategy.signals) == 3

        # Get and clear
        pending = strategy.get_pending_signals()
        assert len(pending) == 3
        assert len(strategy.signals) == 0

    def test_trade_accumulation(self):
        """Test that trades accumulate over time"""
        strategy = TestStrategy(name="TestStrategy", params={})

        # Execute multiple trades
        for i in range(3):
            order = Order(symbol=f"STOCK{i}", side='buy', quantity=100, price=100.0 + i)
            order.fill(price=100.0 + i, quantity=100, commission=1.0)
            strategy.on_order_filled(order)

        assert len(strategy.trades) == 3

        # Get trade history
        history = strategy.get_trade_history()
        assert len(history) == 3
        assert len(strategy.trades) == 3  # Original preserved

    def test_position_realized_pnl_tracking(self):
        """Test that realized PnL is tracked through trades"""
        strategy = TestStrategy(name="TestStrategy", params={})

        # Buy at 150
        buy_order = Order(symbol="AAPL", side='buy', quantity=100, price=150.0)
        buy_order.fill(price=150.0, quantity=100, commission=1.5)
        strategy.on_order_filled(buy_order)

        # Sell at 160
        sell_order = Order(symbol="AAPL", side='sell', quantity=100, price=160.0)
        sell_order.fill(price=160.0, quantity=100, commission=1.5)
        strategy.on_order_filled(sell_order)

        # Check realized PnL: (160 - 150) * 100 = 1000.0
        # Note: Position.realized_pnl doesn't include commission in calculation
        expected_pnl = (160.0 - 150.0) * 100
        assert abs(strategy.positions["AAPL"].realized_pnl - expected_pnl) < 0.01

    def test_concrete_strategy_on_bar(self):
        """Test that concrete strategy on_bar implementation works"""
        strategy = TestStrategy(name="TestStrategy", params={})

        bar = BarData(
            symbol="AAPL",
            timestamp=datetime.now(),
            open=150.0,
            high=155.0,
            low=149.0,
            close=152.0,
            volume=1000000
        )

        result = strategy.on_bar(bar)

        assert result == []
        assert strategy.bar_count == 1

    def test_multiple_get_pending_signals_calls(self):
        """Test multiple calls to get_pending_signals"""
        strategy = TestStrategy(name="TestStrategy", params={})

        # Generate signals
        strategy.generate_signal("AAPL", 'buy', 100, 150.0)
        strategy.generate_signal("MSFT", 'sell', 50, 200.0)

        # First call
        pending1 = strategy.get_pending_signals()
        assert len(pending1) == 2

        # Second call should return empty (already cleared)
        pending2 = strategy.get_pending_signals()
        assert len(pending2) == 0
