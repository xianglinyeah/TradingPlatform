"""Pytest configuration: ensure src/data-ingestion root is on sys.path.

This allows test modules to use the same import style as the source code:
    from core.schema import ...
    from pipelines.fundamentals.merge import ...
"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
