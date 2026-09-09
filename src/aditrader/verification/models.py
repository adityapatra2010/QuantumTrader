"""Immutable domain models for calculation provenance and deterministic verification."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class PillarStatus(StrEnum):
    """Granular outcome status for an individual verification pillar."""

    NOT_RUN = "NOT_RUN"
    INCOMPLETE = "INCOMPLETE"
    PASS = "PASS"
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    STALE = "STALE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class OverallVerificationStatus(StrEnum):
    """Authoritative institutional strategy verification verdict."""

    NOT_RUN = "NOT_RUN"
    INCOMPLETE = "INCOMPLETE"
    PASS = "PASS"
    THEORETICAL_PASS = "THEORETICAL_PASS"  # Options strategies with verified theoretical payoffs
    FAIL = "FAIL"
    BLOCKED = "BLOCKED"
    STALE = "STALE"


class PillarType(StrEnum):
    """Categories of verification pillars."""

    STRUCTURAL = "STRUCTURAL"
    DATA_INTEGRITY = "DATA_INTEGRITY"
    KNOWN_ANSWER_TESTS = "KNOWN_ANSWER_TESTS"
    HISTORICAL_REPLAY = "HISTORICAL_REPLAY"
    EMPIRICAL_METRICS = "EMPIRICAL_METRICS"
    OPTIONS_THEORETICAL = "OPTIONS_THEORETICAL"
    RECONCILIATION = "RECONCILIATION"


class VerificationPillarResult(BaseModel):
    """Evaluation result for a single verification pillar."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    pillar_name: str = Field(..., description="Human readable pillar title")
    pillar_type: PillarType = Field(..., description="Classification of the pillar")
    status: PillarStatus = Field(..., description="Granular outcome status")
    score: float = Field(ge=0.0, le=100.0, default=0.0, description="Normalized score 0-100")
    details: str = Field(..., description="Concise explanation of the pillar evaluation")
    diagnostics: list[str] = Field(
        default_factory=list, description="Specific failure or warning diagnostics"
    )
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Evaluation timestamp"
    )


class VerificationMatrix(BaseModel):
    """Multi-pillar institutional verification matrix with fail-closed precedence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: str = Field(..., description="Strategy identifier")
    strategy_name: str = Field(..., description="Strategy name")
    strategy_hash: str = Field(..., description="SHA-256 digest of canonical strategy DSL")
    overall_status: OverallVerificationStatus = Field(
        ..., description="Authoritative composite verdict"
    )
    is_options: bool = Field(default=False, description="True if multi-leg options strategy")
    structural: VerificationPillarResult = Field(..., description="Static AST schema & rule checks")
    data_integrity: VerificationPillarResult = Field(
        ..., description="Input dataset hygiene & price envelope checks"
    )
    known_answer_tests: VerificationPillarResult = Field(
        ..., description="Deterministic mathematical KAT vectors"
    )
    historical_replay: VerificationPillarResult = Field(
        ..., description="Historical backtest execution"
    )
    empirical_metrics: VerificationPillarResult = Field(
        ..., description="Expectancy, drawdown, sample size gates"
    )
    options_theoretical: VerificationPillarResult = Field(
        ..., description="Black-Scholes payoff & Greek gates"
    )
    reconciliation: VerificationPillarResult = Field(
        ..., description="Balance sheet equity & cash invariant"
    )
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Timestamp of evaluation"
    )

    @property
    def is_fully_verified(self) -> bool:
        """True if strategy has cleared all required institutional bars."""
        return self.overall_status in (
            OverallVerificationStatus.PASS,
            OverallVerificationStatus.THEORETICAL_PASS,
        )

    def to_summary_dict(self) -> dict[str, Any]:
        """Serialize into clean summary dictionary for UI and API consumption."""
        return {
            "strategy_id": self.strategy_id,
            "strategy_name": self.strategy_name,
            "strategy_hash": self.strategy_hash,
            "overall_status": self.overall_status.value,
            "is_fully_verified": self.is_fully_verified,
            "is_options": self.is_options,
            "pillars": {
                "structural": {
                    "status": self.structural.status.value,
                    "details": self.structural.details,
                    "score": self.structural.score,
                },
                "data_integrity": {
                    "status": self.data_integrity.status.value,
                    "details": self.data_integrity.details,
                    "score": self.data_integrity.score,
                },
                "known_answer_tests": {
                    "status": self.known_answer_tests.status.value,
                    "details": self.known_answer_tests.details,
                    "score": self.known_answer_tests.score,
                },
                "historical_replay": {
                    "status": self.historical_replay.status.value,
                    "details": self.historical_replay.details,
                    "score": self.historical_replay.score,
                },
                "empirical_metrics": {
                    "status": self.empirical_metrics.status.value,
                    "details": self.empirical_metrics.details,
                    "score": self.empirical_metrics.score,
                },
                "options_theoretical": {
                    "status": self.options_theoretical.status.value,
                    "details": self.options_theoretical.details,
                    "score": self.options_theoretical.score,
                },
                "reconciliation": {
                    "status": self.reconciliation.status.value,
                    "details": self.reconciliation.details,
                    "score": self.reconciliation.score,
                },
            },
            "evaluated_at": self.evaluated_at.isoformat(),
        }


class CalculationStep(BaseModel):
    """Discrete mathematical calculation step in a provenance trace."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    step_index: int = Field(..., ge=1, description="Sequential 1-indexed step number")
    step_name: str = Field(..., description="Short identifier of the step")
    formula: str = Field(..., description="Mathematical formula applied")
    inputs: dict[str, Any] = Field(..., description="Exact inputs fed into the formula")
    output_value: Any = Field(..., description="Result of this calculation step")
    unit: str = Field(default="", description="Physical or currency unit (e.g. INR, %, pts)")
    explanation: str = Field(
        default="", description="Human-readable explanation of why this step occurs"
    )


