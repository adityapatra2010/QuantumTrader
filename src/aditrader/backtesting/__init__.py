"""Backtesting engine, execution runners, dataset splitters, and analytics."""

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
)
from aditrader.backtesting.options import OptionsBacktestConfig, OptionsBacktestRunner
from aditrader.backtesting.runner import (
    BacktestConfig,
    BacktestResult,
    BacktestRunner,
    UnsupportedStrategyError,
)
from aditrader.backtesting.splitters import (
    WalkForwardWindow,
    generate_walk_forward_windows,
    split_out_of_sample,
    split_train_test,
)

__all__ = [
    "BacktestConfig",
    "BacktestResult",
    "BacktestRunner",
    "DrawdownResult",
    "OptionsBacktestConfig",
    "OptionsBacktestRunner",
    "PerformanceReport",
    "UnsupportedStrategyError",
    "WalkForwardWindow",
    "calculate_expectancy",
    "calculate_max_drawdown",
    "calculate_profit_factor",
    "calculate_sharpe_ratio",
    "calculate_sortino_ratio",
    "calculate_sqn",
    "generate_performance_report",
    "generate_walk_forward_windows",
    "split_out_of_sample",
    "split_train_test",
]
