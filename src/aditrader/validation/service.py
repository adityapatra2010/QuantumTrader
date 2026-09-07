"""Unified Strategy Validation Service orchestrating AST, Historical, and Theoretical Options paths."""

from typing import Any, Literal

from aditrader.backtesting.runner import BacktestResult
from aditrader.data.instruments.specs import is_futures_symbol
from aditrader.strategy.builder.schema import StrategyDSL
from aditrader.validation.ast.validator import ASTValidator
from aditrader.validation.institutional.historical import HistoricalStatisticalValidator
from aditrader.validation.institutional.options_payoff import OptionsTheoreticalValidator
from aditrader.validation.models import (
    GateSeverity,
    OptionsReplayReadiness,
    OptionsReplayStatus,
    ResearchAvailability,
    SampleSizeStatus,
    ValidationGateResult,
    ValidationResult,
    ValidationScope,
    ValidationStatus,
)
from aditrader.validation.policies import (
    ValidationPolicy,
    create_institutional_policy,
)


def check_research_availability(strategy: StrategyDSL) -> ResearchAvailability:
    """Check research and backtesting capabilities for a given strategy."""
    if strategy.legs:
        return ResearchAvailability(
            status="RESEARCH_UNAVAILABLE",
            permitted_alternatives=[
                "Analyze Payoff & Greeks",
                "Static Strategy Validation",
                "Forward Paper Trading",
            ],
            detail=(
                "Historical backtesting is not available for multi-leg option strategies. "
                "Simulating options requires dynamic IV surface and tick-level chain data (Phase 9 OptionsBacktestRunner). "
                "Permitted alternatives: Theoretical Payoff/Greeks Modeling or Live Forward Paper Trading."
            ),
        )

    return ResearchAvailability(
        status="AVAILABLE",
        permitted_alternatives=[
            "Historical Backtest",
            "Walk-Forward Analysis",
            "Out-of-Sample Validation",
            "Forward Paper Trading",
        ],
        detail="Linear asset (Equity/Futures) fully supported for point-in-time historical backtesting.",
    )


