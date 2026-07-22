"""
Context module for strategy data access layer.
Provides unified API for historical data access without exposing data sources.
"""

from .context import Context
from .history_store import HistoryStore
from .reference_store import ReferenceStore

__all__ = ['Context', 'HistoryStore', 'ReferenceStore']
