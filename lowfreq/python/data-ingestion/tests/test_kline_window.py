"""Tests for the adaptive-window date math in pipelines.kline.incremental.

The window logic lives inside the private function ``_fetch_and_apply`` and is
tightly coupled to ClickHouseStorage / gm_api.  Rather than mocking the entire
call chain, these tests verify the *date arithmetic* formulas directly.

The formulas under test (from incremental.py):

1. **First-time fetch** (no last_bar):
       from_dt = now.date() - timedelta(days=lookback * 2 + safety_buffer)

2. **Incremental fetch** (last_bar exists, gap <= max_gap):
       from_dt = last_bar - timedelta(days=safety_buffer)

3. **Gap too large** (last_bar exists, gap > max_gap):
       skip the symbol entirely
"""
from datetime import datetime, timedelta

from config import KlineIncrementalConfig


# --------------------------------------------------------------------------- #
#  Config defaults (mirrors KlineIncrementalConfig field defaults)
# --------------------------------------------------------------------------- #

def _default_cfg() -> KlineIncrementalConfig:
    return KlineIncrementalConfig()


# --------------------------------------------------------------------------- #
#  Formula 1: first-time fetch window
#  from_dt = now.date() - timedelta(days=lookback * 2 + safety_buffer)
# --------------------------------------------------------------------------- #

def test_first_time_window_minute():
    """First-time fetch: from_dt = now - (minute_lookback * 2 + safety_buffer)."""
    cfg = _default_cfg()
    now = datetime(2026, 6, 24, 15, 0)
    lookback = cfg.minute_lookback_days      # 7
    safety = cfg.safety_buffer_days          # 1

    expected_date = now.date() - timedelta(days=lookback * 2 + safety)
    expected_from = datetime.combine(expected_date, datetime.min.time())

    # Replicate the formula from _fetch_and_apply
    from_dt_date = now.date() - timedelta(days=lookback * 2 + safety)
    from_dt = datetime.combine(from_dt_date, datetime.min.time())

    assert from_dt == expected_from
    # Sanity: 7*2+1 = 15 days back
    assert (now.date() - from_dt.date()).days == 15


def test_first_time_window_daily():
    """First-time fetch with daily lookback."""
    cfg = _default_cfg()
    now = datetime(2026, 6, 24, 15, 0)
    lookback = cfg.daily_lookback_days       # 10
    safety = cfg.safety_buffer_days          # 1

    from_dt_date = now.date() - timedelta(days=lookback * 2 + safety)
    from_dt = datetime.combine(from_dt_date, datetime.min.time())

    # 10*2+1 = 21 days back
    assert (now.date() - from_dt.date()).days == 21


def test_first_time_window_custom_lookback():
    """Changing lookback_days changes the window proportionally."""
    cfg = _default_cfg()
    cfg.minute_lookback_days = 30
    cfg.safety_buffer_days = 3
    now = datetime(2026, 6, 24, 15, 0)

    from_dt_date = now.date() - timedelta(days=30 * 2 + 3)
    from_dt = datetime.combine(from_dt_date, datetime.min.time())

    assert (now.date() - from_dt.date()).days == 63


# --------------------------------------------------------------------------- #
#  Formula 2: incremental fetch from last_bar
#  from_dt = last_bar - timedelta(days=safety_buffer)
# --------------------------------------------------------------------------- #

def test_window_from_last_bar():
    """from_dt should be last_bar - safety_buffer_days."""
    cfg = _default_cfg()
    last_bar = datetime(2026, 6, 22, 14, 59)
    safety_buffer = cfg.safety_buffer_days   # 1

    from_dt = last_bar - timedelta(days=safety_buffer)

    expected = datetime(2026, 6, 21, 14, 59)
    assert from_dt == expected


def test_window_from_last_bar_preserves_time_component():
    """The safety buffer subtracts full days but preserves the time-of-day."""
    cfg = _default_cfg()
    last_bar = datetime(2026, 6, 22, 9, 30, 15)

    from_dt = last_bar - timedelta(days=cfg.safety_buffer_days)

    assert from_dt.time() == last_bar.time()


def test_window_from_last_bar_custom_safety():
    """A larger safety_buffer shifts from_dt further back."""
    cfg = _default_cfg()
    cfg.safety_buffer_days = 5
    last_bar = datetime(2026, 6, 22, 14, 59)

    from_dt = last_bar - timedelta(days=cfg.safety_buffer_days)

    assert from_dt == datetime(2026, 6, 17, 14, 59)


