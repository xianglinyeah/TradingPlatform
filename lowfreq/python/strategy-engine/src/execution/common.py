"""Execution Common Types"""
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, List


@dataclass
class Signal:
    """Trading Signal"""
    symbol: str
    signal_type: str  # 'buy' or 'sell'
    quantity: int
    price: Optional[float] = None  # None for market order
    reason: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    strategy_id: str = ""  # Strategy that generated this signal

    def __repr__(self) -> str:
        price_str = f"@ {self.price:.2f}" if self.price else "MARKET"
        return f"Signal({self.signal_type.upper()} {self.quantity} {self.symbol} {price_str})"


@dataclass
class Order:
    """Order"""
    symbol: str
    side: str  # 'buy' or 'sell'
    quantity: int
    price: Optional[float] = None
    status: str = "pending"  # pending, filled, cancelled
    filled_time: Optional[datetime] = None
    filled_price: Optional[float] = None
    filled_quantity: int = 0
    commission: float = 0.0
    avg_price: float = 0.0
    strategy_id: str = ""  # Strategy that placed this order

    def fill(self, price: float, quantity: int, commission: float) -> None:
        """Fill the order at the given price and commission."""
        self.filled_price = price
        self.filled_quantity = quantity
        self.commission = commission
        self.avg_price = price  # Simplified: no partial fills
        self.status = "filled"
        self.filled_time = datetime.now()

    def __repr__(self) -> str:
        return (
            f"Order({self.side.upper()} {self.quantity} {self.symbol}, "
            f"status={self.status}, avg_price={self.avg_price:.2f})"
        )


@dataclass
class PositionLot:
    """Position lot for tracking buy batches"""
    quantity: int
    buy_price: float
    buy_date: date


class Position:
    """Position with lot tracking for market rules"""

    def __init__(self, symbol: str = ""):
        self.symbol = symbol
        self.quantity = 0
        self.avg_price = 0.0
        self.realized_pnl = 0.0
        self.lots: List[PositionLot] = []  # Track buy lots for T+1 rule

    def add(self, quantity: int, price: float, buy_date: date = None) -> None:
        """Add to position (buy)."""
        if buy_date is None:
            buy_date = date.today()

        if self.quantity == 0:
            self.avg_price = price
            self.quantity = quantity
        else:
            # Weighted average price
            total_cost = self.quantity * self.avg_price + quantity * price
            self.quantity += quantity
            self.avg_price = total_cost / self.quantity

        # Track lot for T+1 rule
        self.lots.append(PositionLot(
            quantity=quantity,
            buy_price=price,
            buy_date=buy_date
        ))

    def reduce(self, quantity: int, price: float, trade_date: date = None) -> None:
        """Reduce position (sell) with FIFO lot tracking."""
        if trade_date is None:
            trade_date = date.today()

        if self.quantity < quantity:
            raise ValueError(f"Cannot sell {quantity}, only have {self.quantity}")

        # Calculate realized PnL using avg_price
        self.realized_pnl += (price - self.avg_price) * quantity
        self.quantity -= quantity

        # Reduce lots (FIFO - First In First Out)
        remaining_to_reduce = quantity
        lots_to_keep = []

        for lot in self.lots:
            if remaining_to_reduce <= 0:
                lots_to_keep.append(lot)
                continue

            if lot.buy_date < trade_date:  # Can only sell lots bought before today
                if lot.quantity <= remaining_to_reduce:
                    remaining_to_reduce -= lot.quantity
                    # Don't add to lots_to_keep (lot fully sold)
                else:
                    # Partially reduce this lot
                    lot.quantity -= remaining_to_reduce
                    remaining_to_reduce = 0
                    lots_to_keep.append(lot)
            else:
                lots_to_keep.append(lot)  # Keep today's lots (cannot sell)

        self.lots = lots_to_keep

        if self.quantity == 0:
            self.avg_price = 0.0
            self.lots = []

    def get_sellable_quantity(self, trade_date: date = None) -> int:
        """Get quantity that can be sold on trade_date (excluding today's purchases)"""
        if trade_date is None:
            trade_date = date.today()

        sellable = sum(
            lot.quantity for lot in self.lots
            if lot.buy_date < trade_date
        )
        return sellable

    def market_value(self, current_price: float) -> float:
        """Calculate market value"""
        return self.quantity * current_price

    def unrealized_pnl(self, current_price: float) -> float:
        """Calculate unrealized PnL"""
        if self.quantity == 0:
            return 0.0
        return (current_price - self.avg_price) * self.quantity

    def total_pnl(self, current_price: float) -> float:
        """Calculate total PnL"""
        return self.realized_pnl + self.unrealized_pnl(current_price)

    def __repr__(self) -> str:
        return (
            f"Position(quantity={self.quantity}, "
            f"avg_price={self.avg_price:.2f}, "
            f"realized_pnl={self.realized_pnl:.2f}, "
            f"lots={len(self.lots)})"
        )
