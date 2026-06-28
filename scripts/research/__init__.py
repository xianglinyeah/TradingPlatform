"""Marker package for one-off alpha research scripts.

Scripts under ``scripts/research/`` are NOT part of strategy-engine or any
deployed service. They are vectorized pandas/numpy validations run on the host
against the same data sources (ClickHouse market data, PostgreSQL
fundamentals) used by the live trading stack.

Run from the project root, e.g.::

    python -m scripts.research.volume_breakout_alpha
"""
