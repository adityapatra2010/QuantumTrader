"""Unit tests verifying deterministic backtesting engine, execution timing, and risk gates."""

from datetime import UTC, datetime, timedelta

import pytest

from aditrader.backtesting.runner import BacktestConfig, BacktestRunner
from aditrader.core.models.enums import OrderSide, OrderStatus, SignalDirection
from aditrader.core.models.market_data import Bar
from aditrader.core.risk.models import RiskLimits
from aditrader.data.feeds.synthetic_feed import SyntheticDataFeed
from aditrader.data.session import EXCHANGE_TIMEZONE
from aditrader.strategy.builder.schema import (
    ASTOperator,
    ConditionCategory,
    ConditionGroup,
    ConditionNode,
    StrategyDSL,
    StrategyLegDefinition,
)
from aditrader.strategy.compiler.engine import compile_strategy


def _build_test_strategy(underlying: str = "NIFTY") -> StrategyDSL:
    """Construct a simple declarative threshold strategy."""
    return StrategyDSL(
        schema_version="1.0",
        name="Test Crossover Strategy",
        underlying=underlying,
        timeframe="1m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="close",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=105.0,
                )
            ],
        ),
        exit_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="close",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=115.0,
                )
            ],
        ),
        legs=[
            StrategyLegDefinition(
                contract_type="CE",
                side=OrderSide.BUY,
                strike_offset=0,
                lots=1,
            )
        ],
    )


def _generate_bars() -> list[Bar]:
    """Generate deterministic bar series."""
    start_dt = datetime(2026, 3, 26, 9, 15, tzinfo=UTC)
    bars: list[Bar] = []
    prices = [100.0, 102.0, 106.0, 110.0, 116.0, 112.0]
    for i, p in enumerate(prices):
        bar = Bar(
            timestamp=start_dt + timedelta(minutes=i),
            open=p - 1.0,
            high=p + 2.0,
            low=p - 2.0,
            close=p,
            volume=1000,
            oi=50000,
        )
        bars.append(bar)
    return bars


def test_backtest_runner_empty_data_raises() -> None:
    strategy = compile_strategy(_build_test_strategy())
    runner = BacktestRunner()
    with pytest.raises(ValueError, match="Backtest data is empty"):
        runner.run(strategy, [])


def test_backtest_runner_deterministic_replay() -> None:
    """Verify two runs with identical inputs produce bit-identical results."""
    dsl = _build_test_strategy()
    bars = _generate_bars()

    strategy1 = compile_strategy(dsl)
    runner1 = BacktestRunner(BacktestConfig(initial_capital=500_000.0, trade_lots=1))
    result1 = runner1.run(strategy1, bars)

    strategy2 = compile_strategy(dsl)
    runner2 = BacktestRunner(BacktestConfig(initial_capital=500_000.0, trade_lots=1))
    result2 = runner2.run(strategy2, bars)

    assert result1.bar_count == result2.bar_count == len(bars)
    assert len(result1.signals) == len(result2.signals)
    assert len(result1.trades) == len(result2.trades)
    assert result1.equity_curve == result2.equity_curve
    assert result1.performance.return_pct == result2.performance.return_pct
    assert result1.performance.sharpe_ratio == result2.performance.sharpe_ratio

    for t1, t2 in zip(result1.trades, result2.trades, strict=True):
        assert t1.fill_price == t2.fill_price
        assert t1.timestamp == t2.timestamp
        assert t1.side == t2.side