class CalculationProvenance(BaseModel):
    """Full cryptographic calculation provenance audit trail."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    calculation_id: str = Field(..., description="Unique calculation identifier")
    target_metric: str = Field(
        ..., description="Metric or entity being calculated (e.g. Realized PnL, Expectancy)"
    )
    strategy_id: str = Field(..., description="Target strategy ID")
    strategy_version: str = Field(..., description="Version of the strategy")
    strategy_hash: str = Field(..., description="SHA-256 digest of strategy DSL")
    dataset_name: str | None = Field(default=None, description="Source dataset filename")
    dataset_hash: str | None = Field(default=None, description="SHA-256 digest of dataset bytes")
    engine_version: str = Field(default="1.0.0", description="AdiTrader engine version")
    assumptions: dict[str, Any] = Field(
        default_factory=dict, description="Simulation or calculation assumptions"
    )
    inputs: dict[str, Any] = Field(..., description="Raw inputs to the calculation")
    intermediate_steps: list[CalculationStep] = Field(
        default_factory=list, description="Chronological calculation steps"
    )
    final_value: Any = Field(..., description="Final verified calculated value")
    calculated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Calculation timestamp"
    )


class ReproducibilityComparison(BaseModel):
    """Side-by-side comparison between stored and freshly recalculated values."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    metric_name: str = Field(..., description="Name of the compared metric")
    stored_value: float | None = Field(default=None, description="Persisted historical value")
    fresh_value: float | None = Field(default=None, description="Freshly computed value")
    delta: float = Field(..., description="Fresh value minus Stored value")
    tolerance: float = Field(..., description="Maximum acceptable numerical divergence")
    is_reproduced: bool = Field(..., description="True if |delta| <= tolerance")
    details: str = Field(default="", description="Diagnostic details or mismatch notes")


