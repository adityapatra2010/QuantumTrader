"""Multi-leg options position group domain model and lifecycle management.

Preserves the invariant:
- The resolved contract identity (symbol, strike, expiry, option_type) remains
  permanently attached to each leg within the position group.
- Tracks per-leg unrealized and realized P&L alongside the aggregate group outcome.
- Encapsulates per-leg trailing stops without cross-contract pollution.
"""

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from aditrader.core.models.enums import OrderSide
from aditrader.options.trailing_stop import PremiumTrailingStop, TrailingStopEvent


class PositionGroupStatus(StrEnum):
    """Lifecycle status of a multi-leg options position group."""

    ACTIVE = "ACTIVE"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    CLOSED = "CLOSED"


class PositionGroupLeg(BaseModel):
    """Individual leg within an options position group."""

    model_config = ConfigDict(arbitrary_types_allowed=True, extra="forbid")

    leg_id: str = Field(..., min_length=1, description="Unique leg identifier")
    contract_symbol: str = Field(
        ..., min_length=1, description="Immutable resolved contract identity"
    )
    underlying: str = Field(..., min_length=1, description="Root underlying symbol")
    strike: float = Field(gt=0.0, description="Strike price in INR")
    option_type: Literal["CE", "PE"] = Field(..., description="Option type: CE or PE")
    expiry: date | datetime = Field(..., description="Contract expiration date or datetime")
    side: OrderSide = Field(..., description="Order side: BUY or SELL")
    quantity: int = Field(gt=0, description="Quantity in contract lots or shares")
    lot_size: int = Field(default=1, gt=0, description="Exchange lot size multiplier")
    entry_price: float = Field(gt=0.0, description="Executed fill price / premium")
    entry_timestamp: datetime = Field(..., description="Entry execution timestamp")
    current_price: float = Field(gt=0.0, description="Latest observed market price / LTP")
    current_timestamp: datetime = Field(..., description="Timestamp of latest price update")
    is_closed: bool = Field(default=False, description="True if leg has been exited")
    exit_price: float | None = Field(default=None, description="Exit execution price if closed")
    exit_timestamp: datetime | None = Field(
        default=None, description="Exit execution timestamp if closed"
    )
    trailing_stop: PremiumTrailingStop | None = Field(
        default=None, description="Optional per-contract trailing stop state machine"
    )

    @property
    def total_units(self) -> int:
        """Total executed share/contract units (quantity * lot_size)."""
        return self.quantity * self.lot_size

    @property
    def unrealized_pnl(self) -> float:
        """Mark-to-market unrealized P&L in INR."""
        if self.is_closed:
            return 0.0
        units = self.total_units
        if self.side == OrderSide.BUY:
            return (self.current_price - self.entry_price) * units
        else:
            return (self.entry_price - self.current_price) * units

    @property
    def realized_pnl(self) -> float:
        """Closed-out net profit or loss in INR."""
        if not self.is_closed or self.exit_price is None:
            return 0.0
        units = self.total_units
        if self.side == OrderSide.BUY:
            return (self.exit_price - self.entry_price) * units
        else:
            return (self.entry_price - self.exit_price) * units

    @property
    def notional_entry_value(self) -> float:
        """Gross premium turnover committed at entry in INR."""
        return self.entry_price * self.total_units

    def update_price(self, price: float, timestamp: datetime) -> TrailingStopEvent | None:
        """Update current price and evaluate trailing stop if present."""
        if self.is_closed:
            return None
        self.current_price = price
        self.current_timestamp = timestamp
        if self.trailing_stop is not None:
            return self.trailing_stop.update(
                price=price,
                timestamp=timestamp,
                contract_symbol=self.contract_symbol,
            )
        return None

    def close(self, exit_price: float, timestamp: datetime) -> None:
        """Close this leg at the specified exit price."""
        if self.is_closed:
            return
        self.is_closed = True
        self.exit_price = exit_price
        self.exit_timestamp = timestamp
        self.current_price = exit_price
        self.current_timestamp = timestamp
        if self.trailing_stop is not None:
            self.trailing_stop.close()


