"""Immutable domain models and risk gate classifications."""

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RiskRejectionReason(StrEnum):
    """Specific cause for pre-trade risk gate rejection."""

    MARGIN_LIMIT_EXCEEDED = "MARGIN_LIMIT_EXCEEDED"
    CIRCUIT_BREAKER_ACTIVE = "CIRCUIT_BREAKER_ACTIVE"
    EXPIRY_NAKED_SHORT_PROHIBITED = "EXPIRY_NAKED_SHORT_PROHIBITED"
    POSITION_LIMIT_EXCEEDED = "POSITION_LIMIT_EXCEEDED"


class RiskLimits(BaseModel):
    """Institutional pre-trade risk policy configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_margin_utilization_pct: float = Field(
        default=0.85, ge=0.0, le=1.0, description="Maximum allowed margin utilization (85%)"
    )
    portfolio_drawdown_limit_pct: float = Field(
        default=0.05, ge=0.0, le=1.0, description="Intraday portfolio drawdown circuit breaker (5%)"
    )
    prohibit_expiry_naked_shorts: bool = Field(
        default=True, description="Strictly prohibit unhedged naked short options on expiry day"
    )
    max_concurrent_lots: int = Field(
        default=50, gt=0, description="Maximum allowed cumulative position lots across underlyings"
    )


class RiskCheckResult(BaseModel):
    """Outcome of pre-trade risk gate evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    passed: bool = Field(..., description="Whether the order clears all active risk gates")
    reason: RiskRejectionReason | None = Field(
        default=None, description="Primary rejection classification if failed"
    )
    detail: str | None = Field(
        default=None, description="Human-readable diagnostics explaining the rejection"
    )
