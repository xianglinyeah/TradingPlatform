"""Backtest Engine"""
import pandas as pd
from pathlib import Path
from typing import Dict, List
import logging
from datetime import datetime

from ..execution import MockExecutor
from ..data import BarData
from ..config import load_config
from .base_engine import BaseEngine

logger = logging.getLogger(__name__)


class BacktestEngine(BaseEngine):
    """Backtest Engine for Strategy Testing"""

    def __init__(self, config_path: str):
        """
        Initialize backtest engine

        Args:
            config_path: Path to config YAML file
        """
        super().__init__(config_path)
        self.config = load_config(config_path)

        self.parquet_path = Path(self.config['parquet_path'])
        self.symbols = self.config['symbols']
        self.start_date = str(self.config['start_date'])
        self.end_date = str(self.config['end_date'])

        # Initialize strategies (support multiple strategies)
        strategies_config = self.config['strategies']
        self.strategies = self._load_strategies(strategies_config, default_symbols=self.symbols)

        # Create symbol matchers for each strategy
        self.symbol_matchers = self._create_symbol_matchers(self.strategies)

        # Initialize executor
        initial_capital = self.config.get('initial_capital', 1_000_000)
        commission_rate = self.config.get('commission_rate', 0.0003)
        self.executor = MockExecutor(initial_capital, commission_rate)

        # Statistics
        self.bars_processed = 0
        self.signals_generated = 0
        self.start_time = None
        self.end_time = None

        logger.info(f"ResearchEngine initialized: {len(self.strategies)} strategies, {len(self.symbols)} symbols, {self.start_date} - {self.end_date}")
        for strategy in self.strategies:
            logger.info(f"  - {strategy.name}: {strategy.symbols}")

    def load_data(self, symbol: str) -> pd.DataFrame:
        """
        Load parquet data for symbol

        Args:
            symbol: Stock symbol

        Returns:
            DataFrame with OHLCV data
        """
        # Find all parquet files for this symbol
        start_year = int(self.start_date[:4])
        end_year = int(self.end_date[:4])

        dfs = []
        for year in range(start_year, end_year + 1):
            parquet_file = self.parquet_path / f"{symbol}_{year}.parquet"
            if parquet_file.exists():
                df = pd.read_parquet(parquet_file)
                dfs.append(df)
                logger.info(f"Loaded {parquet_file}: {len(df)} rows")
            else:
                logger.warning(f"Parquet file not found: {parquet_file}")

        if not dfs:
            raise ValueError(f"No data found for {symbol}")

        # Concatenate all data
        full_df = pd.concat(dfs, ignore_index=True)

        # Filter by date range
        full_df['trade_time'] = pd.to_datetime(full_df['trade_time'])
        start_dt = pd.to_datetime(self.start_date, format='%Y%m%d')
        end_dt = pd.to_datetime(self.end_date, format='%Y%m%d')

        full_df = full_df[
            (full_df['trade_time'] >= start_dt) &
            (full_df['trade_time'] <= end_dt)
        ]

        # Sort by trade_time
        full_df = full_df.sort_values('trade_time').reset_index(drop=True)

        logger.info(f"Loaded {len(full_df)} bars for {symbol} ({self.start_date} - {self.end_date})")

        return full_df

    def run(self) -> Dict:
        """
        Run backtest

        Returns:
            Backtest results dictionary
        """
        logger.info("=" * 80)
        logger.info("Starting Research")
        logger.info("=" * 80)

        self.start_time = datetime.now()

        for symbol in self.symbols:
            logger.info(f"\nProcessing {symbol}...")

            try:
                # Load data
                df = self.load_data(symbol)

                # Process each bar
                for idx, row in df.iterrows():
                    # Create bar data
                    bar = BarData(
                        symbol=row['ts_code'],
                        timestamp=row['trade_time'],
                        open=float(row['open']),
                        high=float(row['high']),
                        low=float(row['low']),
                        close=float(row['close']),
                        volume=float(row['volume'])
                    )

                    # Call all strategies that are interested in this symbol
                    all_signals = []
                    for strategy in self.strategies:
                        matcher = self.symbol_matchers[strategy.name]
                        if not matcher.matches(bar.symbol):
                            continue

                        signals = strategy.on_bar(bar)
                        if signals:
                            all_signals.extend(signals)

                    self.bars_processed += 1

                    if all_signals:
                        # Execute all signals (market rules will filter invalid signals)
                        filled_orders = self.executor.execute_signals(all_signals, bar)

                        # Count only executed signals (passed market rules)
                        self.signals_generated += len(filled_orders)

                        # Notify strategies of fills
                        for signal in all_signals:
                            # Get filled orders
                            filled_orders = [
                                order for order in self.executor.orders[-len(all_signals):]
                                if order.status == 'filled' and order.strategy_id == signal.strategy_id
                            ]
                            # Find the strategy that generated this signal
                            for strategy in self.strategies:
                                if strategy.name == signal.strategy_id:
                                    for order in filled_orders:
                                        strategy.on_order_filled(order)
                                    break

                    # Log progress
                    if self.bars_processed % 10000 == 0:
                        logger.info(f"Processed {self.bars_processed} bars...")

                # Log final statistics for this symbol
                position = self.executor.get_position(symbol)
                logger.info(
                    f"{symbol} completed: position={position.quantity}, "
                    f"realized_pnl={position.realized_pnl:.2f}"
                )

            except Exception as e:
                logger.error(f"Error processing {symbol}: {e}")
                raise

        self.end_time = datetime.now()

        # Calculate final results
        results = self._calculate_results()

        # Print report
        self._print_report(results)

        return results

    def _calculate_results(self) -> Dict:
        """Calculate backtest results"""
        # Get current prices (use last known prices)
        current_prices = {}
        for symbol in self.symbols:
            position = self.executor.get_position(symbol)
            if position.quantity != 0:
                # Simplified: use avg_price as current price (should use last bar close)
                current_prices[symbol] = position.avg_price

        # Calculate PnL
        pnl_stats = self.executor.calculate_pnl(current_prices)

        # Add metadata
        # Use first strategy for backward compatibility
        first_strategy = self.strategies[0] if self.strategies else None
        pnl_stats.update({
            'bars_processed': self.bars_processed,
            'signals_generated': self.signals_generated,
            'duration_seconds': (self.end_time - self.start_time).total_seconds(),
            'strategy_name': first_strategy.name if first_strategy else 'unknown',
            'strategy_params': first_strategy.params if first_strategy else {},
            'symbols': self.symbols,
            'start_date': self.start_date,
            'end_date': self.end_date
        })

        return pnl_stats

    def _print_report(self, results: Dict):
        """Print backtest report"""
        logger.info("\n" + "=" * 80)
        logger.info("RESEARCH REPORT")
        logger.info("=" * 80)

        logger.info(f"Strategy: {results['strategy_name']}")
        logger.info(f"Parameters: {results['strategy_params']}")
        logger.info(f"Symbols: {results['symbols']}")
        logger.info(f"Period: {results['start_date']} - {results['end_date']}")
        logger.info("")

        logger.info("Performance:")
        logger.info(f"  Initial Capital: CNY {self.executor.initial_capital:,.2f}")
        logger.info(f"  Final Equity: CNY {results['total_equity']:,.2f}")
        logger.info(f"  Total PnL: CNY {results['total_pnl']:,.2f}")
        logger.info(f"  Return: {results['return_pct']:.2f}%")
        logger.info("")

        logger.info("Breakdown:")
        logger.info(f"  Cash: CNY {results['cash']:,.2f}")
        logger.info(f"  Position Value: CNY {results['position_value']:,.2f}")
        logger.info(f"  Realized PnL: CNY {results['realized_pnl']:,.2f}")
        logger.info(f"  Unrealized PnL: CNY {results['unrealized_pnl']:,.2f}")
        logger.info("")

        logger.info("Trading Statistics:")
        logger.info(f"  Bars Processed: {results['bars_processed']:,}")
        logger.info(f"  Signals Generated: {results['signals_generated']}")
        logger.info(f"  Total Trades: {results['total_trades']}")
        logger.info(f"  Total Commission: CNY {results['total_commission']:,.2f}")
        logger.info(f"  Duration: {results['duration_seconds']:.2f} seconds")
        logger.info("=" * 80)