class OptionPositionGroup:
    """Coordinated multi-leg position container managing collective lifecycle and risk."""

    def __init__(
        self,
        group_id: str,
        strategy_name: str,
        underlying: str,
        created_at: datetime,
        legs: list[PositionGroupLeg],
        target_premium_level: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not group_id or not group_id.strip():
            raise ValueError("group_id must be a non-empty string")
        if not strategy_name or not strategy_name.strip():
            raise ValueError("strategy_name must be a non-empty string")
        if not underlying or not underlying.strip():
            raise ValueError("underlying must be a non-empty string")
        if not legs:
            raise ValueError("OptionPositionGroup must contain at least one leg")

        self._group_id = group_id.strip()
        self._strategy_name = strategy_name.strip()
        self._underlying = underlying.strip()
        self._created_at = created_at
        self._legs = list(legs)
        self._target_premium_level = target_premium_level
        self._metadata = dict(metadata or {})
        self._status = PositionGroupStatus.ACTIVE

    @property
    def group_id(self) -> str:
        """Unique identifier for this position group."""
        return self._group_id

    @property
    def strategy_name(self) -> str:
        """Originating strategy title."""
        return self._strategy_name

    @property
    def underlying(self) -> str:
        """Root underlying symbol."""
        return self._underlying

    @property
    def created_at(self) -> datetime:
        """Creation timestamp."""
        return self._created_at

    @property
    def legs(self) -> list[PositionGroupLeg]:
        """Constituent legs with persistent contract identities."""
        return list(self._legs)

    @property
    def target_premium_level(self) -> float | None:
        """Target premium tier if constructed from ladder (e.g. 50.0)."""
        return self._target_premium_level

    @property
    def metadata(self) -> dict[str, Any]:
        """Auxiliary metadata."""
        return dict(self._metadata)

    @property
    def status(self) -> PositionGroupStatus:
        """Current group status."""
        return self._status

    @property
    def is_closed(self) -> bool:
        """True if all legs in the group have been closed."""
        return all(leg.is_closed for leg in self._legs)

    @property
    def is_any_trailing_stop_triggered(self) -> bool:
        """True if any leg's trailing stop has fired."""
        return any(
            leg.trailing_stop is not None and leg.trailing_stop.is_triggered for leg in self._legs
        )

    @property
    def total_unrealized_pnl(self) -> float:
        """Sum of unrealized P&L across all legs in INR."""
        return sum(leg.unrealized_pnl for leg in self._legs)

    @property
    def total_realized_pnl(self) -> float:
        """Sum of realized P&L across closed legs in INR."""
        return sum(leg.realized_pnl for leg in self._legs)

    @property
    def net_cash_flow_entry(self) -> float:
        """Net cash flow at entry: positive for net credit, negative for net debit."""
        net = 0.0
        for leg in self._legs:
            value = leg.notional_entry_value
            if leg.side == OrderSide.SELL:
                net += value
            else:
                net -= value
        return net

    def get_leg(self, contract_symbol: str) -> PositionGroupLeg | None:
        """Find a leg by its exact resolved contract symbol."""
        for leg in self._legs:
            if leg.contract_symbol == contract_symbol:
                return leg
        return None

    def get_short_legs(self) -> list[PositionGroupLeg]:
        """Return all short (SELL) legs in this group."""
        return [leg for leg in self._legs if leg.side == OrderSide.SELL]

    def get_hedge_legs(self) -> list[PositionGroupLeg]:
        """Return all long (BUY) hedge legs in this group."""
        return [leg for leg in self._legs if leg.side == OrderSide.BUY]

    def update_price(
        self,
        contract_symbol: str,
        price: float,
        timestamp: datetime,
    ) -> list[TrailingStopEvent]:
        """Route quote update to matching leg(s) and collect any trailing stop events."""
        events: list[TrailingStopEvent] = []
        matched = False
        for leg in self._legs:
            if leg.contract_symbol == contract_symbol and not leg.is_closed:
                matched = True
                ev = leg.update_price(price, timestamp)
                if ev is not None:
                    events.append(ev)

        if not matched:
            # Update might be for a symbol not in group, harmless or ignored
            pass

        return events

    def close_leg(self, contract_symbol: str, exit_price: float, timestamp: datetime) -> None:
        """Close a specific leg by contract symbol."""
        for leg in self._legs:
            if leg.contract_symbol == contract_symbol and not leg.is_closed:
                leg.close(exit_price=exit_price, timestamp=timestamp)

        self._refresh_status()

    def close_all(self, exit_prices: dict[str, float], timestamp: datetime) -> None:
        """Close all open legs in the group with provided exit prices."""
        for leg in self._legs:
            if not leg.is_closed:
                price = exit_prices.get(leg.contract_symbol, leg.current_price)
                leg.close(exit_price=price, timestamp=timestamp)

        self._refresh_status()

    def _refresh_status(self) -> None:
        """Update group status based on constituent leg states."""
        closed_count = sum(1 for leg in self._legs if leg.is_closed)
        if closed_count == len(self._legs):
            self._status = PositionGroupStatus.CLOSED
        elif closed_count > 0:
            self._status = PositionGroupStatus.PARTIALLY_CLOSED
        else:
            self._status = PositionGroupStatus.ACTIVE
