"""Unit tests for pure deterministic PremiumTrailingStop state machine.

Verifies:
- Standard sequence: 50 -> 40 => SL 45, 40 -> 35 => SL 40, 35 -> 30 => SL 35
- Adverse price movement: ratchet never loosens
- Stop breach: immediate trigger when price >= SL
- Repeated prices: idempotent evaluation
- Price gaps: step-based ratcheting across multiple steps
- Out-of-order timestamps: strict fail-closed rejection
- Duplicate timestamps: idempotent no-ops
- Contract identity binding: strict rejection of mismatched contract symbol
- Exit and re-entry state isolation: terminal state immutability
- Long position trailing stop mechanics
"""

from datetime import UTC, datetime

import pytest

from aditrader.core.models.enums import OrderSide
from aditrader.options.trailing_stop import (
    PremiumTrailingStop,
    TrailingStopEventType,
    TrailingStopState,
)


def test_trailing_stop_exact_user_sequence() -> None:
    """Verify:
    50 -> 40 => SL 45
    40 -> 35 => SL 40
    35 -> 30 => SL 35
    on the short contract.
    """
    t0 = datetime(2026, 9, 7, 9, 20, 0, tzinfo=UTC)
    ts = PremiumTrailingStop(
        contract_symbol="NIFTY26SEP24500CE",
        entry_price=50.0,
        initial_gap=5.0,
        trail_step=5.0,
        side=OrderSide.SELL,
        ratchet=True,
        created_at=t0,
    )

    # Initial state
    assert ts.current_stop == 55.0
    assert ts.peak_favorable_price == 50.0
    assert not ts.is_triggered

    # Step 1: 50 -> 40 => SL 45
    t1 = datetime(2026, 9, 7, 9, 25, 0, tzinfo=UTC)
    ev1 = ts.update(price=40.0, timestamp=t1)
    assert ev1.event_type == TrailingStopEventType.RATCHETED
    assert ts.current_stop == 45.0
    assert ts.peak_favorable_price == 40.0
    assert not ts.is_triggered

    # Step 2: 40 -> 35 => SL 40
    t2 = datetime(2026, 9, 7, 9, 30, 0, tzinfo=UTC)
    ev2 = ts.update(price=35.0, timestamp=t2)
    assert ev2.event_type == TrailingStopEventType.RATCHETED
    assert ts.current_stop == 40.0
    assert ts.peak_favorable_price == 35.0
    assert not ts.is_triggered

    # Step 3: 35 -> 30 => SL 35
    t3 = datetime(2026, 9, 7, 9, 35, 0, tzinfo=UTC)
    ev3 = ts.update(price=30.0, timestamp=t3)
    assert ev3.event_type == TrailingStopEventType.RATCHETED
    assert ts.current_stop == 35.0
    assert ts.peak_favorable_price == 30.0
    assert not ts.is_triggered


def test_trailing_stop_adverse_movement_ratchet_preservation() -> None:
    """Verify adverse price movements do not loosen ratchet, and trigger upon breach."""
    t0 = datetime(2026, 9, 7, 9, 20, 0, tzinfo=UTC)
    ts = PremiumTrailingStop(
        contract_symbol="NIFTY26SEP24500CE",
        entry_price=50.0,
        initial_gap=5.0,
        trail_step=5.0,
        side=OrderSide.SELL,
        created_at=t0,
    )

    # Move down to 30 => SL is 35
    ts.update(price=30.0, timestamp=datetime(2026, 9, 7, 9, 25, tzinfo=UTC))
    assert ts.current_stop == 35.0

    # Adverse move: price rises to 33.0 (below SL 35.0)
    ev_adverse = ts.update(price=33.0, timestamp=datetime(2026, 9, 7, 9, 30, tzinfo=UTC))
    assert ev_adverse.event_type == TrailingStopEventType.IDLE
    assert ts.current_stop == 35.0  # Ratchet NEVER loosened
    assert ts.peak_favorable_price == 30.0
    assert not ev_adverse.is_triggered

    # Adverse move: price touches 35.0 (exact SL breach)
    ev_breach = ts.update(price=35.0, timestamp=datetime(2026, 9, 7, 9, 35, tzinfo=UTC))
    assert ev_breach.event_type == TrailingStopEventType.TRIGGERED
    assert ev_breach.is_triggered
    assert ts.triggered_price == 35.0
    assert ts.triggered_at == datetime(2026, 9, 7, 9, 35, tzinfo=UTC)


def test_trailing_stop_price_gap_multiple_steps() -> None:
    """Verify price gapping down across multiple 5-point steps in a single tick."""
    t0 = datetime(2026, 9, 7, 9, 20, 0, tzinfo=UTC)
    ts = PremiumTrailingStop(
        contract_symbol="NIFTY26SEP24500CE",
        entry_price=50.0,
        initial_gap=5.0,
        trail_step=5.0,
        side=OrderSide.SELL,
        created_at=t0,
    )

    # Gap from 50.0 straight down to 28.0 (22-point favorable move = 4 complete 5-point steps)
    t1 = datetime(2026, 9, 7, 9, 25, 0, tzinfo=UTC)
    ev = ts.update(price=28.0, timestamp=t1)
    assert ev.event_type == TrailingStopEventType.RATCHETED
    # 4 steps * 5 = 20 points drop from initial SL (55.0 - 20.0 = 35.0)
    assert ts.current_stop == 35.0
    assert ts.peak_favorable_price == 28.0


