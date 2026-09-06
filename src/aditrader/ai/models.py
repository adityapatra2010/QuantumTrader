"""Phase 7 AI Subsystems & Advisory Pipeline Typed Contracts.

Per ADR 012:
- All AI-generated artifacts must carry an immutable ProvenanceRecord.
- AI advisory outputs are strictly non-authoritative proposals.
- Deterministic evidence and AI advisory text are explicitly segregated.
- Zero live execution or direct broker order routing.
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aditrader.strategy.builder.schema import StrategyDSL
from aditrader.validation.models import ValidationResult, ValidationStatus


class AISourceType(StrEnum):
    """Subsystem or model category generating an advisory artifact."""

    PROBABILISTIC_FORECAST = "PROBABILISTIC_FORECAST"
    MULTIMODAL_VISION = "MULTIMODAL_VISION"
    STRATEGY_SUGGESTION = "STRATEGY_SUGGESTION"
    STRATEGY_REVIEW = "STRATEGY_REVIEW"
    EDUCATIONAL_EXPLANATION = "EDUCATIONAL_EXPLANATION"


class ProvenanceRecord(BaseModel):
    """Cryptographic and metadata audit trail for AI-generated artifacts."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_type: AISourceType = Field(description="Subsystem or model category generating artifact")
    model_id: str = Field(
        min_length=1,
        description="Model identifier (e.g., 'chronos-t5-large', 'gemini-2.0-flash')",
    )
    model_version: str = Field(
        min_length=1, description="Version, commit, or checkpoint of the underlying model"
    )
    provider: str = Field(
        min_length=1,
        description="Host/provider infrastructure (e.g., 'local', 'google', 'amazon')",
    )
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        description="Timestamp of generation in UTC",
    )
    input_hash: str = Field(
        description="SHA-256 cryptographic hash (64-char hex) of input dataset, prompt bytes, or chart image",
    )
    seed: int | None = Field(
        default=None, description="Sampling seed for deterministic reproducibility if applicable"
    )
    is_deterministic: bool = Field(
        default=False,
        description=(
            "Implementation-trust assertion: True if identical input_hash and seed "
            "guarantee bit-for-bit reproducible output"
        ),
    )
    confidence: float | None = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Normalized model confidence score (0.0 to 1.0) or None if uncalibrated",
    )

    @field_validator("input_hash")
    @classmethod
    def validate_input_hash(cls, v: str) -> str:
        """Enforce strict 64-character SHA-256 hexadecimal digest format."""
        if len(v) != 64 or not all(c in "0123456789abcdefABCDEF" for c in v):
            raise ValueError("input_hash must be a valid 64-character SHA-256 hexadecimal digest")
        return v.lower()

    @field_validator("generated_at")
    @classmethod
    def validate_generated_at_tz(cls, v: datetime) -> datetime:
        """Ensure generated_at is timezone-aware and normalized to UTC."""
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("generated_at must be a timezone-aware datetime")
        return v.astimezone(UTC)


