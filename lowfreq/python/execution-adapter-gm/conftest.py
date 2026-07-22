"""Pytest bootstrap for execution-adapter-gm.

Adds the project root to ``sys.path`` so test modules can import siblings
using the same bare-module form the application itself uses, e.g.::

    from utils.symbol_converter import from_gm
    from broker.enums import proto_side_to_gm

This mirrors how ``main.py`` is launched (``python main.py`` from the
project root) and keeps the tests decoupled from any packaging metadata
that does not yet exist (no setup.py / pyproject.toml).
"""
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
