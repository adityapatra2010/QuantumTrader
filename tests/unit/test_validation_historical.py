"""Unit tests for historical statistical validation on linear assets (Equities & Futures)."""

import pytest

from aditrader.backtesting.analytics.metrics import PerformanceReport
from aditrader.backtesting.runner import BacktestResult
from aditrader.core.models.enums import OrderSide
from aditrader.strategy.builder.schema import (
    ASTOperator,
    ConditionCategory,
    ConditionGroup,
    ConditionNode,
    StrategyDSL,
    StrategyLegDefinition,
)
from aditrader.validation.institutional.historical import HistoricalStatisticalValidator
from aditrader.validation.models import (
    SampleSizeStatus,
    ValidationScope,
    ValidationStatus,
)
from aditrader.validation.policies import (
    create_institutional_policy,
    create_moderate_policy,
    create_research_policy,
)


def _build_test_dsl(underlying: str = "RELIANCE") -> StrategyDSL:
    return StrategyDSL(
        schema_version="1.0",
        name="Equity Momentum Strategy",
        underlying=underlying,
        timeframe="5m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="close",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=2500.0,
                )
            ],
        ),
        legs=[],
    )


def _build_backtest_result(
    total_trades: int = 120,
    expectancy: float = 150.0,
    profit_factor: float = 1.65,
    max_drawdown_pct: float = 0.08,
    sharpe_ratio: float = 1.45,
    sortino_ratio: float = 1.80,
    sqn: float = 2.10,
    net_profit: float = 18_000.0,
) -> BacktestResult:
    perf = PerformanceReport(
        starting_equity=100_000.0,
        ending_equity=100_000.0 + net_profit,
        net_profit=net_profit,
        return_pct=net_profit / 100_000.0,
        total_trades=total_trades,
        winning_trades=int(total_trades * 0.6),
        losing_trades=int(total_trades * 0.4),
        win_rate=0.60,
        gross_profit=30_000.0,
        gross_loss=12_000.0,
        profit_factor=profit_factor,
        expectancy=expectancy,
        max_drawdown_amount=8_000.0,
        max_drawdown_pct=max_drawdown_pct,
        sharpe_ratio=sharpe_ratio,
        sortino_ratio=sortino_ratio,
        sqn=sqn,
    )
    return BacktestResult(
        strategy_name="Equity Momentum Strategy",
        underlying="RELIANCE",
        bar_count=500,
        signals=[],
        orders=[],
        trades=[],
        equity_curve=[100_000.0, 118_000.0],
        equity_timestamps=[],
        performance=perf,
    )


def test_historical_validation_approved_strategy() -> None:
    dsl = _build_test_dsl()
    res = _build_backtest_result()
    val_res = HistoricalStatisticalValidator.validate(dsl, res)

    assert val_res.status == ValidationStatus.APPROVED
    assert val_res.validation_scope == ValidationScope.HISTORICAL
    assert val_res.sample_size_status == SampleSizeStatus.SUFFICIENT_SAMPLE
    assert val_res.validation_score >= 80.0
    assert len(val_res.failed_gates) == 0
    assert val_res.historical_vs_theoretical == "HISTORICAL"


def test_historical_validation_negative_expectancy_rejection() -> None:
    dsl = _build_test_dsl()
    res = _build_backtest_result(expectancy=-25.0, profit_factor=0.85, net_profit=-5_000.0)
    val_res = HistoricalStatisticalValidator.validate(dsl, res)

    assert val_res.status == ValidationStatus.REJECTED
    assert "POSITIVE_EXPECTANCY_FLOOR" in val_res.failed_gates
    assert val_res.validation_score <= 25.0


def test_historical_validation_inadequate_sample_size() -> None:
    dsl = _build_test_dsl()
    # 5m timeframe default institutional requirement is 100 trades. 20 trades is insufficient.
    res = _build_backtest_result(total_trades=20)
    policy = create_institutional_policy()
    val_res = HistoricalStatisticalValidator.validate(dsl, res, policy)

    assert val_res.status == ValidationStatus.REJECTED
    assert val_res.sample_size_status == SampleSizeStatus.INSUFFICIENT_SAMPLE
    assert "SAMPLE_SIZE_SIGNIFICANCE" in val_res.failed_gates


