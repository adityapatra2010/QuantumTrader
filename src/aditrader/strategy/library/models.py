"""Immutable domain models for Strategy Library, DNA vectors, and versioned records."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from aditrader.strategy.builder.schema import StrategyDSL


class StrategyCategory(StrEnum):
    """Categorization of strategy provenance."""

    BUILT_IN = "Built-in"
    USER = "User"
    AI_GENERATED = "AI Generated"
    IMPORTED = "Imported"
    ARCHIVED = "Archived"


class Directionality(StrEnum):
    """Directional bias classification."""

    DELTA_NEUTRAL = "Delta-Neutral"
    BULLISH = "Bullish"
    BEARISH = "Bearish"


class ThetaExposure(StrEnum):
    """Time-decay exposure classification."""

    HIGH_POSITIVE = "High Positive"
    LOW_POSITIVE = "Low Positive"
    NEUTRAL = "Neutral"
    NEGATIVE = "Negative"


class VegaExposure(StrEnum):
    """Volatility exposure classification."""

    POSITIVE = "Positive"
    NEGATIVE = "Negative"
    NEUTRAL = "Neutral"


class GammaRisk(StrEnum):
    """Gamma risk / tail-risk exposure classification."""

    LOW = "Low"
    MODERATE = "Moderate"
    HIGH = "High"


class MarginEfficiency(StrEnum):
    """Capital efficiency rating."""

    HIGH = "High"
    MODERATE = "Moderate"
    LOW = "Low"


class TradingStyle(StrEnum):
    """Trading duration / frequency style."""

    SCALPING = "Scalping"
    INTRADAY = "Intraday"
    POSITIONAL = "Positional"
    EXPIRY_DAY = "Expiry-Day"


class MarketRegime(StrEnum):
    """Target market regime classification."""

    LOW_IV_SIDEWAYS = "Low IV Sideways"
    HIGH_IV_EXPANSION = "High IV Expansion"
    TREND_FOLLOWING = "Trend Following"
    RANGEBOUND = "Rangebound"


class StrategyDNA(BaseModel):
    """Multi-dimensional quantitative profile vector for strategy classification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    directionality: Directionality = Field(..., description="Directional delta bias")
    theta_exposure: ThetaExposure = Field(..., description="Sensitivity to time decay")
    vega_exposure: VegaExposure = Field(..., description="Sensitivity to volatility shifts")
    gamma_risk: GammaRisk = Field(..., description="Unhedged tail risk rating")
    margin_efficiency: MarginEfficiency = Field(..., description="Margin requirement efficiency")
    style: TradingStyle = Field(..., description="Holding period trading style")
    target_regime: MarketRegime = Field(..., description="Optimal market regime match")


class StrategyRecord(BaseModel):
    """Version-controlled catalog record containing strategy metadata, DNA, and AST DSL."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str = Field(..., min_length=1, description="Unique strategy record identifier (UUID)")
    name: str = Field(..., min_length=1, description="Human-readable strategy name")
    version: str = Field(..., min_length=1, description="Semantic version string (e.g., '1.0.0')")
    category: StrategyCategory = Field(default=StrategyCategory.BUILT_IN, description="Strategy origin")
    creator: str = Field(default="System", description="Strategy author or generator subsystem")
    created_at: datetime = Field(..., description="Creation timestamp in UTC/IST")
    validation_score: float | None = Field(
        default=None, ge=0.0, le=100.0, description="Quantitative validation score [0-100]"
    )
    dna: StrategyDNA = Field(..., description="Calculated DNA profile vector")
    dsl_definition: StrategyDSL = Field(..., description="Declarative JSON AST definition")
