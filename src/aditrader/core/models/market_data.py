"""Immutable market data models for ticks, aggregated OHLCV bars, and data provenance."""

from datetime import date, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MarketDataSourceType(StrEnum):
    """Origin classification for market data observations."""

    LIVE_BROKER = "LIVE_BROKER"
    HISTORICAL_RECORD = "HISTORICAL_RECORD"
    AGGREGATED_BAR = "AGGREGATED_BAR"
    SYNTHETIC_TEST = "SYNTHETIC_TEST"


class MarketDataProvenance(BaseModel):
    """Audit metadata tracking the origin, resolution, and authenticity of market data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_type: MarketDataSourceType = Field(..., description="Data origin classification")
    provider: str = Field(
        ..., description="Source venue or adapter identifier (e.g. 'kotak', 'csv', 'parquet')"
    )
    symbol: str = Field(..., min_length=1, description="Instrument trading symbol")
    timeframe: str | None = Field(
        default=None, description="Granularity/resolution (e.g. 'tick', '1m', '5m')"
    )
    is_synthetic: bool = Field(
        default=False, description="True if observation contains simulated or synthetic data"
    )


class Tick(BaseModel):
    """Normalized market tick event capturing genuine quote and trade data."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(..., min_length=1, description="Trading instrument symbol")
    ltp: float = Field(..., ge=0.0, description="Last traded price")
    timestamp: datetime = Field(..., description="Exchange tick timestamp in Asia/Kolkata")
    volume: int = Field(default=0, ge=0, description="Session cumulative or tick traded volume")
    oi: int | None = Field(
        default=None, ge=0, description="Total open interest contracts if available"
    )
    bid: float | None = Field(
        default=None, ge=0.0, description="Best available bid price if available"
    )
    ask: float | None = Field(
        default=None, ge=0.0, description="Best available ask price if available"
    )
    bid_qty: int | None = Field(
        default=None, ge=0, description="Best available bid quantity if available"
    )
    ask_qty: int | None = Field(
        default=None, ge=0, description="Best available ask quantity if available"
    )
    exchange: str | None = Field(
        default=None, description="Exchange segment (e.g. 'NSE', 'NFO', 'BSE')"
    )
    instrument_token: str | None = Field(
        default=None, description="Broker or exchange instrument token"
    )
    source: str | None = Field(
        default=None, description="Provider origin identifier (e.g. 'KOTAK_LIVE', 'SYNTHETIC')"
    )
    data_type: str = Field(default="TICK", description="Data resolution category ('TICK', 'QUOTE')")
    is_synthetic: bool = Field(
        default=False, description="True if tick was synthetically generated"
    )

    @model_validator(mode="after")
    def validate_bid_ask_spread(self) -> "Tick":
        """Assert valid bid/ask relationship when both quotes are present."""
        if (
            self.bid is not None
            and self.ask is not None
            and self.bid > 0.0
            and self.ask > 0.0
            and self.bid > self.ask
        ):
            raise ValueError(
                f"Invalid crossed market: Bid price ({self.bid}) cannot exceed Ask price ({self.ask})"
            )
        return self


