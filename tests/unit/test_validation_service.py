"""Unit tests for StrategyValidationService and check_research_availability."""

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
from aditrader.validation.models import (
    ValidationScope,
    ValidationStatus,
)
from aditrader.validation.service import (
    StrategyValidationService,
    check_research_availability,
)


def _make_equity_dsl() -> StrategyDSL:
    return StrategyDSL(
        schema_version="1.0",
        name="Equity Trend Following",
        underlying="TCS",
        timeframe="15m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="close",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=3500.0,
                )
            ],
        ),
        legs=[],
    )


def _make_options_dsl() -> StrategyDSL:
    return StrategyDSL(
        schema_version="1.0",
        name="Nifty Bear Put Spread",
        underlying="NIFTY",
        timeframe="15m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="rsi",
                    operator=ASTOperator.LESS_THAN,
                    threshold=40.0,
                )
            ],
        ),
        legs=[
            StrategyLegDefinition(
                contract_type="PE",
                side=OrderSide.BUY,
                strike_offset=0,
                lots=1,
            ),
            StrategyLegDefinition(
                contract_type="PE",
                side=OrderSide.SELL,
                strike_offset=-2,
                lots=1,
            ),
        ],
    )


def _make_backtest_result(trades: int = 120, expectancy: float = 80.0) -> BacktestResult:
    perf = PerformanceReport(
        starting_equity=100_000.0,
        ending_equity=110_000.0,
        net_profit=10_000.0,
        return_pct=0.10,
        total_trades=trades,
        winning_trades=int(trades * 0.6),
        losing_trades=int(trades * 0.4),
        win_rate=0.60,
        gross_profit=20_000.0,
        gross_loss=10_000.0,
        profit_factor=2.0,
        expectancy=expectancy,
        max_drawdown_amount=5_000.0,
        max_drawdown_pct=0.05,
        sharpe_ratio=1.5,
        sortino_ratio=2.0,
        sqn=2.5,
    )
    return BacktestResult(
        strategy_name="Equity Trend Following",
        underlying="TCS",
        bar_count=600,
        signals=[],
        orders=[],
        trades=[],
        equity_curve=[100_000.0, 110_000.0],
        equity_timestamps=[],
        performance=perf,
    )


def test_check_research_availability() -> None:
    equity_dsl = _make_equity_dsl()
    avail_eq = check_research_availability(equity_dsl)
    assert avail_eq.status == "AVAILABLE"
    assert "Historical Backtest" in avail_eq.permitted_alternatives

    opt_dsl = _make_options_dsl()
    avail_opt = check_research_availability(opt_dsl)
    assert avail_opt.status == "RESEARCH_UNAVAILABLE"
    assert "Analyze Payoff & Greeks" in avail_opt.permitted_alternatives
    assert "Historical Backtest" not in avail_opt.permitted_alternatives


def test_service_ast_failure_short_circuit() -> None:
    service = StrategyValidationService()
    # Schema version 99.0 triggers AST rejection
    bad_dict = {
        "schema_version": "99.0",
        "name": "Unsupported Version Strategy",
        "underlying": "INFY",
        "timeframe": "5m",
        "entry_conditions": {
            "operator": "AND",
            "conditions": [
                {
                    "category": "indicator",
                    "field": "close",
                    "operator": "GREATER_THAN",
                    "threshold": 1000.0,
                }
            ],
        },
        "legs": [],
    }
    res = service.validate(bad_dict)
    assert res.status == ValidationStatus.REJECTED
    assert res.validation_scope == ValidationScope.STRUCTURAL
    assert "SCHEMA_VERSION_CHECK" in res.failed_gates


def test_service_options_path_without_backtest_result() -> None:
    service = StrategyValidationService()
    opt_dsl = _make_options_dsl()
    res = service.validate(opt_dsl)

    assert res.validation_scope == ValidationScope.THEORETICAL
    assert res.status == ValidationStatus.APPROVED
    assert res.historical_vs_theoretical == "THEORETICAL"


def test_service_options_path_rejects_backtest_result() -> None:
    service = StrategyValidationService()
    opt_dsl = _make_options_dsl()
    bt_res = _make_backtest_result()

    with pytest.raises(ValueError, match="cannot accept a historical BacktestResult"):
        service.validate(opt_dsl, backtest_result=bt_res)


def test_service_linear_path_missing_backtest_result() -> None:
    service = StrategyValidationService()
    equity_dsl = _make_equity_dsl()
    res = service.validate(equity_dsl)

    assert res.validation_scope == ValidationScope.HISTORICAL
    assert res.status == ValidationStatus.NOT_RECOMMENDED
    assert "MISSING_BACKTEST_RESULT" in res.failed_gates


def test_service_linear_path_with_backtest_result() -> None:
    service = StrategyValidationService()
    equity_dsl = _make_equity_dsl()
    bt_res = _make_backtest_result()
    res = service.validate(equity_dsl, backtest_result=bt_res)

    assert res.validation_scope == ValidationScope.HISTORICAL
    assert res.status == ValidationStatus.APPROVED
    assert res.historical_vs_theoretical == "HISTORICAL"


def test_service_validates_raw_dict() -> None:
    service = StrategyValidationService()
    equity_dsl = _make_equity_dsl()
    dict_payload = equity_dsl.model_dump(mode="json")

    bt_res = _make_backtest_result()
    res = service.validate(dict_payload, backtest_result=bt_res)

    assert res.validation_scope == ValidationScope.HISTORICAL
    assert res.status == ValidationStatus.APPROVED
