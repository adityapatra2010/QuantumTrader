"""Immutable order contract and validation logic."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, model_validator

from aditrader.core.models.enums import OrderSide, OrderStatus, OrderType


class Order(BaseModel):
    """Formal broker order with execution lifecycle tracking."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    order_id: str = Field(..., min_length=1, description="Unique order identifier")
    symbol: str = Field(..., min_length=1, description="Target trading instrument symbol")
    side: OrderSide = Field(..., description="Order side (BUY or SELL)")
    order_type: OrderType = Field(..., description="Order execution type (MARKET or LIMIT)")
    qty: int = Field(..., gt=0, description="Total order contract/share quantity")
    price: float | None = Field(default=None, gt=0.0, description="Limit price if LIMIT order")
    status: OrderStatus = Field(default=OrderStatus.CREATED, description="Lifecycle status")
    created_at: datetime = Field(..., description="Creation timestamp in Asia/Kolkata")
    updated_at: datetime = Field(..., description="Last state update timestamp")
    signal_id: str | None = Field(default=None, description="Originating signal ID if applicable")
    filled_qty: int = Field(default=0, ge=0, description="Accumulated filled quantity")
    average_fill_price: float = Field(
        default=0.0, ge=0.0, description="Volume-weighted average fill price"
    )
    rejection_reason: str | None = Field(default=None, description="Reason if status is REJECTED")

    @model_validator(mode="after")
    def validate_order_spec(self) -> "Order":
        """Validate order type consistency and fill quantities."""
        if self.order_type == OrderType.LIMIT and self.price is None:
            raise ValueError("Limit orders require an explicit price > 0.0")
        if self.filled_qty > self.qty:
            raise ValueError(
                f"Filled quantity ({self.filled_qty}) cannot exceed total order quantity ({self.qty})"
            )
        if self.status == OrderStatus.FILLED and self.filled_qty != self.qty:
            raise ValueError(
                f"Order marked FILLED but filled_qty ({self.filled_qty}) != total qty ({self.qty})"
            )
        if self.status == OrderStatus.REJECTED and not self.rejection_reason:
            raise ValueError("Rejected orders must specify a rejection_reason")
        return self
