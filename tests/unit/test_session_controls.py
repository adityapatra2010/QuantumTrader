"""Unit tests verifying NSE session calendar, market hours, and timezone controls."""

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import pytest

from aditrader.data.session import (
    EXCHANGE_TIMEZONE,
    MarketClosedError,
    MarketSessionStatus,
    get_session_status,
    is_holiday,
    is_market_open,
    is_weekend,
    normalize_to_ist,
    validate_session_time,
)


def test_timezone_normalization_to_ist() -> None:
    """Verify naive and aware timestamps normalize to Asia/Kolkata."""
    # 1. Naive timestamp
    naive_dt = datetime(2024, 12, 2, 9, 15, 0)
    ist_dt = normalize_to_ist(naive_dt)
    assert ist_dt.tzinfo == EXCHANGE_TIMEZONE
    assert ist_dt.hour == 9 and ist_dt.minute == 15

    # 2. UTC timestamp -> converts to IST (+5:30)
    utc_dt = datetime(2024, 12, 2, 3, 45, 0, tzinfo=ZoneInfo("UTC"))
    converted_ist = normalize_to_ist(utc_dt)
    assert converted_ist.tzinfo == EXCHANGE_TIMEZONE
    assert converted_ist.hour == 9 and converted_ist.minute == 15


def test_weekend_detection() -> None:
    """Verify Saturday and Sunday are flagged as weekends."""
    saturday = datetime(2024, 12, 7, 10, 0, tzinfo=EXCHANGE_TIMEZONE)
    sunday = datetime(2024, 12, 8, 10, 0, tzinfo=EXCHANGE_TIMEZONE)
    monday = datetime(2024, 12, 9, 10, 0, tzinfo=EXCHANGE_TIMEZONE)

    assert is_weekend(saturday) is True
    assert is_weekend(sunday) is True
    assert is_weekend(monday) is False
    assert get_session_status(saturday) == MarketSessionStatus.WEEKEND


def test_holiday_detection() -> None:
    """Verify official NSE holidays are recognized."""
    christmas = datetime(2024, 12, 25, 10, 0, tzinfo=EXCHANGE_TIMEZONE)
    regular_day = datetime(2024, 12, 24, 10, 0, tzinfo=EXCHANGE_TIMEZONE)

    assert is_holiday(christmas) is True
    assert is_holiday(regular_day) is False
    assert get_session_status(christmas) == MarketSessionStatus.HOLIDAY


def test_session_hours_transitions() -> None:
    """Verify transitions between PRE_OPEN, REGULAR_HOURS, POST_MARKET, and CLOSED."""
    # Trading date: Monday 2024-12-02
    base_date = date(2024, 12, 2)

    # 08:30 IST -> CLOSED
    t_early = datetime.combine(base_date, time(8, 30), tzinfo=EXCHANGE_TIMEZONE)
    assert get_session_status(t_early) == MarketSessionStatus.CLOSED
    assert is_market_open(t_early) is False

    # 09:05 IST -> PRE_OPEN
    t_pre_open = datetime.combine(base_date, time(9, 5), tzinfo=EXCHANGE_TIMEZONE)
    assert get_session_status(t_pre_open) == MarketSessionStatus.PRE_OPEN
    assert is_market_open(t_pre_open) is False

    # 09:15 IST -> REGULAR_HOURS (Open)
    t_open = datetime.combine(base_date, time(9, 15), tzinfo=EXCHANGE_TIMEZONE)
    assert get_session_status(t_open) == MarketSessionStatus.REGULAR_HOURS
    assert is_market_open(t_open) is True

    # 12:30 IST -> REGULAR_HOURS
    t_midday = datetime.combine(base_date, time(12, 30), tzinfo=EXCHANGE_TIMEZONE)
    assert get_session_status(t_midday) == MarketSessionStatus.REGULAR_HOURS
    assert is_market_open(t_midday) is True

    # 15:30 IST -> REGULAR_HOURS (Market Close Boundary)
    t_close = datetime.combine(base_date, time(15, 30), tzinfo=EXCHANGE_TIMEZONE)
    assert get_session_status(t_close) == MarketSessionStatus.REGULAR_HOURS
    assert is_market_open(t_close) is True

    # 15:45 IST -> POST_MARKET
    t_post = datetime.combine(base_date, time(15, 45), tzinfo=EXCHANGE_TIMEZONE)
    assert get_session_status(t_post) == MarketSessionStatus.POST_MARKET
    assert is_market_open(t_post) is False

    # 16:30 IST -> CLOSED
    t_night = datetime.combine(base_date, time(16, 30), tzinfo=EXCHANGE_TIMEZONE)
    assert get_session_status(t_night) == MarketSessionStatus.CLOSED
    assert is_market_open(t_night) is False


def test_validate_session_time_exception() -> None:
    """Verify validate_session_time raises MarketClosedError outside regular hours."""
    base_date = date(2024, 12, 2)
    open_time = datetime.combine(base_date, time(10, 0), tzinfo=EXCHANGE_TIMEZONE)
    closed_time = datetime.combine(base_date, time(16, 0), tzinfo=EXCHANGE_TIMEZONE)

    # Open time should pass silently
    validate_session_time(open_time)

    # Closed time should raise MarketClosedError
    with pytest.raises(MarketClosedError, match="Operation rejected: NSE market is"):
        validate_session_time(closed_time)
