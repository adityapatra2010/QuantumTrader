"""Immutable market data models for ticks and aggregated OHLCV bars."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Tick(BaseModel):
    """Normalized live market tick event."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(..., min_length=1, description="Trading instrument symbol")
    ltp: float = Field(..., ge=0.0, description="Last traded price")
    bid: float = Field(..., ge=0.0, description="Best available bid price")
    ask: float = Field(..., ge=0.0, description="Best available ask price")
    volume: int = Field(..., ge=0, description="Cumulative trading volume for the session")
    oi: int = Field(..., ge=0, description="Total open interest contracts")
    timestamp: datetime = Field(..., description="Exchange tick timestamp in Asia/Kolkata")


class Bar(BaseModel):
    """Standard point-in-time OHLCV candle representation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: datetime = Field(..., description="Candle opening/closing timestamp in Asia/Kolkata")
    open: float = Field(..., gt=0.0, description="Bar open price")
    high: float = Field(..., gt=0.0, description="Bar highest price")
    low: float = Field(..., gt=0.0, description="Bar lowest price")
    close: float = Field(..., gt=0.0, description="Bar close price")
    volume: int = Field(..., ge=0, description="Bar volume traded")
    oi: int = Field(..., ge=0, description="Open interest at candle close")

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