def test_historical_validation_inadequate_sample_moderate_policy() -> None:
    dsl = _build_test_dsl()
    # Moderate policy flags NOT_RECOMMENDED on insufficient sample instead of hard reject
    res = _build_backtest_result(total_trades=25)
    policy = create_moderate_policy()
    val_res = HistoricalStatisticalValidator.validate(dsl, res, policy)

    assert val_res.status == ValidationStatus.NOT_RECOMMENDED
    assert val_res.sample_size_status == SampleSizeStatus.INSUFFICIENT_SAMPLE


def test_historical_validation_excessive_drawdown() -> None:
    dsl = _build_test_dsl()
    # Institutional policy allows max 15% drawdown. 22% breaches limit.
    res = _build_backtest_result(max_drawdown_pct=0.22)
    val_res = HistoricalStatisticalValidator.validate(dsl, res)

    assert val_res.status == ValidationStatus.REJECTED
    assert "MAX_DRAWDOWN_TOLERANCE" in val_res.failed_gates


def test_historical_validation_poor_profit_factor() -> None:
    dsl = _build_test_dsl()
    # Institutional target is 1.30. 1.10 breaches target threshold.
    res = _build_backtest_result(profit_factor=1.10)
    val_res = HistoricalStatisticalValidator.validate(dsl, res)

    assert val_res.status == ValidationStatus.REJECTED
    assert "PROFIT_FACTOR_TARGET" in val_res.failed_gates


def test_historical_validation_oos_robustness_failure() -> None:
    dsl = _build_test_dsl()
    is_res = _build_backtest_result(sharpe_ratio=2.0)
    # OOS Sharpe is 0.40 -> 0.40 / 2.0 = 0.20 retention < 0.50 policy threshold!
    oos_res = _build_backtest_result(sharpe_ratio=0.40)

    val_res = HistoricalStatisticalValidator.validate(dsl, is_res, oos_result=oos_res)
    assert val_res.status == ValidationStatus.REJECTED
    assert "OOS_SHARPE_RETENTION" in val_res.failed_gates


def test_historical_validation_walk_forward_consistency_failure() -> None:
    dsl = _build_test_dsl()
    main_res = _build_backtest_result()

    # 4 windows: only 1 profitable (25% < 60% requirement)
    wf_windows = [
        _build_backtest_result(net_profit=1000.0),
        _build_backtest_result(net_profit=-2000.0),
        _build_backtest_result(net_profit=-1500.0),
        _build_backtest_result(net_profit=-800.0),
    ]

    val_res = HistoricalStatisticalValidator.validate(
        dsl, main_res, walk_forward_results=wf_windows
    )
    assert val_res.status == ValidationStatus.REJECTED
    assert "WALK_FORWARD_CONSISTENCY" in val_res.failed_gates


def test_historical_validation_refuses_options_strategy() -> None:
    # Option strategy with legs MUST be rejected by HistoricalStatisticalValidator
    dsl = StrategyDSL(
        schema_version="1.0",
        name="Option Strategy",
        underlying="NIFTY",
        timeframe="5m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="close",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=24000.0,
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
    res = _build_backtest_result()

    with pytest.raises(
        ValueError, match="Historical statistical validation is strictly prohibited for options"
    ):
        HistoricalStatisticalValidator.validate(dsl, res)


def test_historical_validation_research_policy_warnings() -> None:
    dsl = _build_test_dsl()
    # Research policy does not hard-reject on low Sharpe or higher drawdown
    res = _build_backtest_result(
        total_trades=25,
        profit_factor=1.05,
        max_drawdown_pct=0.30,
        sharpe_ratio=0.40,
    )
    val_res = HistoricalStatisticalValidator.validate(dsl, res, policy=create_research_policy())

    assert val_res.status == ValidationStatus.APPROVED
    assert val_res.policy_name == "Research"
