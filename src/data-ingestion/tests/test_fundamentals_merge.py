"""Tests for pipelines.fundamentals.merge (merge_batches, row_key).

These cover the row-merging logic used when a single fundamentals API table
requires multiple batched calls (each batch returns a different subset of
fields for the same logical rows).
"""
from core.schema import FundTableSpec, TableKind, FundApiMethod, TABLES
from pipelines.fundamentals.merge import merge_batches, row_key


# --------------------------------------------------------------------------- #
#  Helpers
# --------------------------------------------------------------------------- #

def _quarterly_spec(returns_rpt_type: bool = False) -> FundTableSpec:
    """A minimal quarterly spec with two known fields for testing."""
    return FundTableSpec(
        table_name="test_quarterly",
        kind=TableKind.Quarterly,
        fields=("total_assets", "total_liabilities"),
        has_rpt_type_params=True,
        returns_rpt_type=returns_rpt_type,
        method=FundApiMethod.Balance,
    )


def _daily_spec() -> FundTableSpec:
    """A minimal daily spec."""
    return FundTableSpec(
        table_name="test_daily",
        kind=TableKind.Daily,
        fields=("pe_ttm", "pb_lyr"),
        has_rpt_type_params=False,
        returns_rpt_type=False,
        method=FundApiMethod.Valuation,
    )


# --------------------------------------------------------------------------- #
#  merge_batches
# --------------------------------------------------------------------------- #

def test_merge_batches_combines_fields():
    """Two batches with different fields for the same key -> merged row has all fields."""
    spec = _quarterly_spec()
    target = [{"symbol": "600000.SH", "rpt_date": "2023-12-31", "total_assets": 100}]
    incoming = [{"symbol": "600000.SH", "rpt_date": "2023-12-31", "total_liabilities": 50}]

    merge_batches(target, incoming, spec)

    assert len(target) == 1
    assert target[0]["total_assets"] == 100
    assert target[0]["total_liabilities"] == 50


def test_merge_batches_new_row_appended():
    """Incoming row whose key doesn't exist in target -> appended."""
    spec = _quarterly_spec()
    target = [{"symbol": "600000.SH", "rpt_date": "2023-12-31", "total_assets": 100}]
    incoming = [{"symbol": "600001.SH", "rpt_date": "2023-12-31", "total_assets": 200}]

    merge_batches(target, incoming, spec)

    assert len(target) == 2
    assert target[1]["symbol"] == "600001.SH"
    assert target[1]["total_assets"] == 200


def test_merge_batches_empty_incoming_noop():
    """Empty incoming list -> target unchanged."""
    spec = _quarterly_spec()
    original = [{"symbol": "600000.SH", "rpt_date": "2023-12-31", "total_assets": 100}]
    target = list(original)

    merge_batches(target, [], spec)

    assert target == original


def test_merge_batches_overwrites_existing_field():
    """If a field exists in both target and incoming, the incoming value wins."""
    spec = _quarterly_spec()
    target = [{"symbol": "600000.SH", "rpt_date": "2023-12-31", "total_assets": 100}]
    incoming = [{"symbol": "600000.SH", "rpt_date": "2023-12-31", "total_assets": 999}]

    merge_batches(target, incoming, spec)

    assert target[0]["total_assets"] == 999


def test_merge_batches_multiple_rows_and_batches():
    """Mix of matches and new rows across multiple incoming entries."""
    spec = _quarterly_spec()
    target = [
        {"symbol": "600000.SH", "rpt_date": "2023-12-31", "total_assets": 100},
        {"symbol": "600001.SH", "rpt_date": "2023-12-31", "total_assets": 200},
    ]
    incoming = [
        {"symbol": "600000.SH", "rpt_date": "2023-12-31", "total_liabilities": 50},
        {"symbol": "600002.SH", "rpt_date": "2023-12-31", "total_assets": 300},
    ]

    merge_batches(target, incoming, spec)

    assert len(target) == 3
    # First row merged
    assert target[0]["total_assets"] == 100
    assert target[0]["total_liabilities"] == 50
    # Second row unchanged
    assert target[1]["total_assets"] == 200
    # Third row appended
    assert target[2]["symbol"] == "600002.SH"
    assert target[2]["total_assets"] == 300


