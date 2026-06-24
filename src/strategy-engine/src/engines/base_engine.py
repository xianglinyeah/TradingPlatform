"""Base Engine Module"""
from typing import List, Dict
from pathlib import Path
import logging

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

    def _load_strategies(self, strategies_config: List[Dict],
                          default_symbols: List[str] = None) -> List[BaseStrategy]:
        """
        Load strategies from configuration (Common method for both engines)

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
            strategy_symbols = strategy_config.get('symbols', default_symbols or [])
            strategy_exclude_symbols = strategy_config.get('exclude_symbols', [])
            strategy_params = strategy_config.get('params', {})

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
            logger.info(f"  Symbols: {strategy_symbols}, Excludes: {strategy_exclude_symbols}")

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