class ForecastResult(BaseModel):
    """Probabilistic time-series price trajectory forecast with lookahead prevention."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    cutoff_timestamp: datetime = Field(
        description="Point-in-time timestamp of the last closed bar ingested for the forecast"
    )
    horizon_bars: int = Field(gt=0, description="Number of forward bars predicted in the horizon")
    timestamps: list[datetime] = Field(
        description="Explicit future timestamps corresponding to predicted steps"
    )
    predicted_close: list[float] = Field(
        description="Expected median or point close prices across the horizon"
    )
    predicted_high: list[float] = Field(
        description="Upper confidence bound close prices across the horizon"
    )
    predicted_low: list[float] = Field(
        description="Lower confidence bound close prices across the horizon"
    )
    confidence_spread: float = Field(
        ge=0.0, description="Normalized forecast uncertainty / spread metric"
    )
    provenance: ProvenanceRecord = Field(description="Provenance audit record for this forecast")
    warning: str | None = Field(
        default=None, description="Optional diagnostic warning (e.g. regime shift, high variance)"
    )

    @field_validator("cutoff_timestamp")
    @classmethod
    def validate_cutoff_tz(cls, v: datetime) -> datetime:
        """Ensure cutoff_timestamp is timezone-aware and normalized to UTC."""
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("cutoff_timestamp must be a timezone-aware datetime")
        return v.astimezone(UTC)

    @field_validator("timestamps")
    @classmethod
    def validate_timestamps_tz_and_monotonic(cls, v: list[datetime]) -> list[datetime]:
        """Ensure all horizon timestamps are timezone-aware, normalized to UTC, and strictly monotonic."""
        normalized: list[datetime] = []
        for i, ts in enumerate(v):
            if ts.tzinfo is None or ts.tzinfo.utcoffset(ts) is None:
                raise ValueError(f"Forecast timestamp[{i}] must be a timezone-aware datetime")
            norm_ts = ts.astimezone(UTC)
            if normalized and norm_ts <= normalized[-1]:
                raise ValueError(
                    f"Forecast timestamps must be strictly monotonically increasing. "
                    f"timestamp[{i}] ({norm_ts}) <= timestamp[{i - 1}] ({normalized[-1]})"
                )
            normalized.append(norm_ts)
        return normalized

    @model_validator(mode="after")
    def validate_forecast_integrity(self) -> "ForecastResult":
        """Enforce strict lookahead prevention, array dimension equality, and price envelopes."""
        n = self.horizon_bars
        if not (
            len(self.timestamps)
            == len(self.predicted_close)
            == len(self.predicted_high)
            == len(self.predicted_low)
            == n
        ):
            raise ValueError(
                f"All forecast series (timestamps, close, high, low) must match horizon_bars ({n}). "
                f"Got: timestamps={len(self.timestamps)}, close={len(self.predicted_close)}, "
                f"high={len(self.predicted_high)}, low={len(self.predicted_low)}"
            )

        # Anti-lookahead constraint: all forecast targets must be strictly future relative to cutoff
        for i, ts in enumerate(self.timestamps):
            if ts <= self.cutoff_timestamp:
                raise ValueError(
                    f"Lookahead violation: Forecast timestamp[{i}] ({ts}) is not strictly after "
                    f"cutoff_timestamp ({self.cutoff_timestamp})"
                )

        # Numerical envelope validation
        for i in range(n):
            c = self.predicted_close[i]
            h = self.predicted_high[i]
            low = self.predicted_low[i]
            if c < 0.0 or h < 0.0 or low < 0.0:
                raise ValueError(f"Forecast prices must be non-negative at index {i}")
            if not (low <= c <= h):
                raise ValueError(
                    f"Price envelope breach at index {i}: low ({low}) <= close ({c}) <= high ({h}) violated"
                )

        return self


class PatternObservation(BaseModel):
    """Specific technical pattern observation extracted from chart imagery."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(
        min_length=1, description="Pattern name (e.g., 'Double Bottom', 'Bull Flag', 'Channel')"
    )
    confidence: float = Field(
        ge=0.0, le=1.0, description="Calibrated confidence score for the pattern"
    )
    description: str | None = Field(
        default=None, description="Optional context or coordinate explanation"
    )


class VisionResult(BaseModel):
    """Observable structural market features extracted from chart images by multimodal vision."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    trend: Literal["Bullish", "Bearish", "Neutral"] = Field(
        description="Identified macro directional bias"
    )
    support: list[float] = Field(
        default_factory=list, description="Extracted support price coordinates"
    )
    resistance: list[float] = Field(
        default_factory=list, description="Extracted resistance price coordinates"
    )
    patterns: list[PatternObservation] = Field(
        default_factory=list, description="Detected chart and candlestick structures"
    )
    reasoning: str = Field(description="Advisory technical reasoning explaining observed features")
    source_image_hash: str = Field(
        min_length=1,
        description=(
            "SHA-256 cryptographic hash (64-char hex) of the input chart image bytes. "
            "Ergonomic top-level mirror of provenance.input_hash."
        ),
    )
    is_empty: bool = Field(
        default=False,
        description="True if no reliable technical levels or patterns could be detected",
    )
    provenance: ProvenanceRecord = Field(
        description="Model provenance record for vision extraction"
    )

    @model_validator(mode="after")
    def validate_levels(self) -> "VisionResult":
        """Verify price levels are strictly positive."""
        for s in self.support:
            if s <= 0.0:
                raise ValueError(f"Support level must be positive, got {s}")
        for r in self.resistance:
            if r <= 0.0:
                raise ValueError(f"Resistance level must be positive, got {r}")
        return self


class BiasCfg(BaseModel):
    """Machine-readable, configurable selling vs buying bias for strategy suggestion."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    sell_pct: float = Field(
        default=0.60, ge=0.0, le=1.0, description="Premium selling strategy allocation fraction"
    )
    buy_pct: float = Field(
        default=0.40, ge=0.0, le=1.0, description="Premium buying strategy allocation fraction"
    )

    @model_validator(mode="after")
    def validate_bias_sum(self) -> "BiasCfg":
        """Assert allocation proportions sum exactly to 100% within floating tolerance."""
        if abs((self.sell_pct + self.buy_pct) - 1.0) > 1e-6:
            raise ValueError(
                f"sell_pct ({self.sell_pct}) and buy_pct ({self.buy_pct}) must sum to 1.0"
            )
        return self