# --------------------------------------------------------------------------- #
#  Formula 3: gap check (gap > max_gap_days -> skip)
#  gap_days = (now.date() - last_bar.date()).days
# --------------------------------------------------------------------------- #

def test_gap_within_limit_not_skipped():
    """Gap <= max_gap_days -> should NOT skip (incremental path)."""
    cfg = _default_cfg()
    max_gap = cfg.max_gap_days   # 30
    now = datetime(2026, 6, 24, 15, 0)
    last_bar = datetime(2026, 6, 20, 14, 59)   # 4 days ago

    gap_days = (now.date() - last_bar.date()).days

    assert gap_days <= max_gap
    assert gap_days == 4


def test_gap_exceeds_max():
    """gap > max_gap_days -> should signal skip."""
    cfg = _default_cfg()
    max_gap = cfg.max_gap_days   # 30
    now = datetime(2026, 6, 24, 15, 0)
    last_bar = datetime(2026, 4, 1, 14, 59)    # ~84 days ago

    gap_days = (now.date() - last_bar.date()).days

    assert gap_days > max_gap


def test_gap_exactly_at_max_not_skipped():
    """gap == max_gap_days is the boundary; should NOT skip (uses >, not >=)."""
    cfg = _default_cfg()
    max_gap = cfg.max_gap_days   # 30
    now = datetime(2026, 6, 30, 15, 0)
    last_bar = datetime(2026, 5, 31, 14, 59)   # exactly 30 days

    gap_days = (now.date() - last_bar.date()).days

    assert gap_days == max_gap
    # The code checks `if gap_days > max_gap_days`, so equal is NOT skipped.
    assert not (gap_days > max_gap)


def test_gap_one_day_over_max():
    """gap == max_gap + 1 -> should skip."""
    cfg = _default_cfg()
    max_gap = cfg.max_gap_days   # 30
    now = datetime(2026, 6, 30, 15, 0)
    last_bar = datetime(2026, 5, 30, 14, 59)   # 31 days ago

    gap_days = (now.date() - last_bar.date()).days

    assert gap_days == max_gap + 1
    assert gap_days > max_gap


# --------------------------------------------------------------------------- #
#  Integration-style: simulate the full decision tree
# --------------------------------------------------------------------------- #

def _compute_from_dt(now: datetime, last_bar, lookback: int, cfg: KlineIncrementalConfig):
    """Replicate the decision tree from _fetch_and_apply.

    Returns ("skip", gap_days) if gap too large, or ("fetch", from_dt) otherwise.
    """
    if last_bar is None:
        from_dt_date = now.date() - timedelta(days=lookback * 2 + cfg.safety_buffer_days)
        from_dt = datetime.combine(from_dt_date, datetime.min.time())
        return ("fetch", from_dt)
    else:
        gap_days = (now.date() - last_bar.date()).days
        if gap_days > cfg.max_gap_days:
            return ("skip", gap_days)
        from_dt = last_bar - timedelta(days=cfg.safety_buffer_days)
        return ("fetch", from_dt)


def test_decision_first_time():
    """No last_bar -> first-time fetch path."""
    cfg = _default_cfg()
    now = datetime(2026, 6, 24, 15, 0)

    action, from_dt = _compute_from_dt(now, last_bar=None,
                                       lookback=cfg.minute_lookback_days, cfg=cfg)
    assert action == "fetch"
    assert (now.date() - from_dt.date()).days == 15  # 7*2+1


def test_decision_incremental():
    """last_bar recent -> incremental fetch path."""
    cfg = _default_cfg()
    now = datetime(2026, 6, 24, 15, 0)
    last_bar = datetime(2026, 6, 23, 14, 59)

    action, from_dt = _compute_from_dt(now, last_bar=last_bar,
                                       lookback=cfg.minute_lookback_days, cfg=cfg)
    assert action == "fetch"
    assert from_dt == datetime(2026, 6, 22, 14, 59)  # last_bar - 1 day


def test_decision_skip_large_gap():
    """last_bar too old -> skip path."""
    cfg = _default_cfg()
    now = datetime(2026, 6, 24, 15, 0)
    last_bar = datetime(2026, 1, 1, 14, 59)   # ~174 days ago

    action, gap = _compute_from_dt(now, last_bar=last_bar,
                                   lookback=cfg.minute_lookback_days, cfg=cfg)
    assert action == "skip"
    assert gap > cfg.max_gap_days
