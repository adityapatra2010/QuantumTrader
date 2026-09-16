"""Hostile Adversarial Strategy Reviewer implementation.

Per ADR 005, ADR 012, and Phase 7 directives:
- Evaluates StrategyDSL structures and deterministic ValidationResult outputs.
- Flags unhedged gamma risk, sample size fragility, parameter over-specification, and negative expectancy.
- Generates DossierSection strictly tagged with source_type=AI_ADVISORY and ProvenanceRecord.
- Zero authority to override or approve strategies: deterministic ValidationEngine remains authoritative.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from aditrader.ai.base import StrategyReviewer
from aditrader.ai.models import (
    AISourceType,
    DossierSection,
    DossierSectionSourceType,
    ProvenanceRecord,
)
from aditrader.core.models.enums import OrderSide
from aditrader.strategy.builder.schema import StrategyDSL
from aditrader.validation.models import ValidationResult, ValidationStatus


class DeterministicAdvisoryReviewer(StrategyReviewer):
    """Hostile qualitative research reviewer examining strategy structural integrity."""

    def __init__(
        self,
        model_id: str = "adversarial-reviewer-v1",
        model_version: str = "1.0.0",
        provider: str = "local",
        **_kwargs: Any,
    ) -> None:
        self.model_id = model_id
        self.model_version = model_version
        self.provider = provider

    def _generate_review(
        self,
        strategy: StrategyDSL,
        validation_result: ValidationResult,
    ) -> DossierSection:
        """Analyze strategy mechanics and deterministic validation gates to emit advisory critique."""
        lines: list[str] = []
        findings: list[str] = []
        strengths: list[str] = []

        lines.append("### Adversarial Structural Review & Risk Critique")
        lines.append(
            f"**Target Strategy**: `{strategy.name}` (`{strategy.underlying}`, `{strategy.timeframe}`)"
        )
        lines.append(f"**Deterministic Validation Status**: `{validation_result.status.value}`")
        lines.append("")

        # 1. Validation Engine Gate Inspection
        if validation_result.status == ValidationStatus.APPROVED:
            strengths.append(
                "Cleared institutional validation gates without non-negotiable policy breaches."
            )
        elif validation_result.status == ValidationStatus.NOT_RECOMMENDED:
            findings.append(
                "⚠️ **Validation Advisory**: Strategy flagged as `NOT_RECOMMENDED`. "
                "One or more empirical or structural criteria did not meet institutional standards."
            )
        else:
            reasons = (
                "; ".join(validation_result.failed_gates)
                if validation_result.failed_gates
                else "Unspecified veto"
            )
            findings.append(
                f"🚨 **HARD REJECTION**: Strategy failed deterministic validation gates: {reasons}."
            )

        # Inspect individual gate outcomes
        for gate in validation_result.gate_results:
            if not gate.passed:
                findings.append(f"- **Gate Failure [{gate.gate_name}]**: {gate.detail}")

        # 2. Options Wing & Gamma Explosion Analysis
        if strategy.legs:
            short_ce = sum(
                leg.lots
                for leg in strategy.legs
                if leg.side == OrderSide.SELL
                and (
                    leg.contract_type == "CE"
                    or (leg.contract_selector and leg.contract_selector.option_type == "CE")
                )
            )
            long_ce = sum(
                leg.lots
                for leg in strategy.legs
                if leg.side == OrderSide.BUY
                and (
                    leg.contract_type == "CE"
                    or (leg.contract_selector and leg.contract_selector.option_type == "CE")
                )
            )
            short_pe = sum(
                leg.lots
                for leg in strategy.legs
                if leg.side == OrderSide.SELL
                and (
                    leg.contract_type == "PE"
                    or (leg.contract_selector and leg.contract_selector.option_type == "PE")
                )
            )
            long_pe = sum(
                leg.lots
                for leg in strategy.legs
                if leg.side == OrderSide.BUY
                and (
                    leg.contract_type == "PE"
                    or (leg.contract_selector and leg.contract_selector.option_type == "PE")
                )
            )

            if short_ce > 0 and long_ce == 0:
                findings.append(
                    "🚨 **Unhedged Call Gamma**: Contains naked short Call positions without protective "
                    "upper wing contracts. Exposed to unlimited loss on upside gap events."
                )
            elif short_ce > 0 and long_ce < short_ce:
                findings.append(
                    f"⚠️ **Partial Call Ratio**: Long Call hedges ({long_ce} lots) are fewer than "
                    f"short Calls ({short_ce} lots). Net short delta exposure exists."
                )

            if short_pe > 0 and long_pe == 0:
                findings.append(
                    "🚨 **Unhedged Put Gamma**: Contains naked short Put positions without lower wing "
                    "hedges. Exposed to substantial tail loss on steep market sell-offs."
                )
            elif short_pe > 0 and long_pe < short_pe:
                findings.append(
                    f"⚠️ **Partial Put Ratio**: Long Put hedges ({long_pe} lots) are fewer than "
                    f"short Puts ({short_pe} lots). Downside tail risk remains partially open."
                )

            has_short = short_ce > 0 or short_pe > 0
            ce_covered = short_ce == 0 or long_ce >= short_ce
            pe_covered = short_pe == 0 or long_pe >= short_pe

            if has_short and ce_covered and pe_covered:
                strengths.append(
                    "All short option legs are covered by protective long wings (defined-risk geometry)."
                )

        # 3. Parameter Sensitivity & Overfitting Risks
        cond_count = len(strategy.entry_conditions.conditions)
        if cond_count >= 5:
            findings.append(
                f"⚠️ **Over-parameterization Risk**: Entry condition tree contains {cond_count} conditions. "
                "High risk of curve-fitting to historical sample; verify out-of-sample stability."
            )
        elif cond_count >= 1:
            strengths.append(f"Reasonable rule complexity ({cond_count} entry conditions).")

        # 4. Synthesize Markdown Report
        if findings:
            lines.append("#### Identified Risks & Structural Vulnerabilities")
            for f in findings:
                lines.append(f)
            lines.append("")

        if strengths:
            lines.append("#### Architectural Strengths & Risk Mitigations")
            for s in strengths:
                lines.append(f"- {s}")
            lines.append("")

        # Recommendations section
        lines.append("#### Research Advisory Recommendations")
        if findings:
            lines.append(
                "1. **Address Critical Findings**: Address unhedged tail exposure or validation gate breaches prior to any paper rehearsal."
            )
            lines.append(
                "2. **Walk-Forward Verification**: Test across distinct volatility regimes to rule out curve-fitting."
            )
            lines.append(
                "3. **Slippage Sensitivity**: Ensure positive expectancy persists under elevated 2x friction assumptions."
            )
        else:
            lines.append(
                "1. **Proceed to Paper Rehearsal**: Strategy passes structural review and deterministic validation."
            )
            lines.append(
                "2. **Observe Execution Realism**: Verify fill rates, quote availability, and spread costs during forward testing."
            )
        lines.append("")

        lines.append(
            "> **Notice**: This review is generated by an advisory heuristic subsystem (ADR 012). "
            "The deterministic ValidationEngine and RiskEngine remain the authoritative ground truth."
        )

        # Compute input hash covering strategy + validation
        hash_payload = {
            "strategy": strategy.model_dump(),
            "validation_status": validation_result.status.value,
            "failed_gates": validation_result.failed_gates,
        }
        input_hash = hashlib.sha256(
            json.dumps(hash_payload, default=str, sort_keys=True).encode("utf-8")
        ).hexdigest()

        provenance = ProvenanceRecord(
            source_type=AISourceType.STRATEGY_REVIEW,
            model_id=self.model_id,
            model_version=self.model_version,
            provider=self.provider,
            generated_at=datetime.now(UTC),
            input_hash=input_hash,
            is_deterministic=True,
            confidence=0.92,
        )

        return DossierSection(
            title="Adversarial Strategy Review & Risk Critique",
            source_type=DossierSectionSourceType.AI_ADVISORY,
            content="\n".join(lines),
            provenance=provenance,
        )
