"""Live Trading Engine (Kafka + gRPC)"""
from confluent_kafka import Consumer
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

# RunRegistry is optional for the default config-loaded path; required for hot-load.
try:
    from ..run import RunStatus, UnknownRunError, get_global_registry
    RUN_REGISTRY_AVAILABLE = True
except ImportError:
    RUN_REGISTRY_AVAILABLE = False
    UnknownRunError = KeyError  # type: ignore

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
            ch_section = self.config.get('clickhouse')
            if ch_section:
                logger.info("Initializing HistoryStore from ClickHouse: %s",
                            ch_section.get('host', 'clickhouse.infrastructure'))
                try:
                    from ..context.history_store import ClickHouseConfig
                    ch_cfg = ClickHouseConfig(
                        host=ch_section.get('host', 'clickhouse.infrastructure'),
                        port=int(ch_section.get('port', 8123)),
                        database=ch_section.get('database', 'market_data'),
                        username=ch_section.get('username', 'dev_user'),
                        password=ch_section.get('password', 'dev_pass'),
                    )

                    daily_window = int(ch_section.get('daily_window', self.config.get('daily_window', 120)))
                    minute_window = self.config.get('minute_window', 240)
                    self.history_store = HistoryStore(
                        daily_window=daily_window,
                        minute_window=minute_window,
                    )

                    # Restrict warmup to symbols the strategies actually care
                    # about. Strategies hold TS-format codes in config
                    # (600000.SH); HistoryStore uses GM format internally, so
                    # convert here.
                    warm_syms: list[str] = []
                    for s in self.strategies:
                        for sym in getattr(s, 'symbols', []) or []:
                            if sym not in warm_syms:
                                warm_syms.append(sym)

                    max_workers = self.config.get('warmup_max_workers', 8)
                    self.history_store.warmup(
                        clickhouse=ch_cfg,
                        symbols=warm_syms or None,
                        max_workers=max_workers,
                    )
                    logger.info("HistoryStore warmup completed successfully")

                    self.context = Context(self.history_store)

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
                logger.info("No 'clickhouse' config section; strategies will run without daily data")
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

        # Run registry (hot-loaded runs) - optional but usually present.
        # When a bar arrives with a SessionId that matches a registered run,
        # we route to that run's isolated strategy instance instead of the
        # config-loaded defaults below.
        self.run_registry = get_global_registry() if RUN_REGISTRY_AVAILABLE else None
        # Cache the executor's currently-active session_id so we only call
        # update_session_id on actual changes (avoids log spam).
        self._current_executor_session_id: Optional[str] = self.executor.session_id
        # Per-run symbol matchers, lazily built when a run is registered.
        self._run_matchers: Dict[str, object] = {}

        logger.info("LiveEngine initialized (Kafka + gRPC mode)")
        logger.info(f"Kafka: {self.kafka_brokers}, topic: {self.kafka_topic}")
        logger.info(f"Loaded {len(self.strategies)} strategies")
        for strategy in self.strategies:
            logger.info(f"  - {strategy.name}: {strategy.symbols}")
        if self.run_registry is not None:
            logger.info("RunRegistry available - per-run hot-load routing ENABLED")

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

            # Routing metadata - both optional. Source distinguishes
            # Simulation (replay) from GM (live). SessionId is the
            # run_id we dispatch on (see RunRegistry).
            session_id = data.get('sessionId') or data.get('SessionId') or data.get('session_id')
            source = data.get('source') or data.get('Source')

            if not symbol:
                raise ValueError(f"No symbol field found in data: {data}")

            logger.info(f"[KAFKA_MSG_PARSE] symbol={symbol}, timestamp_str={timestamp_str}, "
                        f"session_id={session_id}, source={source}")

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
                volume=float(volume) if volume else 0.0,
                session_id=session_id,
                source=source,
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

        # Create Kafka consumer using confluent-kafka (librdkafka-based, same
        # library used by market-data-gm). Configuration matches the previous
        # kafka-python settings: auto-commit on, earliest offset reset for new
        # groups, and the same session/heartbeat timeouts.
        consumer = Consumer({
            'bootstrap.servers': self.kafka_brokers,
            'group.id': self.kafka_group_id,
            # 'earliest' avoids silent message loss for a new group_id or
            # expired offsets; once offsets are committed this is unused.
            'auto.offset.reset': 'earliest',
            'enable.auto.commit': True,
            'session.timeout.ms': 180000,    # 3 minutes (was 30s originally)
            'heartbeat.interval.ms': 10000,  # 10 seconds (was 3s originally)
            # Refresh topic metadata every 10s instead of librdkafka's 5-min
            # default. Required for the smoke test, which deletes and recreates
            # the topic to clear it: without a fast refresh, the consumer can
            # sit on a stale "0 partitions" view for minutes after the topic
            # reappears. Cheap in steady state (one metadata fetch per interval).
            'topic.metadata.refresh.interval.ms': 10000,
        })
        consumer.subscribe([self.kafka_topic])

        logger.info(f"Connected to Kafka: {self.kafka_brokers}")
        logger.info("Waiting for market data...")
        logger.info("Press Ctrl+C to stop\n")

        try:
            while True:
                # poll() returns None on timeout; an error wrapper otherwise.
                message = consumer.poll(timeout=1.0)
                if message is None:
                    continue
                if message.error():
                    logger.warning("kafka error: %s", message.error())
                    continue
                try:
                    # Parse bar data. confluent-kafka exposes the payload via
                    # .value() (a method) rather than the kafka-python attribute.
                    bar = self.parse_kafka_message(message.value())

                    # Control messages return None.
                    if bar is None:
                        continue

                    all_signals = self._route_bar(bar)

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

                        # Execute signals - executor.session_id is kept in sync
                        # with the run we just routed to inside _route_bar.
                        filled_orders = self.executor.execute_signals(all_signals, bar)

                        # Notify the originating strategy instances of fills.
                        self._dispatch_fills(filled_orders, bar)

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

    # ------------------------------------------------------------------
    # Per-run routing (hot-loaded strategies)
    # ------------------------------------------------------------------

    def _route_bar(self, bar: BarData) -> List:
        """Decide which strategy instance(s) process this bar.

        Two paths:

        1. Per-run path (preferred when RunRegistry is available AND the
           bar's SessionId is registered). We dispatch to that run's
           isolated strategy instance and switch the executor's
           session_id so orders land in the right Execution.Service
           session.

        2. Default path (legacy). Bar is routed to every config-loaded
           strategy whose SymbolMatcher accepts it. This preserves the
           pre-hot-load behaviour for live GM traffic and for any
           simulation that did not pre-register its run_id.

        Returning an empty list means "no signal this bar".
        """
        # Try per-run routing first.
        if self.run_registry is not None and bar.session_id and \
                self.run_registry.has(bar.session_id):
            ctx = self.run_registry.get(bar.session_id)

            # Symbol filter at the run level.
            matcher = self._get_or_create_run_matcher(ctx)
            if not matcher.matches(bar.symbol):
                return []

            # Switch the executor session so subsequent gRPC SubmitOrder
            # calls carry this run's identifier. Cheap when unchanged.
            self._sync_executor_session(ctx.run_id)

            ctx.touch()
            ctx.bars_processed += 1
            with metrics.bar_processing_duration.labels(
                strategy_name=ctx.strategy_name
            ).time():
                signals = ctx.strategy_instance.on_bar(bar)
            if signals:
                ctx.signals_generated += len(signals)
                metrics.bars_processed.labels(symbol=bar.symbol).inc()
            return signals or []

        # Default path (also reached when a bar's session_id is not registered,
        # e.g. a replay started directly without going through Dashboard.Service).
        # We DO NOT drop the bar - that would break the smoke test, the live GM
        # feed, and any pre-existing replay workflow. Instead we fall back to
        # the config-loaded default strategies and log a one-shot hint so users
        # know hot-load is available.
        if self.run_registry is not None and bar.session_id and bar.source == "Simulation":
            # Log at debug to avoid spam - every replay bar without a registered
            # run_id hits this. Real spec violations (Dashboard.Service forgot
            # to register) are rare and surface as "no trades" anyway.
            logger.debug(
                "Bar for unregistered run_id=%s falling back to default strategies. "
                "Register via POST /runs/%s/config for per-run isolation.",
                bar.session_id, bar.session_id,
            )

        # Default path: fan out to config-loaded strategies.
        all_signals = []
        for strategy in self.strategies:
            matcher = self.symbol_matchers[strategy.name]
            if not matcher.matches(bar.symbol):
                continue
            with metrics.bar_processing_duration.labels(
                strategy_name=strategy.name
            ).time():
                signals = strategy.on_bar(bar)
            if signals:
                all_signals.extend(signals)
            metrics.bars_processed.labels(symbol=bar.symbol).inc()
        return all_signals

    def _get_or_create_run_matcher(self, ctx):
        """Cache a SymbolMatcher per run_id. Matcher construction is
        cheap but called per-bar, so memoize on run_id."""
        from ..utils.symbol_matcher import SymbolMatcher

        matcher = self._run_matchers.get(ctx.run_id)
        if matcher is None:
            matcher = SymbolMatcher(ctx.symbols, ctx.exclude_symbols)
            self._run_matchers[ctx.run_id] = matcher
        return matcher

    def _sync_executor_session(self, session_id: str) -> None:
        """Update the executor's session_id only on actual change.

        The executor stamps session_id onto every gRPC order/position
        request. For multi-run isolation it must match the run that
        produced the signal. We avoid spamming the log when consecutive
        bars come from the same run.
        """
        if session_id == self._current_executor_session_id:
            return
        if hasattr(self.executor, "update_session_id"):
            self.executor.update_session_id(session_id)
            self._current_executor_session_id = session_id

    def _dispatch_fills(self, filled_orders, bar: BarData) -> None:
        """Notify the originating strategy instance of each fill.

        For per-run orders, strategy_id on the order is
        "<class_name>::<run_id>" (set by RunRegistry.register). We
        resolve it back to the run's strategy instance.

        For default-path orders, strategy_id is the config strategy name
        and we look it up in self.strategies as before.
        """
        for order in filled_orders:
            strategy_instance = self._resolve_strategy_instance(order.strategy_id)
            if strategy_instance is not None:
                strategy_instance.on_order_filled(order)

            logger.info(
                f"[{order.strategy_id}] Filled: {order.side.upper()} {order.quantity} "
                f"{order.symbol} @ {order.avg_price:.2f}"
            )

    def _resolve_strategy_instance(self, strategy_id: str):
        """Find the strategy instance that produced an order.

        strategy_id format from RunRegistry is "<class>::<run_id>";
        from default strategies it is the bare strategy name.
        """
        # Per-run: "<class>::<run_id>"
        if "::" in strategy_id and self.run_registry is not None:
            run_id = strategy_id.split("::", 1)[1]
            try:
                ctx = self.run_registry.get(run_id)
                return ctx.strategy_instance
            except UnknownRunError:
                # The run was swept between signal and fill - log and
                # fall through to the default lookup.
                logger.warning(
                    "Run gone before fill notification: strategy_id=%s",
                    strategy_id,
                )

        # Default path
        for strategy in self.strategies:
            if strategy.name == strategy_id:
                return strategy
        return None

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
