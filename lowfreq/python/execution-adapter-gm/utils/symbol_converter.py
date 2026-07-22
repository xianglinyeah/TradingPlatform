"""Symbol format conversion.

GM format:   SHSE.600000 / SZSE.000001
Std format:  600000.SH  / 000001.SZ
"""
from __future__ import annotations


_EXCHANGE_FULL_TO_SHORT = {
    "SHSE": "SH",
    "SZSE": "SZ",
}

_EXCHANGE_SHORT_TO_FULL = {
    "SH": "SHSE",
    "SZ": "SZSE",
}


def from_gm(symbol: str) -> str:
    """SHSE.600000 -> 600000.SH. Returns the input unchanged if not recognized."""
    if not symbol or "." not in symbol:
        return symbol
    exchange, code = symbol.split(".", 1)
    suffix = _EXCHANGE_FULL_TO_SHORT.get(exchange.upper(), exchange)
    return f"{code}.{suffix}"


def to_gm(symbol: str) -> str:
    """600000.SH -> SHSE.600000. Returns the input unchanged if not recognized."""
    if not symbol or "." not in symbol:
        return symbol
    code, exchange = symbol.split(".", 1)
    full = _EXCHANGE_SHORT_TO_FULL.get(exchange.upper(), exchange)
    return f"{full}.{code}"