def test_backtest_runner_execution_timing_anti_lookahead() -> None:
    """
    Verify lookahead protection:
    - Default (allow_same_bar_execution=False): signal at Bar T close -> fills at Bar T+1 open.
    - Explicit (allow_same_bar_execution=True): signal at Bar T close -> fills at Bar T close.
    """
    dsl = _build_test_strategy()
    bars = _generate_bars()

    # Bar 0: close 100.0
    # Bar 1: close 102.0
    # Bar 2: close 106.0 -> Entry signal triggers at Bar 2 close!
    # Bar 3: open 109.0, close 110.0

    # 1. Default Next-Bar Open Execution
    strat_next_bar = compile_strategy(dsl)
    runner_next_bar = BacktestRunner(BacktestConfig(allow_same_bar_execution=False))
    res_next_bar = runner_next_bar.run(strat_next_bar, bars)

    assert len(res_next_bar.signals) >= 1
    sig_entry = res_next_bar.signals[0]
    assert sig_entry.timestamp == bars[2].timestamp
    assert sig_entry.direction == SignalDirection.BUY

    # First trade must execute at Bar 3 timestamp at Bar 3 open price (109.0)
    assert len(res_next_bar.trades) >= 1
    trade_next_bar = res_next_bar.trades[0]
    assert trade_next_bar.timestamp == bars[3].timestamp
    assert trade_next_bar.fill_price == pytest.approx(bars[3].open, rel=1e-3)

    # 2. Configured Same-Bar Close Execution
    strat_same_bar = compile_strategy(dsl)
    runner_same_bar = BacktestRunner(BacktestConfig(allow_same_bar_execution=True))
    res_same_bar = runner_same_bar.run(strat_same_bar, bars)

    # First trade must execute at Bar 2 timestamp at Bar 2 close price (106.0)
    assert len(res_same_bar.trades) >= 1
    trade_same_bar = res_same_bar.trades[0]
    assert trade_same_bar.timestamp == bars[2].timestamp
    assert trade_same_bar.fill_price == pytest.approx(bars[2].close, rel=1e-3)


def test_backtest_runner_risk_engine_rejection() -> None:
    """Verify pre-trade risk engine blocks orders exceeding institutional risk limits."""
    dsl = _build_test_strategy()
    bars = _generate_bars()

    # Extremely restrictive margin utilization ceiling (0.01%) -> order will fail margin gate
    restrictive_limits = RiskLimits(max_margin_utilization_pct=0.0001)
    runner = BacktestRunner(
        BacktestConfig(
            initial_capital=10_000.0,
            trade_lots=50,
            risk_limits=restrictive_limits,
        )
    )
    strat = compile_strategy(dsl)
    result = runner.run(strat, bars)

    # Signals are generated by strategy
    assert len(result.signals) > 0

    # Orders were submitted
    assert len(result.orders) > 0

    # But rejected by pre-trade risk engine
    assert any(o.status == OrderStatus.REJECTED for o in result.orders)

    # No fills occurred
    assert len(result.trades) == 0


def test_backtest_runner_synthetic_feed_integration() -> None:
    """Verify backtest runner can ingest a DataFeed directly."""
    start = datetime(2026, 3, 2, 9, 15, tzinfo=EXCHANGE_TIMEZONE)
    feed = SyntheticDataFeed(
        symbol="NIFTY",
        start_price=100.0,
        start_time=start,
        num_bars=30,
        seed=42,
    )
    dsl = _build_test_strategy()
    strat = compile_strategy(dsl)

    runner = BacktestRunner()
    result = runner.run(strat, feed)

    assert result.bar_count == 30
    assert len(result.equity_curve) == 30
    assert result.strategy_name == dsl.name
    assert result.underlying == dsl.underlying
    assert result.performance is not None


def test_backtest_runner_walk_forward_pipeline() -> None:
    """Verify backtesting across walk-forward windows preserves zero timestamp leakage."""
    from aditrader.backtesting.splitters import generate_walk_forward_windows

    start = datetime(2026, 3, 2, 9, 15, tzinfo=EXCHANGE_TIMEZONE)
    feed = SyntheticDataFeed(
        symbol="NIFTY", start_price=100.0, start_time=start, num_bars=60, seed=42
    )
    bars = list(feed.stream())

    windows = generate_walk_forward_windows(
        bars, train_size=30, test_size=10, step_size=10, anchored=False
    )
    assert len(windows) == 3

    dsl = _build_test_strategy()
    runner = BacktestRunner()

    for w in windows:
        # Zero timestamp leakage assertion
        assert w.train_bars[-1].timestamp < w.test_bars[0].timestamp

        strat_train = compile_strategy(dsl)
        res_train = runner.run(strat_train, w.train_bars)
        assert res_train.bar_count == 30

        strat_test = compile_strategy(dsl)
        res_test = runner.run(strat_test, w.test_bars)
        assert res_test.bar_count == 10