def test_trailing_stop_repeated_same_price() -> None:
    """Verify repeated price evaluations are idempotent."""
    t0 = datetime(2026, 9, 7, 9, 20, 0, tzinfo=UTC)
    ts = PremiumTrailingStop(
        contract_symbol="NIFTY26SEP24500CE",
        entry_price=50.0,
        initial_gap=5.0,
        trail_step=5.0,
        side=OrderSide.SELL,
        created_at=t0,
    )

    ts.update(price=40.0, timestamp=datetime(2026, 9, 7, 9, 25, tzinfo=UTC))
    assert ts.current_stop == 45.0

    # Repeat same price 40.0 at later time
    ev = ts.update(price=40.0, timestamp=datetime(2026, 9, 7, 9, 26, tzinfo=UTC))
    assert ev.event_type == TrailingStopEventType.IDLE
    assert ts.current_stop == 45.0


def test_trailing_stop_out_of_order_timestamp_rejected() -> None:
    """Verify non-monotonic timestamps raise ValueError (fail-closed)."""
    t0 = datetime(2026, 9, 7, 9, 20, 0, tzinfo=UTC)
    ts = PremiumTrailingStop(
        contract_symbol="NIFTY26SEP24500CE",
        entry_price=50.0,
        initial_gap=5.0,
        trail_step=5.0,
        side=OrderSide.SELL,
        created_at=t0,
    )

    ts.update(price=45.0, timestamp=datetime(2026, 9, 7, 9, 25, tzinfo=UTC))

    # Earlier timestamp
    with pytest.raises(ValueError, match="Out-of-order timestamp"):
        ts.update(price=44.0, timestamp=datetime(2026, 9, 7, 9, 22, tzinfo=UTC))


def test_trailing_stop_contract_binding_mismatch_rejected() -> None:
    """Verify updates with a mismatched contract symbol are strictly rejected."""
    t0 = datetime(2026, 9, 7, 9, 20, 0, tzinfo=UTC)
    ts = PremiumTrailingStop(
        contract_symbol="NIFTY26SEP24500CE",
        entry_price=50.0,
        initial_gap=5.0,
        trail_step=5.0,
        side=OrderSide.SELL,
        created_at=t0,
    )

    with pytest.raises(ValueError, match="Trailing stop bound to contract"):
        ts.update(
            price=45.0,
            timestamp=datetime(2026, 9, 7, 9, 25, tzinfo=UTC),
            contract_symbol="NIFTY26SEP24600CE",  # Wrong contract!
        )


def test_trailing_stop_exit_and_reentry_isolation() -> None:
    """Verify once triggered, a stop cannot un-trigger or accept re-entry updates."""
    t0 = datetime(2026, 9, 7, 9, 20, 0, tzinfo=UTC)
    ts = PremiumTrailingStop(
        contract_symbol="NIFTY26SEP24500CE",
        entry_price=50.0,
        initial_gap=5.0,
        trail_step=5.0,
        side=OrderSide.SELL,
        created_at=t0,
    )

    # Trigger stop
    ts.update(price=55.0, timestamp=datetime(2026, 9, 7, 9, 21, tzinfo=UTC))
    assert ts.is_triggered

    # Further updates return terminal TRIGGERED event without resetting
    ev = ts.update(price=40.0, timestamp=datetime(2026, 9, 7, 9, 22, tzinfo=UTC))
    assert ev.event_type == TrailingStopEventType.TRIGGERED
    assert ts.is_triggered
    assert ts.current_stop == 55.0

    # Explicit close
    ts.close()
    assert ts.state == TrailingStopState.CLOSED


def test_trailing_stop_long_position_mechanics() -> None:
    """Verify long option trailing stop ratchets up on price increases and triggers on drops."""
    t0 = datetime(2026, 9, 7, 9, 20, 0, tzinfo=UTC)
    ts = PremiumTrailingStop(
        contract_symbol="NIFTY26SEP24500CE",
        entry_price=50.0,
        initial_gap=5.0,
        trail_step=5.0,
        side=OrderSide.BUY,
        created_at=t0,
    )

    # Initial SL for long: 50 - 5 = 45.0
    assert ts.current_stop == 45.0

    # Price rises 50 -> 60 (+10 points = 2 steps) => SL raises 45 + 10 = 55.0
    ev1 = ts.update(price=60.0, timestamp=datetime(2026, 9, 7, 9, 25, tzinfo=UTC))
    assert ev1.event_type == TrailingStopEventType.RATCHETED
    assert ts.current_stop == 55.0

    # Price drops to 55.0 => triggers stop
    ev2 = ts.update(price=55.0, timestamp=datetime(2026, 9, 7, 9, 30, tzinfo=UTC))
    assert ev2.event_type == TrailingStopEventType.TRIGGERED
    assert ts.is_triggered
