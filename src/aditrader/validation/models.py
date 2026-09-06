"""Domain models and outcome contracts for the Strategy Validation Engine."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ValidationStatus(StrEnum):
    """Institutional three-state validation outcome."""

    APPROVED = "APPROVED"
    NOT_RECOMMENDED = "NOT_RECOMMENDED"
    REJECTED = "REJECTED"


class ValidationScope(StrEnum):
    """Scope of evaluation applied to strategy."""

    HISTORICAL = "HISTORICAL"
    THEORETICAL = "THEORETICAL"
    STRUCTURAL = "STRUCTURAL"


class SampleSizeStatus(StrEnum):
    """Statistical sample size evaluation outcome."""

    SUFFICIENT_SAMPLE = "SUFFICIENT_SAMPLE"
    INSUFFICIENT_SAMPLE = "INSUFFICIENT_SAMPLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class GateSeverity(StrEnum):
    """Severity of a validation gate constraint."""

    HARD_FLOOR = "HARD_FLOOR"  # Invariant safety constraint; failure triggers immediate REJECTED
    THRESHOLD = "THRESHOLD"  # Policy threshold; failure triggers NOT_RECOMMENDED or REJECTED
    WARNING = "WARNING"  # Informational warning; penalizes score without hard rejection alone


class ValidationGateResult(BaseModel):
    """Outcome of a single validation rule evaluation."""

    model_config = ConfigDict(frozen=True)

    gate_name: str = Field(description="Identifier of the validation rule/gate")
    passed: bool = Field(description="True if the constraint was satisfied")
    severity: GateSeverity = Field(description="Enforcement severity tier")
    detail: str = Field(description="Human-readable explanation of result")
    observed_value: Any = Field(default=None, description="Measured strategy value")
    threshold_value: Any = Field(default=None, description="Policy threshold applied")


class ValidationResult(BaseModel):
    """Institutional Strategy Validation Dossier."""

    model_config = ConfigDict(frozen=True)

    strategy_id: str | None = Field(default=None, description="Optional unique strategy ID")
    strategy_name: str = Field(description="Name of the evaluated strategy")
    schema_version: str = Field(default="1.0", description="Strategy DSL schema version")
    underlying: str = Field(description="Underlying market symbol")
    asset_class: Literal["EQUITY", "FUTURES", "OPTIONS"] = Field(description="Asset classification")
    validation_scope: ValidationScope = Field(
        description="Evaluation method: HISTORICAL, THEORETICAL, or STRUCTURAL"
    )
    status: ValidationStatus = Field(
        description="Final verdict: APPROVED, NOT_RECOMMENDED, REJECTED"
    )
    validation_score: float = Field(
        ge=0.0, le=100.0, description="Normalized composite validation score (0 to 100)"
    )
    sample_size_status: SampleSizeStatus = Field(
        description="Distinguishes statistically sufficient samples from unrepresentative data"
    )
    historical_vs_theoretical: Literal["HISTORICAL", "THEORETICAL"] = Field(
        description="Explicit barrier preventing theoretical option metrics from masquerading as backtests"
    )
    metrics: dict[str, Any] = Field(
        default_factory=dict, description="Observed metric snapshot (strictly scope-isolated)"
    )
    failed_gates: list[str] = Field(
        default_factory=list, description="Names of all failed validation gates"
    )
    gate_results: list[ValidationGateResult] = Field(
        default_factory=list, description="Granular breakdown of all evaluated gates"
    )
    warnings: list[str] = Field(
        default_factory=list, description="Informational warnings and diagnostic flags"
    )
    suggested_improvements: list[str] = Field(
        default_factory=list, description="Actionable optimization suggestions"
    )
    policy_name: str = Field(
        default="Institutional", description="Name of active validation policy"
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Evaluation timestamp"
    )


class ResearchAvailability(BaseModel):
    """Explicit product integrity model for research capability discovery."""

    model_config = ConfigDict(frozen=True)

    status: Literal["AVAILABLE", "RESEARCH_UNAVAILABLE"]
    permitted_alternatives: list[str] = Field(default_factory=list)
    detail: str
