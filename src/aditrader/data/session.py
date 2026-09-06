"""NSE trading session calendar, market hours enforcement, and exchange timezone normalization."""

from datetime import date, datetime, time
from enum import StrEnum
from typing import Final
from zoneinfo import ZoneInfo

# NSE Exchange Timezone
EXCHANGE_TIMEZONE_STR: Final[str] = "Asia/Kolkata"
EXCHANGE_TIMEZONE: Final[ZoneInfo] = ZoneInfo(EXCHANGE_TIMEZONE_STR)

# NSE Regular Trading Hours (IST)
MARKET_PRE_OPEN_START: Final[time] = time(9, 0, 0)
MARKET_PRE_OPEN_END: Final[time] = time(9, 15, 0)
MARKET_OPEN_TIME: Final[time] = time(9, 15, 0)
MARKET_CLOSE_TIME: Final[time] = time(15, 30, 0)
POST_MARKET_START: Final[time] = time(15, 40, 0)
POST_MARKET_END: Final[time] = time(16, 0, 0)

# Standard NSE Fixed Calendar Holidays (Sample / Baseline for verification)
STANDARD_NSE_HOLIDAYS: Final[set[date]] = {
    date(2024, 1, 26),  # Republic Day
    date(2024, 3, 8),  # Mahashivratri
    date(2024, 3, 25),  # Holi
    date(2024, 3, 29),  # Good Friday
    date(2024, 4, 11),  # Id-Ul-Fitr
    date(2024, 4, 17),  # Ram Navami
    date(2024, 5, 1),  # Maharashtra Day
    date(2024, 6, 17),  # Bakri Id
    date(2024, 7, 17),  # Muharram
    date(2024, 8, 15),  # Independence Day
    date(2024, 10, 2),  # Mahatma Gandhi Jayanti
    date(2024, 11, 1),  # Diwali Laxmi Pujan
    date(2024, 11, 15),  # Guru Nanak Jayanti
    date(2024, 12, 25),  # Christmas
    date(2025, 1, 26),
    date(2025, 8, 15),
    date(2025, 10, 2),
    date(2025, 12, 25),
    date(2026, 1, 26),
    date(2026, 8, 15),
    date(2026, 10, 2),
    date(2026, 12, 25),
}


class MarketSessionStatus(StrEnum):
    """Status of the National Stock Exchange market session."""

    WEEKEND = "WEEKEND"
    HOLIDAY = "HOLIDAY"
    PRE_OPEN = "PRE_OPEN"
    REGULAR_HOURS = "REGULAR_HOURS"
    POST_MARKET = "POST_MARKET"
    CLOSED = "CLOSED"


class MarketClosedError(Exception):
    """Raised when an operation requires the market to be open during regular hours."""

    pass


def normalize_to_ist(dt: datetime) -> datetime:
    """
    Ensure the timestamp is timezone-aware and normalized to Asia/Kolkata (IST).

    If the timestamp is naive, it is assumed to already represent Asia/Kolkata local time.
    """
    if dt.tzinfo is None:
        return dt.replace(tzinfo=EXCHANGE_TIMEZONE)
    return dt.astimezone(EXCHANGE_TIMEZONE)


def is_weekend(dt: datetime) -> bool:
    """Check if given timestamp falls on a weekend (Saturday or Sunday)."""
    ist_dt = normalize_to_ist(dt)
    return ist_dt.weekday() in (5, 6)  # 5=Saturday, 6=Sunday


def is_holiday(dt: datetime, holiday_calendar: set[date] | None = None) -> bool:
    """Check if given timestamp falls on an exchange holiday."""
    ist_dt = normalize_to_ist(dt)
    holidays = holiday_calendar if holiday_calendar is not None else STANDARD_NSE_HOLIDAYS
    return ist_dt.date() in holidays


def get_session_status(
    dt: datetime, holiday_calendar: set[date] | None = None
) -> MarketSessionStatus:
    """Determine the exact NSE market session status for a given point-in-time timestamp."""
    ist_dt = normalize_to_ist(dt)

    if is_weekend(ist_dt):
        return MarketSessionStatus.WEEKEND

    if is_holiday(ist_dt, holiday_calendar):
        return MarketSessionStatus.HOLIDAY

    current_time = ist_dt.time()

    if MARKET_PRE_OPEN_START <= current_time < MARKET_PRE_OPEN_END:
        return MarketSessionStatus.PRE_OPEN
    elif MARKET_OPEN_TIME <= current_time <= MARKET_CLOSE_TIME:
        return MarketSessionStatus.REGULAR_HOURS
    elif POST_MARKET_START <= current_time <= POST_MARKET_END:
        return MarketSessionStatus.POST_MARKET
    else:
        return MarketSessionStatus.CLOSED


def is_market_open(dt: datetime, holiday_calendar: set[date] | None = None) -> bool:
    """Return True strictly if timestamp falls within regular NSE trading hours (09:15–15:30 IST)."""
    return get_session_status(dt, holiday_calendar) == MarketSessionStatus.REGULAR_HOURS


def validate_session_time(dt: datetime, holiday_calendar: set[date] | None = None) -> None:
    """
    Raise MarketClosedError if given timestamp is outside regular trading hours.

    Used by execution and live simulation runners to prevent look-ahead or off-market operations.
    """
    status = get_session_status(dt, holiday_calendar)
    if status != MarketSessionStatus.REGULAR_HOURS:
        ist_dt = normalize_to_ist(dt)
        raise MarketClosedError(
            f"Operation rejected: NSE market is {status.value} at {ist_dt.strftime('%Y-%m-%d %H:%M:%S %Z')}"
        )
