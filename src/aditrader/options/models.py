"""Immutable domain models for options derivatives, chains, Greeks, and payoff analytics."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aditrader.core.models.enums import OrderSide


class Greeks(BaseModel):
    """
    First and second-order Black-Scholes option sensitivity Greeks.

    Tolerances and scaling:
    - Delta: sensitivity to 1 INR underlying move (Call: [0, 1], Put: [-1, 0])
    - Gamma: sensitivity of Delta to 1 INR underlying move (Gamma > 0)
    - Theta: daily time decay in INR (calendar day: 1/365, trading day: 1/252)
    - Vega: sensitivity to 1% (1 vol point) change in implied volatility
    - Rho: sensitivity to 1% change in risk-free interest rate
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    delta: float = Field(
        description="Rate of change of option price with respect to underlying price"
    )
    gamma: float = Field(description="Rate of change of delta with respect to underlying price")
    theta: float = Field(description="1-calendar-day time decay of option price in INR")
    theta_trading: float = Field(description="1-trading-day time decay of option price in INR")
    vega: float = Field(
        description="Sensitivity of option price per 1% change in implied volatility"
    )
    rho: float = Field(description="Sensitivity of option price per 1% change in risk-free rate")


class OptionLeg(BaseModel):
    """
    Individual leg component of a single or multi-leg options strategy.

    Indian Market Specifics:
    - European exercise style assumption (NSE equity/index options are European style since 2018).
    - Lot sizes must come directly from scrip master ContractMetadata, never hardcoded.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    underlying: str = Field(min_length=1, description="Underlying asset symbol, e.g., NIFTY")
    expiry: datetime = Field(description="Contract expiration datetime in Asia/Kolkata")
    strike: float = Field(gt=0.0, description="Strike price of the option contract")
    option_type: Literal["CE", "PE"] = Field(description="Call (CE) or Put (PE)")
    side: OrderSide = Field(description="BUY (Long) or SELL (Short)")
    qty: int = Field(gt=0, description="Total contract lots or shares")
    entry_price: float = Field(ge=0.0, description="Execution premium in INR")
    lot_size: int = Field(default=1, gt=0, description="Exchange lot size from scrip master")

    @model_validator(mode="after")
    def validate_lot_multiple(self) -> "OptionLeg":
        """Verify quantity is a multiple of official exchange lot size."""
        if self.lot_size > 1 and self.qty % self.lot_size != 0:
            raise ValueError(
                f"Quantity {self.qty} must be an integer multiple of exchange lot size {self.lot_size}"
            )
        return self


class OptionStrategy(BaseModel):
    """Structured collection of option legs forming a single or multi-leg strategy."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(min_length=1, description="Unique strategy instance identifier")
    name: str = Field(min_length=1, description="Strategy name, e.g. Iron Condor, Long Straddle")
    legs: list[OptionLeg] = Field(min_length=1, description="Constituent option legs")
    dna_tags: list[str] = Field(default_factory=list, description="Strategy DNA classifications")
    created_at: datetime = Field(default_factory=datetime.now, description="Creation timestamp")


class ChainStrikeData(BaseModel):
    """Market quotes and derived metrics for a specific strike and option type (CE or PE)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ltp: float = Field(ge=0.0, description="Last traded premium price")
    bid: float | None = Field(default=None, ge=0.0, description="Best available bid")
    ask: float | None = Field(default=None, ge=0.0, description="Best available ask")
    volume: int = Field(default=0, ge=0, description="Accumulated trading volume")
    oi: int = Field(default=0, ge=0, description="Open interest contracts")
    iv: float | None = Field(
        default=None, ge=0.0, description="Implied volatility (annualized decimal)"
    )
    greeks: Greeks | None = Field(default=None, description="Computed Black-Scholes Greeks")


class ChainRow(BaseModel):
    """Grid row representing an option chain strike level for a specific expiration date."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strike: float = Field(gt=0.0, description="Strike price level")
    expiry: datetime = Field(description="Contract expiry datetime")
    call: ChainStrikeData | None = Field(
        default=None, description="Call option market and Greeks data"
    )
    put: ChainStrikeData | None = Field(
        default=None, description="Put option market and Greeks data"
    )


class PayoffPoint(BaseModel):
    """Coordinate point along the strategy underlying price spectrum."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    underlying_price: float = Field(description="Underlying spot price level at evaluation")
    pnl_at_expiry: float = Field(description="Total strategy P&L at expiration in INR")
    pnl_mtm: dict[int, float] = Field(
        default_factory=dict,
        description="Mark-to-market P&L mapped by Days-to-Expiry (DTE)",
    )


class PayoffSummary(BaseModel):
    """Key quantitative boundaries derived dynamically from the strategy payoff curve."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_profit: float | None = Field(
        default=None, description="Maximum attainable profit in INR (None if undefined/infinite)"
    )
    max_loss: float | None = Field(
        default=None, description="Maximum potential loss in INR (None if undefined/infinite)"
    )
    breakevens: list[float] = Field(
        default_factory=list, description="Exact underlying prices where at-expiry P&L = 0.0"
    )
    net_debit_credit: float = Field(
        description="Net entry cash flow: positive for net credit, negative for net debit"
    )
    risk_reward_ratio: float | None = Field(
        default=None, description="Max profit / Max loss ratio where bounded"
    )
