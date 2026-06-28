"""
Context - Unified data access layer for strategies.

Provides strategies with access to historical data without exposing
data sources (Parquet/Kafka/DB).
"""

import logging
import pandas as pd
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .history_store import HistoryStore
    from .reference_store import ReferenceStore

logger = logging.getLogger(__name__)


class Context:
    """
    Single data entry point for strategies.

    Usage:
        daily_df  = context.get_daily_bars(symbol)   # pd.DataFrame
        minute_df = context.get_minute_bars(symbol)  # pd.DataFrame
        fund      = context.reference.get_fundamental(symbol)
    """

    def __init__(
        self,
        history_store: "HistoryStore",
        reference_store: Optional["ReferenceStore"] = None,
    ) -> None:
        self._history = history_store
        self.reference = reference_store

        # Import here to avoid circular dependency
        from .reference_store import ReferenceStore as RefStore
        if self.reference is None:
            self.reference = RefStore()

    # ------------------------------------------------------------------
    # Market data (returns DataFrame for easy pandas operations)
    # ------------------------------------------------------------------

    def get_daily_bars(self, symbol: str) -> pd.DataFrame:
        """
        Return last N daily bars (determined by HistoryStore.daily_window).
        Columns: date, open, high, low, close, volume
        Sorted ascending by time; latest row is yesterday's close.
        """
        records = self._history.get_daily_bars(symbol)
        if not records:
            return pd.DataFrame()
        return pd.DataFrame(records)

    def get_minute_bars(self, symbol: str) -> pd.DataFrame:
        """
        Return last N minute bars.
        Columns: datetime, open, high, low, close, volume
        Sorted ascending by time; latest row is current bar.
        """
        records = self._history.get_minute_bars(symbol)
        if not records:
            return pd.DataFrame()
        return pd.DataFrame(records)

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def is_ready(self) -> bool:
        return self._history.is_ready
