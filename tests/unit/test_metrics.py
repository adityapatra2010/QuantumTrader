"""Unit tests verifying mathematical accuracy of performance and risk metrics."""

import math

import pytest

from aditrader.backtesting.analytics.metrics import (
    calculate_expectancy,
    calculate_max_drawdown,
    calculate_profit_factor,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_sqn,
    generate_performance_report,
    resolve_periods_per_year,
)


def test_calculate_expectancy_benchmark() -> None:
    """Verify expectancy formula against known trade outcomes."""
    # 2 wins (+100, +150) and 2 losses (-50, -50)
    pnls = [100.0, -50.0, 150.0, -50.0]
    expectancy = calculate_expectancy(pnls)
    # Win rate: 0.5, avg win: 125.0; Loss rate: 0.5, avg loss: 50.0
    # E = (0.5 * 125.0) - (0.5 * 50.0) = 62.5 - 25.0 = 37.5
    assert expectancy == pytest.approx(37.5)


def test_calculate_expectancy_empty_or_all_wins() -> None:
    """Verify expectancy on edge cases (empty list, zero losses)."""
    assert calculate_expectancy([]) == 0.0

    all_wins = [50.0, 50.0, 50.0]
    assert calculate_expectancy(all_wins) == pytest.approx(50.0)


def test_calculate_profit_factor_benchmark() -> None:
    """Verify Profit Factor calculation: Gross Profits / Gross Losses."""
    pnls = [100.0, -50.0, 150.0, -50.0]
    # Gross profit: 250, Gross loss: 100 -> PF = 2.5
    assert calculate_profit_factor(pnls) == pytest.approx(2.5)

    # Zero losses -> None (statistically undefined)
    assert calculate_profit_factor([100.0, 200.0]) is None

    # Zero profits -> 0.0 PF
    assert calculate_profit_factor([-100.0, -50.0]) == 0.0


def test_calculate_max_drawdown_benchmark() -> None:
    """Verify peak-to-trough drawdown calculation in INR and percentage."""
    equity = [1000.0, 1200.0, 1100.0, 900.0, 1300.0]
    dd = calculate_max_drawdown(equity)

    # Peak: 1200, Trough: 900 -> DD amount: 300, DD pct: 300/1200 = 0.25 (25%)
    assert dd.max_drawdown_amount == pytest.approx(300.0)
    assert dd.max_drawdown_pct == pytest.approx(0.25)


def test_calculate_sharpe_and_sortino_ratios() -> None:
    """Verify annualized Sharpe and Sortino ratios."""
    # Positive daily returns with occasional dip
    returns = [0.01, 0.02, -0.005, 0.015, 0.008]
    sharpe = calculate_sharpe_ratio(returns, risk_free_rate=0.0, periods_per_year=252)
    sortino = calculate_sortino_ratio(returns, risk_free_rate=0.0, periods_per_year=252)

    assert sharpe is not None and sharpe > 0.0
    assert sortino is not None and sortino > 0.0
    # Because downside deviation is smaller than total volatility, Sortino > Sharpe
    assert sortino > sharpe


def test_calculate_sqn_benchmark() -> None:
    """Verify System Quality Number (Van Tharp)."""
    pnls = [100.0, -50.0, 150.0, -50.0]
    sqn = calculate_sqn(pnls)

    # Mean: 37.5, N: 4, Sample Variance: 10625.0, StdDev: 103.0776
    # SQN = sqrt(4) * (37.5 / 103.0776) = 0.7276
    assert sqn is not None
    assert sqn == pytest.approx(0.7276, rel=1e-3)


def test_generate_performance_report_integration() -> None:
    """Verify full PerformanceReport generation."""
    equity_curve = [100_000.0, 105_000.0, 102_000.0, 110_000.0]
    trade_pnls = [5_000.0, -3_000.0, 8_000.0]

    report = generate_performance_report(
        starting_equity=100_000.0,
        equity_curve=equity_curve,
        trade_pnls=trade_pnls,
    )

    assert report.starting_equity == 100_000.0
    assert report.ending_equity == 110_000.0
    assert report.net_profit == 10_000.0
    assert report.return_pct == pytest.approx(0.10)
    assert report.total_trades == 3
    assert report.winning_trades == 2
    assert report.losing_trades == 1
    assert report.win_rate == pytest.approx(2 / 3)
    assert report.profit_factor == pytest.approx(13_000.0 / 3_000.0)
    assert report.max_drawdown_amount == pytest.approx(3_000.0)
    assert report.max_drawdown_pct == pytest.approx(3_000.0 / 105_000.0)


