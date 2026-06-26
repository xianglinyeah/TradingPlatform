"""Live Trading Engine (Kafka + gRPC)"""
from kafka import KafkaConsumer
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional

from .. import metrics

try:
    from ..execution import RealGrpcExecutor
    REAL_GRPC_AVAILABLE = True
except ImportError:
    REAL_GRPC_AVAILABLE = False
from ..data import BarData
from ..config import load_config
from .base_engine import BaseEngine

# Import Context and HistoryStore for daily data support
try:
    from ..context import Context, HistoryStore
    CONTEXT_AVAILABLE = True
except ImportError:
    CONTEXT_AVAILABLE = False
    Context = None
    HistoryStore = None

logger = logging.getLogger(__name__)


class LiveEngine(BaseEngine):
    """
    Live Trading Engine (Kafka + gRPC)

    Consumes market data from Kafka and executes strategies via gRPC to ExecutionService
    Data source is determined by ReplayService (historical replay) or MarketDataService (live data)
    """

    def __init__(self, config_path: str):
        """
        Initialize live engine

        Args:
            config_path: Path to config YAML file
        """
        super().__init__(config_path)
        self.config = load_config(config_path)
        self.mode = self.config.get('mode', 'live')  # Set mode from config

        # Kafka configuration
        self.kafka_brokers = self.config['kafka_brokers']
        self.kafka_topic = self.config['kafka_topic']
        self.kafka_group_id = self.config['kafka_group_id']

        # Initialize strategies (support multiple strategies)
        strategies_config = self.config['strategies']
        self.strategies = self._load_strategies(strategies_config)

        self.symbol_matchers = self._create_symbol_matchers(self.strategies)

        # Initialize HistoryStore and Context for daily data support
        self.context: Optional[Context] = None
        self.history_store: Optional[HistoryStore] = None

        if CONTEXT_AVAILABLE:
            parquet_dir = self.config.get('parquet_data_dir')
            if parquet_dir:
                logger.info(f"Initializing HistoryStore with parquet_dir: {parquet_dir}")
                try:
                    # Initialize HistoryStore with default windows
                    daily_window = self.config.get('daily_window', 120)
                    minute_window = self.config.get('minute_window', 240)
                    self.history_store = HistoryStore(
                        daily_window=daily_window,
                        minute_window=minute_window
                    )

                    # Warmup HistoryStore (BLOCKING - waits for completion)
                    logger.info("Starting HistoryStore warmup (this may take several seconds)...")
                    max_workers = self.config.get('warmup_max_workers', 8)
                    self.history_store.warmup(parquet_dir, max_workers=max_workers)
                    logger.info("HistoryStore warmup completed successfully")

                    # Create Context
                    self.context = Context(self.history_store)

                    # Set context for all strategies that support it
                    context_set_count = 0
                    for strategy in self.strategies:
                        if hasattr(strategy, 'set_context'):
                            strategy.set_context(self.context)
                            context_set_count += 1

                    logger.info(f"Context set for {context_set_count}/{len(self.strategies)} strategies")

                except Exception as e:
                    logger.error(f"Failed to initialize HistoryStore: {e}")
                    logger.warning("Strategies will run without daily data context")
                    self.history_store = None
                    self.context = None
            else:
                logger.info("No parquet_data_dir configured, strategies will run without daily data")
        else:
            logger.info("Context module not available, strategies will run without daily data")

        # Initialize executor - ONLY GRPC MODE SUPPORTED
        initial_capital = self.config.get('initial_capital', 1_000_000)
        commission_rate = self.config.get('commission_rate', 0.0003)

        # Always use gRPC executor
        if not REAL_GRPC_AVAILABLE:
            raise ImportError("RealGrpcExecutor not available. Please check gRPC dependencies.")

        execution_service_address = self.config.get('execution_service_address', 'localhost:5101')
        session_id = self.config.get('session_id', None)
        self.executor = RealGrpcExecutor(execution_service_address, session_id, initial_capital)

        # Statistics
        self.bars_processed = 0
        self.signals_generated = 0
        self.start_time = None

        logger.info("LiveEngine initialized (Kafka + gRPC mode)")
        logger.info(f"Kafka: {self.kafka_brokers}, topic: {self.kafka_topic}")
        logger.info(f"Loaded {len(self.strategies)} strategies")
        for strategy in self.strategies:
            logger.info(f"  - {strategy.name}: {strategy.symbols}")

    def update_session_id(self, session_id: str):
        """
        Update session ID for new replay session

        Args:
            session_id: New session ID from ReplayService
        """
        logger.info(f"Updating session ID to: {session_id}")
        if hasattr(self.executor, 'update_session_id'):
            self.executor.update_session_id(session_id)
        else:
            logger.warning("Executor does not support session ID updates")

        # Reset all strategies
        for strategy in self.strategies:
            strategy.reset()

    def parse_kafka_message(self, message: bytes) -> BarData:
        """
        Parse Kafka message into BarData

        Args:
            message: Raw Kafka message bytes

        Returns:
            BarData object or None (for control messages)
        """
        try:
            data = json.loads(message.decode('utf-8'))

            # Debug: log the data structure
            logger.info(f"[KAFKA_MSG_RECEIVED] Raw data: {data}")

            # Check if this is a control message
            if isinstance(data, dict) and data.get('type') == 'RESET':
                logger.info("Received RESET signal, resetting strategy state")
                # Extract and update session_id
                new_session_id = data.get('session_id')
                if new_session_id:
                    self.update_session_id(new_session_id)
                    logger.info(f"Session ID updated from RESET message: {new_session_id}")
                # Strategies are reset in update_session_id
                return None  # Return None for control messages, not processed as bar data

            # Handle different possible field names
            symbol = data.get('symbol') or data.get('ts_code') or data.get('Symbol')
            timestamp_str = (data.get('timestamp') or data.get('trade_time') or
                           data.get('datetime') or data.get('eventTime') or
                           data.get('EventTime'))  # Add EventTime for Replay system
            open_price = data.get('open') or data.get('Open') or data.get('o')
            high_price = data.get('high') or data.get('High') or data.get('h')
            low_price = data.get('low') or data.get('Low') or data.get('l')
            close_price = data.get('close') or data.get('Close') or data.get('c')
            volume = data.get('volume') or data.get('Volume') or data.get('vol') or data.get('v')

            if not symbol:
                raise ValueError(f"No symbol field found in data: {data}")

            logger.info(f"[KAFKA_MSG_PARSE] symbol={symbol}, timestamp_str={timestamp_str}")

            # Parse timestamp
            if isinstance(timestamp_str, str):
                if timestamp_str.endswith('Z'):
                    timestamp_str = timestamp_str.replace('Z', '+00:00')
                timestamp = datetime.fromisoformat(timestamp_str)
            else:
                timestamp = datetime.now()
                logger.warning(f"[KAFKA_MSG_PARSE] No valid timestamp_str, using current time: {timestamp}")

            logger.info(f"[LIVE_ENGINE] Parsed bar: {symbol} @ {timestamp} (from Kafka message)")
            return BarData(
                symbol=symbol,
                timestamp=timestamp,
                open=float(open_price) if open_price else 0.0,
                high=float(high_price) if high_price else 0.0,
                low=float(low_price) if low_price else 0.0,
                close=float(close_price) if close_price else 0.0,
                volume=float(volume) if volume else 0.0
            )
        except Exception as e:
            logger.error(f"Failed to parse Kafka message: {e}")
            logger.debug(f"Message content: {message}")
            raise

    def run(self):
        """Run live trading engine (Kafka + gRPC)"""
        logger.info("=" * 80)
        logger.info("Starting Live Trading Engine (Kafka + gRPC)")
        logger.info("=" * 80)

        self.start_time = datetime.now()

        # Create Kafka consumer with improved configuration
        consumer = KafkaConsumer(
            self.kafka_topic,
            bootstrap_servers=self.kafka_brokers,
            group_id=self.kafka_group_id,
            # 'earliest' avoids silent message loss for a new group_id or
            # expired offsets; once offsets are committed this is unused.
            auto_offset_reset='earliest',
            enable_auto_commit=True,
            api_version=(2, 6, 0),  # Specify Kafka version to avoid compression issues
            # Removed consumer_timeout_ms for production - run indefinitely
            session_timeout_ms=180000,  # Session timeout 3 minutes (increased from 30s)
            heartbeat_interval_ms=10000  # Heartbeat interval 10 seconds (increased from 3s)
        )

        logger.info(f"Connected to Kafka: {self.kafka_brokers}")
        logger.info("Waiting for market data...")
        logger.info("Press Ctrl+C to stop\n")

        try:
            for message in consumer:
                try:
                    # Parse bar data
                    bar = self.parse_kafka_message(message.value)

                    # Control messages return None.
                    if bar is None:
                        continue

                    all_signals = []
                    for strategy in self.strategies:
                        matcher = self.symbol_matchers[strategy.name]
                        if not matcher.matches(bar.symbol):
                            continue

                        with metrics.bar_processing_duration.labels(strategy_name=strategy.name).time():
                            signals = strategy.on_bar(bar)
                        if signals:
                            all_signals.extend(signals)
                        metrics.bars_processed.labels(symbol=bar.symbol).inc()

                    self.bars_processed += 1

                    if all_signals:
                        self.signals_generated += len(all_signals)

                        # Log signals
                        for signal in all_signals:
                            logger.info(
                                f"[{signal.strategy_id}] Signal: {signal.signal_type.upper()} "
                                f"{signal.quantity} {signal.symbol} "
                                f"@ {bar.close:.2f} - {signal.reason}"
                            )

                        # Execute signals
                        filled_orders = self.executor.execute_signals(all_signals, bar)

                        # Notify strategies of fills
                        for order in filled_orders:
                            # Find the strategy that placed this order
                            for strategy in self.strategies:
                                if strategy.name == order.strategy_id:
                                    strategy.on_order_filled(order)
                                    break

                            logger.info(
                                f"[{order.strategy_id}] Filled: {order.side.upper()} {order.quantity} "
                                f"{order.symbol} @ {order.avg_price:.2f}"
                            )

                    # Log status periodically
                    if self.bars_processed % 100 == 0:
                        self._log_status(bar)

                except Exception as e:
                    logger.error(f"Error processing message: {e}")
                    continue

        except KeyboardInterrupt:
            logger.info("\nShutting down...")

        finally:
            consumer.close()
            self._print_final_report()

    def _log_status(self, current_bar: BarData):
        """Log current status"""
        position = self.executor.get_position(current_bar.symbol)

        logger.info(
            f"[{self.bars_processed} bars] {current_bar.symbol} @ {current_bar.close:.2f} | "
            f"Position: {position.quantity} | "
            f"PnL: {position.total_pnl(current_bar.close):.2f}"
        )

    def _print_final_report(self):
        """Print final report"""
        duration = (datetime.now() - self.start_time).total_seconds()

        logger.info("\n" + "=" * 80)
        logger.info(f"{self.mode.upper()} TRADING REPORT")
        logger.info("=" * 80)

        logger.info(f"Duration: {duration:.2f} seconds")
        logger.info(f"Bars Processed: {self.bars_processed}")
        logger.info(f"Signals Generated: {self.signals_generated}")
        logger.info(f"Total Trades: {self.executor.total_trades}")

        # Print positions
        logger.info("\nPositions:")
        positions = self.executor.get_all_positions()
        if positions:
            for symbol, pos in positions.items():
                logger.info(f"  {symbol}: {pos.quantity} shares @ {pos.avg_price:.2f}")
        else:
            logger.info("  No open positions")

        logger.info(f"\nCash: ¥{self.executor.cash:,.2f}")
        logger.info("=" * 80)
