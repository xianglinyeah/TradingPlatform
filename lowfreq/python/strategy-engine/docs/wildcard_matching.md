# Stock Symbol Wildcard Matching

## Overview

strategy_engine now supports wildcard pattern matching for stock symbols, solving the problem of having to hard-code thousands of stock symbols.

## Supported Wildcard Patterns

### Predefined Wildcards

| Pattern | Description | Examples |
|---------|-------------|----------|
| `*` | All stocks | Matches all A-share symbols |
| `*.SH` | All Shanghai Stock Exchange | `600519.SH`, `600000.SH`, `688001.SH` |
| `*.SZ` | All Shenzhen Stock Exchange | `000001.SZ`, `300001.SZ`, `002594.SZ` |
| `600*.SH` | Shanghai main board (600) | `600000.SH`, `600519.SH` |
| `601*.SH` | Shanghai main board (601) | `601000.SH`, `601318.SH` |
| `603*.SH` | Shanghai main board (603) | `603000.SH`, `603993.SH` |
| `605*.SH` | Shanghai main board (605) | `605000.SH` |
| `688*.SH` | STAR Market | `688001.SH`, `688999.SH` |
| `00*.SZ` | Shenzhen main board | `000001.SZ`, `002594.SZ` |
| `30*.SZ` | ChiNext | `300001.SZ`, `300999.SZ` |

### Custom Wildcards

Supports `*` as a wildcard:

```yaml
symbols:
  - "600*.*"    # Starts with 600, any exchange (in practice only SH)
  - "000*.*"    # Starts with 000, any exchange
```

## Exclude Patterns

You can specify stock symbols to exclude:

```yaml
strategies:
  - name: scanner
    class: MovingAverageStrategy
    symbols:
      - "*.SH"  # All Shanghai Stock Exchange stocks
    exclude_symbols:
      - "ST.*"    # Exclude ST stocks
      - "*ST.*"   # Exclude *ST stocks
      - "688*.SH" # Exclude STAR Market
```

## Configuration Examples

### Example 1: Scan Shanghai Main Board

```yaml
strategies:
  - name: sh_scanner
    class: MovingAverageStrategy
    symbols:
      - "600*.SH"
      - "601*.SH"
      - "603*.SH"
      - "605*.SH"
    exclude_symbols:
      - "ST.*"
    params:
      ema_period: 10
      # ... other parameters
```

### Example 2: Scan the Entire Market (Excluding ST Stocks)

```yaml
strategies:
  - name: market_scanner
    class: MovingAverageStrategy
    symbols:
      - "*"  # All stocks
    exclude_symbols:
      - "ST.*"    # Exclude ST
      - "*ST.*"   # Exclude *ST
```

### Example 3: Exact Match (Backward Compatible)

```yaml
strategies:
  - name: blue_chips
    class: MovingAverageStrategy
    symbols:
      - "600519.SH"  # Kweichow Moutai
      - "000001.SZ"  # Ping An Bank
```

### Example 4: Mixed Mode

```yaml
strategies:
  - name: mixed_matcher
    class: MovingAverageStrategy
    symbols:
      - "600*.SH"   # Shanghai stocks starting with 600
      - "000001.SZ" # Plus Ping An Bank (exact match)
    exclude_symbols:
      - "600000.SH" # But exclude Shanghai Pudong Development Bank
```

## Performance

Wildcard matching has been optimized:

1. **Exact match**: Uses hash table lookup, O(1) time complexity
2. **Regex match**: Pre-compiled regex, ~1-5us per match
3. **Estimated performance**: 500,000 K-lines/day x 5us = 2.5 seconds, fully acceptable

## Backward Compatibility

Fully backward compatible with existing exact-match configurations:

```yaml
# Old configuration still valid
strategies:
  - name: my_strategy
    symbols:
      - 600519.SH  # Exact match (no quotes)
      - "000001.SZ" # Exact match (with quotes)
```

## Testing

Run unit tests to verify functionality:

```bash
cd src/strategy_engine
py -m pytest tests/utils/test_symbol_matcher.py -v
```

Run integration tests:

```bash
py main.py research --config config/test_wildcard.yaml
```

## Implementation Details

### Core Class: SymbolMatcher

Location: `src/utils/symbol_matcher.py`

Main methods:
- `matches(symbol: str) -> bool`: Check whether a symbol matches
- `is_all_stocks() -> bool`: Whether all stocks are matched

### Usage

A `SymbolMatcher` is automatically created in `BacktestEngine` and `LiveEngine`:

```python
# Create a matcher for each strategy
self.symbol_matchers = {}
for strategy in self.strategies:
    matcher = SymbolMatcher(strategy.symbols, strategy.exclude_symbols)
    self.symbol_matchers[strategy.name] = matcher

# Use in main loop
for strategy in self.strategies:
    matcher = self.symbol_matchers[strategy.name]
    if not matcher.matches(bar.symbol):
        continue
    # Process matched stock
```

## Notes

1. **Case-sensitive**: Stock symbol case must match exactly
   - OK: `600519.SH`
   - Not OK: `600519.sh`

2. **Correct format**: Must include the exchange suffix
   - OK: `600519.SH`
   - Not OK: `600519`

3. **Performance considerations**: Full-market scanning ("*" pattern) generates significant computation
   - Recommend combining with `exclude_symbols` to exclude unneeded stocks
   - Consider using an external file approach (future implementation)

## Future Extensions

Planned features:

1. **External files**: Read stock lists from files
   ```yaml
   symbols_file: "config/scanner_stocks.txt"
   ```

2. **Dynamic API**: Fetch stock lists from an API
   ```yaml
   symbols_url: "http://internal-api/stocks?market_cap_top=1000"
   ```

3. **Regular expressions**: Support more complex patterns
   ```yaml
   symbols:
     - "^600\d{3}\.SH$"  # Regular expression
   ```
