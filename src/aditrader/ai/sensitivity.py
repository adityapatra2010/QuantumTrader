"""Parameter Sensitivity and Robustness Research Engine.

Per ADR 011, ADR 012, and Phase 7 directives:
- Deterministic parameter grid evaluation across volatility shifts (IV), slippage friction, and wings.
- Quantifies strategy fragility vs stability without fabricated numbers.
- Emits structured SensitivityGridResult and DossierSection categorized strictly as DETERMINISTIC.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from aditrader.ai.models import (
    DossierSection,
    DossierSectionSourceType,
)
from aditrader.core.models.enums import OrderSide
from aditrader.data.instruments.specs import resolve_contract_specs
from aditrader.options.greeks import calculate_greeks
from aditrader.options.iv import black_scholes_price
from aditrader.options.models import OptionLeg, OptionStrategy
from aditrader.options.payoff import calculate_strategy_payoff
from aditrader.strategy.builder.schema import StrategyDSL


class SensitivityPoint(BaseModel):
    """Single evaluated point in a parameter sensitivity grid."""

    model_config = ConfigDict(frozen=True)

    parameter_value: float | str = Field(description="Evaluated parameter value or shift")
    max_loss: float = Field(description="Maximum theoretical loss at this parameter setting")
    max_profit: float = Field(description="Maximum theoretical profit at this parameter setting")
    net_delta: float = Field(description="Aggregate net portfolio delta")
    net_gamma: float = Field(description="Aggregate net portfolio gamma")
    notes: str = Field(default="", description="Observation notes for this grid point")


class SensitivityGridResult(BaseModel):
    """Structured output of deterministic parameter sensitivity research."""

    model_config = ConfigDict(frozen=True)

    strategy_name: str = Field(description="Evaluated strategy name")
    parameter_name: str = Field(description="Name of varied parameter (e.g. 'iv_shift_pct')")
    baseline_value: float | str = Field(description="Baseline reference parameter value")
    grid_points: list[SensitivityPoint] = Field(description="Evaluated points across the grid")
    stability_verdict: Literal["STABLE", "FRAGILE", "DEGRADED"] = Field(
        description="Robustness classification based on metric variance across grid"
    )
    fragile_zones: list[str] = Field(
        default_factory=list, description="Zones where risk parameters breach safety margins"
    )


class ParameterSensitivityEngine:
    """Evaluates strategy stability across parameter variation grids."""

    def __init__(self) -> None:
        pass

    def evaluate_options_iv_sensitivity(
        self,
        strategy: StrategyDSL,
        spot_price: float = 24000.0,
        baseline_iv: float = 0.15,
        iv_shifts: list[float] | None = None,
        dte_days: float = 5.0,
    ) -> SensitivityGridResult:
        """Evaluate multi-leg option strategy sensitivity to implied volatility (IV) shifts.

        Args:
            strategy: Declarative StrategyDSL with option legs.
            spot_price: Prevailing reference spot price.
            baseline_iv: Base implied volatility fraction (e.g. 0.15 = 15%).
            iv_shifts: Percentage shifts in IV to evaluate (e.g. [-0.05, -0.02, 0.0, +0.02, +0.05]).
            dte_days: Days to expiry for valuation.
        """
        shifts = iv_shifts or [-0.05, -0.02, 0.0, 0.02, 0.05]
        grid_points: list[SensitivityPoint] = []
        fragile_zones: list[str] = []

        # If no legs, emit dummy baseline
        if not strategy.legs:
            return SensitivityGridResult(
                strategy_name=strategy.name,
                parameter_name="iv_shift_pct",
                baseline_value=f"{baseline_iv:.1%}",
                grid_points=[
                    SensitivityPoint(
                        parameter_value="0.0%",
                        max_loss=0.0,
                        max_profit=0.0,
                        net_delta=1.0,
                        net_gamma=0.0,
                        notes="Linear spot/futures strategy; zero option IV sensitivity.",
                    )
                ],
                stability_verdict="STABLE",
            )

        step, lot_size = resolve_contract_specs(
            underlying=strategy.underlying,
            spot_price=spot_price,
        )
        atm_strike = round(spot_price / step) * step
        t_years = max(1e-4, dte_days / 365.0)
        now_dt = datetime.now(UTC)
        expiry_dt = now_dt + timedelta(days=dte_days)

        # Pre-resolve strikes for all legs
        resolved_legs_info: list[tuple[float, Literal["CE", "PE"], OrderSide, int]] = []
        for leg in strategy.legs:
            raw_opt = (
                leg.contract_type
                or (leg.contract_selector.option_type if leg.contract_selector else "CE")
                or "CE"
            )
            opt_type: Literal["CE", "PE"] = "PE" if str(raw_opt).upper() == "PE" else "CE"
            side = (
                leg.side
                if isinstance(leg.side, OrderSide)
                else (
                    OrderSide.SELL
                    if str(leg.side).upper() in ("SELL", "ORDERSIDE.SELL")
                    else OrderSide.BUY
                )
            )

            if leg.strike_offset is not None:
                leg_strike = atm_strike + float(leg.strike_offset) * step
            elif leg.contract_selector is not None:
                sel = leg.contract_selector
                target_p = sel.target_ltp
                if target_p is None and sel.min_ltp is not None and sel.max_ltp is not None:
                    target_p = (sel.min_ltp + sel.max_ltp) / 2.0
                elif target_p is None and strategy.premium_bands:
                    target_p = (
                        strategy.premium_bands[0].min_ltp + strategy.premium_bands[0].max_ltp
                    ) / 2.0
                elif target_p is None:
                    target_p = 50.0

                best_strike = atm_strike
                best_diff = float("inf")
                for offset in range(-50, 51):
                    cand_k = atm_strike + offset * step
                    if cand_k <= 0:
                        continue
                    p = black_scholes_price(
                        spot=spot_price,
                        strike=cand_k,
                        time_to_expiry=t_years,
                        volatility=baseline_iv,
                        option_type=opt_type,
                    )
                    diff = abs(p - target_p)
                    if diff < best_diff:
                        best_diff = diff
                        best_strike = cand_k
                leg_strike = best_strike
            else:
                leg_strike = atm_strike

            leg_strike = max(step, leg_strike)
            resolved_legs_info.append((leg_strike, opt_type, side, leg.lots))

        # Payoff evaluation spot spectrum (+/- 15%)
        lower_bound = round(spot_price * 0.85, 0)
        upper_bound = round(spot_price * 1.15, 0)
        step_eval = step / 2.0
        n_points = int((upper_bound - lower_bound) / step_eval) + 1
        price_range = [round(lower_bound + i * step_eval, 2) for i in range(n_points)]

        for shift in shifts:
            test_iv = max(0.01, baseline_iv + shift)
            shift_pct_str = f"{shift * 100:+.1f}%"

            total_delta = 0.0
            total_gamma = 0.0
            concrete_legs: list[OptionLeg] = []

            for leg_strike, opt_type, side, lots in resolved_legs_info:
                prem = black_scholes_price(
                    spot=spot_price,
                    strike=leg_strike,
                    time_to_expiry=t_years,
                    volatility=test_iv,
                    option_type=opt_type,
                )
                greek = calculate_greeks(
                    spot=spot_price,
                    strike=leg_strike,
                    time_to_expiry=t_years,
                    volatility=test_iv,
                    option_type=opt_type,
                )

                qty_multiplier = lots * (1 if side == OrderSide.BUY else -1)
                total_delta += greek.delta * qty_multiplier
                total_gamma += greek.gamma * qty_multiplier

                concrete_legs.append(
                    OptionLeg(
                        underlying=strategy.underlying,
                        expiry=expiry_dt,
                        strike=leg_strike,
                        option_type=opt_type,
                        side=side,
                        qty=lots * lot_size,
                        entry_price=round(prem, 2),
                        lot_size=lot_size,
                    )
                )

            opt_strategy = OptionStrategy(
                id=f"SENS-{strategy.name}-{shift}",
                name=strategy.name,
                legs=concrete_legs,
            )

            _, summary = calculate_strategy_payoff(
                strategy=opt_strategy,
                underlying_price_range=price_range,
                dte_slices=[int(dte_days), 1],
                volatility=test_iv,
            )

            # Max loss and max profit from authentic payoff evaluation
            max_profit = summary.max_profit if summary.max_profit is not None else 0.0
            max_loss = summary.max_loss if summary.max_loss is not None else float("inf")

            notes = f"IV {test_iv:.1%}"
            if summary.max_loss is None:
                notes += " (UNLIMITED LOSS EXPOSURE)"
                fragile_zones.append(
                    f"IV {test_iv:.1%}: Unhedged tail risk; theoretical loss is unbounded"
                )
            elif total_gamma < -0.01:
                notes += " (High negative gamma risk)"
                fragile_zones.append(
                    f"IV {test_iv:.1%}: Gamma explosion risk (net gamma: {total_gamma:.4f})"
                )

            grid_points.append(
                SensitivityPoint(
                    parameter_value=shift_pct_str,
                    max_loss=round(max_loss, 2) if max_loss != float("inf") else -1.0,
                    max_profit=round(max_profit, 2),
                    net_delta=round(total_delta, 4),
                    net_gamma=round(total_gamma, 6),
                    notes=notes,
                )
            )

        stability: Literal["STABLE", "FRAGILE", "DEGRADED"] = (
            "FRAGILE" if fragile_zones else "STABLE"
        )
        return SensitivityGridResult(
            strategy_name=strategy.name,
            parameter_name="iv_shift_pct",
            baseline_value=f"{baseline_iv:.1%}",
            grid_points=grid_points,
            stability_verdict=stability,
            fragile_zones=fragile_zones,
        )

    def to_dossier_section(self, result: SensitivityGridResult) -> DossierSection:
        """Convert sensitivity grid results into a DETERMINISTIC DossierSection."""
        lines: list[str] = []
        lines.append(f"### Parameter Sensitivity Grid: `{result.parameter_name}`")
        lines.append(f"- **Strategy**: `{result.strategy_name}`")
        lines.append(f"- **Baseline Setting**: `{result.baseline_value}`")
        lines.append(f"- **Stability Verdict**: `{result.stability_verdict}`")
        lines.append("")

        lines.append(
            "| Shift / Value | Max Loss (₹) | Max Profit (₹) | Net Delta | Net Gamma | Notes |"
        )
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for pt in result.grid_points:
            lines.append(
                f"| {pt.parameter_value} | ₹{pt.max_loss:,.2f} | ₹{pt.max_profit:,.2f} | "
                f"{pt.net_delta:+.4f} | {pt.net_gamma:+.6f} | {pt.notes} |"
            )
        lines.append("")

        if result.fragile_zones:
            lines.append("#### Identified Fragile Zones")
            for zone in result.fragile_zones:
                lines.append(f"- ⚠️ {zone}")
            lines.append("")
        else:
            lines.append(
                "No critical gamma explosion or parameter fragility zones detected across evaluated range."
            )
            lines.append("")

        lines.append(
            "> **Deterministic Computation**: Greeks and payoff bounds calculated analytically via Black-Scholes."
        )

        return DossierSection(
            title="Parameter Sensitivity & Robustness Grid",
            source_type=DossierSectionSourceType.DETERMINISTIC,
            content="\n".join(lines),
            provenance=None,  # Not AI-generated; purely deterministic math
        )
