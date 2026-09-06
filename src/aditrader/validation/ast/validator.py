"""Static AST Validator evaluating Strategy DSL condition trees and leg contracts."""

from typing import Any, Literal

from pydantic import ValidationError

from aditrader.data.instruments.specs import is_futures_symbol
from aditrader.strategy.builder.schema import (
    ASTOperator,
    ConditionGroup,
    ConditionNode,
    StrategyDSL,
    StrategyLegDefinition,
)
from aditrader.validation.models import (
    GateSeverity,
    SampleSizeStatus,
    ValidationGateResult,
    ValidationResult,
    ValidationScope,
    ValidationStatus,
)

SUPPORTED_TIMEFRAMES = {
    "1s",
    "5s",
    "15s",
    "30s",
    "1m",
    "3m",
    "5m",
    "10m",
    "15m",
    "30m",
    "1h",
    "2h",
    "4h",
    "1d",
    "1w",
    "1m_month",
}


class ASTValidator:
    """Static declarative AST validator for Version 1.0 Strategy DSL trees."""

    @classmethod
    def validate(cls, strategy: StrategyDSL | dict[str, Any]) -> ValidationResult:
        """Validate strategy AST structure without executing code or querying brokers.

        Args:
            strategy: StrategyDSL object or raw JSON/dict document.

        Returns:
            ValidationResult with scope=STRUCTURAL and comprehensive diagnostics.
        """
        gate_results: list[ValidationGateResult] = []
        warnings: list[str] = []
        suggestions: list[str] = []

        # ----------------------------------------------------------------------
        # 1. Parse / Schema Conformance
        # ----------------------------------------------------------------------
        dsl: StrategyDSL
        if isinstance(strategy, dict):
            # Check schema version header
            schema_ver = strategy.get("schema_version")
            if schema_ver != "1.0":
                gate_results.append(
                    ValidationGateResult(
                        gate_name="SCHEMA_VERSION_CHECK",
                        passed=False,
                        severity=GateSeverity.HARD_FLOOR,
                        detail=f"Unsupported schema_version '{schema_ver}'. Expected '1.0'.",
                        observed_value=schema_ver,
                        threshold_value="1.0",
                    )
                )

            try:
                dsl = StrategyDSL.model_validate(strategy)
                gate_results.append(
                    ValidationGateResult(
                        gate_name="PYDANTIC_SCHEMA_PARSE",
                        passed=True,
                        severity=GateSeverity.HARD_FLOOR,
                        detail="Strategy document parsed successfully into StrategyDSL.",
                    )
                )
            except ValidationError as err:
                for error in err.errors():
                    loc = " -> ".join(str(x) for x in error["loc"])
                    msg = error["msg"]
                    gate_results.append(
                        ValidationGateResult(
                            gate_name=f"SCHEMA_SYNTAX_ERROR:{loc}",
                            passed=False,
                            severity=GateSeverity.HARD_FLOOR,
                            detail=f"Field '{loc}' validation failed: {msg}",
                            observed_value=error.get("input"),
                        )
                    )
                return cls._build_rejected_result(
                    strategy_name=strategy.get("name", "Unknown Strategy"),
                    underlying=strategy.get("underlying", "UNKNOWN"),
                    gate_results=gate_results,
                    warnings=warnings,
                    suggestions=["Fix JSON schema formatting errors before resubmission."],
                )
        else:
            dsl = strategy

        # ----------------------------------------------------------------------
        # 2. Required Core Attributes & Timeframe Validation
        # ----------------------------------------------------------------------
        tf = dsl.timeframe.lower().strip()
        if tf not in SUPPORTED_TIMEFRAMES:
            gate_results.append(
                ValidationGateResult(
                    gate_name="TIMEFRAME_SUPPORT_CHECK",
                    passed=False,
                    severity=GateSeverity.HARD_FLOOR,
                    detail=f"Timeframe '{dsl.timeframe}' is not recognized. Must be one of {sorted(SUPPORTED_TIMEFRAMES)}.",
                    observed_value=dsl.timeframe,
                )
            )
        else:
            gate_results.append(
                ValidationGateResult(
                    gate_name="TIMEFRAME_SUPPORT_CHECK",
                    passed=True,
                    severity=GateSeverity.HARD_FLOOR,
                    detail=f"Timeframe '{dsl.timeframe}' is supported.",
                    observed_value=dsl.timeframe,
                )
            )

        if not dsl.underlying or len(dsl.underlying.strip()) == 0:
            gate_results.append(
                ValidationGateResult(
                    gate_name="UNDERLYING_REQUIRED_CHECK",
                    passed=False,
                    severity=GateSeverity.HARD_FLOOR,
                    detail="Underlying market symbol is required.",
                )
            )

        # ----------------------------------------------------------------------
        # 3. Condition Tree Validation
        # ----------------------------------------------------------------------
        cls._validate_condition_group(
            group=dsl.entry_conditions,
            context_name="entry_conditions",
            gate_results=gate_results,
            warnings=warnings,
            suggestions=suggestions,
            dsl_target_regime=dsl.target_regime,
        )

        if dsl.exit_conditions is not None:
            cls._validate_condition_group(
                group=dsl.exit_conditions,
                context_name="exit_conditions",
                gate_results=gate_results,
                warnings=warnings,
                suggestions=suggestions,
                dsl_target_regime=dsl.target_regime,
            )

        # ----------------------------------------------------------------------
        # 4. Strategy Legs Contract Validation
        # ----------------------------------------------------------------------
        cls._validate_legs(
            legs=dsl.legs,
            gate_results=gate_results,
            warnings=warnings,
            suggestions=suggestions,
        )

        # ----------------------------------------------------------------------
        # 5. Composite Outcome Resolution
        # ----------------------------------------------------------------------
        failed_gates = [g.gate_name for g in gate_results if not g.passed]
        hard_floor_failures = [
            g for g in gate_results if not g.passed and g.severity == GateSeverity.HARD_FLOOR
        ]
        threshold_failures = [
            g for g in gate_results if not g.passed and g.severity == GateSeverity.THRESHOLD
        ]

        if hard_floor_failures:
            status = ValidationStatus.REJECTED
            score = max(
                0.0, 100.0 - (len(hard_floor_failures) * 35.0 + len(threshold_failures) * 15.0)
            )
        elif threshold_failures:
            status = ValidationStatus.NOT_RECOMMENDED
            score = max(30.0, 100.0 - (len(threshold_failures) * 20.0 + len(warnings) * 5.0))
        else:
            status = ValidationStatus.APPROVED
            score = max(70.0, 100.0 - (len(warnings) * 5.0))

        asset_class = cls._resolve_asset_class(dsl)

        return ValidationResult(
            strategy_name=dsl.name,
            schema_version=dsl.schema_version,
            underlying=dsl.underlying,
            asset_class=asset_class,
            validation_scope=ValidationScope.STRUCTURAL,
            status=status,
            validation_score=round(score, 1),
            sample_size_status=SampleSizeStatus.NOT_APPLICABLE,
            historical_vs_theoretical="THEORETICAL",
            metrics={
                "leg_count": len(dsl.legs),
                "has_exit_conditions": dsl.exit_conditions is not None,
                "timeframe": dsl.timeframe,
            },
            failed_gates=failed_gates,
            gate_results=gate_results,
            warnings=warnings,
            suggested_improvements=suggestions,
            policy_name="AST_Structural_Policy",
        )

    @classmethod
    def _validate_condition_group(
        cls,
        group: ConditionGroup,
        context_name: str,
        gate_results: list[ValidationGateResult],
        warnings: list[str],
        suggestions: list[str],
        dsl_target_regime: str | None,
    ) -> None:
        """Recursively validate condition group combinators and leaf operator nodes."""
        # Children cardinality
        if group.operator == ASTOperator.NOT:
            if len(group.conditions) != 1:
                gate_results.append(
                    ValidationGateResult(
                        gate_name=f"{context_name}.NOT_OPERATOR_CARDINALITY",
                        passed=False,
                        severity=GateSeverity.HARD_FLOOR,
                        detail=f"ConditionGroup with NOT operator must contain exactly 1 condition child. Found: {len(group.conditions)}.",
                        observed_value=len(group.conditions),
                        threshold_value=1,
                    )
                )
        else:
            if len(group.conditions) == 0:
                gate_results.append(
                    ValidationGateResult(
                        gate_name=f"{context_name}.EMPTY_GROUP_CHECK",
                        passed=False,
                        severity=GateSeverity.HARD_FLOOR,
                        detail=f"ConditionGroup '{context_name}' cannot be empty.",
                    )
                )

        # Child node inspection
        for idx, child in enumerate(group.conditions):
            child_ctx = f"{context_name}[{idx}]"
            if isinstance(child, ConditionGroup):
                cls._validate_condition_group(
                    group=child,
                    context_name=child_ctx,
                    gate_results=gate_results,
                    warnings=warnings,
                    suggestions=suggestions,
                    dsl_target_regime=dsl_target_regime,
                )
            elif isinstance(child, ConditionNode):
                cls._validate_condition_node(
                    node=child,
                    context_name=child_ctx,
                    gate_results=gate_results,
                    warnings=warnings,
                    suggestions=suggestions,
                    dsl_target_regime=dsl_target_regime,
                )

    @classmethod
    def _validate_condition_node(
        cls,
        node: ConditionNode,
        context_name: str,
        gate_results: list[ValidationGateResult],
        warnings: list[str],
        suggestions: list[str],
        dsl_target_regime: str | None,
    ) -> None:
        """Validate leaf condition node operators and required operand configurations."""
        # Within Range Operator
        if node.operator == ASTOperator.WITHIN_RANGE:
            if node.range_min is None or node.range_max is None:
                gate_results.append(
                    ValidationGateResult(
                        gate_name=f"{context_name}.WITHIN_RANGE_BOUNDS_REQUIRED",
                        passed=False,
                        severity=GateSeverity.HARD_FLOOR,
                        detail="WITHIN_RANGE operator requires both range_min and range_max to be set.",
                    )
                )
            elif (
                isinstance(node.range_min, (int, float))
                and isinstance(node.range_max, (int, float))
                and node.range_min >= node.range_max
            ):
                gate_results.append(
                    ValidationGateResult(
                        gate_name=f"{context_name}.WITHIN_RANGE_CONTRADICTORY_BOUNDS",
                        passed=False,
                        severity=GateSeverity.HARD_FLOOR,
                        detail=f"range_min ({node.range_min}) must be strictly less than range_max ({node.range_max}).",
                        observed_value=(node.range_min, node.range_max),
                    )
                )

        # Crosses Operators
        if (
            node.operator in (ASTOperator.CROSSES_ABOVE, ASTOperator.CROSSES_BELOW)
            and node.compare_to_field is None
            and node.compare_indicator is None
            and node.threshold is None
        ):
            gate_results.append(
                ValidationGateResult(
                    gate_name=f"{context_name}.CROSSOVER_TARGET_REQUIRED",
                    passed=False,
                    severity=GateSeverity.HARD_FLOOR,
                    detail=f"{node.operator} operator requires comparison target (compare_to_field/compare_indicator) or a threshold.",
                )
            )

        # Regime Matching
        if node.operator == ASTOperator.MATCHES_REGIME:
            effective_regime = node.target_regime or dsl_target_regime
            if not effective_regime:
                gate_results.append(
                    ValidationGateResult(
                        gate_name=f"{context_name}.REGIME_TARGET_REQUIRED",
                        passed=False,
                        severity=GateSeverity.HARD_FLOOR,
                        detail="MATCHES_REGIME operator requires a target_regime defined on the condition or the strategy root.",
                    )
                )

    @classmethod
    def _validate_legs(
        cls,
        legs: list[StrategyLegDefinition],
        gate_results: list[ValidationGateResult],
        warnings: list[str],
        suggestions: list[str],
    ) -> None:
        """Validate option leg configurations, strike bounds, and conflicting offset structures."""
        if not legs:
            return

        seen_legs: dict[tuple[str, int, int], StrategyLegDefinition] = {}

        for idx, leg in enumerate(legs):
            leg_ctx = f"legs[{idx}]"

            # Strike Offset Range Check
            if abs(leg.strike_offset) > 50:
                gate_results.append(
                    ValidationGateResult(
                        gate_name=f"{leg_ctx}.STRIKE_OFFSET_BOUNDS",
                        passed=False,
                        severity=GateSeverity.HARD_FLOOR,
                        detail=f"Absurd strike_offset {leg.strike_offset}. Must be within [-50, 50] steps of ATM.",
                        observed_value=leg.strike_offset,
                    )
                )
            elif abs(leg.strike_offset) > 20:
                warnings.append(
                    f"Leg {idx} uses deep OTM/ITM strike offset ({leg.strike_offset}). Ensure adequate liquidity in live trading."
                )

            # Quantity / Lots constraints
            if leg.lots < 1 or leg.lots > 100:
                gate_results.append(
                    ValidationGateResult(
                        gate_name=f"{leg_ctx}.LOTS_CONSTRAINT",
                        passed=False,
                        severity=GateSeverity.HARD_FLOOR,
                        detail=f"Leg lots ({leg.lots}) must be between 1 and 100.",
                        observed_value=leg.lots,
                    )
                )

            # Duplicate / Contradictory Legs Check
            leg_key = (leg.contract_type, leg.strike_offset, leg.expiry_offset)
            if leg_key in seen_legs:
                prior_leg = seen_legs[leg_key]
                if prior_leg.side != leg.side and prior_leg.lots == leg.lots:
                    gate_results.append(
                        ValidationGateResult(
                            gate_name="CONTRADICTORY_SELF_CANCELING_LEGS",
                            passed=False,
                            severity=GateSeverity.HARD_FLOOR,
                            detail=(
                                f"Leg {idx} ({leg.side} {leg.lots} lots {leg.contract_type} offset={leg.strike_offset}) "
                                f"directly cancels prior leg ({prior_leg.side} {prior_leg.lots} lots). "
                                "Opposing identical legs produce zero economic position."
                            ),
                        )
                    )
                elif prior_leg.side == leg.side:
                    warnings.append(
                        f"Leg {idx} duplicates existing leg with identical contract, strike offset, and expiry. Consider combining lots."
                    )
            else:
                seen_legs[leg_key] = leg

    @classmethod
    def _resolve_asset_class(cls, dsl: StrategyDSL) -> Literal["EQUITY", "FUTURES", "OPTIONS"]:
        """Categorize strategy asset class."""
        if dsl.legs:
            return "OPTIONS"
        if is_futures_symbol(dsl.underlying):
            return "FUTURES"
        return "EQUITY"

    @classmethod
    def _build_rejected_result(
        cls,
        strategy_name: str,
        underlying: str,
        gate_results: list[ValidationGateResult],
        warnings: list[str],
        suggestions: list[str],
    ) -> ValidationResult:
        """Helper to construct rejected result on initial JSON parse failure."""
        return ValidationResult(
            strategy_name=strategy_name,
            schema_version="1.0",
            underlying=underlying,
            asset_class="EQUITY",
            validation_scope=ValidationScope.STRUCTURAL,
            status=ValidationStatus.REJECTED,
            validation_score=0.0,
            sample_size_status=SampleSizeStatus.NOT_APPLICABLE,
            historical_vs_theoretical="THEORETICAL",
            failed_gates=[g.gate_name for g in gate_results if not g.passed],
            gate_results=gate_results,
            warnings=warnings,
            suggested_improvements=suggestions,
            policy_name="AST_Structural_Policy",
        )
