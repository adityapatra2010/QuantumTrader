"""Immutable execution contracts for trades, positions, and ledger account balances."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from aditrader.core.models.enums import OrderSide


class Trade(BaseModel):
    """Immutable record of an executed order fill."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trade_id: str = Field(..., min_length=1, description="Unique execution fill identifier")
    order_id: str = Field(..., min_length=1, description="Associated order identifier")
    symbol: str = Field(..., min_length=1, description="Instrument traded")
    side: OrderSide = Field(..., description="Trade side (BUY or SELL)")
    qty: int = Field(..., gt=0, description="Quantity executed in this fill")
    fill_price: float = Field(..., gt=0.0, description="Executed fill price")
    slippage: float = Field(default=0.0, ge=0.0, description="Estimated/realized slippage penalty")
    stt: float = Field(default=0.0, ge=0.0, description="Securities Transaction Tax applied")
    charges: float = Field(
        default=0.0, ge=0.0, description="Exchange, GST, and SEBI regulatory fees"
    )
    timestamp: datetime = Field(..., description="Fill execution timestamp in Asia/Kolkata")


class Position(BaseModel):
    """Aggregate open/closed position record for an underlying or derivative."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    symbol: str = Field(..., min_length=1, description="Instrument identifier")
    qty: int = Field(
        default=0, description="Net lot/share quantity (positive: Long, negative: Short, 0: Flat)"
    )
    buy_avg_price: float = Field(
        default=0.0, ge=0.0, description="Average entry price for active long exposure"
    )
    sell_avg_price: float = Field(
        default=0.0, ge=0.0, description="Average entry price for active short exposure"
    )
    realized_pnl: float = Field(default=0.0, description="Closed-out net profit or loss")
    unrealized_pnl: float = Field(
        default=0.0, description="Mark-to-market open position profit or loss"
    )
    updated_at: datetime = Field(..., description="Last position update timestamp in Asia/Kolkata")


class AccountBalance(BaseModel):
    """Financial snapshot of simulated paper capital and margin utilization."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_capital: float = Field(
        ..., description="Net account equity including cash and unrealized P&L"
    )
    available_margin: float = Field(
        ..., description="Liquid capital available to commit to new positions"
    )
    used_margin: float = Field(
        default=0.0, ge=0.0, description="Capital locked in open margin requirements"
    )
    realized_pnl: float = Field(
        default=0.0, description="Total realized profit/loss across closed trades"
    )
    unrealized_pnl: float = Field(
        default=0.0, description="Total mark-to-market profit/loss across open positions"
    )
