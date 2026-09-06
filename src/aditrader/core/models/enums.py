"""Enumerations for orders, signals, and execution states."""

from enum import StrEnum


class OrderSide(StrEnum):
    """Trading order direction."""

    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    """Order execution pricing mechanism."""

    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(StrEnum):
    """Lifecycle state machine stages for simulated and real orders."""

    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class SignalDirection(StrEnum):
    """Strategy directive recommendations."""

    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"
