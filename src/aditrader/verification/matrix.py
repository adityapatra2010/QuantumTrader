"""Verification Matrix calculation engine applying strict fail-closed precedence.

Enforces polymorphic requirements across asset classes:
- Linear Equities / Futures: requires historical replay and empirical metrics.
- Multi-leg Options: requires theoretical Black-Scholes and payoff bounds (ADR 011);
  historical replay is NOT_APPLICABLE, achieving THEORETICAL_PASS when verified.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any

from aditrader.strategy.builder.schema import StrategyDSL
from aditrader.verification.models import (
    OverallVerificationStatus,
    PillarStatus,
    VerificationMatrix,
    VerificationPillarResult,
)


class VerificationMatrixEvaluator:
    """Evaluates multi-pillar verification states and computes composite institutional verdicts."""

    @classmethod
    def compute_matrix(
        cls,
        *,
        strategy_id: str,
        strategy_name: str,
        strategy_dsl: StrategyDSL | dict[str, Any],
        structural_pillar: VerificationPillarResult,
        data_integrity_pillar: VerificationPillarResult,
        known_answer_pillar: VerificationPillarResult,
        historical_replay_pillar: VerificationPillarResult,
        empirical_metrics_pillar: VerificationPillarResult,
        options_theoretical_pillar: VerificationPillarResult,
        reconciliation_pillar: VerificationPillarResult,
    ) -> VerificationMatrix:
        """Evaluate composite status across all pillars enforcing fail-closed precedence."""
        dsl = (
            strategy_dsl
            if isinstance(strategy_dsl, StrategyDSL)
            else StrategyDSL.model_validate(strategy_dsl)
        )
        is_options = bool(dsl.legs)

        # Canonical SHA-256 hash of strategy DSL
        dsl_json = json.dumps(dsl.model_dump(mode="json"), sort_keys=True)
        strategy_hash = hashlib.sha256(dsl_json.encode("utf-8")).hexdigest()

        # Determine required pillars based on strategy archetype (Polymorphism)
        if is_options:
            # Multi-leg options strategy
            required_pillars = [
                structural_pillar,
                known_answer_pillar,
                options_theoretical_pillar,
            ]
        else:
            # Linear equity or futures strategy
            required_pillars = [
                structural_pillar,
                known_answer_pillar,
                data_integrity_pillar,
                historical_replay_pillar,
                empirical_metrics_pillar,
                reconciliation_pillar,
            ]

        # Strict Precedence Order:
        # 1. Any required pillar BLOCKED -> BLOCKED
        # 2. Any required pillar FAIL -> FAIL
        # 3. Any required pillar STALE -> STALE
        # 4. Any required pillar NOT_RUN or INCOMPLETE -> INCOMPLETE
        # 5. All required pillars PASS -> THEORETICAL_PASS (options) or PASS (linear)

        if not required_pillars:
            overall_status = OverallVerificationStatus.INCOMPLETE
        elif any(p.status == PillarStatus.BLOCKED for p in required_pillars):
            overall_status = OverallVerificationStatus.BLOCKED
        elif any(p.status == PillarStatus.FAIL for p in required_pillars):
            overall_status = OverallVerificationStatus.FAIL
        elif any(p.status == PillarStatus.STALE for p in required_pillars):
            overall_status = OverallVerificationStatus.STALE
        elif any(
            p.status in (PillarStatus.NOT_RUN, PillarStatus.INCOMPLETE) for p in required_pillars
        ):
            overall_status = OverallVerificationStatus.INCOMPLETE
        elif all(p.status == PillarStatus.PASS for p in required_pillars):
            if is_options:
                overall_status = OverallVerificationStatus.THEORETICAL_PASS
            else:
                overall_status = OverallVerificationStatus.PASS
        else:
            # Strictly fail-closed fallback
            overall_status = OverallVerificationStatus.INCOMPLETE

        return VerificationMatrix(
            strategy_id=strategy_id,
            strategy_name=strategy_name,
            strategy_hash=strategy_hash,
            overall_status=overall_status,
            is_options=is_options,
            structural=structural_pillar,
            data_integrity=data_integrity_pillar,
            known_answer_tests=known_answer_pillar,
            historical_replay=historical_replay_pillar,
            empirical_metrics=empirical_metrics_pillar,
            options_theoretical=options_theoretical_pillar,
            reconciliation=reconciliation_pillar,
            evaluated_at=datetime.now(UTC),
        )
