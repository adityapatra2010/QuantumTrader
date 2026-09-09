"""Deterministic calculation reproducibility engine.

Answers: "Can this exact result be reproduced fresh from raw inputs and rules?"
Compares stored historical records against newly recomputed values using calibrated
institutional tolerances (1 paisa for currency, 0.01 bps for ratios).
Detects floating-point drift, code divergence, or dataset tampering without silent overwriting.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from aditrader.backtesting.analytics.metrics import (
    calculate_expectancy,
    calculate_max_drawdown,
    calculate_profit_factor,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_sqn,
    resolve_periods_per_year,
)
from aditrader.verification.models import (
    ReproducibilityComparison,
    ReproducibilitySummary,
)
from aditrader.verification.tolerances import get_metric_tolerance

logger = logging.getLogger(__name__)


class ReproducibilityEngine:
    """Re-runs deterministic calculations and compares outputs side-by-side."""

    @classmethod
    def compare_metric(
        cls,
        metric_name: str,
        stored_value: float | None,
        fresh_value: float | None,
        custom_tolerance: float | None = None,
    ) -> ReproducibilityComparison:
        """Compare a single persisted metric against freshly calculated ground truth."""
        tolerance = (
            custom_tolerance if custom_tolerance is not None else get_metric_tolerance(metric_name)
        )

        # Case 1: Both are None (statistically undefined, e.g. Sortino with 0 downside)
        if stored_value is None and fresh_value is None:
            return ReproducibilityComparison(
                metric_name=metric_name,
                stored_value=None,
                fresh_value=None,
                delta=0.0,
                tolerance=tolerance,
                is_reproduced=True,
                details="Both values are identically None (statistically undefined per ADR 011)",
            )

        # Case 2: One is None and the other is numeric
        if stored_value is None or fresh_value is None:
            return ReproducibilityComparison(
                metric_name=metric_name,
                stored_value=stored_value,
                fresh_value=fresh_value,
                delta=float("inf"),
                tolerance=tolerance,
                is_reproduced=False,
                details=f"Undefined mismatch: stored={stored_value} vs fresh={fresh_value}",
            )

        # Case 3: Both are numeric
        delta = round(fresh_value - stored_value, 6)
        abs_delta = abs(delta)
        is_reproduced = abs_delta <= tolerance

        details = (
            f"Tolerance match: |delta|={abs_delta:.6f} <= {tolerance}"
            if is_reproduced
            else f"DIVERGENCE DETECTED: |delta|={abs_delta:.6f} exceeds tolerance {tolerance}"
        )

        return ReproducibilityComparison(
            metric_name=metric_name,
            stored_value=stored_value,
            fresh_value=fresh_value,
            delta=delta,
            tolerance=tolerance,
            is_reproduced=is_reproduced,
            details=details,
        )

    @classmethod
    def audit_metrics_reproducibility(
        cls,
        *,
        strategy_id: str,
        stored_metrics: dict[str, Any],
        trade_pnls: list[float],
        equity_curve: list[float],
        timeframe: str = "5m",
        dataset_available: bool = True,
        dataset_path_str: str | None = None,
    ) -> ReproducibilitySummary:
        """Recalculate complete quantitative metrics and produce side-by-side audit summary."""
        if not dataset_available:
            return ReproducibilitySummary(
                strategy_id=strategy_id,
                overall_reproduced=False,
                mismatch_count=1,
                comparisons=[],
                evaluated_at=datetime.now(UTC),
                reason=f"BLOCKED: Source dataset '{dataset_path_str or 'unknown'}' unavailable or moved",
            )

        # Fresh computations
        periods_per_year = resolve_periods_per_year(timeframe)

        fresh_expectancy = calculate_expectancy(trade_pnls)
        fresh_pf = calculate_profit_factor(trade_pnls)
        fresh_dd = calculate_max_drawdown(equity_curve)
        fresh_sqn = calculate_sqn(trade_pnls)

        # Periodic returns for Sharpe / Sortino
        returns: list[float] = []
        for i in range(1, len(equity_curve)):
            prev = equity_curve[i - 1]
            curr = equity_curve[i]
            returns.append((curr - prev) / prev if prev > 0 else 0.0)

        rf_rate = float(stored_metrics.get("risk_free_rate", 0.065))
        fresh_sharpe = calculate_sharpe_ratio(
            returns, risk_free_rate=rf_rate, periods_per_year=periods_per_year
        )
        fresh_sortino = calculate_sortino_ratio(
            returns, risk_free_rate=rf_rate, periods_per_year=periods_per_year
        )

        if equity_curve and len(equity_curve) >= 2:
            fresh_net_profit = round(equity_curve[-1] - equity_curve[0], 2)
        else:
            fresh_net_profit = round(sum(trade_pnls), 2)
        fresh_win_rate = (
            round(sum(1 for p in trade_pnls if p > 0) / len(trade_pnls), 6) if trade_pnls else 0.0
        )

        checks = [
            (
                "mathematical_expectancy",
                stored_metrics.get("mathematical_expectancy") or stored_metrics.get("expectancy"),
                fresh_expectancy,
            ),
            ("profit_factor", stored_metrics.get("profit_factor"), fresh_pf),
            ("max_drawdown_pct", stored_metrics.get("max_drawdown_pct"), fresh_dd.max_drawdown_pct),
            (
                "max_drawdown_amount",
                stored_metrics.get("max_drawdown_amount"),
                fresh_dd.max_drawdown_amount,
            ),
            ("sharpe_ratio", stored_metrics.get("sharpe_ratio"), fresh_sharpe),
            ("sortino_ratio", stored_metrics.get("sortino_ratio"), fresh_sortino),
            ("sqn", stored_metrics.get("sqn"), fresh_sqn),
            ("win_rate", stored_metrics.get("win_rate"), fresh_win_rate),
            ("net_profit", stored_metrics.get("net_profit"), fresh_net_profit),
        ]

        comparisons: list[ReproducibilityComparison] = []
        mismatches = 0

        for name, stored_val, fresh_val in checks:
            # Skip metrics not recorded in the stored baseline
            if stored_val is None and name not in stored_metrics:
                if name == "mathematical_expectancy" and "expectancy" in stored_metrics:
                    pass
                else:
                    continue
            comp = cls.compare_metric(name, stored_val, fresh_val)
            comparisons.append(comp)
            if not comp.is_reproduced:
                mismatches += 1

        overall_ok = mismatches == 0
        reason = (
            "All metrics reproduced bit-for-bit within institutional tolerances."
            if overall_ok
            else f"{mismatches} metric(s) diverged from stored values."
        )

        return ReproducibilitySummary(
            strategy_id=strategy_id,
            overall_reproduced=overall_ok,
            mismatch_count=mismatches,
            comparisons=comparisons,
            evaluated_at=datetime.now(UTC),
            reason=reason,
        )
