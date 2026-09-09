"""Unit tests verifying deterministic backtesting engine, execution timing, and risk gates."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from aditrader.backtesting.runner import BacktestConfig, BacktestRunner
from aditrader.core.models.enums import OrderStatus, SignalDirection
from aditrader.core.models.market_data import Bar
from aditrader.core.models.trade_signal import Signal
from aditrader.core.risk.models import RiskLimits
from aditrader.data.feeds.synthetic_feed import SyntheticDataFeed
from aditrader.data.session import EXCHANGE_TIMEZONE
from aditrader.strategy.builder.schema import (
    ASTOperator,
    ConditionCategory,
    ConditionGroup,
    ConditionNode,
    StrategyDSL,
)
from aditrader.strategy.compiler.engine import ExecutableStrategy, compile_strategy


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
        legs=[],
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


def test_backtest_runner_expiry_naked_short_rejection() -> None:
    """Verify backtest runner enforces unhedged naked short rejection on expiry day."""
    from aditrader.core.risk.models import RiskRejectionReason

    # Strategy that sells CE on trigger
    dsl = StrategyDSL(
        schema_version="1.0",
        name="Short Call Expiry Strategy",
        underlying="NIFTY",
        timeframe="1m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="close",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=100.0,
                )
            ],
        ),
        legs=[],
    )
    bars = _generate_bars()

    class ExpiryShortStrategy(ExecutableStrategy):
        def on_bar(self, history: list[Bar], **kwargs: Any) -> Signal | None:
            sig = super().on_bar(history, **kwargs)
            if sig is not None:
                return sig.model_copy(
                    update={
                        "direction": SignalDirection.SELL,
                        "metadata": {"is_expiry_day": True, "is_naked_short": True},
                    }
                )
            return None

    strat = ExpiryShortStrategy(dsl)
    runner = BacktestRunner(BacktestConfig(allow_same_bar_execution=True))
    result = runner.run(strat, bars)

    assert len(result.signals) > 0
    assert len(result.orders) > 0
    assert any(
        o.status == OrderStatus.REJECTED
        and RiskRejectionReason.EXPIRY_NAKED_SHORT_PROHIBITED.value in (o.rejection_reason or "")
        for o in result.orders
    )
    assert len(result.trades) == 0


def test_backtest_runner_timeframe_aware_metrics() -> None:
    """Verify BacktestRunner automatically resolves timeframe annualization if not explicitly set."""
    import math

    dsl = _build_test_strategy()
    assert dsl.timeframe == "1m"
    bars = _generate_bars()

    # 1. Automatic timeframe-resolved (1m -> 94,500 periods)
    runner_auto = BacktestRunner(BacktestConfig(periods_per_year=None, risk_free_rate=0.0))
    res_auto = runner_auto.run(compile_strategy(dsl), bars)

    # 2. Forced daily annualization (252 periods)
    runner_daily = BacktestRunner(BacktestConfig(periods_per_year=252, risk_free_rate=0.0))
    res_daily = runner_daily.run(compile_strategy(dsl), bars)

    if (
        res_daily.performance.sharpe_ratio is not None
        and res_daily.performance.sharpe_ratio != 0.0
        and res_auto.performance.sharpe_ratio is not None
    ):
        ratio = res_auto.performance.sharpe_ratio / res_daily.performance.sharpe_ratio
        assert ratio == pytest.approx(math.sqrt(375), rel=1e-2)


def test_options_backtest_runner_boundary() -> None:
    """Verify that OptionsBacktestRunner enforces architectural boundary and raises NotImplementedError."""
    from aditrader.backtesting.options import OptionsBacktestConfig, OptionsBacktestRunner

    opt_config = OptionsBacktestConfig(
        pricing_mode="black_scholes_synthetic",
        iv_smile_interpolation=True,
    )
    runner = OptionsBacktestRunner(opt_config)
    dsl = _build_test_strategy()
    bars = _generate_bars()
    strat = compile_strategy(dsl)

    with pytest.raises(
        NotImplementedError, match="OptionsBacktestRunner is an architectural placeholder"
    ):
        runner.run(strat, bars)


def test_backtest_runner_refuses_options_iron_condor() -> None:
    """Verify BacktestRunner refuses multi-leg option strategy (Iron Condor) with UnsupportedStrategyError."""
    from aditrader.backtesting import UnsupportedStrategyError
    from aditrader.strategy.library import create_nifty_iron_condor_dsl

    dsl = create_nifty_iron_condor_dsl()
    strat = compile_strategy(dsl)
    bars = _generate_bars()
    runner = BacktestRunner()

    with pytest.raises(UnsupportedStrategyError, match="defines 4 option leg"):
        runner.run(strat, bars)


def test_backtest_runner_refuses_options_long_straddle() -> None:
    """Verify BacktestRunner refuses multi-leg option strategy (Long Straddle) with UnsupportedStrategyError."""
    from aditrader.backtesting import UnsupportedStrategyError
    from aditrader.strategy.library import create_nifty_long_straddle_dsl

    dsl = create_nifty_long_straddle_dsl()
    strat = compile_strategy(dsl)
    bars = _generate_bars()
    runner = BacktestRunner()

    with pytest.raises(UnsupportedStrategyError, match="defines 2 option leg"):
        runner.run(strat, bars)


def test_backtest_runner_volume_participation_normal_pass() -> None:
    """Verify order within volume participation limit executes completely."""
    dsl = _build_test_strategy()
    strat = compile_strategy(dsl)
    bars = _generate_bars()

    cfg = BacktestConfig(
        trade_lots=50,
        max_volume_participation_pct=0.10,
        volume_limit_action="REJECT",
    )
    runner = BacktestRunner(cfg)
    result = runner.run(strat, bars)

    assert any(o.status == OrderStatus.FILLED and o.filled_qty == 50 for o in result.orders)
    assert len(result.trades) > 0


def test_backtest_runner_volume_participation_rejection() -> None:
    """Verify order exceeding volume participation limit is rejected under REJECT policy."""
    dsl = _build_test_strategy()
    strat = compile_strategy(dsl)
    bars = _generate_bars()

    cfg = BacktestConfig(
        trade_lots=200,
        max_volume_participation_pct=0.10,
        volume_limit_action="REJECT",
    )
    runner = BacktestRunner(cfg)
    result = runner.run(strat, bars)

    assert any(
        o.status == OrderStatus.REJECTED
        and "Volume limit exceeded: order qty (200) exceeds max participation (100"
        in (o.rejection_reason or "")
        for o in result.orders
    )
    assert len(result.trades) == 0


def test_backtest_runner_volume_participation_partial_fill() -> None:
    """Verify order exceeding volume participation limit is capped to max volume under PARTIAL_FILL policy."""
    dsl = _build_test_strategy()
    strat = compile_strategy(dsl)
    bars = _generate_bars()

    cfg = BacktestConfig(
        trade_lots=200,
        max_volume_participation_pct=0.10,
        volume_limit_action="PARTIAL_FILL",
        risk_limits=RiskLimits(max_concurrent_lots=500),
    )
    runner = BacktestRunner(cfg)
    result = runner.run(strat, bars)

    assert any(o.status == OrderStatus.FILLED and o.filled_qty == 100 for o in result.orders)
    assert len(result.trades) > 0
    assert result.trades[0].qty == 100


def test_backtest_runner_intraday_circuit_breaker_session_reset() -> None:
    """Verify intraday circuit breaker trips on Day 1 loss and resets on Day 2 session start."""
    from aditrader.core.risk.models import RiskRejectionReason

    dsl = StrategyDSL(
        schema_version="1.0",
        name="Session Test Strategy",
        underlying="NIFTY",
        timeframe="1m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="close",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=140.0,
                )
            ],
        ),
        legs=[],
    )

    class MultiSignalStrategy(ExecutableStrategy):
        def on_bar(self, history: list[Bar], **kwargs: Any) -> Signal | None:
            bar = history[-1]
            if bar.close >= 140.0:
                return Signal(
                    timestamp=bar.timestamp,
                    symbol=self.dsl.underlying,
                    direction=SignalDirection.BUY,
                    confidence=1.0,
                    metadata={"timeframe": self.dsl.timeframe},
                )
            return None

    day1 = datetime(2026, 3, 26, 9, 15, tzinfo=UTC)
    day2 = datetime(2026, 3, 27, 9, 15, tzinfo=UTC)

    bars = [
        # Day 1
        Bar(timestamp=day1, open=100.0, high=102.0, low=98.0, close=100.0, volume=1000, oi=0),
        Bar(
            timestamp=day1 + timedelta(minutes=1),
            open=100.0,
            high=200.0,
            low=100.0,
            close=200.0,
            volume=1000,
            oi=0,
        ),
        Bar(
            timestamp=day1 + timedelta(minutes=2),
            open=200.0,
            high=200.0,
            low=130.0,
            close=130.0,
            volume=1000,
            oi=0,
        ),
        Bar(
            timestamp=day1 + timedelta(minutes=3),
            open=130.0,
            high=200.0,
            low=130.0,
            close=200.0,
            volume=1000,
            oi=0,
        ),
        Bar(
            timestamp=day1 + timedelta(minutes=4),
            open=200.0,
            high=200.0,
            low=195.0,
            close=200.0,
            volume=1000,
            oi=0,
        ),
        # Day 2: Session transition resets intraday circuit breaker
        Bar(timestamp=day2, open=200.0, high=205.0, low=198.0, close=200.0, volume=1000, oi=0),
        Bar(
            timestamp=day2 + timedelta(minutes=1),
            open=200.0,
            high=202.0,
            low=199.0,
            close=200.0,
            volume=1000,
            oi=0,
        ),
        Bar(
            timestamp=day2 + timedelta(minutes=2),
            open=200.0,
            high=205.0,
            low=198.0,
            close=200.0,
            volume=1000,
            oi=0,
        ),
    ]

    cfg = BacktestConfig(
        initial_capital=100_000.0,
        trade_lots=100,
        risk_limits=RiskLimits(portfolio_drawdown_limit_pct=0.05, max_concurrent_lots=500),
    )
    runner = BacktestRunner(cfg)
    result = runner.run(MultiSignalStrategy(dsl), bars)

    assert any(
        o.status == OrderStatus.REJECTED
        and RiskRejectionReason.CIRCUIT_BREAKER_ACTIVE.value in (o.rejection_reason or "")
        for o in result.orders
    )
    day2_filled_orders = [
        o
        for o in result.orders
        if o.created_at.date() == day2.date() and o.status == OrderStatus.FILLED
    ]
    assert len(day2_filled_orders) >= 1


def test_backtest_runner_terminal_open_position_accounting() -> None:
    """Verify terminal open position is reported with unrealized loss and liquidation friction without fake exit trades."""
    dsl = StrategyDSL(
        schema_version="1.0",
        name="Hold Strategy",
        underlying="NIFTY",
        timeframe="1m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="close",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=100.0,
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
                    threshold=999999.0,
                )
            ],
        ),
        legs=[],
    )

    start_dt = datetime(2026, 3, 26, 9, 15, tzinfo=UTC)
    bars = [
        Bar(timestamp=start_dt, open=95.0, high=98.0, low=94.0, close=95.0, volume=1000, oi=0),
        Bar(
            timestamp=start_dt + timedelta(minutes=1),
            open=95.0,
            high=105.0,
            low=95.0,
            close=105.0,
            volume=1000,
            oi=0,
        ),
        Bar(
            timestamp=start_dt + timedelta(minutes=2),
            open=105.0,
            high=106.0,
            low=104.0,
            close=105.0,
            volume=1000,
            oi=0,
        ),
        Bar(
            timestamp=start_dt + timedelta(minutes=3),
            open=105.0,
            high=105.0,
            low=79.0,
            close=80.0,
            volume=1000,
            oi=0,
        ),
    ]

    cfg = BacktestConfig(initial_capital=100_000.0, trade_lots=10)
    runner = BacktestRunner(cfg)
    result = runner.run(compile_strategy(dsl), bars)

    # 1. Open position remains at simulation terminus
    assert len(result.terminal_positions) == 1
    assert result.terminal_positions[0].symbol == "NIFTY"
    assert result.terminal_positions[0].qty == 10

    # 2. Terminal unrealized PnL is negative (bought at ~105, final close is 80)
    assert result.terminal_unrealized_pnl < -200.0

    # 3. Liquidated ending equity reflects mark-to-market plus full exit charges & slippage friction
    assert result.liquidated_ending_equity is not None
    assert result.liquidated_ending_equity < result.equity_curve[-1]

    # 4. No artificial closed trades injected into roundtrip trade performance
    assert result.performance.total_trades == 0
    assert result.performance.ending_equity == result.equity_curve[-1]
