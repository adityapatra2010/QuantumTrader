"""Pure deterministic premium-based trailing stop loss state machine for options contracts.

Follows institutional risk mechanics:
- For Short positions (e.g. SELL @ 50, gap=5, step=5):
  * Initial SL = 55.0
  * Price drops 50 -> 40 => SL ratchets to 45.0
  * Price drops 40 -> 35 => SL ratchets to 40.0
  * Price drops 35 -> 30 => SL ratchets to 35.0
  * Adverse price moves (30 -> 33) never loosen the ratchet
  * Price touching or breaching SL (>= 35.0) triggers the stop immediately
- Bound strictly to the resolved contract identity (never jumps to new contracts)
- Enforces temporal causality (rejects out-of-order timestamps)
"""

import math
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aditrader.core.models.enums import OrderSide


class TrailingStopState(StrEnum):
    """Lifecycle state of the trailing stop."""

    ARMED = "ARMED"
    TRIGGERED = "TRIGGERED"
    CLOSED = "CLOSED"


class TrailingStopEventType(StrEnum):
    """Classification of trailing stop evaluation events."""

    INITIALIZED = "INITIALIZED"
    RATCHETED = "RATCHETED"
    TRIGGERED = "TRIGGERED"
    IDLE = "IDLE"


class TrailingStopEvent(BaseModel):
    """Detailed observation emitted upon price evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    event_type: TrailingStopEventType = Field(..., description="Action taken during update")
    contract_symbol: str = Field(..., description="Target contract identifier")
    timestamp: datetime = Field(..., description="Evaluation timestamp")
    price: float = Field(..., description="Current observed price")
    current_stop: float = Field(..., description="Active stop level after update")
    peak_favorable_price: float = Field(..., description="Best price reached so far")
    is_triggered: bool = Field(..., description="True if stop has triggered")
    message: str = Field(..., description="Diagnostic description of the event")


class PremiumTrailingStop:
    """Deterministic, per-contract trailing stop state machine.

    Immutable contract binding: bound to a single contract symbol upon creation.
    Cannot be switched or reassigned to a different contract.
    """

    def __init__(
        self,
        contract_symbol: str,
        entry_price: float,
        initial_gap: float,
        trail_step: float,
        side: OrderSide = OrderSide.SELL,
        ratchet: bool = True,
        created_at: datetime | None = None,
    ) -> None:
        if not contract_symbol or not contract_symbol.strip():
            raise ValueError("contract_symbol must be a non-empty string")
        if entry_price <= 0.0:
            raise ValueError(f"entry_price must be strictly positive, got {entry_price}")
        if initial_gap <= 0.0:
            raise ValueError(f"initial_gap must be strictly positive, got {initial_gap}")
        if trail_step <= 0.0:
            raise ValueError(f"trail_step must be strictly positive, got {trail_step}")

        self._contract_symbol = contract_symbol.strip()
        self._entry_price = float(entry_price)
        self._initial_gap = float(initial_gap)
        self._trail_step = float(trail_step)
        self._side = side
        self._ratchet = ratchet

        # Initial state
        self._state = TrailingStopState.ARMED
        self._peak_favorable_price = self._entry_price
        self._last_price = self._entry_price
        self._last_timestamp = created_at
        self._triggered_at: datetime | None = None
        self._triggered_price: float | None = None

        if self._side == OrderSide.SELL:
            # Short option: price falling is favorable; stop is above price
            self._current_stop = self._entry_price + self._initial_gap
        else:
            # Long option: price rising is favorable; stop is below price
            self._current_stop = max(0.0, self._entry_price - self._initial_gap)

    @property
    def contract_symbol(self) -> str:
        """Contract identity this stop is bound to."""
        return self._contract_symbol

    @property
    def entry_price(self) -> float:
        """Execution price at position entry."""
        return self._entry_price

    @property
    def initial_gap(self) -> float:
        """Initial distance between entry price and stop."""
        return self._initial_gap

    @property
    def trail_step(self) -> float:
        """Step size for ratcheting."""
        return self._trail_step

    @property
    def side(self) -> OrderSide:
        """Position side (BUY or SELL)."""
        return self._side

    @property
    def current_stop(self) -> float:
        """Current active stop price."""
        return self._current_stop

    @property
    def peak_favorable_price(self) -> float:
        """Best favorable price observed during the position lifetime."""
        return self._peak_favorable_price

    @property
    def state(self) -> TrailingStopState:
        """Current state machine status."""
        return self._state

    @property
    def is_triggered(self) -> bool:
        """True if stop was triggered by market price."""
        return self._state == TrailingStopState.TRIGGERED

    @property
    def triggered_at(self) -> datetime | None:
        """Timestamp when stop was triggered."""
        return self._triggered_at

    @property
    def triggered_price(self) -> float | None:
        """Price at which stop was triggered."""
        return self._triggered_price

    def update(
        self,
        price: float,
        timestamp: datetime,
        contract_symbol: str | None = None,
    ) -> TrailingStopEvent:
        """Evaluate incoming price against the trailing stop.

        Args:
            price: Current observed price / LTP
            timestamp: Observation timestamp in Asia/Kolkata or UTC
            contract_symbol: Optional contract identity to verify binding

        Returns:
            TrailingStopEvent describing state transition
        """
        # 1. Verify contract identity binding
        if contract_symbol is not None and contract_symbol.strip() != self._contract_symbol:
            raise ValueError(
                f"Trailing stop bound to contract '{self._contract_symbol}', "
                f"cannot be updated with contract '{contract_symbol.strip()}'"
            )

        if price <= 0.0:
            raise ValueError(f"Price must be strictly positive, got {price}")

        # 2. Check temporal causality
        if self._last_timestamp is not None and timestamp < self._last_timestamp:
            raise ValueError(
                f"Out-of-order timestamp: update timestamp ({timestamp}) is earlier than "
                f"last observed timestamp ({self._last_timestamp})"
            )

        # 3. If already triggered or closed, return terminal event
        if self._state == TrailingStopState.TRIGGERED:
            return TrailingStopEvent(
                event_type=TrailingStopEventType.TRIGGERED,
                contract_symbol=self._contract_symbol,
                timestamp=timestamp,
                price=price,
                current_stop=self._current_stop,
                peak_favorable_price=self._peak_favorable_price,
                is_triggered=True,
                message=f"Stop already triggered at {self._triggered_at} (price {self._triggered_price})",
            )

        if self._state == TrailingStopState.CLOSED:
            return TrailingStopEvent(
                event_type=TrailingStopEventType.IDLE,
                contract_symbol=self._contract_symbol,
                timestamp=timestamp,
                price=price,
                current_stop=self._current_stop,
                peak_favorable_price=self._peak_favorable_price,
                is_triggered=False,
                message="Position already closed",
            )

        # 4. Evaluate stop breach
        if self._side == OrderSide.SELL:
            # Short position: triggered if price rises to or above current stop
            if price >= self._current_stop:
                self._state = TrailingStopState.TRIGGERED
                self._triggered_at = timestamp
                self._triggered_price = price
                self._last_price = price
                self._last_timestamp = timestamp
                return TrailingStopEvent(
                    event_type=TrailingStopEventType.TRIGGERED,
                    contract_symbol=self._contract_symbol,
                    timestamp=timestamp,
                    price=price,
                    current_stop=self._current_stop,
                    peak_favorable_price=self._peak_favorable_price,
                    is_triggered=True,
                    message=f"Short trailing stop triggered: price {price:.2f} >= SL {self._current_stop:.2f}",
                )

            # Check favorable move (price drop)
            if price < self._peak_favorable_price:
                self._peak_favorable_price = price

            # Ratchet calculation: for short, every step drop below entry drops the stop
            favorable_drop = self._entry_price - self._peak_favorable_price
            if favorable_drop >= self._trail_step:
                steps = math.floor(favorable_drop / self._trail_step)
                candidate_stop = (self._entry_price + self._initial_gap) - (
                    steps * self._trail_step
                )
                if self._ratchet:
                    # Ratchet mode: stop can only move down (never up)
                    if candidate_stop < self._current_stop:
                        prev_stop = self._current_stop
                        self._current_stop = candidate_stop
                        self._last_price = price
                        self._last_timestamp = timestamp
                        return TrailingStopEvent(
                            event_type=TrailingStopEventType.RATCHETED,
                            contract_symbol=self._contract_symbol,
                            timestamp=timestamp,
                            price=price,
                            current_stop=self._current_stop,
                            peak_favorable_price=self._peak_favorable_price,
                            is_triggered=False,
                            message=f"SL ratcheted down from {prev_stop:.2f} to {self._current_stop:.2f}",
                        )
                else:
                    self._current_stop = candidate_stop

        else:
            # Long position: triggered if price falls to or below current stop
            if price <= self._current_stop:
                self._state = TrailingStopState.TRIGGERED
                self._triggered_at = timestamp
                self._triggered_price = price
                self._last_price = price
                self._last_timestamp = timestamp
                return TrailingStopEvent(
                    event_type=TrailingStopEventType.TRIGGERED,
                    contract_symbol=self._contract_symbol,
                    timestamp=timestamp,
                    price=price,
                    current_stop=self._current_stop,
                    peak_favorable_price=self._peak_favorable_price,
                    is_triggered=True,
                    message=f"Long trailing stop triggered: price {price:.2f} <= SL {self._current_stop:.2f}",
                )

            # Check favorable move (price rise)
            if price > self._peak_favorable_price:
                self._peak_favorable_price = price

            # Ratchet calculation: for long, every step rise above entry raises the stop
            favorable_gain = self._peak_favorable_price - self._entry_price
            if favorable_gain >= self._trail_step:
                steps = math.floor(favorable_gain / self._trail_step)
                candidate_stop = (self._entry_price - self._initial_gap) + (
                    steps * self._trail_step
                )
                if self._ratchet:
                    if candidate_stop > self._current_stop:
                        prev_stop = self._current_stop
                        self._current_stop = candidate_stop
                        self._last_price = price
                        self._last_timestamp = timestamp
                        return TrailingStopEvent(
                            event_type=TrailingStopEventType.RATCHETED,
                            contract_symbol=self._contract_symbol,
                            timestamp=timestamp,
                            price=price,
                            current_stop=self._current_stop,
                            peak_favorable_price=self._peak_favorable_price,
                            is_triggered=False,
                            message=f"SL ratcheted up from {prev_stop:.2f} to {self._current_stop:.2f}",
                        )
                else:
                    self._current_stop = candidate_stop

        self._last_price = price
        self._last_timestamp = timestamp
        return TrailingStopEvent(
            event_type=TrailingStopEventType.IDLE,
            contract_symbol=self._contract_symbol,
            timestamp=timestamp,
            price=price,
            current_stop=self._current_stop,
            peak_favorable_price=self._peak_favorable_price,
            is_triggered=False,
            message=f"Price {price:.2f} evaluated; SL held at {self._current_stop:.2f}",
        )

    def close(self) -> None:
        """Mark the stop as closed upon explicit position exit."""
        self._state = TrailingStopState.CLOSED

    def to_dict(self) -> dict[str, Any]:
        """Diagnostic state serialization."""
        return {
            "contract_symbol": self._contract_symbol,
            "entry_price": self._entry_price,
            "initial_gap": self._initial_gap,
            "trail_step": self._trail_step,
            "side": self._side.value,
            "current_stop": self._current_stop,
            "peak_favorable_price": self._peak_favorable_price,
            "state": self._state.value,
            "is_triggered": self.is_triggered,
            "triggered_at": self._triggered_at.isoformat() if self._triggered_at else None,
            "triggered_price": self._triggered_price,
        }