def test_metrics_edge_cases_and_zero_trades() -> None:
    """Verify metrics behavior on zero trades, flat equity, and constant returns."""
    # Zero trades report
    report = generate_performance_report(
        starting_equity=100_000.0,
        equity_curve=[100_000.0],
        trade_pnls=[],
    )
    assert report.total_trades == 0
    assert report.win_rate == 0.0
    assert report.profit_factor == 0.0
    assert report.expectancy == 0.0
    assert report.max_drawdown_amount == 0.0
    assert report.max_drawdown_pct == 0.0
    assert report.sharpe_ratio is None
    assert report.sortino_ratio is None
    assert report.sqn is None

    # Negative returns
    neg_returns = [-0.01, -0.02, -0.015, -0.005]
    sharpe_neg = calculate_sharpe_ratio(neg_returns, risk_free_rate=0.0)
    sortino_neg = calculate_sortino_ratio(neg_returns, risk_free_rate=0.0)
    assert sharpe_neg is not None and sharpe_neg < 0.0
    assert sortino_neg is not None and sortino_neg < 0.0

    # Single trade SQN
    assert calculate_sqn([100.0]) is None

    # Zero variance SQN
    assert calculate_sqn([100.0, 100.0, 100.0]) is None


def test_resolve_periods_per_year() -> None:
    """Verify timeframe resolution mapping across daily, weekly, and intraday bars."""
    # Daily / Weekly / Monthly
    assert resolve_periods_per_year("1d") == 252
    assert resolve_periods_per_year("daily") == 252
    assert resolve_periods_per_year("D") == 252
    assert resolve_periods_per_year("1w") == 52
    assert resolve_periods_per_year("weekly") == 52
    assert resolve_periods_per_year("1mo") == 12

    # Intraday minutes (375 min session)
    assert resolve_periods_per_year("1m") == 252 * 375  # 94,500
    assert resolve_periods_per_year("5m") == 252 * 75  # 18,900
    assert resolve_periods_per_year("15m") == 252 * 25  # 6,300
    assert resolve_periods_per_year("30m") == int(252 * 12.5)  # 3,150
    assert resolve_periods_per_year("75m") == 252 * 5  # 1,260

    # Intraday hours
    assert resolve_periods_per_year("1h") == int(252 * 6.25)  # 1,575
    assert resolve_periods_per_year("1hour") == int(252 * 6.25)  # 1,575

    # Case insensitivity and whitespace
    assert resolve_periods_per_year("  5M  ") == 18_900
    assert resolve_periods_per_year("15MIN") == 6_300

    # Fallback to default
    assert resolve_periods_per_year("unknown_tf") == 252
    assert resolve_periods_per_year("custom", trading_days_per_year=250) == 250


def test_timeframe_aware_sharpe_scaling() -> None:
    """Verify that intraday returns annualized with 5m periods yield higher factor than daily."""
    # Say a 5m bar has mean return of 0.0002 with std 0.001
    intraday_returns = [0.0002, 0.0001, -0.0001, 0.0003, 0.0002] * 20
    daily_factor = resolve_periods_per_year("1d")
    m5_factor = resolve_periods_per_year("5m")

    sharpe_daily_scale = calculate_sharpe_ratio(
        intraday_returns, risk_free_rate=0.0, periods_per_year=daily_factor
    )
    sharpe_5m_scale = calculate_sharpe_ratio(
        intraday_returns, risk_free_rate=0.0, periods_per_year=m5_factor
    )

    # sqrt(18900) / sqrt(252) = sqrt(75) approx 8.66x
    assert sharpe_5m_scale is not None and sharpe_daily_scale is not None
    ratio = sharpe_5m_scale / sharpe_daily_scale
    assert ratio == pytest.approx(math.sqrt(75), rel=1e-3)


def test_finite_metrics_zero_downside_and_flat() -> None:
    """Verify that zero downside deviation and zero variance return None rather than infinity."""
    # 1. Zero downside deviation with positive excess returns -> Sortino should be None (not inf!)
    positive_returns = [0.01, 0.02, 0.015, 0.03]
    sortino = calculate_sortino_ratio(positive_returns, risk_free_rate=0.0)
    assert sortino is None

    # 2. Zero variance (all returns identical) -> Sharpe and Sortino should be None
    flat_returns = [0.005, 0.005, 0.005, 0.005]
    assert calculate_sharpe_ratio(flat_returns, risk_free_rate=0.0) is None
    assert calculate_sortino_ratio(flat_returns, risk_free_rate=0.0) is None

    # 3. Flat equity curve in report
    report = generate_performance_report(
        starting_equity=100_000.0,
        equity_curve=[100_000.0, 100_000.0, 100_000.0],
        trade_pnls=[],
    )
    assert report.sharpe_ratio is None
    assert report.sortino_ratio is None
    assert report.profit_factor == 0.0


def test_strict_timeframe_resolution() -> None:
    """Verify strict mode timeframe resolution and second intervals."""
    # Second intervals
    assert resolve_periods_per_year("1s") == 252 * (375 * 60)  # 5,670,000
    assert resolve_periods_per_year("30s") == int(252 * (375 * 2))  # 189,000

    # Strict mode valid
    assert resolve_periods_per_year("1d", strict=True) == 252
    assert resolve_periods_per_year("5m", strict=True) == 18_900

    # Strict mode invalid raises ValueError
    with pytest.raises(ValueError, match="Unsupported or unrecognized timeframe format"):
        resolve_periods_per_year("invalid_tf", strict=True)
