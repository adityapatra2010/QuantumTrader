"""Calculation Provenance Tracer generating granular explainable calculation trees.

Answers: "How was this calculated?"
Deconstructs:
- Individual trades: Signal -> Order -> Fills -> Position changes -> Statutory Fees -> Realized P&L
- Aggregate metrics: Trades -> Grouping -> Formula -> Intermediate stats -> Final metric
- Theoretical payoffs: Multi-leg structure -> Valuation models -> Root-finding breakevens -> Final bounds
"""

from __future__ import annotations

from uuid import uuid4

from aditrader.core.costs import CostCalculator, resolve_instrument_class
from aditrader.core.models.enums import OrderSide
from aditrader.verification.models import CalculationProvenance, CalculationStep


class ProvenanceTracer:
    """Generates transparent mathematical step-by-step provenance for trades and metrics."""

    @classmethod
    def trace_trade(
        cls,
        *,
        trade_id: str,
        symbol: str,
        side: OrderSide,
        qty: int,
        entry_price: float,
        exit_price: float,
        entry_timestamp: str,
        exit_timestamp: str,
        strategy_id: str,
        strategy_version: str = "1.0",
        strategy_hash: str = "",
        is_reversal: bool = False,
        reversal_prev_qty: int = 0,
    ) -> CalculationProvenance:
        """Deconstruct trade execution and P&L into explicit auditable calculation steps."""
        calc_id = f"CALC-TRADE-{trade_id}-{uuid4().hex[:6]}"
        steps: list[CalculationStep] = []
        step_idx = 1

        inst_class = resolve_instrument_class(symbol)

        # Step 1: Position Acquisition
        entry_turnover = round(float(qty) * entry_price, 2)
        steps.append(
            CalculationStep(
                step_index=step_idx,
                step_name="POSITION_ENTRY",
                formula="entry_turnover = qty * entry_price",
                inputs={
                    "qty": qty,
                    "entry_price": entry_price,
                    "side": str(side),
                    "timestamp": entry_timestamp,
                },
                output_value=entry_turnover,
                unit="INR",
                explanation=f"Executed entry fill of {qty} units at ₹{entry_price:.2f}",
            )
        )
        step_idx += 1

        # Step 2: Entry Statutory Taxes
        entry_side = OrderSide.BUY if side == OrderSide.BUY else OrderSide.SELL
        entry_charges = CostCalculator.calculate(
            side=entry_side, qty=qty, price=entry_price, instrument=inst_class
        )
        steps.append(
            CalculationStep(
                step_index=step_idx,
                step_name="ENTRY_STATUTORY_CHARGES",
                formula="STT + Exchange_Charges + SEBI + Stamp_Duty + GST(18%) + Brokerage(₹20)",
                inputs={
                    "brokerage": entry_charges.brokerage,
                    "stt": entry_charges.stt,
                    "exchange_charges": entry_charges.exchange_charges,
                    "sebi_charges": entry_charges.sebi_charges,
                    "stamp_duty": entry_charges.stamp_duty,
                    "gst": entry_charges.gst,
                },
                output_value=entry_charges.total_charges,
                unit="INR",
                explanation="Applied statutory exchange fees and taxes on opening order",
            )
        )
        step_idx += 1

        # Step 3: Exit Execution
        exit_turnover = round(float(qty) * exit_price, 2)
        steps.append(
            CalculationStep(
                step_index=step_idx,
                step_name="POSITION_EXIT",
                formula="exit_turnover = qty * exit_price",
                inputs={"qty": qty, "exit_price": exit_price, "timestamp": exit_timestamp},
                output_value=exit_turnover,
                unit="INR",
                explanation=f"Executed closing fill of {qty} units at ₹{exit_price:.2f}",
            )
        )
        step_idx += 1

        # Step 4: Exit Statutory Taxes
        exit_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
        exit_charges = CostCalculator.calculate(
            side=exit_side, qty=qty, price=exit_price, instrument=inst_class
        )
        steps.append(
            CalculationStep(
                step_index=step_idx,
                step_name="EXIT_STATUTORY_CHARGES",
                formula="STT + Exchange_Charges + SEBI + Stamp_Duty + GST(18%) + Brokerage(₹20)",
                inputs={
                    "brokerage": exit_charges.brokerage,
                    "stt": exit_charges.stt,
                    "exchange_charges": exit_charges.exchange_charges,
                    "sebi_charges": exit_charges.sebi_charges,
                    "stamp_duty": exit_charges.stamp_duty,
                    "gst": exit_charges.gst,
                },
                output_value=exit_charges.total_charges,
                unit="INR",
                explanation="Applied statutory exchange fees and taxes on closing order",
            )
        )
        step_idx += 1

        # Step 5: Gross Realized P&L
        if side == OrderSide.BUY:
            gross_pnl = round(float(qty) * (exit_price - entry_price), 2)
            formula_str = "qty * (exit_price - entry_price)"
        else:
            gross_pnl = round(float(qty) * (entry_price - exit_price), 2)
            formula_str = "qty * (entry_price - exit_price)"

        steps.append(
            CalculationStep(
                step_index=step_idx,
                step_name="GROSS_REALIZED_PNL",
                formula=formula_str,
                inputs={
                    "qty": qty,
                    "entry_price": entry_price,
                    "exit_price": exit_price,
                    "side": str(side),
                },
                output_value=gross_pnl,
                unit="INR",
                explanation="Calculated gross trading profit before statutory taxes",
            )
        )
        step_idx += 1

        # Step 6: Net Realized P&L
        total_fees = round(entry_charges.total_charges + exit_charges.total_charges, 2)
        net_pnl = round(gross_pnl - total_fees, 2)
        steps.append(
            CalculationStep(
                step_index=step_idx,
                step_name="NET_REALIZED_PNL",
                formula="gross_realized_pnl - total_statutory_charges",
                inputs={"gross_pnl": gross_pnl, "total_statutory_charges": total_fees},
                output_value=net_pnl,
                unit="INR",
                explanation="Deducted opening and closing statutory charges from gross profit",
            )
        )

        return CalculationProvenance(
            calculation_id=calc_id,
            target_metric="NET_REALIZED_PNL",
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            strategy_hash=strategy_hash,
            assumptions={"instrument_class": inst_class, "is_reversal": is_reversal},
            inputs={
                "trade_id": trade_id,
                "symbol": symbol,
                "side": str(side),
                "qty": qty,
                "entry_price": entry_price,
                "exit_price": exit_price,
            },
            intermediate_steps=steps,
            final_value=net_pnl,
        )

    @classmethod
    def trace_expectancy(
        cls,
        *,
        trade_pnls: list[float],
        strategy_id: str,
        strategy_hash: str = "",
        dataset_name: str | None = None,
    ) -> CalculationProvenance:
        """Deconstruct mathematical expectancy into explicit auditable calculation steps."""
        calc_id = f"CALC-EXP-{uuid4().hex[:8]}"
        steps: list[CalculationStep] = []

        n = len(trade_pnls)
        if n == 0:
            return CalculationProvenance(
                calculation_id=calc_id,
                target_metric="MATHEMATICAL_EXPECTANCY",
                strategy_id=strategy_id,
                strategy_version="1.0",
                strategy_hash=strategy_hash,
                dataset_name=dataset_name,
                inputs={"total_trades": 0, "trade_pnls": []},
                intermediate_steps=[
                    CalculationStep(
                        step_index=1,
                        step_name="ZERO_TRADES",
                        formula="E = 0.0 when N = 0",
                        inputs={"N": 0},
                        output_value=0.0,
                        unit="INR",
                        explanation="Zero trades executed; expectancy is 0.0",
                    )
                ],
                final_value=0.0,
            )

        wins = [p for p in trade_pnls if p > 0.0]
        losses = [abs(p) for p in trade_pnls if p < 0.0]

        win_count = len(wins)
        loss_count = len(losses)
        win_rate_raw = win_count / n
        loss_rate_raw = loss_count / n
        win_rate = round(win_rate_raw, 6)
        loss_rate = round(loss_rate_raw, 6)

        avg_win_raw = sum(wins) / win_count if win_count > 0 else 0.0
        avg_loss_raw = sum(losses) / loss_count if loss_count > 0 else 0.0
        avg_win = round(avg_win_raw, 2)
        avg_loss = round(avg_loss_raw, 2)

        steps.append(
            CalculationStep(
                step_index=1,
                step_name="SAMPLE_PARTITIONING",
                formula="N = count(trades), Wins = count(p > 0), Losses = count(p < 0)",
                inputs={"total_trades": n, "win_trades": win_count, "loss_trades": loss_count},
                output_value={"win_rate": win_rate, "loss_rate": loss_rate},
                unit="fraction",
                explanation=f"Partitioned {n} completed trades into {win_count} wins and {loss_count} losses",
            )
        )

        steps.append(
            CalculationStep(
                step_index=2,
                step_name="AVERAGE_PAYOFFS",
                formula="avg_win = sum(wins)/count(wins), avg_loss = sum(losses)/count(losses)",
                inputs={"gross_profit": round(sum(wins), 2), "gross_loss": round(sum(losses), 2)},
                output_value={"avg_win": avg_win, "avg_loss": avg_loss},
                unit="INR",
                explanation=f"Calculated average winning trade (₹{avg_win:.2f}) and average losing trade (₹{avg_loss:.2f})",
            )
        )

        # Expected value formula: (Win Rate * Avg Win) - (Loss Rate * Avg Loss)
        component_win = round(win_rate_raw * avg_win_raw, 2)
        component_loss = round(loss_rate_raw * avg_loss_raw, 2)
        expectancy = round((win_rate_raw * avg_win_raw) - (loss_rate_raw * avg_loss_raw), 2)

        steps.append(
            CalculationStep(
                step_index=3,
                step_name="EXPECTANCY_SYNTHESIS",
                formula="E = (Win_Rate * Avg_Win) - (Loss_Rate * Avg_Loss)",
                inputs={
                    "win_rate": win_rate,
                    "avg_win": avg_win,
                    "loss_rate": loss_rate,
                    "avg_loss": avg_loss,
                    "component_win": component_win,
                    "component_loss": component_loss,
                },
                output_value=expectancy,
                unit="INR",
                explanation=f"Mathematical expectancy per completed trade: ₹{expectancy:.2f}",
            )
        )

        return CalculationProvenance(
            calculation_id=calc_id,
            target_metric="MATHEMATICAL_EXPECTANCY",
            strategy_id=strategy_id,
            strategy_version="1.0",
            strategy_hash=strategy_hash,
            dataset_name=dataset_name,
            inputs={"total_trades": n, "gross_profit": sum(wins), "gross_loss": sum(losses)},
            intermediate_steps=steps,
            final_value=expectancy,
        )

    @classmethod
    def trace_max_drawdown(
        cls,
        *,
        equity_curve: list[float],
        strategy_id: str,
        strategy_hash: str = "",
        dataset_name: str | None = None,
    ) -> CalculationProvenance:
        """Deconstruct peak-to-trough drawdown calculation into step-by-step progression."""
        calc_id = f"CALC-MDD-{uuid4().hex[:8]}"
        steps: list[CalculationStep] = []

        if not equity_curve or len(equity_curve) < 2:
            return CalculationProvenance(
                calculation_id=calc_id,
                target_metric="MAX_DRAWDOWN",
                strategy_id=strategy_id,
                strategy_version="1.0",
                strategy_hash=strategy_hash,
                dataset_name=dataset_name,
                inputs={"equity_points": len(equity_curve)},
                intermediate_steps=[
                    CalculationStep(
                        step_index=1,
                        step_name="INSUFFICIENT_POINTS",
                        formula="MDD = 0.0 for < 2 equity points",
                        inputs={"points": len(equity_curve)},
                        output_value=0.0,
                        unit="INR",
                        explanation="Fewer than 2 equity observations; drawdown is 0.0",
                    )
                ],
                final_value={"amount": 0.0, "pct": 0.0},
            )

        current_peak = equity_curve[0]
        current_peak_idx = 0
        max_dd_peak = equity_curve[0]
        max_dd_peak_idx = 0
        max_dd_amount = 0.0
        max_dd_pct = 0.0
        trough_idx = 0

        for idx, eq in enumerate(equity_curve):
            if eq > current_peak:
                current_peak = eq
                current_peak_idx = idx
            dd_amount = current_peak - eq
            dd_pct = (dd_amount / current_peak) if current_peak > 0.0 else 0.0
            if dd_amount > max_dd_amount:
                max_dd_amount = dd_amount
                max_dd_pct = dd_pct
                max_dd_peak = current_peak
                max_dd_peak_idx = current_peak_idx
                trough_idx = idx

        steps.append(
            CalculationStep(
                step_index=1,
                step_name="PEAK_DETECTION",
                formula="Peak_t = max(Equity_0...t)",
                inputs={"peak_value": max_dd_peak, "peak_bar_index": max_dd_peak_idx},
                output_value=max_dd_peak,
                unit="INR",
                explanation=f"High-water mark equity peak identified at ₹{max_dd_peak:.2f} (bar index #{max_dd_peak_idx})",
            )
        )

        steps.append(
            CalculationStep(
                step_index=2,
                step_name="TROUGH_EVALUATION",
                formula="DD_amount = Peak - Equity_trough",
                inputs={
                    "peak": max_dd_peak,
                    "trough_value": equity_curve[trough_idx],
                    "trough_bar_index": trough_idx,
                },
                output_value=round(max_dd_amount, 2),
                unit="INR",
                explanation=f"Deepest decline to ₹{equity_curve[trough_idx]:.2f} (bar index #{trough_idx}) produces ₹{max_dd_amount:.2f} decline",
            )
        )

        steps.append(
            CalculationStep(
                step_index=3,
                step_name="PERCENTAGE_NORMALIZATION",
                formula="MDD% = DD_amount / Peak",
                inputs={"dd_amount": max_dd_amount, "peak": max_dd_peak},
                output_value=round(max_dd_pct, 6),
                unit="fraction",
                explanation=f"Normalized maximum peak-to-trough drawdown is {max_dd_pct * 100:.2f}%",
            )
        )

        return CalculationProvenance(
            calculation_id=calc_id,
            target_metric="MAX_DRAWDOWN",
            strategy_id=strategy_id,
            strategy_version="1.0",
            strategy_hash=strategy_hash,
            dataset_name=dataset_name,
            inputs={"total_equity_points": len(equity_curve), "initial_equity": equity_curve[0]},
            intermediate_steps=steps,
            final_value={"amount": round(max_dd_amount, 2), "pct": round(max_dd_pct, 6)},
        )
