"""Typed configuration models for AI Subsystems, per-subsystem routing, and usage budgets.

Per Phase 7A:
- Decouples domain logic from provider-specific model IDs.
- Subsystems (Vision, Forecasting, Suggestor, Reviewer, OCR) can be configured independently.
- Spend and request budgets are strictly configuration data.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aditrader.ai.catalog import AICapability


class ModelUsageLimit(BaseModel):
    """Usage thresholds and bounds for a specific model or provider."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_requests: int | None = Field(
        default=None, gt=0, description="Maximum cumulative requests allowed"
    )
    max_tokens: int | None = Field(
        default=None, gt=0, description="Maximum cumulative tokens allowed"
    )
    max_spend: float | None = Field(
        default=None, ge=0.0, description="Maximum total spend in budget currency"
    )


class AIBudgetConfig(BaseModel):
    """Provider-agnostic spend and usage budget configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_total_spend: float | None = Field(
        default=None, ge=0.0, description="Maximum aggregate spend across all AI calls"
    )
    max_total_requests: int | None = Field(
        default=None, gt=0, description="Maximum aggregate number of AI inference requests"
    )
    currency: str = Field(default="USD", min_length=1, description="Budget accounting currency")
    warn_spend_threshold_pct: float = Field(
        default=0.80,
        ge=0.0,
        le=1.0,
        description="Threshold percentage (0.0 - 1.0) to emit spend warning",
    )
    model_limits: dict[str, ModelUsageLimit] = Field(
        default_factory=dict, description="Optional per-model or per-provider usage limits"
    )


class SubsystemModelConfig(BaseModel):
    """Routing and inference configuration for a single AI subsystem."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(min_length=1, description="Configured AI provider identifier")
    model_id: str = Field(min_length=1, description="Configured model identifier within provider")
    temperature: float | None = Field(
        default=None, ge=0.0, le=2.0, description="Optional sampling temperature"
    )
    timeout_seconds: float = Field(
        default=30.0, gt=0.0, description="Inference timeout deadline in seconds"
    )
    max_retries: int = Field(
        default=2, ge=0, description="Maximum number of retry attempts on transient network error"
    )
    required_capabilities: set[AICapability] = Field(
        default_factory=set, description="Capabilities required for this subsystem assignment"
    )
    extra_params: dict[str, Any] = Field(
        default_factory=dict, description="Additional provider-specific parameters (non-secret)"
    )


class AISubsystemsConfig(BaseModel):
    """Independent model selection across all five functional AI subsystems."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    vision: SubsystemModelConfig = Field(
        description="Configuration for multimodal chart vision subsystem"
    )
    forecasting: SubsystemModelConfig = Field(
        description="Configuration for probabilistic time-series forecasting subsystem"
    )
    strategy_suggestor: SubsystemModelConfig = Field(
        description="Configuration for declarative strategy suggestion subsystem"
    )
    strategy_reviewer: SubsystemModelConfig = Field(
        description="Configuration for qualitative structural review subsystem"
    )
    ocr: SubsystemModelConfig = Field(
        description="Configuration for optical character recognition subsystem"
    )


class AIServiceConfig(BaseModel):
    """Root configuration for AI Advisory Services Layer."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    enabled: bool = Field(
        default=True, description="Global toggle for AI advisory features (offline when False)"
    )
    subsystems: AISubsystemsConfig = Field(
        description="Subsystem-specific provider and model configurations"
    )
    budget: AIBudgetConfig = Field(
        default_factory=AIBudgetConfig, description="Usage and spend budget configuration"
    )
