"""Immutable market data models for ticks, aggregated OHLCV bars, and data provenance."""

from datetime import datetime
from enum import StrEnum

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
