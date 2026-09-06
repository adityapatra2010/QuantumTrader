"""Unit tests for Strategy Builder declarative JSON AST schema validation."""

import pytest
from pydantic import ValidationError

from aditrader.core.models.enums import OrderSide
from aditrader.strategy.builder.schema import (
    ASTOperator,
    ConditionCategory,
    ConditionGroup,
    ConditionNode,
    StrategyDSL,
    StrategyLegDefinition,
)


def test_valid_strategy_dsl_instantiation() -> None:
    """Verify that a well-formed StrategyDSL parses cleanly."""
    dsl = StrategyDSL(
        schema_version="1.0",
        name="Valid Test Strategy",
        underlying="NIFTY",
        timeframe="5m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    indicator="RSI",
                    indicator_params={"period": 14},
                    operator=ASTOperator.GREATER_THAN,
                    threshold=50.0,
                )
            ],
        ),
        legs=[
            StrategyLegDefinition(contract_type="CE", side=OrderSide.BUY, strike_offset=0, lots=1)
        ],
    )
    assert dsl.schema_version == "1.0"
    assert dsl.name == "Valid Test Strategy"
    assert len(dsl.entry_conditions.conditions) == 1
    assert len(dsl.legs) == 1


def test_invalid_schema_version_rejected() -> None:
    """Verify that unsupported schema_version values raise ValidationError."""
    with pytest.raises(ValidationError) as exc_info:
        StrategyDSL(
            schema_version="2.0",  # type: ignore[arg-type]
            name="Invalid Schema Strategy",
            underlying="NIFTY",
            timeframe="5m",
            entry_conditions=ConditionGroup(
                operator=ASTOperator.AND,
                conditions=[
                    ConditionNode(
                        category=ConditionCategory.INDICATOR,
                        indicator="RSI",
                        operator=ASTOperator.GREATER_THAN,
                        threshold=50.0,
                    )
                ],
            ),
        )
    assert "schema_version" in str(exc_info.value)


def test_logical_operator_rejected_in_leaf_node() -> None:
    """Verify that composite operators (AND, OR, NOT) cannot be used as leaf operators."""
    with pytest.raises(ValidationError) as exc_info:
        ConditionNode(
            category=ConditionCategory.INDICATOR,
            indicator="RSI",
            operator=ASTOperator.AND,
            threshold=50.0,
        )
    assert "Logical operator AND cannot be used as a leaf operator" in str(exc_info.value)


def test_within_range_operand_validation() -> None:
    """Verify that WITHIN_RANGE enforces both range_min and range_max and min <= max."""
    # Missing range_max
    with pytest.raises(ValidationError) as exc_info:
        ConditionNode(
            category=ConditionCategory.INDICATOR,
            indicator="RSI",
            operator=ASTOperator.WITHIN_RANGE,
            range_min=40.0,
        )
    assert "WITHIN_RANGE requires both 'range_min' and 'range_max'" in str(exc_info.value)

    # range_min > range_max
    with pytest.raises(ValidationError) as exc_info_order:
        ConditionNode(
            category=ConditionCategory.INDICATOR,
            indicator="RSI",
            operator=ASTOperator.WITHIN_RANGE,
            range_min=70.0,
            range_max=30.0,
        )
    assert "cannot be greater than range_max" in str(exc_info_order.value)


def test_matches_regime_requires_target_regime() -> None:
    """Verify that MATCHES_REGIME requires target_regime field."""
    with pytest.raises(ValidationError) as exc_info:
        ConditionNode(
            category=ConditionCategory.REGIME,
            operator=ASTOperator.MATCHES_REGIME,
        )
    assert "Operator MATCHES_REGIME requires 'target_regime'" in str(exc_info.value)


def test_crosses_above_requires_comparison_target() -> None:
    """Verify that CROSSES_ABOVE requires a target to cross."""
    with pytest.raises(ValidationError) as exc_info:
        ConditionNode(
            category=ConditionCategory.INDICATOR,
            indicator="EMA",
            operator=ASTOperator.CROSSES_ABOVE,
        )
    assert "requires 'threshold', 'compare_to_field', or 'compare_indicator'" in str(exc_info.value)


def test_condition_group_not_requires_exactly_one_child() -> None:
    """Verify that NOT group rejects empty or multiple conditions."""
    # Empty
    with pytest.raises(ValidationError) as exc_empty:
        ConditionGroup(
            operator=ASTOperator.NOT,
            conditions=[],
        )
    assert "Operator NOT must contain exactly one child condition" in str(exc_empty.value)

    # Multiple
    child1 = ConditionNode(
        category=ConditionCategory.INDICATOR,
        indicator="RSI",
        operator=ASTOperator.GREATER_THAN,
        threshold=50.0,
    )
    child2 = ConditionNode(
        category=ConditionCategory.INDICATOR,
        indicator="SMA",
        operator=ASTOperator.LESS_THAN,
        threshold=100.0,
    )
    with pytest.raises(ValidationError) as exc_multi:
        ConditionGroup(
            operator=ASTOperator.NOT,
            conditions=[child1, child2],
        )
    assert "Operator NOT must contain exactly one child condition" in str(exc_multi.value)


def test_condition_group_and_requires_at_least_one_child() -> None:
    """Verify that AND/OR groups reject empty conditions list."""
    with pytest.raises(ValidationError) as exc_empty:
        ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[],
        )
    assert "requires at least one child condition" in str(exc_empty.value)


def test_immutability_enforced() -> None:
    """Verify frozen immutability of AST nodes."""
    node = ConditionNode(
        category=ConditionCategory.INDICATOR,
        indicator="RSI",
        operator=ASTOperator.GREATER_THAN,
        threshold=50.0,
    )
    with pytest.raises(ValidationError):
        setattr(node, "threshold", 60.0)