class SuggestionResult(BaseModel):
    """Container for AI-suggested declarative strategy proposals."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_dsl: StrategyDSL = Field(
        description="Declarative AST representation of proposed strategy"
    )
    provenance: ProvenanceRecord = Field(
        description="Metadata describing originating AI model and inputs"
    )
    bias_applied: BiasCfg = Field(
        description="Exact bias configuration applied during proposal generation"
    )
    regime_context: str = Field(
        min_length=1, description="Market regime context justifying strategy choice"
    )
    rationale: str = Field(
        min_length=1, description="Quantitative rationale for selected structure and strikes"
    )
    validation_result: ValidationResult | None = Field(
        default=None,
        description=(
            "Deterministic validation outcome if evaluated. NOTE: Consumers must inspect "
            "validation_result.status (e.g. APPROVED) directly; presence does not imply approval."
        ),
    )
    is_validated: bool = Field(
        default=False,
        description=(
            "True only if evaluated and approved by StrategyValidationService "
            "(status == ValidationStatus.APPROVED). Remains False if REJECTED or NOT_RECOMMENDED."
        ),
    )

    @model_validator(mode="after")
    def validate_validation_status(self) -> "SuggestionResult":
        """Ensure is_validated is strictly coupled to an APPROVED ValidationResult."""
        if self.is_validated and (
            self.validation_result is None
            or self.validation_result.status != ValidationStatus.APPROVED
        ):
            raise ValueError(
                "is_validated can only be True if validation_result is present and status is APPROVED"
            )
        return self


class DossierSectionSourceType(StrEnum):
    """Categorization of evidence source in quantitative research dossiers."""

    DETERMINISTIC = "DETERMINISTIC"  # Verified backtest results, payoff math, ledger records
    AI_ADVISORY = "AI_ADVISORY"  # Probabilistic forecasts, LLM reviews, visual chart extractions
    STRUCTURAL = "STRUCTURAL"  # AST DSL definitions, leg configurations, rule trees
    METADATA = "METADATA"  # System environment, git commit, timestamps, run IDs


class DossierSection(BaseModel):
    """Single section within a quantitative research dossier."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    title: str = Field(min_length=1, description="Human-readable section title")
    source_type: DossierSectionSourceType = Field(description="Origin category of section contents")
    content: str = Field(
        description=(
            "Markdown-formatted section body. Providers must provide non-empty content "
            "and raise AIMalformedOutputError rather than returning empty placeholders."
        )
    )
    provenance: ProvenanceRecord | None = Field(
        default=None, description="Mandatory provenance record for AI_ADVISORY sections"
    )

    @model_validator(mode="after")
    def validate_provenance_requirement(self) -> "DossierSection":
        """Enforce provenance requirement for AI_ADVISORY sections."""
        if self.source_type == DossierSectionSourceType.AI_ADVISORY and self.provenance is None:
            raise ValueError(
                "Sections with source_type AI_ADVISORY must include a ProvenanceRecord"
            )
        return self


class ResearchDossier(BaseModel):
    """Institutional Quantitative Research Dossier."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dossier_id: str = Field(min_length=1, description="Unique identifier for the research dossier")
    strategy_name: str = Field(min_length=1, description="Name of the researched strategy")
    strategy_id: str | None = Field(default=None, description="Optional unique strategy ID")
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Generation timestamp (UTC)"
    )
    sections: list[DossierSection] = Field(
        min_length=1, description="Ordered sections of the dossier"
    )
    validation_result: ValidationResult | None = Field(
        default=None, description="Authoritative validation dossier if evaluated"
    )
    disclaimer: str = Field(
        default=(
            "Advisory Notice: Sections tagged AI_ADVISORY contain synthetic model outputs, forecasts, "
            "and hypotheses. They do not constitute empirical historical proof, guaranteed performance, "
            "or financial advice. Deterministic validation gates remain the authoritative ground truth."
        ),
        description="Institutional compliance and non-advice disclaimer",
    )

    @field_validator("generated_at")
    @classmethod
    def validate_dossier_generated_at_tz(cls, v: datetime) -> datetime:
        """Ensure dossier generated_at is timezone-aware and normalized to UTC."""
        if v.tzinfo is None or v.tzinfo.utcoffset(v) is None:
            raise ValueError("generated_at must be a timezone-aware datetime")
        return v.astimezone(UTC)
