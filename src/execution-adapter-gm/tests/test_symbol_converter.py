"""Unit tests for ``utils.symbol_converter``.

Covers the two public helpers ``from_gm`` / ``to_gm`` plus the documented
edge cases (missing dot, empty string, unknown exchange prefix).

GM format:   SHSE.600000 / SZSE.000001
Std format:  600000.SH  / 000001.SZ
"""
from utils.symbol_converter import from_gm, to_gm


# ---------- from_gm: GM -> std ----------

def test_from_gm_shse():
    """SHSE.600000 -> 600000.SH"""
    assert from_gm("SHSE.600000") == "600000.SH"


def test_from_gm_szse():
    """SZSE.000001 -> 000001.SZ"""
    assert from_gm("SZSE.000001") == "000001.SZ"


def test_from_gm_no_dot():
    """Input without a dot is returned unchanged."""
    assert from_gm("600000") == "600000"


def test_from_gm_empty():
    """Empty string short-circuits to empty."""
    assert from_gm("") == ""


def test_from_gm_unknown_exchange():
    """Unknown exchange prefix is preserved verbatim (passthrough).

    The implementation upper-cases the prefix before lookup, so an
    unrecognized token simply reappears as the suffix.
    """
    assert from_gm("UNKNOWN.123") == "123.UNKNOWN"


def test_from_gm_lowercase_exchange():
    """Exchange matching is case-insensitive."""
    assert from_gm("shse.600000") == "600000.SH"
    assert from_gm("szse.000001") == "000001.SZ"


def test_from_gm_preserves_code_with_dots():
    """Only the first dot splits exchange / code; the rest is kept verbatim."""
    # ``split(".", 1)`` keeps everything after the first dot as the code.
    assert from_gm("SHSE.600000.A") == "600000.A.SH"


# ---------- to_gm: std -> GM ----------

def test_to_gm_sh():
    """600000.SH -> SHSE.600000"""
    assert to_gm("600000.SH") == "SHSE.600000"


def test_to_gm_sz():
    """000001.SZ -> SZSE.000001"""
    assert to_gm("000001.SZ") == "SZSE.000001"


def test_to_gm_no_dot():
    """Input without a dot is returned unchanged."""
    assert to_gm("600000") == "600000"


def test_to_gm_empty():
    """Empty string short-circuits to empty."""
    assert to_gm("") == ""


def test_to_gm_unknown_exchange():
    """Unknown short suffix is preserved verbatim (passthrough)."""
    assert to_gm("123.UNKNOWN") == "UNKNOWN.123"


def test_to_gm_lowercase_suffix():
    """Short-suffix matching is case-insensitive."""
    assert to_gm("600000.sh") == "SHSE.600000"
    assert to_gm("000001.sz") == "SZSE.000001"


# ---------- round trips ----------

def test_roundtrip_shse():
    """from_gm ∘ to_gm is identity for SHSE symbols."""
    assert to_gm(from_gm("SHSE.600000")) == "SHSE.600000"


def test_roundtrip_szse():
    """from_gm ∘ to_gm is identity for SZSE symbols."""
    assert to_gm(from_gm("SZSE.000001")) == "SZSE.000001"


def test_roundtrip_std_to_gm_to_std():
    """to_gm ∘ from_gm is identity for std symbols."""
    assert from_gm(to_gm("600000.SH")) == "600000.SH"
    assert from_gm(to_gm("000001.SZ")) == "000001.SZ"
