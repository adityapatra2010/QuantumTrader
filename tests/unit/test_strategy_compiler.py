"""Unit tests verifying deterministic Strategy Compiler and condition evaluation engine."""

from datetime import UTC, datetime

from aditrader.core.models.enums import OrderSide, SignalDirection
from aditrader.core.models.market_data import Bar
from aditrader.options.models import Greeks
from aditrader.strategy.builder.conditions import EvaluationContext
from aditrader.strategy.builder.schema import (
    ASTOperator,
    ConditionCategory,
    ConditionGroup,
    ConditionNode,
    StrategyDSL,
    StrategyLegDefinition,
)
from aditrader.strategy.compiler.engine import compile_strategy
from aditrader.strategy.compiler.evaluators import DefaultASTEvaluator


def _create_mock_bars(n: int = 25, base_price: float = 100.0, step: float = 1.0) -> list[Bar]:
    """Helper to generate a sequence of valid Bar objects."""
    bars: list[Bar] = []
    start_dt = datetime(2026, 9, 7, 9, 15, tzinfo=UTC)
    for i in range(n):
        price = base_price + i * step
        dt = datetime.fromtimestamp(start_dt.timestamp() + i * 60, tz=UTC)
        bars.append(
            Bar(
                timestamp=dt,
                open=price,
                high=price + 2.0,
                low=price - 1.0,
                close=price + 0.5,
                volume=1000 + i * 10,
                oi=50000 + i * 100,
            )
        )
    return bars


def test_evaluator_indicator_and_logic() -> None:
    """Verify evaluation of AND condition group containing indicator rules."""
    bars = _create_mock_bars(n=30, base_price=100.0, step=2.0)
    context = EvaluationContext(history=bars)

    # Condition 1: RSI > 50 (should be True since price is steadily rising)
    # Condition 2: Close > 120 (latest close is ~ 158.5)
    and_group = ConditionGroup(
        operator=ASTOperator.AND,
        conditions=[
            ConditionNode(
                category=ConditionCategory.INDICATOR,
                indicator="RSI",
                indicator_params={"period": 14},
                operator=ASTOperator.GREATER_THAN,
                threshold=50.0,
            ),
            ConditionNode(
                category=ConditionCategory.INDICATOR,
                field="close",
                operator=ASTOperator.GREATER_THAN,
                threshold=120.0,
            ),
        ],
    )

    evaluator = DefaultASTEvaluator()
    assert evaluator.evaluate(and_group, context) is True

    # If we add an impossible condition to the AND group, it should evaluate False
    impossible_node = ConditionNode(
        category=ConditionCategory.INDICATOR,
        field="close",
        operator=ASTOperator.LESS_THAN,
        threshold=50.0,
    )
    failing_group = ConditionGroup(
        operator=ASTOperator.AND,
        conditions=[and_group, impossible_node],
    )
    assert evaluator.evaluate(failing_group, context) is False


def test_evaluator_or_and_not_logic() -> None:
    """Verify OR and NOT logical combinators."""
    bars = _create_mock_bars(n=20, base_price=100.0, step=1.0)
    context = EvaluationContext(history=bars)
    evaluator = DefaultASTEvaluator()

    false_node = ConditionNode(
        category=ConditionCategory.INDICATOR,
        field="close",
        operator=ASTOperator.LESS_THAN,
        threshold=50.0,
    )
    true_node = ConditionNode(
        category=ConditionCategory.INDICATOR,
        field="close",
        operator=ASTOperator.GREATER_THAN,
        threshold=50.0,
    )

    # OR Group (False OR True) -> True
    or_group = ConditionGroup(
        operator=ASTOperator.OR,
        conditions=[false_node, true_node],
    )
    assert evaluator.evaluate(or_group, context) is True

    # NOT Group (NOT False) -> True
    not_group = ConditionGroup(
        operator=ASTOperator.NOT,
        conditions=[false_node],
    )
    assert evaluator.evaluate(not_group, context) is True


def test_evaluator_greeks_and_premium() -> None:
    """Verify Greeks and option premium decay evaluation."""
    bars = _create_mock_bars(n=10)
    mock_greeks = Greeks(
        delta=0.45,
        gamma=0.03,
        theta=-12.5,
        theta_trading=-17.5,
        vega=8.2,
        rho=1.5,
    )
    context = EvaluationContext(
        history=bars,
        greeks=mock_greeks,
        current_premium=50.0,
        entry_premium=100.0,  # 50% decay
    )
    evaluator = DefaultASTEvaluator()

    delta_node = ConditionNode(
        category=ConditionCategory.GREEKS,
        field="delta",
        operator=ASTOperator.WITHIN_RANGE,
        range_min=0.40,
        range_max=0.50,
    )
    assert evaluator.evaluate(delta_node, context) is True

    decay_node = ConditionNode(
        category=ConditionCategory.PREMIUM,
        field="decay_pct",
        operator=ASTOperator.GREATER_THAN,
        threshold=0.40,  # 50% decay > 40%
    )
    assert evaluator.evaluate(decay_node, context) is True


def test_executable_strategy_signal_lifecycle() -> None:
    """Verify deterministic signal generation: Entry on trigger, then Exit on trigger."""
    bars = _create_mock_bars(n=30, base_price=100.0, step=2.0)

    dsl = StrategyDSL(
        schema_version="1.0",
        name="Lifecycle Test Strategy",
        underlying="NIFTY",
        timeframe="5m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="close",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=120.0,
                )
            ],
        ),
        exit_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.PREMIUM,
                    field="decay_pct",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=0.50,
                )
            ],
        ),
        legs=[
            StrategyLegDefinition(contract_type="CE", side=OrderSide.SELL, strike_offset=1, lots=1)
        ],
    )

    strategy = compile_strategy(dsl)
    assert bool(strategy.position_active) is False

    # Bar 1..10: close is < 120 -> no signal
    early_bars = bars[:10]  # latest close around 100 + 9*2 + 0.5 = 118.5
    sig1 = strategy.on_bar(early_bars)
    assert sig1 is None
    assert bool(strategy.position_active) is False

    # Bar 1..15: latest close > 120 -> Entry Signal emitted
    entry_bars = bars[:15]
    sig_entry = strategy.on_bar(entry_bars)
    assert sig_entry is not None
    assert sig_entry.direction == SignalDirection.BUY
    assert sig_entry.metadata["action"] == "ENTRY"
    assert sig_entry.symbol == "NIFTY"
    assert bool(strategy.position_active) is True

    # Next bar while position active and decay not met -> No signal
    sig_hold = strategy.on_bar(
        bars[:16],
        current_premium=80.0,
        entry_premium=100.0,  # 20% decay < 50%
    )
    assert sig_hold is None
    assert bool(strategy.position_active) is True

    # Next bar when decay > 50% -> Exit Signal emitted
    sig_exit = strategy.on_bar(
        bars[:17],
        current_premium=40.0,
        entry_premium=100.0,  # 60% decay > 50%
    )
    assert sig_exit is not None
    assert sig_exit.direction == SignalDirection.SELL
    assert sig_exit.metadata["action"] == "EXIT"
    assert bool(strategy.position_active) is False
