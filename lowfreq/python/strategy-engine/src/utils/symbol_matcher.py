"""Symbol Matcher for Wildcard Pattern Matching"""
import re
from typing import List, Optional, Pattern, Set
from logging import getLogger

logger = getLogger(__name__)


class SymbolMatcher:
    """
    Symbol code wildcard matcher

    Supported patterns:
    - "*" : All symbols
    - "*.SH" : All Shanghai Exchange symbols
    - "*.SZ" : All Shenzhen Exchange symbols
    - "600*.SH" : Shanghai Main Board (600 prefix)
    - "00*.SZ" : Shenzhen Main Board (00 prefix)
    - "30*.SZ" : ChiNext (30 prefix)
    - "688*.SH" : STAR Market (688 prefix)
    - Exact match: "600519.SH"
    """

    # Predefined wildcard patterns
    WILDCARD_PATTERNS = {
        "*": r"^.+\.(SH|SZ)$",           # All symbols
        "*.SH": r"^[0-9]{6}\.SH$",       # All Shanghai Exchange
        "*.SZ": r"^[0-9]{6}\.SZ$",       # All Shenzhen Exchange
        "600*.SH": r"^600[0-9]{3}\.SH$", # Shanghai Main Board (600 prefix)
        "601*.SH": r"^601[0-9]{3}\.SH$", # Shanghai Main Board (601 prefix)
        "603*.SH": r"^603[0-9]{3}\.SH$", # Shanghai Main Board (603 prefix)
        "605*.SH": r"^605[0-9]{3}\.SH$", # Shanghai Main Board (605 prefix)
        "688*.SH": r"^688[0-9]{3}\.SH$", # STAR Market (688 prefix)
        "00*.SZ": r"^00[0-9]{4}\.SZ$",   # Shenzhen Main Board (00 prefix)
        "30*.SZ": r"^30[0-9]{4}\.SZ$",   # ChiNext (30 prefix)
    }

    def __init__(self, patterns: List[str], exclude_patterns: Optional[List[str]] = None):
        """
        Initialize matcher

        Args:
            patterns: List of wildcard patterns to include
            exclude_patterns: List of wildcard patterns to exclude
        """
        self.patterns = patterns or ["*"]  # Default all
        self.exclude_patterns = exclude_patterns or []

        # Pre-compile regex patterns
        self._compile_patterns()

        logger.debug(f"SymbolMatcher initialized: {len(self.patterns)} patterns, "
                     f"{len(self.exclude_patterns)} excludes")

    def _compile_patterns(self):
        """Pre-compile all regex patterns"""
        # Exact match set (O(1) lookup)
        self.exact_matches: Set[str] = set()
        # Regex pattern list
        self.regex_patterns: List[Pattern] = []

        for pattern in self.patterns:
            if '*' not in pattern:
                # Exact match
                self.exact_matches.add(pattern)
            elif pattern in self.WILDCARD_PATTERNS:
                # Predefined wildcard
                self.regex_patterns.append(re.compile(self.WILDCARD_PATTERNS[pattern]))
            else:
                # Custom wildcard (e.g., "600*.*")
                regex = self._wildcard_to_regex(pattern)
                self.regex_patterns.append(re.compile(regex))

        # Compile exclusion patterns
        self.exclude_exact: Set[str] = set()
        self.exclude_regex: List[Pattern] = []

        for pattern in self.exclude_patterns:
            if '*' not in pattern:
                self.exclude_exact.add(pattern)
            elif pattern in self.WILDCARD_PATTERNS:
                self.exclude_regex.append(re.compile(self.WILDCARD_PATTERNS[pattern]))
            else:
                regex = self._wildcard_to_regex(pattern)
                self.exclude_regex.append(re.compile(regex))

    @staticmethod
    def _wildcard_to_regex(pattern: str) -> str:
        """
        Convert wildcard to regex

        Examples:
            "600*.SH" -> "^600.*\\.SH$"
            "*.SZ" -> "^.*\\.SZ$"
            "ST.*" -> "^ST\\..*$"
        """
        # Escape special characters (except * and .)
        escaped = re.escape(pattern)
        # Restore . (no need to escape)
        escaped = escaped.replace(r'\.', '.')
        # Convert * to .* (match any character)
        regex = escaped.replace(r'\*', '.*')
        # Add anchors
        return f"^{regex}$"

    def matches(self, symbol: str) -> bool:
        """
        Check if symbol matches any include pattern and is not in exclusion list

        Args:
            symbol: Symbol code, e.g., "600519.SH"

        Returns:
            True if matches, False if not matches
        """
        # 1. Check exclusion list (priority)
        if self._match_excludes(symbol):
            return False

        # 2. Check include patterns
        # 2a. Exact match (O(1))
        if symbol in self.exact_matches:
            return True

        # 2b. Regex match
        for regex in self.regex_patterns:
            if regex.match(symbol):
                return True

        return False

    def _match_excludes(self, symbol: str) -> bool:
        """Check if symbol matches exclusion patterns"""
        if symbol in self.exclude_exact:
            return True

        for regex in self.exclude_regex:
            if regex.match(symbol):
                return True

        return False

    def is_all_stocks(self) -> bool:
        """Check if matches all symbols (patterns=["*"] and no exclusions)"""
        return (self.patterns == ["*"] and
                not self.exclude_patterns and
                not self.exclude_regex)

    def __repr__(self) -> str:
        return (f"SymbolMatcher(patterns={self.patterns}, "
                f"excludes={self.exclude_patterns})")
