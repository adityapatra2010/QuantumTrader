"""Institutional numerical tolerance definitions for deterministic verification.

Per Auditor Directive:
Monetary values (INR) are rounded to 2 decimal places in PaperBroker (paisa).
Ratios and Greeks use calibrated float tolerances to avoid false-alarm mismatch alerts.
"""

from __future__ import annotations

from typing import Final

TOLERANCE_MONETARY: Final[float] = 0.01
"""1 paisa (₹0.01) tolerance for Indian currency ledger sums, cash balances, and statutory taxes."""

TOLERANCE_RATIO: Final[float] = 1e-4
"""0.01 basis point (0.0001) tolerance for dimensionless ratios (Sharpe, Sortino, SQN, Profit Factor)."""

TOLERANCE_PERCENT: Final[float] = 1e-4
"""0.01% (0.0001) tolerance for fractions and percentages (Max Drawdown %, Win Rate, Return %)."""

TOLERANCE_GREEKS: Final[float] = 1e-4
"""Analytical benchmark tolerance for Black-Scholes Greeks (Delta, Gamma, Theta, Vega, Rho)."""

TOLERANCE_DIMENSIONLESS: Final[float] = TOLERANCE_RATIO
TOLERANCE_PERCENTAGE: Final[float] = TOLERANCE_PERCENT


def is_close_monetary(a: float, b: float) -> bool:
    """Check if two monetary figures match within paisa tolerance (₹0.01)."""
    return abs(a - b) <= TOLERANCE_MONETARY


def is_close_ratio(a: float, b: float) -> bool:
    """Check if two dimensionless ratios match within basis point tolerance (1e-4)."""
    return abs(a - b) <= TOLERANCE_RATIO


def get_metric_tolerance(metric_name: str) -> float:
    """Return calibrated tolerance threshold based on metric classification."""
    m = metric_name.strip().lower()

    # 1. Explicit monetary amounts (INR)
    if "amount" in m or any(
        k in m
        for k in (
            "equity",
            "capital",
            "pnl",
            "profit",
            "loss",
            "cash",
            "margin",
            "tax",
            "charge",
            "stt",
            "gst",
            "fee",
            "turnover",
            "inr",
        )
    ):
        if "pct" in m or "percent" in m or "rate" in m or "factor" in m:
            return TOLERANCE_PERCENT
        return TOLERANCE_MONETARY

    # 2. Drawdown differentiation
    if "drawdown" in m:
        if "amt" in m or "amount" in m or "inr" in m:
            return TOLERANCE_MONETARY
        return TOLERANCE_PERCENT

    # 3. Percentages and rates
    if any(k in m for k in ("pct", "percent", "rate")):
        return TOLERANCE_PERCENT

    # 4. Dimensionless performance ratios
    if any(k in m for k in ("sharpe", "sortino", "sqn", "factor", "ratio")):
        return TOLERANCE_RATIO

    # 5. Options sensitivities & implied volatility
    if any(k in m for k in ("delta", "gamma", "theta", "vega", "rho", "iv")):
        return TOLERANCE_GREEKS

    return TOLERANCE_RATIO