class StrategyValidationService:
    """Institutional Strategy Validation Service.

    Orchestrates the three explicit validation paths:
    1. Static AST Structural Validation (ALL strategies)
    2. Historical Statistical Validation (EQUITIES and FUTURES only)
    3. Theoretical Payoff & Greek Risk Validation (OPTIONS only)
    """

    def __init__(self, default_policy: ValidationPolicy | None = None) -> None:
        self.policy = default_policy or create_institutional_policy()

    def validate(
        self,
        strategy: StrategyDSL | dict[str, Any],
        backtest_result: BacktestResult | None = None,
        policy: ValidationPolicy | None = None,
        *,
        spot_price: float = 24000.0,
        dte_days: float = 7.0,
        oos_result: BacktestResult | None = None,
        walk_forward_results: list[BacktestResult] | None = None,
        evaluation_time: Any | None = None,
        hierarchy: Any | None = None,
    ) -> ValidationResult:
        """Execute appropriate validation pipeline matching strategy asset class.

        Args:
            strategy: StrategyDSL instance or raw JSON/dict definition.
            backtest_result: Required for Equities/Futures historical statistical validation.
            policy: Optional ValidationPolicy override (defaults to Institutional).
            spot_price: Prevailing underlying spot price for theoretical option payoff analysis.
            dte_days: Days to expiry for theoretical option payoff analysis.
            oos_result: Optional Out-of-Sample BacktestResult for overfitting analysis.
            walk_forward_results: Optional list of window BacktestResults for parameter stability.
            evaluation_time: Optional datetime for deterministic options payoff calculations.
            hierarchy: Optional DerivativesHierarchy instance for exact strike steps and lot sizes.

        Returns:
            ValidationResult with explicit scope, metrics, and gate outcomes.
        """
        active_policy = policy or self.policy

        # Step 1: Static AST Validation
        ast_result = ASTValidator.validate(strategy)
        if ast_result.status == ValidationStatus.REJECTED:
            return ast_result

        dsl = (
            strategy if isinstance(strategy, StrategyDSL) else StrategyDSL.model_validate(strategy)
        )

        # Step 2: Route by Strategy Type
        if dsl.legs:
            # Options Derivative Strategy Path
            if backtest_result is not None:
                raise ValueError(
                    f"Option strategy '{dsl.name}' cannot accept a historical BacktestResult. "
                    "Options backtesting is not supported. Use theoretical payoff validation."
                )
            return OptionsTheoreticalValidator.validate(
                strategy=dsl,
                policy=active_policy,
                spot_price=spot_price,
                dte_days=dte_days,
                evaluation_time=evaluation_time,
                hierarchy=hierarchy,
            )
        else:
            # Linear Equities / Futures Historical Statistical Path
            if backtest_result is None:
                return ValidationResult(
                    strategy_name=dsl.name,
                    schema_version=dsl.schema_version,
                    underlying=dsl.underlying,
                    asset_class="FUTURES" if is_futures_symbol(dsl.underlying) else "EQUITY",
                    validation_scope=ValidationScope.HISTORICAL,
                    status=ValidationStatus.NOT_RECOMMENDED,
                    validation_score=ast_result.validation_score,
                    sample_size_status=SampleSizeStatus.NOT_APPLICABLE,
                    historical_vs_theoretical="HISTORICAL",
                    metrics={},
                    failed_gates=["MISSING_BACKTEST_RESULT"],
                    gate_results=[
                        ValidationGateResult(
                            gate_name="MISSING_BACKTEST_RESULT",
                            passed=False,
                            severity=GateSeverity.THRESHOLD,
                            detail="No BacktestResult provided. Strategy passed AST validation but lacks historical performance verification.",
                        )
                    ],
                    warnings=[
                        "BacktestResult missing. Historical statistical gates were not evaluated."
                    ],
                    suggested_improvements=[
                        "Execute BacktestRunner to generate historical performance metrics."
                    ],
                    policy_name=active_policy.policy_name,
                )

            return HistoricalStatisticalValidator.validate(
                strategy=dsl,
                result=backtest_result,
                policy=active_policy,
                oos_result=oos_result,
                walk_forward_results=walk_forward_results,
            )


