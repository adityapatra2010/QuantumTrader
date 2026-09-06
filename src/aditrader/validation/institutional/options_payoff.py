"""Theoretical payoff and Greek risk validation engine for multi-leg option strategies."""

from datetime import UTC, datetime, timedelta
from typing import Any

from aditrader.core.models.enums import OrderSide
from aditrader.data.instruments.specs import resolve_contract_specs
from aditrader.options.iv import black_scholes_price
from aditrader.options.models import OptionLeg, OptionStrategy
from aditrader.options.payoff import calculate_strategy_payoff
from aditrader.strategy.builder.schema import StrategyDSL, StrategyLegDefinition
from aditrader.strategy.library.dna import profile_strategy_dna
from aditrader.strategy.library.models import GammaRisk
from aditrader.validation.models import (
    GateSeverity,
    SampleSizeStatus,
    ValidationGateResult,
    ValidationResult,
    ValidationScope,
    ValidationStatus,
)
from aditrader.validation.policies import ValidationPolicy, create_institutional_policy


class OptionsTheoreticalValidator:
    """Theoretical payoff and risk boundary validator for options derivatives.

    Strict Architectural Constraint:
    Evaluates only mathematical payoff boundaries, risk-reward ratios, and Greek exposures.
    NEVER emits historical statistical metrics (expectancy, Sharpe, win rate) for options.
    """

    @classmethod
    def _verify_structural_wings(cls, legs: list[StrategyLegDefinition]) -> tuple[bool, str]:
        """Algebraically verify that all short options are covered by protective long wings."""
        short_calls = [
            leg for leg in legs if leg.contract_type == "CE" and leg.side == OrderSide.SELL
        ]
        long_calls = [
            leg for leg in legs if leg.contract_type == "CE" and leg.side == OrderSide.BUY
        ]
        short_puts = [
            leg for leg in legs if leg.contract_type == "PE" and leg.side == OrderSide.SELL
        ]
        long_puts = [leg for leg in legs if leg.contract_type == "PE" and leg.side == OrderSide.BUY]

        # 1. Check Short Calls
        total_short_call_lots = sum(leg.lots for leg in short_calls)
        total_long_call_lots = sum(leg.lots for leg in long_calls)
        if total_short_call_lots > 0 and total_long_call_lots < total_short_call_lots:
            return (
                False,
                f"Unhedged short calls: {total_short_call_lots} short lots vs {total_long_call_lots} long protective lots",
            )

        # 2. Check Short Puts
        total_short_put_lots = sum(leg.lots for leg in short_puts)
        total_long_put_lots = sum(leg.lots for leg in long_puts)
        if total_short_put_lots > 0 and total_long_put_lots < total_short_put_lots:
            return (
                False,
                f"Unhedged short puts: {total_short_put_lots} short lots vs {total_long_put_lots} long protective lots",
            )

        return True, "All short legs structurally hedged"

    @classmethod
    def validate(
        cls,
        strategy: StrategyDSL,
        policy: ValidationPolicy | None = None,
        *,
        spot_price: float = 24000.0,
        volatility: float = 0.18,
        dte_days: float = 7.0,
        evaluation_time: datetime | None = None,
        hierarchy: Any | None = None,
    ) -> ValidationResult:
        """Validate options strategy structure against theoretical risk policies."""
        active_policy = policy or create_institutional_policy()

        if not strategy.legs:
            raise ValueError(
                f"Strategy '{strategy.name}' has no option legs. "
                "OptionsTheoreticalValidator requires a multi-leg options strategy. "
                "Use HistoricalStatisticalValidator for linear assets (Equities/Futures)."
            )

        gate_results: list[ValidationGateResult] = []
        warnings: list[str] = []
        suggestions: list[str] = []

        # ----------------------------------------------------------------------
        # 1. Profile Strategy DNA (Greeks & Regimes)
        # ----------------------------------------------------------------------
        dna = profile_strategy_dna(strategy)

        # ----------------------------------------------------------------------
        # 2. Materialize Option Legs for Theoretical Payoff Analysis
        # ----------------------------------------------------------------------
        step, lot_size = resolve_contract_specs(
            underlying=strategy.underlying,
            spot_price=spot_price,
            hierarchy=hierarchy,
        )
        atm_strike = round(spot_price / step) * step

        concrete_legs: list[OptionLeg] = []
        t_years = max(1e-4, dte_days / 365.0)
        now_dt = evaluation_time if evaluation_time is not None else datetime.now(UTC)
        expiry_dt = now_dt + timedelta(days=dte_days)

        for leg in strategy.legs:
            leg_strike = atm_strike + float(leg.strike_offset) * step
            side = leg.side

            # Calculate Black-Scholes theoretical entry premium
            premium = black_scholes_price(
                spot=spot_price,
                strike=leg_strike,
                time_to_expiry=t_years,
                volatility=volatility,
                option_type=leg.contract_type,
            )
            total_qty = leg.lots * lot_size

            concrete_legs.append(
                OptionLeg(
                    underlying=strategy.underlying,
                    expiry=expiry_dt,
                    strike=leg_strike,
                    option_type=leg.contract_type,
                    side=side,
                    qty=total_qty,
                    entry_price=round(premium, 2),
                    lot_size=lot_size,
                )
            )

        opt_strategy = OptionStrategy(
            id=f"THEO-{strategy.name}",
            name=strategy.name,
            legs=concrete_legs,
        )

        # Evaluate payoff curve over wide spot range (+/- 15%)
        lower_bound = round(spot_price * 0.85, 0)
        upper_bound = round(spot_price * 1.15, 0)
        step_eval = step / 2.0
        n_points = int((upper_bound - lower_bound) / step_eval) + 1
        price_range = [round(lower_bound + i * step_eval, 2) for i in range(n_points)]

        _, summary = calculate_strategy_payoff(
            strategy=opt_strategy,
            underlying_price_range=price_range,
            dte_slices=[int(dte_days), max(1, int(dte_days // 2)), 1],
            volatility=volatility,
        )

        structurally_hedged, wing_reason = cls._verify_structural_wings(strategy.legs)
        is_defined_risk = (summary.max_loss is not None) and structurally_hedged

        # ----------------------------------------------------------------------
        # 3. Gate: Defined Risk vs. Unbounded Loss Exposure
        # ----------------------------------------------------------------------
        if not is_defined_risk:
            severity = (
                GateSeverity.HARD_FLOOR
                if active_policy.require_defined_risk_for_options
                else GateSeverity.WARNING
            )
            detail_msg = (
                f"Strategy exhibits theoretical unbounded/undefined maximum loss: {wing_reason}."
                if not structurally_hedged
                else "Strategy exhibits theoretical unbounded/undefined maximum loss. "
                "Short wings are exposed without protective long hedging."
            )
            gate_results.append(
                ValidationGateResult(
                    gate_name="DEFINED_RISK_ARCHITECTURE",
                    passed=not active_policy.require_defined_risk_for_options,
                    severity=severity,
                    detail=detail_msg,
                    observed_value=False,
                    threshold_value=True,
                )
            )
            warnings.append("Strategy carries undefined tail risk (unbounded maximum loss).")
            suggestions.append("Add protective OTM wings to convert into a defined-risk spread.")
        else:
            gate_results.append(
                ValidationGateResult(
                    gate_name="DEFINED_RISK_ARCHITECTURE",
                    passed=True,
                    severity=GateSeverity.HARD_FLOOR,
                    detail=f"Strategy has strictly defined maximum loss (Max Loss: ₹{abs(summary.max_loss or 0.0):,.2f}).",
                    observed_value=True,
                    threshold_value=True,
                )
            )

        # ----------------------------------------------------------------------
        # 4. Gate: Unhedged Expiry Gamma Explosion Protection
        # ----------------------------------------------------------------------
        if active_policy.ban_naked_short_options_near_expiry and dna.gamma_risk == GammaRisk.HIGH:
            gate_results.append(
                ValidationGateResult(
                    gate_name="EXPIRY_NAKED_GAMMA_VETO",
                    passed=False,
                    severity=GateSeverity.HARD_FLOOR,
                    detail=(
                        f"Unhedged short gamma risk is {dna.gamma_risk.value}. "
                        "Selling naked short options near expiry triggers catastrophic convexity."
                    ),
                    observed_value=dna.gamma_risk.value,
                    threshold_value=GammaRisk.MODERATE.value,
                )
            )
            suggestions.append(
                "Hedge short options with long contracts to mitigate tail gamma explosion."
            )
        else:
            gate_results.append(
                ValidationGateResult(
                    gate_name="EXPIRY_NAKED_GAMMA_VETO",
                    passed=True,
                    severity=GateSeverity.HARD_FLOOR,
                    detail=f"Gamma risk ({dna.gamma_risk.value}) satisfies institutional safety floor.",
                    observed_value=dna.gamma_risk.value,
                )
            )

        # ----------------------------------------------------------------------
        # 5. Gate: Risk/Reward Payoff Ratio
        # ----------------------------------------------------------------------
        if (
            summary.risk_reward_ratio is not None
            and active_policy.max_theoretical_risk_reward_ratio is not None
        ):
            # In PayoffSummary, risk_reward_ratio is max_profit / max_loss.
            # Convert to loss / profit ratio (risk per unit reward)
            loss_to_reward = (
                (1.0 / summary.risk_reward_ratio) if summary.risk_reward_ratio > 0 else 999.0
            )
            if loss_to_reward > active_policy.max_theoretical_risk_reward_ratio:
                gate_results.append(
                    ValidationGateResult(
                        gate_name="THEORETICAL_RISK_REWARD_RATIO",
                        passed=False,
                        severity=GateSeverity.THRESHOLD,
                        detail=(
                            f"Theoretical risk/reward ratio ({loss_to_reward:.2f}) "
                            f"exceeds policy ceiling ({active_policy.max_theoretical_risk_reward_ratio:.2f})."
                        ),
                        observed_value=round(loss_to_reward, 2),
                        threshold_value=active_policy.max_theoretical_risk_reward_ratio,
                    )
                )
                suggestions.append(
                    "Widen credit spread strikes or adjust wing widths to improve risk/reward."
                )
            else:
                gate_results.append(
                    ValidationGateResult(
                        gate_name="THEORETICAL_RISK_REWARD_RATIO",
                        passed=True,
                        severity=GateSeverity.THRESHOLD,
                        detail=f"Risk/reward ratio ({loss_to_reward:.2f}) is acceptable.",
                        observed_value=round(loss_to_reward, 2),
                        threshold_value=active_policy.max_theoretical_risk_reward_ratio,
                    )
                )

        # ----------------------------------------------------------------------
        # 6. Gate: Breakeven Bounds Corridor
        # ----------------------------------------------------------------------
        if summary.breakevens:
            be_str = ", ".join(f"₹{b:,.1f}" for b in summary.breakevens)
            gate_results.append(
                ValidationGateResult(
                    gate_name="BREAKEVEN_CORRIDOR_CHECK",
                    passed=True,
                    severity=GateSeverity.THRESHOLD,
                    detail=f"Breakeven bounds resolved at: {be_str}.",
                    observed_value=summary.breakevens,
                )
            )
        else:
            warnings.append("No breakeven points found within +/- 15% underlying price spectrum.")

        # ----------------------------------------------------------------------
        # 7. Score & Outcome Determination
        # ----------------------------------------------------------------------
        score = 0.0
        if is_defined_risk:
            score += 40.0
        if dna.gamma_risk in (GammaRisk.LOW, GammaRisk.MODERATE):
            score += 30.0
        if summary.risk_reward_ratio is not None:
            score += 20.0
        if summary.breakevens:
            score += 10.0

        failed_gates = [g.gate_name for g in gate_results if not g.passed]
        hard_floor_failed = any(
            not g.passed and g.severity == GateSeverity.HARD_FLOOR for g in gate_results
        )
        threshold_failed = any(
            not g.passed and g.severity == GateSeverity.THRESHOLD for g in gate_results
        )

        if hard_floor_failed:
            status = ValidationStatus.REJECTED
            score = min(score, 20.0)
        elif threshold_failed:
            if active_policy.reject_on_threshold_breach:
                status = ValidationStatus.REJECTED
            else:
                status = ValidationStatus.NOT_RECOMMENDED
        else:
            status = ValidationStatus.APPROVED

        return ValidationResult(
            strategy_name=strategy.name,
            schema_version=strategy.schema_version,
            underlying=strategy.underlying,
            asset_class="OPTIONS",
            validation_scope=ValidationScope.THEORETICAL,
            status=status,
            validation_score=round(score, 1),
            sample_size_status=SampleSizeStatus.NOT_APPLICABLE,
            historical_vs_theoretical="THEORETICAL",
            metrics={
                "is_defined_risk": is_defined_risk,
                "max_profit": summary.max_profit,
                "max_loss": summary.max_loss,
                "risk_reward_ratio": summary.risk_reward_ratio,
                "net_debit_credit": summary.net_debit_credit,
                "breakevens": summary.breakevens,
                "directionality": dna.directionality.value,
                "gamma_risk": dna.gamma_risk.value,
                "theta_exposure": dna.theta_exposure.value,
                "vega_exposure": dna.vega_exposure.value,
                "margin_efficiency": dna.margin_efficiency.value,
            },
            failed_gates=failed_gates,
            gate_results=gate_results,
            warnings=warnings,
            suggested_improvements=suggestions,
            policy_name=active_policy.policy_name,
        )
