"""Base Engine Module"""
from typing import List, Dict, Optional
from pathlib import Path
import logging
import os

from ..strategies import BaseStrategy
from ..common.strategy_registry import STRATEGY_CLASSES
from ..utils.symbol_matcher import SymbolMatcher


logger = logging.getLogger(__name__)


class BaseEngine:
    """
    Base Engine Class - Common functionality for Backtest and Live engines
    """

    def __init__(self, config_path: str):
        """Initialize base engine with config"""
        self.config_path = config_path

    def _resolve_universe_symbols(self, universe_id: str) -> List[str]:
        """Resolve a universe_id from market_ref.universe_member via PostgreSQL.

        Uses the UNIVERSE_PG_CONN env var (Npgsql-style connection string).
        Returns an empty list if the env var is unset (e.g. research mode),
        in which case the strategy falls back to its explicit symbols list.
        """
        conn_str = os.getenv("UNIVERSE_PG_CONN")
        if not conn_str:
            logger.warning(
                "UNIVERSE_PG_CONN not set; cannot resolve universe_id=%s", universe_id
            )
            return []
        from ..data.universe import UniverseLookup
        lookup = UniverseLookup(conn_str)
        members = lookup.get_current_members(universe_id)
        logger.info(
            "Resolved universe_id=%s -> %d symbols", universe_id, len(members)
        )
        return members

    def _load_strategies(self, strategies_config: List[Dict],
                          default_symbols: List[str] = None) -> List[BaseStrategy]:
        """
        Load strategies from configuration (Common method for both engines)

        Each strategy may declare either:
          - `symbols:` explicit list (legacy)
          - `universe_id:` resolve membership from market_ref at startup
        If both are present, the explicit list wins. If neither, falls back
        to default_symbols.

        Args:
            strategies_config: Strategy configurations from YAML
            default_symbols: Default symbols list if not specified in config

        Returns:
            List of enabled strategy instances
        """
        # Load enabled strategies
        strategies = []
        for strategy_config in strategies_config:
            if not strategy_config.get('enabled', True):
                logger.info(f"Skipping disabled strategy: {strategy_config.get('name')}")
                continue

            strategy_name = strategy_config['name']
            strategy_class_name = strategy_config.get('class', 'MovingAverageStrategy')
            strategy_exclude_symbols = strategy_config.get('exclude_symbols', [])
            strategy_params = strategy_config.get('params', {})

            # Symbol resolution: explicit list wins; else universe_id; else default
            if 'symbols' in strategy_config and strategy_config['symbols']:
                strategy_symbols = strategy_config['symbols']
                logger.info(f"Strategy {strategy_name}: using explicit symbols list")
            elif strategy_config.get('universe_id'):
                strategy_symbols = self._resolve_universe_symbols(
                    strategy_config['universe_id']
                )
                logger.info(
                    f"Loaded strategy: {strategy_name} "
                    f"(universe_id={strategy_config['universe_id']}, "
                    f"{len(strategy_symbols)} symbols)"
                )
            else:
                strategy_symbols = default_symbols or []
                logger.info(f"Strategy {strategy_name}: using default symbols")

            if strategy_class_name not in STRATEGY_CLASSES:
                logger.error(f"Unknown strategy class: {strategy_class_name}")
                continue

            strategy_class = STRATEGY_CLASSES[strategy_class_name]
            strategy = strategy_class(
                name=strategy_name,
                symbols=strategy_symbols,
                exclude_symbols=strategy_exclude_symbols,
                params=strategy_params
            )
            strategies.append(strategy)
            logger.info(f"Loaded strategy: {strategy_name} ({strategy_class_name})")
            logger.info(f"  Symbols: {len(strategy_symbols)} symbols, Excludes: {strategy_exclude_symbols}")

        return strategies

    def _create_symbol_matchers(self, strategies: List[BaseStrategy]) -> Dict[str, SymbolMatcher]:
        """
        Create symbol matchers for strategies

        Args:
            strategies: List of strategy instances

        Returns:
            Dict mapping strategy name to its symbol matcher
        """
        symbol_matchers = {}
        for strategy in strategies:
            matcher = SymbolMatcher(strategy.symbols, strategy.exclude_symbols)
            symbol_matchers[strategy.name] = matcher
            logger.debug(f"  Symbol matcher for {strategy.name}: {matcher}")

        return symbol_matchers
