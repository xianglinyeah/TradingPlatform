"""Strategies Module"""
from .base import BaseStrategy
from .moving_average import MovingAverageStrategy
from .buy_every_bar import BuyEveryBarStrategy
from .daily_breakout import DailyBreakoutStrategy

__all__ = [
    'BaseStrategy',
    'MovingAverageStrategy',
    'BuyEveryBarStrategy',
    'DailyBreakoutStrategy',
]
