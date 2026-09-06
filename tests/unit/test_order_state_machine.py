"""Unit tests verifying the formal Order State Machine transitions."""

from datetime import UTC, datetime

import pytest

from aditrader.core.models import Order, OrderSide, OrderStatus, OrderType
from aditrader.core.state_machine import InvalidOrderStateTransitionError, OrderStateMachine


@pytest.fixture
def sample_order() -> Order:
    now = datetime.now(UTC)
    return Order(
        order_id="ORD-TEST-001",
        symbol="NIFTY24DEC24000CE",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        qty=50,
        price=150.0,
        status=OrderStatus.CREATED,
        created_at=now,
        updated_at=now,
    )


def test_valid_transitions_pipeline(sample_order: Order) -> None:
    """Verify CREATED -> SUBMITTED -> FILLED lifecycle."""
    now = datetime.now(UTC)

    # 1. CREATED -> SUBMITTED
    submitted = OrderStateMachine.transition(sample_order, OrderStatus.SUBMITTED, timestamp=now)
    assert submitted.status == OrderStatus.SUBMITTED
    assert submitted.updated_at == now

    # 2. SUBMITTED -> FILLED
    filled = OrderStateMachine.transition(
        submitted,
        OrderStatus.FILLED,
        timestamp=now,
        filled_qty=50,
        average_fill_price=149.5,
    )
    assert filled.status == OrderStatus.FILLED
    assert filled.filled_qty == 50
    assert filled.average_fill_price == 149.5


def test_partial_fill_to_filled(sample_order: Order) -> None:
    """Verify SUBMITTED -> PARTIALLY_FILLED -> FILLED lifecycle."""
    now = datetime.now(UTC)

    submitted = OrderStateMachine.transition(sample_order, OrderStatus.SUBMITTED, timestamp=now)

    # Partial fill of 25 lots
    partial = OrderStateMachine.transition(
        submitted,
        OrderStatus.PARTIALLY_FILLED,
        timestamp=now,
        filled_qty=25,
        average_fill_price=150.0,
    )
    assert partial.status == OrderStatus.PARTIALLY_FILLED
    assert partial.filled_qty == 25

    # Remainder fill of 50 lots
    full = OrderStateMachine.transition(
        partial,
        OrderStatus.FILLED,
        timestamp=now,
        filled_qty=50,
        average_fill_price=150.2,
    )
    assert full.status == OrderStatus.FILLED
    assert full.filled_qty == 50


def test_cancellation_from_submitted_and_partial(sample_order: Order) -> None:
    """Verify order cancellation from SUBMITTED and PARTIALLY_FILLED."""
    now = datetime.now(UTC)

    # Cancel from SUBMITTED
    submitted = OrderStateMachine.transition(sample_order, OrderStatus.SUBMITTED, timestamp=now)
    cancelled = OrderStateMachine.transition(submitted, OrderStatus.CANCELLED, timestamp=now)
    assert cancelled.status == OrderStatus.CANCELLED

    # Cancel from PARTIALLY_FILLED
    submitted2 = OrderStateMachine.transition(sample_order, OrderStatus.SUBMITTED, timestamp=now)
    partial = OrderStateMachine.transition(
        submitted2,
        OrderStatus.PARTIALLY_FILLED,
        timestamp=now,
        filled_qty=10,
        average_fill_price=150.0,
    )
    cancelled_partial = OrderStateMachine.transition(partial, OrderStatus.CANCELLED, timestamp=now)
    assert cancelled_partial.status == OrderStatus.CANCELLED
    assert cancelled_partial.filled_qty == 10


def test_rejection_from_created_and_submitted(sample_order: Order) -> None:
    """Verify pre-trade and broker rejection."""
    now = datetime.now(UTC)

    # Reject from CREATED
    rejected_created = OrderStateMachine.transition(
        sample_order,
        OrderStatus.REJECTED,
        timestamp=now,
        rejection_reason="Insufficient Margin",
    )
    assert rejected_created.status == OrderStatus.REJECTED
    assert rejected_created.rejection_reason == "Insufficient Margin"

    # Reject from SUBMITTED
    submitted = OrderStateMachine.transition(sample_order, OrderStatus.SUBMITTED, timestamp=now)
    rejected_sub = OrderStateMachine.transition(
        submitted,
        OrderStatus.REJECTED,
        timestamp=now,
        rejection_reason="Market circuit limit breached",
    )
    assert rejected_sub.status == OrderStatus.REJECTED


def test_illegal_state_transitions(sample_order: Order) -> None:
    """Verify illegal transitions are prevented by raising InvalidOrderStateTransitionError."""
    now = datetime.now(UTC)

    # CREATED -> FILLED is illegal (must be SUBMITTED first)
    with pytest.raises(InvalidOrderStateTransitionError):
        OrderStateMachine.transition(
            sample_order, OrderStatus.FILLED, timestamp=now, filled_qty=50, average_fill_price=150.0
        )

    # Terminal state FILLED cannot transition to anything
    submitted = OrderStateMachine.transition(sample_order, OrderStatus.SUBMITTED, timestamp=now)
    filled = OrderStateMachine.transition(
        submitted, OrderStatus.FILLED, timestamp=now, filled_qty=50, average_fill_price=150.0
    )

    with pytest.raises(InvalidOrderStateTransitionError):
        OrderStateMachine.transition(filled, OrderStatus.CANCELLED, timestamp=now)

    with pytest.raises(InvalidOrderStateTransitionError):
        OrderStateMachine.transition(filled, OrderStatus.SUBMITTED, timestamp=now)