class ReproducibilitySummary(BaseModel):
    """Aggregate reproducibility assessment for a backtest or session run."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    strategy_id: str = Field(..., description="Strategy identifier")
    overall_reproduced: bool = Field(
        ..., description="True if all checked metrics reproduced within tolerance"
    )
    mismatch_count: int = Field(
        default=0, ge=0, description="Number of metrics exceeding tolerance"
    )
    comparisons: list[ReproducibilityComparison] = Field(
        default_factory=list, description="Per-metric comparisons"
    )
    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Audit timestamp"
    )
    reason: str | None = Field(
        default=None, description="High-level reason if reproduction failed or blocked"
    )


class EvidenceBundle(BaseModel):
    """Structured institutional evidence dossier with SHA-256 tamper digest."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    bundle_id: str = Field(..., description="Unique evidence bundle identifier")
    strategy_id: str = Field(..., description="Evaluated strategy identifier")
    strategy_name: str = Field(..., description="Strategy name")
    strategy_hash: str = Field(..., description="SHA-256 digest of strategy DSL")
    dataset_name: str | None = Field(default=None, description="Evaluated dataset filename")
    dataset_hash: str | None = Field(default=None, description="SHA-256 digest of dataset")
    engine_version: str = Field(default="1.0.0", description="AdiTrader engine version")
    assumptions: dict[str, Any] = Field(
        default_factory=dict, description="Execution and fee assumptions"
    )
    verification_matrix: VerificationMatrix = Field(..., description="Granular verification matrix")
    overall_status: OverallVerificationStatus = Field(..., description="Authoritative verdict")
    kat_passed: int = Field(ge=0, description="Count of passed known-answer tests")
    kat_total: int = Field(ge=0, description="Total known-answer tests evaluated")
    reproducibility_summary: ReproducibilitySummary | None = Field(
        default=None, description="Reproducibility audit"
    )
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Generation timestamp"
    )
    tamper_hash: str = Field(..., description="Cryptographic SHA-256 digest over bundle payload")

    @staticmethod
    def _compute_digest_from_components(
        *,
        bundle_id: str,
        strategy_id: str,
        strategy_name: str,
        strategy_hash: str,
        dataset_name: str | None,
        dataset_hash: str | None,
        engine_version: str,
        overall_status: OverallVerificationStatus,
        kat_passed: int,
        kat_total: int,
        assumptions: dict[str, Any],
        verification_matrix: VerificationMatrix,
        reproducibility_summary: ReproducibilitySummary | None,
        generated_at: datetime,
    ) -> str:
        """Compute deterministic SHA-256 digest over the entire evidence bundle payload."""
        matrix_dict = verification_matrix.model_dump(mode="json")
        repro_dict = (
            reproducibility_summary.model_dump(mode="json")
            if reproducibility_summary is not None
            else None
        )
        ts_str = generated_at.astimezone(UTC).isoformat()
        canonical_payload = {
            "assumptions": assumptions,
            "bundle_id": bundle_id,
            "dataset_hash": dataset_hash,
            "dataset_name": dataset_name,
            "engine_version": engine_version,
            "generated_at": ts_str,
            "kat_passed": kat_passed,
            "kat_total": kat_total,
            "overall_status": overall_status.value,
            "reproducibility_summary": repro_dict,
            "strategy_hash": strategy_hash,
            "strategy_id": strategy_id,
            "strategy_name": strategy_name,
            "verification_matrix": matrix_dict,
        }
        raw_bytes = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return hashlib.sha256(raw_bytes).hexdigest()

    @classmethod
    def create(
        cls,
        *,
        bundle_id: str,
        strategy_id: str,
        strategy_name: str,
        strategy_hash: str,
        verification_matrix: VerificationMatrix,
        overall_status: OverallVerificationStatus,
        kat_passed: int,
        kat_total: int,
        dataset_name: str | None = None,
        dataset_hash: str | None = None,
        engine_version: str = "1.0.0",
        assumptions: dict[str, Any] | None = None,
        reproducibility_summary: ReproducibilitySummary | None = None,
        generated_at: datetime | None = None,
    ) -> EvidenceBundle:
        """Construct an EvidenceBundle and compute its canonical SHA-256 tamper digest."""
        gen_ts = generated_at or datetime.now(UTC)
        final_assumptions = assumptions or {}
        digest = cls._compute_digest_from_components(
            bundle_id=bundle_id,
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            strategy_hash=strategy_hash,
            dataset_name=dataset_name,
            dataset_hash=dataset_hash,
            engine_version=engine_version,
            overall_status=overall_status,
            kat_passed=kat_passed,
            kat_total=kat_total,
            assumptions=final_assumptions,
            verification_matrix=verification_matrix,
            reproducibility_summary=reproducibility_summary,
            generated_at=gen_ts,
        )
        return cls(
            bundle_id=bundle_id,
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            strategy_hash=strategy_hash,
            dataset_name=dataset_name,
            dataset_hash=dataset_hash,
            engine_version=engine_version,
            assumptions=final_assumptions,
            verification_matrix=verification_matrix,
            overall_status=overall_status,
            kat_passed=kat_passed,
            kat_total=kat_total,
            reproducibility_summary=reproducibility_summary,
            generated_at=gen_ts,
            tamper_hash=digest,
        )

    def compute_tamper_hash(self) -> str:
        """Compute the expected canonical SHA-256 digest of this bundle."""
        return self._compute_digest_from_components(
            bundle_id=self.bundle_id,
            strategy_id=self.strategy_id,
            strategy_name=self.strategy_name,
            strategy_hash=self.strategy_hash,
            dataset_name=self.dataset_name,
            dataset_hash=self.dataset_hash,
            engine_version=self.engine_version,
            overall_status=self.overall_status,
            kat_passed=self.kat_passed,
            kat_total=self.kat_total,
            assumptions=self.assumptions,
            verification_matrix=self.verification_matrix,
            reproducibility_summary=self.reproducibility_summary,
            generated_at=self.generated_at,
        )

    def verify_tamper_hash(self) -> bool:
        """Verify that tamper_hash matches the cryptographic digest of the complete bundle."""
        return self.tamper_hash == self.compute_tamper_hash()
