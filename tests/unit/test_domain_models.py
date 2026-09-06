"""Unit tests verifying immutability, data constraints, and invariants of core domain models."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from aditrader.core.models import (
    AccountBalance,
    Bar,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    Signal,
    SignalDirection,
    Tick,
    Trade,
)


def test_tick_immutability_and_validation() -> None:
    """Verify Tick immutability and non-negative constraints."""
    now = datetime.now(UTC)
    tick = Tick(
        symbol="NIFTY",
        ltp=24500.50,
        bid=24500.00,
        ask=24501.00,
        volume=150000,
        oi=3200000,
        timestamp=now,
    )
    assert tick.symbol == "NIFTY"
    assert tick.ltp == 24500.50

    # Test immutability
    with pytest.raises(ValidationError):
        setattr(tick, "ltp", 25000.0)

    # Test negative price rejection
    with pytest.raises(ValidationError):
        Tick(symbol="NIFTY", ltp=-10.0, bid=100.0, ask=101.0, volume=10, oi=100, timestamp=now)


def test_bar_price_envelope_validation() -> None:
    """Verify Bar price envelope: high >= open, close, low."""
    now = datetime.now(UTC)
    valid_bar = Bar(
        timestamp=now,
        open=24000.0,
        high=24100.0,
        low=23950.0,
        close=24050.0,
        volume=50000,
        oi=1200000,
    )
    assert valid_bar.close == 24050.0

    # Immutability
    with pytest.raises(ValidationError):
        setattr(valid_bar, "close", 24100.0)

    # High lower than Open/Close
    with pytest.raises(ValueError, match="High price"):
        Bar(timestamp=now, open=24000.0, high=23900.0, low=23800.0, close=24000.0, volume=10, oi=10)

    # Low higher than Open/Close
    with pytest.raises(ValueError, match="Low price"):
        Bar(timestamp=now, open=24000.0, high=24200.0, low=24100.0, close=24150.0, volume=10, oi=10)


def test_signal_constraints() -> None:
    """Verify Signal confidence bounds and defaults."""
    now = datetime.now(UTC)
    sig = Signal(
        timestamp=now,
        symbol="BANKNIFTY",
        direction=SignalDirection.BUY,
        confidence=0.85,
        metadata={"indicator": "RSI_Oversold"},
    )
    assert sig.direction == SignalDirection.BUY
    assert sig.metadata["indicator"] == "RSI_Oversold"

    # Confidence must be between 0.0 and 1.0
    with pytest.raises(ValidationError):
        Signal(timestamp=now, symbol="BANKNIFTY", direction=SignalDirection.BUY, confidence=1.5)


def test_order_invariants() -> None:
    """Verify Order limit price requirements and fill bounds."""
    now = datetime.now(UTC)

    # Limit order without price should fail
    with pytest.raises(ValueError, match="Limit orders require an explicit price"):
        Order(
            order_id="ORD-001",
            symbol="NIFTY",
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            qty=50,
            price=None,
            created_at=now,
            updated_at=now,
        )

    # Valid market order
    mkt_order = Order(
        order_id="ORD-002",
        symbol="NIFTY",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        qty=50,
        created_at=now,
        updated_at=now,
    )
    assert mkt_order.status == OrderStatus.CREATED

    # Filled quantity exceeding order quantity should fail
    with pytest.raises(ValueError, match="Filled quantity"):
        Order(
            order_id="ORD-003",
            symbol="NIFTY",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=50,
            filled_qty=60,
            created_at=now,
            updated_at=now,
        )

    # Rejected order without reason should fail
    with pytest.raises(ValueError, match="rejection_reason"):
        Order(
            order_id="ORD-004",
            symbol="NIFTY",
            side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            qty=50,
            status=OrderStatus.REJECTED,
            rejection_reason=None,
            created_at=now,
            updated_at=now,
        )


def test_trade_position_and_balance_immutability() -> None:
    """Verify Trade, Position, and AccountBalance immutability."""
    now = datetime.now(UTC)
    trade = Trade(
        trade_id="TRD-001",
        order_id="ORD-001",
        symbol="NIFTY",
        side=OrderSide.BUY,
        qty=50,
        fill_price=24000.0,
        slippage=2.5,
        stt=0.0,
        charges=35.5,
        timestamp=now,
    )
    with pytest.raises(ValidationError):
        setattr(trade, "fill_price", 24100.0)

    pos = Position(
        symbol="NIFTY",
        qty=50,
        buy_avg_price=24000.0,
        updated_at=now,
    )
    with pytest.raises(ValidationError):
        setattr(pos, "qty", 100)

    bal = AccountBalance(
        total_capital=1000000.0,
        available_margin=850000.0,
        used_margin=150000.0,
        realized_pnl=0.0,
        unrealized_pnl=0.0,
    )
    with pytest.raises(ValidationError):
        setattr(bal, "total_capital", 900000.0)
