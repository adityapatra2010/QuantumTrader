"""Facade re-exporting performance metrics."""

from aditrader.backtesting.analytics.metrics import (
    DrawdownResult,
    PerformanceReport,
    calculate_expectancy,
    calculate_max_drawdown,
    calculate_profit_factor,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_sqn,
    generate_performance_report,
    resolve_periods_per_year,
)

__all__ = [
    "DrawdownResult",
    "PerformanceReport",
    "calculate_expectancy",
    "calculate_max_drawdown",
    "calculate_profit_factor",
    "calculate_sharpe_ratio",
    "calculate_sortino_ratio",
    "calculate_sqn",
    "generate_performance_report",
    "resolve_periods_per_year",
]
