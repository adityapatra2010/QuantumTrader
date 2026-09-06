"""Mathematical performance metrics and portfolio risk statistics.

Per .agents/skills/performance-metrics.md:
Computes uniform statistical metrics across backtests and paper simulations:
- Mathematical Expectancy (E)
- Profit Factor (PF)
- Sharpe Ratio
- Sortino Ratio
- Maximum Drawdown (MDD)
- System Quality Number (SQN)
"""

import math
from typing import NamedTuple

from pydantic import BaseModel, ConfigDict, Field


class DrawdownResult(NamedTuple):
    """Container for drawdown calculations."""

    max_drawdown_amount: float
    max_drawdown_pct: float


class PerformanceReport(BaseModel):
    """Institutional quantitative performance and risk report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    starting_equity: float = Field(..., ge=0.0, description="Initial starting capital")
    ending_equity: float = Field(..., description="Final portfolio capital")
    net_profit: float = Field(..., description="Total net profit/loss in INR")
    return_pct: float = Field(..., description="Percentage return on initial capital")

    total_trades: int = Field(..., ge=0, description="Total executed roundtrip trades")
    winning_trades: int = Field(..., ge=0, description="Count of profitable trades")
    losing_trades: int = Field(..., ge=0, description="Count of unprofitable trades")
    win_rate: float = Field(..., ge=0.0, le=1.0, description="Proportion of winning trades")

    gross_profit: float = Field(..., ge=0.0, description="Sum of all positive trade PnLs")
    gross_loss: float = Field(..., ge=0.0, description="Sum of all negative trade PnLs (absolute)")
    profit_factor: float = Field(..., ge=0.0, description="Gross profit divided by gross loss")

    expectancy: float = Field(..., description="Mathematical expectancy per trade in INR")
    max_drawdown_amount: float = Field(
        ..., ge=0.0, description="Maximum peak-to-trough decline in INR"
    )
    max_drawdown_pct: float = Field(
        ..., ge=0.0, le=1.0, description="Maximum peak-to-trough decline fraction"
    )

    sharpe_ratio: float = Field(
        ..., description="Annualized risk-adjusted excess return over volatility"
    )
    sortino_ratio: float = Field(
        ..., description="Annualized risk-adjusted excess return over downside volatility"
    )
    sqn: float = Field(..., description="System Quality Number (Van Tharp)")


def calculate_expectancy(trade_pnls: list[float]) -> float:
    r"""Calculate mathematical expectancy per trade.

    Formula:
        E = (Win Rate * Average Win) - (Loss Rate * Average Loss)
        Equivalently: E = sum(trade_pnls) / len(trade_pnls)

    Args:
        trade_pnls: List of net PnL values per completed trade.

    Returns:
        Mathematical expectancy in currency units (0.0 if no trades).
    """
    if not trade_pnls:
        return 0.0

    wins = [p for p in trade_pnls if p > 0.0]
    losses = [abs(p) for p in trade_pnls if p < 0.0]

    n = len(trade_pnls)
    win_rate = len(wins) / n
    loss_rate = len(losses) / n

    avg_win = (sum(wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0

    return (win_rate * avg_win) - (loss_rate * avg_loss)


def calculate_profit_factor(trade_pnls: list[float]) -> float:
    r"""Calculate Profit Factor (PF).

    Formula:
        PF = sum(Gross Profits) / sum(|Gross Losses|)

    Args:
        trade_pnls: List of net PnL values per completed trade.

    Returns:
        Profit Factor. Returns float('inf') if no losses and positive profit;
        returns 0.0 if no trades or no profits.
    """
    if not trade_pnls:
        return 0.0

    gross_profit = sum(p for p in trade_pnls if p > 0.0)
    gross_loss = sum(abs(p) for p in trade_pnls if p < 0.0)

    if gross_loss == 0.0:
        return float("inf") if gross_profit > 0.0 else 0.0

    return gross_profit / gross_loss


def calculate_max_drawdown(equity_curve: list[float]) -> DrawdownResult:
    r"""Calculate Maximum Peak-to-Trough Drawdown in currency amount and percentage.

    Formula:
        Peak_t = max_{0 <= s <= t} (Equity_s)
        DD_t = Peak_t - Equity_t
        DD%_t = DD_t / Peak_t

    Args:
        equity_curve: Chronological series of portfolio equity values.

    Returns:
        DrawdownResult(max_drawdown_amount, max_drawdown_pct).
    """
    if not equity_curve or len(equity_curve) < 2:
        return DrawdownResult(0.0, 0.0)

    peak = equity_curve[0]
    max_dd_amount = 0.0
    max_dd_pct = 0.0

    for equity in equity_curve:
        if equity > peak:
            peak = equity
        dd_amount = peak - equity
        dd_pct = (dd_amount / peak) if peak > 0.0 else 0.0

        if dd_amount > max_dd_amount:
            max_dd_amount = dd_amount
        if dd_pct > max_dd_pct:
            max_dd_pct = dd_pct

    return DrawdownResult(max_drawdown_amount=max_dd_amount, max_drawdown_pct=max_dd_pct)


def calculate_sharpe_ratio(
    returns: list[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    r"""Calculate Annualized Sharpe Ratio.

    Formula:
        Sharpe = ((R_p - R_f) / sigma_p) * sqrt(periods_per_year)

    Args:
        returns: Periodic fractional returns (e.g. daily returns [r_1, r_2, ...]).
        risk_free_rate: Annualized risk-free rate (e.g. 0.065 for 6.5%).
        periods_per_year: Frequency scaling factor (252 for daily, 252 * 75 for 5m).

    Returns:
        Annualized Sharpe Ratio (0.0 if standard deviation is zero or len < 2).
    """
    n = len(returns)
    if n < 2:
        return 0.0

    rf_per_period = risk_free_rate / periods_per_year
    excess_returns = [r - rf_per_period for r in returns]
    mean_excess = sum(excess_returns) / n

    variance = sum((r - (sum(returns) / n)) ** 2 for r in returns) / (n - 1)
    if variance <= 0.0:
        return 0.0

    std_dev = math.sqrt(variance)
    return (mean_excess / std_dev) * math.sqrt(periods_per_year)


def calculate_sortino_ratio(
    returns: list[float],
    risk_free_rate: float = 0.0,
    periods_per_year: int = 252,
) -> float:
    r"""Calculate Annualized Sortino Ratio focusing on downside risk.

    Formula:
        Sortino = ((R_p - R_f) / sigma_d) * sqrt(periods_per_year)
        sigma_d = sqrt(mean(min(0, r_i - r_f)^2))

    Args:
        returns: Periodic fractional returns.
        risk_free_rate: Annualized risk-free rate.
        periods_per_year: Frequency scaling factor (252 for daily).

    Returns:
        Annualized Sortino Ratio.
    """
    n = len(returns)
    if n < 2:
        return 0.0

    rf_per_period = risk_free_rate / periods_per_year
    excess_returns = [r - rf_per_period for r in returns]
    mean_excess = sum(excess_returns) / n

    downside_diffs = [min(0.0, er) ** 2 for er in excess_returns]
    downside_variance = sum(downside_diffs) / n

    if downside_variance <= 0.0:
        return float("inf") if mean_excess > 0.0 else 0.0

    downside_std = math.sqrt(downside_variance)
    return (mean_excess / downside_std) * math.sqrt(periods_per_year)


def calculate_sqn(trade_pnls: list[float]) -> float:
    r"""Calculate System Quality Number (SQN) per Van Tharp.

    Formula:
        SQN = sqrt(N) * (Mean PnL / StdDev PnL)

    Args:
        trade_pnls: List of net PnL values per completed trade.

    Returns:
        SQN score (0.0 if N < 2 or std dev == 0).
    """
    n = len(trade_pnls)
    if n < 2:
        return 0.0

    mean_pnl = sum(trade_pnls) / n
    variance = sum((p - mean_pnl) ** 2 for p in trade_pnls) / (n - 1)

    if variance <= 0.0:
        return 0.0

    std_dev = math.sqrt(variance)
    return math.sqrt(n) * (mean_pnl / std_dev)


def generate_performance_report(
    starting_equity: float,
    equity_curve: list[float],
    trade_pnls: list[float],
    risk_free_rate: float = 0.065,
    periods_per_year: int = 252,
) -> PerformanceReport:
    """Generate comprehensive PerformanceReport from simulation history."""
    ending_equity = equity_curve[-1] if equity_curve else starting_equity
    net_profit = ending_equity - starting_equity
    return_pct = (net_profit / starting_equity) if starting_equity > 0.0 else 0.0

    total_trades = len(trade_pnls)
    wins = [p for p in trade_pnls if p > 0.0]
    losses = [abs(p) for p in trade_pnls if p < 0.0]

    winning_trades = len(wins)
    losing_trades = len(losses)
    win_rate = (winning_trades / total_trades) if total_trades > 0 else 0.0

    gross_profit = sum(wins)
    gross_loss = sum(losses)
    profit_factor = calculate_profit_factor(trade_pnls)
    expectancy = calculate_expectancy(trade_pnls)

    dd = calculate_max_drawdown(equity_curve)

    # Periodic returns from equity curve
    if len(equity_curve) >= 2:
        returns = [
            (equity_curve[i] - equity_curve[i - 1]) / equity_curve[i - 1]
            for i in range(1, len(equity_curve))
            if equity_curve[i - 1] > 0.0
        ]
    else:
        returns = []

    sharpe = calculate_sharpe_ratio(
        returns, risk_free_rate=risk_free_rate, periods_per_year=periods_per_year
    )
    sortino = calculate_sortino_ratio(
        returns, risk_free_rate=risk_free_rate, periods_per_year=periods_per_year
    )
    sqn = calculate_sqn(trade_pnls)

    return PerformanceReport(
        starting_equity=starting_equity,
        ending_equity=ending_equity,
        net_profit=net_profit,
        return_pct=return_pct,
        total_trades=total_trades,
        winning_trades=winning_trades,
        losing_trades=losing_trades,
        win_rate=win_rate,
        gross_profit=gross_profit,
        gross_loss=gross_loss,
        profit_factor=profit_factor,
        expectancy=expectancy,
        max_drawdown_amount=dd.max_drawdown_amount,
        max_drawdown_pct=dd.max_drawdown_pct,
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        sqn=sqn,
    )