class Bar(BaseModel):
    """Standard point-in-time OHLCV candle representation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime = Field(..., description="Candle opening/closing timestamp in Asia/Kolkata")
    open: float = Field(..., gt=0.0, description="Bar open price")
    high: float = Field(..., gt=0.0, description="Bar highest price")
    low: float = Field(..., gt=0.0, description="Bar lowest price")
    close: float = Field(..., gt=0.0, description="Bar close price")
    volume: int = Field(default=0, ge=0, description="Bar volume traded")
    oi: int = Field(default=0, ge=0, description="Open interest at candle close")
    symbol: str | None = Field(default=None, description="Trading instrument symbol")
    vwap: float | None = Field(
        default=None, ge=0.0, description="Volume-weighted average price if available"
    )
    tick_count: int | None = Field(
        default=None, ge=0, description="Number of ticks aggregated into bar"
    )
    source: str | None = Field(
        default=None, description="Origin feed identifier (e.g. 'KOTAK_LIVE', 'CSV_HISTORICAL')"
    )
    timeframe: str | None = Field(
        default=None, description="Bar resolution (e.g. '1m', '5m', '1d')"
    )
    is_synthetic: bool = Field(default=False, description="True if bar was synthetically generated")

    @model_validator(mode="after")
    def validate_price_bounds(self) -> "Bar":
        """Assert OHLC price envelope consistency."""
        if self.high < self.low:
            raise ValueError(
                f"High price ({self.high}) cannot be lower than Low price ({self.low})"
            )
        if self.high < max(self.open, self.close):
            raise ValueError(f"High price ({self.high}) must be >= open and close")
        if self.low > min(self.open, self.close):
            raise ValueError(f"Low price ({self.low}) must be <= open and close")
        return self


class DerivativeQuoteRecord(BaseModel):
    """Normalized daily observation record for exchange-traded derivative contracts.

    Faithfully captures all 15 fields of the official NSE derivative quote/download schema:
    Date, Expiry Date, Option Type, Strike Price, Open Price, High Price, Low Price,
    Close Price, Last Price, Settlement Price, Volume, Value (₹ Lakhs), Premium Value (₹ Lakhs),
    Open Interest, Change in OI.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime = Field(..., description="Observation / session date-time in Asia/Kolkata")
    symbol: str = Field(..., min_length=1, description="Root underlying symbol (e.g. 'RELIANCE')")
    trading_symbol: str = Field(
        ...,
        min_length=1,
        description="Composite derivative contract identifier (e.g. 'RELIANCE 29-Sep-2026 CE 1370')",
    )
    expiry_date: date = Field(..., description="Contract expiration date")
    option_type: Literal["CE", "PE", "XX"] = Field(
        ..., description="Option type ('CE', 'PE') or 'XX' for futures"
    )
    strike_price: float | None = Field(
        default=None, description="Strike price in INR (None for futures)"
    )
    open: float | None = Field(default=None, gt=0.0, description="Daily open price if traded")
    high: float | None = Field(default=None, gt=0.0, description="Daily high price if traded")
    low: float | None = Field(default=None, gt=0.0, description="Daily low price if traded")
    close: float | None = Field(default=None, gt=0.0, description="Daily close price if available")
    last_price: float | None = Field(
        default=None, gt=0.0, description="Last traded price (LTP) if available"
    )
    settlement_price: float | None = Field(
        default=None, gt=0.0, description="Daily official settlement price if available"
    )
    volume: int = Field(default=0, ge=0, description="Traded contracts / volume")
    value_lakhs: float | None = Field(
        default=None, ge=0.0, description="Notional turnover value in Lakhs"
    )
    premium_value_lakhs: float | None = Field(
        default=None, ge=0.0, description="Premium turnover value in Lakhs"
    )
    oi: int | None = Field(default=None, ge=0, description="Total open interest contracts")
    change_in_oi: int | None = Field(default=None, description="Net change in open interest")
    vwap: float | None = Field(
        default=None, ge=0.0, description="Volume-weighted average price if available"
    )
    source: str = Field(default="NSE_DERIVATIVE_QUOTE", description="Origin data source identifier")

    @model_validator(mode="after")
    def validate_derivative_record(self) -> "DerivativeQuoteRecord":
        """Validate price envelopes when traded, and enforce strike requirements for options."""
        if (
            self.open is not None
            and self.high is not None
            and self.low is not None
            and self.close is not None
        ):
            if self.high < self.low:
                raise ValueError(
                    f"High price ({self.high}) cannot be lower than Low price ({self.low})"
                )
            if self.high < max(self.open, self.close):
                raise ValueError(f"High price ({self.high}) must be >= open and close")
            if self.low > min(self.open, self.close):
                raise ValueError(f"Low price ({self.low}) must be <= open and close")

        if self.option_type in ("CE", "PE") and (
            self.strike_price is None or self.strike_price <= 0.0
        ):
            raise ValueError(
                f"Option contract '{self.trading_symbol}' ({self.option_type}) requires a positive strike price"
            )
        return self

    @property
    def underlying(self) -> str:
        """Root underlying symbol alias."""
        return self.symbol

    @property
    def open_price(self) -> float | None:
        """Daily open price alias."""
        return self.open

    @property
    def high_price(self) -> float | None:
        """Daily high price alias."""
        return self.high

    @property
    def low_price(self) -> float | None:
        """Daily low price alias."""
        return self.low

    @property
    def close_price(self) -> float | None:
        """Daily close price alias."""
        return self.close

    @property
    def open_interest(self) -> int | None:
        """Open interest alias."""
        return self.oi

    @property
    def contract_symbol(self) -> str:
        """Composite contract symbol identifier alias."""
        return self.trading_symbol