def check_options_replay_readiness(
    strategy: StrategyDSL,
    chain_available: bool = False,
    is_intraday_data: bool = False,
) -> OptionsReplayReadiness:
    """Assess whether an options strategy can be replayed against available market data.

    Distinguishes:
    - REPLAYABLE: Options strategy with chain data having intraday timestamps and contract LTP.
    - STRUCTURALLY_VALID_NOT_REPLAYABLE: Valid strategy DSL and selectors, but market data is daily EOD quote archive or missing intraday granularity.
    - UNSUPPORTED: Strategy missing contract selectors/strikes or unhedged naked short gamma.
    """
    if not strategy.legs:
        return OptionsReplayReadiness(
            status=OptionsReplayStatus.UNSUPPORTED,
            has_option_legs=False,
            dynamic_selector_supported=True,
            strike_resolution="THEORETICAL_ONLY",
            selection_policy="N/A (Linear strategy)",
            data_source_requirement="None (Linear asset uses OHLCV candles)",
            reason="Strategy has no option legs.",
        )

    has_selector = any(leg.contract_selector is not None for leg in strategy.legs)
    strike_res: Literal["PRE_RESOLVED", "POINT_IN_TIME_DYNAMIC"] = (
        "POINT_IN_TIME_DYNAMIC" if has_selector else "PRE_RESOLVED"
    )

    # Extract semantic descriptions for diagnostic presentation
    opt_types = set()
    for leg in strategy.legs:
        t = leg.contract_type or (
            leg.contract_selector.option_type if leg.contract_selector else None
        )
        if t:
            opt_types.add(t)
    option_type_str = "/".join(sorted(opt_types)) if opt_types else "CE"

    bands_list: list[str] = []
    if strategy.premium_bands:
        for b in strategy.premium_bands:
            bands_list.append(f"{b.min_ltp:.2f}–{b.max_ltp:.2f}")

    short_leg = next(
        (
            leg_item
            for leg_item in strategy.legs
            if str(leg_item.side).upper() in ("SELL", "ORDERSIDE.SELL")
        ),
        None,
    )
    short_desc = None
    if short_leg:
        opt_t = short_leg.contract_type or (
            short_leg.contract_selector.option_type if short_leg.contract_selector else "CE"
        )
        short_desc = f"SELL {short_leg.lots} dynamically selected {opt_t}"

    hedge_leg = next(
        (
            leg_item
            for leg_item in strategy.legs
            if str(leg_item.side).upper() in ("BUY", "ORDERSIDE.BUY")
        ),
        None,
    )
    hedge_desc = None
    if hedge_leg:
        opt_t = hedge_leg.contract_type or (
            hedge_leg.contract_selector.option_type if hedge_leg.contract_selector else "CE"
        )
        tgt = (
            hedge_leg.contract_selector.target_ltp
            if hedge_leg.contract_selector and hedge_leg.contract_selector.target_ltp is not None
            else 5.0
        )
        hedge_desc = (
            f"BUY {hedge_leg.lots} dynamically selected {opt_t}\n"
            f"  Target premium: configurable around ₹{tgt:.0f}"
        )

    has_ts = any(leg_item.trailing_stop is not None for leg_item in strategy.legs)
    trailing_desc = "contract-specific premium ratchet" if has_ts else None

    if chain_available and is_intraday_data:
        return OptionsReplayReadiness(
            status=OptionsReplayStatus.REPLAYABLE,
            has_option_legs=True,
            dynamic_selector_supported=True,
            strike_resolution=strike_res,
            selection_policy="CLOSEST_PREMIUM with deterministic tie-breaker",
            data_source_requirement="Intraday option-chain feed with point-in-time quotes",
            reason="Intraday option-chain feed is available with genuine timestamps and contract identities.",
            underlying=strategy.underlying,
            option_type=option_type_str,
            premium_bands=bands_list,
            short_summary=short_desc,
            hedge_summary=hedge_desc,
            trailing_summary=trailing_desc,
        )

    if chain_available and not is_intraday_data:
        return OptionsReplayReadiness(
            status=OptionsReplayStatus.STRUCTURALLY_VALID_NOT_REPLAYABLE,
            has_option_legs=True,
            dynamic_selector_supported=True,
            strike_resolution=strike_res,
            selection_policy="CLOSEST_PREMIUM with deterministic tie-breaker",
            data_source_requirement="Intraday option-chain feed with point-in-time quotes",
            reason=(
                "Strategy is structurally valid with dynamic selectors, but provided market data is a daily EOD "
                "derivative quote archive lacking intraday bar/tick granularity for continuous execution."
            ),
            underlying=strategy.underlying,
            option_type=option_type_str,
            premium_bands=bands_list,
            short_summary=short_desc,
            hedge_summary=hedge_desc,
            trailing_summary=trailing_desc,
        )

    return OptionsReplayReadiness(
        status=OptionsReplayStatus.STRUCTURALLY_VALID_NOT_REPLAYABLE,
        has_option_legs=True,
        dynamic_selector_supported=True,
        strike_resolution=strike_res,
        selection_policy="CLOSEST_PREMIUM with deterministic tie-breaker",
        data_source_requirement="Point-in-time option chain snapshot feed",
        reason=(
            "Strategy structure and selectors are valid, but no active option-chain feed is currently attached. "
            "Replay requires a point-in-time option chain provider."
        ),
        underlying=strategy.underlying,
        option_type=option_type_str,
        premium_bands=bands_list,
        short_summary=short_desc,
        hedge_summary=hedge_desc,
        trailing_summary=trailing_desc,
    )