def test_merge_batches_only_known_fields_copied():
    """Fields not in spec.fields are NOT copied from incoming to target."""
    spec = _quarterly_spec()  # fields = total_assets, total_liabilities
    target = [{"symbol": "600000.SH", "rpt_date": "2023-12-31", "total_assets": 100}]
    incoming = [{"symbol": "600000.SH", "rpt_date": "2023-12-31",
                 "unknown_field": "should_not_appear", "total_liabilities": 50}]

    merge_batches(target, incoming, spec)

    assert "unknown_field" not in target[0]
    assert target[0]["total_liabilities"] == 50


def test_merge_batches_with_real_balance_sheet_spec():
    """Smoke test using a real spec from TABLES."""
    balance_spec = next(t for t in TABLES if t.table_name == "balance_sheet")
    target = [{"symbol": "600000.SH", "rpt_date": "2023-12-31",
               "ttl_ast": 1_000_000}]
    incoming = [{"symbol": "600000.SH", "rpt_date": "2023-12-31",
                 "ttl_liab": 500_000}]

    merge_batches(target, incoming, balance_spec)

    assert target[0]["ttl_ast"] == 1_000_000
    assert target[0]["ttl_liab"] == 500_000


# --------------------------------------------------------------------------- #
#  row_key
# --------------------------------------------------------------------------- #

def test_row_key_quarterly():
    """Quarterly table without returns_rpt_type -> key is (symbol, rpt_date)."""
    spec = _quarterly_spec(returns_rpt_type=False)
    row = {"symbol": "600000.SH", "rpt_date": "2023-12-31"}

    key = row_key(row, spec)

    assert key == ("600000.SH", "2023-12-31")


def test_row_key_daily():
    """Daily table -> key is (symbol, trade_date)."""
    spec = _daily_spec()
    row = {"symbol": "600000.SH", "trade_date": "2024-01-15"}

    key = row_key(row, spec)

    assert key == ("600000.SH", "2024-01-15")


def test_row_key_quarterly_with_rpt_type():
    """Quarterly table with returns_rpt_type -> key includes data_type."""
    spec = _quarterly_spec(returns_rpt_type=True)
    row = {"symbol": "600000.SH", "rpt_date": "2023-12-31", "data_type": "Q4"}

    key = row_key(row, spec)

    assert key == ("600000.SH", "2023-12-31", "Q4")


def test_row_key_quarterly_with_rpt_type_distinguishes_data_types():
    """Two rows same symbol+rpt_date but different data_type -> different keys."""
    spec = _quarterly_spec(returns_rpt_type=True)
    row_a = {"symbol": "600000.SH", "rpt_date": "2023-12-31", "data_type": "Q4"}
    row_b = {"symbol": "600000.SH", "rpt_date": "2023-12-31", "data_type": "Annual"}

    assert row_key(row_a, spec) != row_key(row_b, spec)


def test_row_key_missing_symbol_returns_none_in_key():
    """If symbol is missing, the key tuple contains None for that position."""
    spec = _quarterly_spec()
    row = {"rpt_date": "2023-12-31"}

    key = row_key(row, spec)

    assert key == (None, "2023-12-31")


def test_row_key_with_real_finance_prime_spec():
    """finance_prime is a real quarterly spec with returns_rpt_type=True."""
    prime_spec = next(t for t in TABLES if t.table_name == "finance_prime")
    assert prime_spec.returns_rpt_type is True

    row = {"symbol": "600000.SH", "rpt_date": "2023-12-31", "data_type": "001"}

    key = row_key(row, prime_spec)

    assert key == ("600000.SH", "2023-12-31", "001")
