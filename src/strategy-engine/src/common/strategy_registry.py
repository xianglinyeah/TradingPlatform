"""Strategy Registry for Dynamic Loading"""
from ..strategies import (
    BaseStrategy,
    MovingAverageStrategy,
    BuyEveryBarStrategy,
    DailyBreakoutStrategy
)

# Strategy registry for dynamic loading
STRATEGY_CLASSES = {
    'MovingAverageStrategy': MovingAverageStrategy,
    'BuyEveryBarStrategy': BuyEveryBarStrategy,
    'DailyBreakoutStrategy': DailyBreakoutStrategy,
}
