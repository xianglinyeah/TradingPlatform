"""Unit tests for SymbolMatcher"""
import pytest
from src.utils.symbol_matcher import SymbolMatcher


class TestSymbolMatcher:
    """Test suite for wildcard symbol matching"""

    def test_exact_match(self):
        """Test exact symbol matching"""
        matcher = SymbolMatcher(["600519.SH", "000001.SZ"])

        assert matcher.matches("600519.SH") == True
        assert matcher.matches("000001.SZ") == True
        assert matcher.matches("600000.SH") == False
        assert matcher.matches("000002.SZ") == False

    def test_wildcard_all(self):
        """Test '*' wildcard (all stocks)"""
        matcher = SymbolMatcher(["*"])

        assert matcher.matches("600519.SH") == True
        assert matcher.matches("000001.SZ") == True
        assert matcher.matches("600000.SH") == True
        assert matcher.matches("999999.SH") == True  # Even fake symbols

    def test_wildcard_exchange(self):
        """Test exchange wildcards (*.SH, *.SZ)"""
        matcher = SymbolMatcher(["*.SH"])

        assert matcher.matches("600519.SH") == True
        assert matcher.matches("600000.SH") == True
        assert matcher.matches("000001.SZ") == False
        assert matcher.matches("000002.SZ") == False

    def test_wildcard_prefix(self):
        """Test prefix wildcards (600*.SH, 00*.SZ)"""
        matcher = SymbolMatcher(["600*.SH", "00*.SZ"])

        assert matcher.matches("600000.SH") == True
        assert matcher.matches("600519.SH") == True
        assert matcher.matches("603000.SH") == False  # 603 prefix doesn't match
        assert matcher.matches("000001.SZ") == True
        assert matcher.matches("002594.SZ") == True
        assert matcher.matches("300001.SZ") == False  # 30 prefix doesn't match

    def test_wildcard_kcb(self):
        """Test KeChuangBan wildcard (688*.SH)"""
        matcher = SymbolMatcher(["688*.SH"])

        assert matcher.matches("688001.SH") == True
        assert matcher.matches("688999.SH") == True
        assert matcher.matches("600000.SH") == False

    def test_wildcard_cyb(self):
        """Test ChuangYeBan wildcard (30*.SZ)"""
        matcher = SymbolMatcher(["30*.SZ"])

        assert matcher.matches("300001.SZ") == True
        assert matcher.matches("300999.SZ") == True
        assert matcher.matches("000001.SZ") == False

    def test_exclusion_simple(self):
        """Test simple exclusion"""
        matcher = SymbolMatcher(["*"], exclude_patterns=["600000.SH"])

        assert matcher.matches("600519.SH") == True
        assert matcher.matches("000001.SZ") == True
        assert matcher.matches("600000.SH") == False  # Excluded

    def test_exclusion_wildcard(self):
        """Test wildcard exclusion"""
        matcher = SymbolMatcher(["*.SH"], exclude_patterns=["ST.*", "*ST.*"])

        assert matcher.matches("600519.SH") == True
        assert matcher.matches("600000.SH") == True
        assert matcher.matches("ST600000.SH") == False  # Excluded (ST.)
        assert matcher.matches("*ST600000.SH") == False  # Excluded (*ST)

    def test_exclusion_with_wildcard_pattern(self):
        """Test exclusion with pattern"""
        matcher = SymbolMatcher(["60*.SH"], exclude_patterns=["601*.SH"])

        assert matcher.matches("600000.SH") == True
        assert matcher.matches("600519.SH") == True
        assert matcher.matches("601000.SH") == False  # Excluded (601.*)
        assert matcher.matches("603000.SH") == True   # Should match 60*.SH

    def test_empty_patterns(self):
        """Test empty patterns (should default to all stocks)"""
        matcher = SymbolMatcher([])

        # Empty patterns default to ["*"]
        assert matcher.matches("600519.SH") == True
        assert matcher.matches("000001.SZ") == True

    def test_complex_pattern(self):
        """Test complex patterns with multiple rules"""
        matcher = SymbolMatcher(
            patterns=["600*.SH", "00*.SZ"],
            exclude_patterns=["ST.*", "688*.SH"]
        )

        assert matcher.matches("600519.SH") == True   # In 600*.SH
        assert matcher.matches("000001.SZ") == True   # In 00*.SZ
        assert matcher.matches("600000.SH") == True   # In 600*.SH
        assert matcher.matches("688001.SH") == False  # Excluded (688*.SH)
        assert matcher.matches("ST600000.SH") == False  # Excluded (ST.*)
        assert matcher.matches("300001.SZ") == False  # Not in patterns

    def test_is_all_stocks(self):
        """Test is_all_stocks detection"""
        matcher1 = SymbolMatcher(["*"])
        assert matcher1.is_all_stocks() == True

        matcher2 = SymbolMatcher(["*.SH"])
        assert matcher2.is_all_stocks() == False

        matcher3 = SymbolMatcher(["*"], exclude_patterns=["ST.*"])
        assert matcher3.is_all_stocks() == False

    def test_performance_exact_match(self):
        """Test that exact matches use set lookup (O(1))"""
        # Create matcher with many exact matches
        symbols = [f"{i:06d}.SH" for i in range(100000)]
        matcher = SymbolMatcher(symbols)

        # Should be fast (O(1) lookup)
        assert matcher.matches("000000.SH") == True
        assert matcher.matches("000001.SH") == True
        assert matcher.matches("099999.SH") == True
        assert matcher.matches("100000.SH") == False  # Not in list

    def test_custom_wildcard(self):
        """Test custom wildcard patterns"""
        matcher = SymbolMatcher(["600*.*", "000*.*"])

        assert matcher.matches("600000.SH") == True
        assert matcher.matches("600123.SH") == True
        assert matcher.matches("000001.SZ") == True
        assert matcher.matches("000123.SZ") == True
        assert matcher.matches("123456.SH") == False
