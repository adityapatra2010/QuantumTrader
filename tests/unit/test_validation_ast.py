"""Unit tests verifying AST structural validation rules, schema conformance, and diagnostics."""

from aditrader.core.models.enums import OrderSide
from aditrader.strategy.builder.schema import (
    ASTOperator,
    ConditionCategory,
    ConditionGroup,
    ConditionNode,
    StrategyDSL,
    StrategyLegDefinition,
)
from aditrader.validation.ast.validator import ASTValidator
from aditrader.validation.models import ValidationScope, ValidationStatus


def _build_valid_dsl() -> StrategyDSL:
    return StrategyDSL(
        schema_version="1.0",
        name="Valid Moving Average Crossover",
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
        legs=[],
    )


def test_ast_validation_valid_strategy() -> None:
    dsl = _build_valid_dsl()
    res = ASTValidator.validate(dsl)

    assert res.status == ValidationStatus.APPROVED
    assert res.validation_scope == ValidationScope.STRUCTURAL
    assert res.validation_score >= 90.0
    assert len(res.failed_gates) == 0
    assert res.asset_class == "EQUITY"
    assert res.historical_vs_theoretical == "THEORETICAL"


def test_ast_validation_malformed_json_dict() -> None:
    raw_dict = {
        "schema_version": "1.0",
        "name": "Malformed Strategy",
        # Missing "underlying", "timeframe", "entry_conditions"
    }
    res = ASTValidator.validate(raw_dict)

    assert res.status == ValidationStatus.REJECTED
    assert res.validation_score == 0.0
    assert any("SCHEMA_SYNTAX_ERROR" in gate for gate in res.failed_gates)


def test_ast_validation_unsupported_schema_version() -> None:
    raw_dict = {
        "schema_version": "2.0",
        "name": "Future Schema",
        "underlying": "NIFTY",
        "timeframe": "5m",
        "entry_conditions": {
            "operator": "AND",
            "conditions": [
                {
                    "category": "indicator",
                    "field": "close",
                    "operator": "GREATER_THAN",
                    "threshold": 100.0,
                }
            ],
        },
    }
    res = ASTValidator.validate(raw_dict)

    assert res.status == ValidationStatus.REJECTED
    assert "SCHEMA_VERSION_CHECK" in res.failed_gates


def test_ast_validation_unsupported_timeframe() -> None:
    raw_dict = {
        "schema_version": "1.0",
        "name": "Invalid Timeframe Strat",
        "underlying": "NIFTY",
        "timeframe": "99z",
        "entry_conditions": {
            "operator": "AND",
            "conditions": [
                {
                    "category": "indicator",
                    "field": "close",
                    "operator": "GREATER_THAN",
                    "threshold": 100.0,
                }
            ],
        },
    }
    res = ASTValidator.validate(raw_dict)

    assert res.status == ValidationStatus.REJECTED
    assert "TIMEFRAME_SUPPORT_CHECK" in res.failed_gates


def test_ast_validation_invalid_operator_in_leaf() -> None:
    raw_dict = {
        "schema_version": "1.0",
        "name": "Leaf Logic Strat",
        "underlying": "NIFTY",
        "timeframe": "5m",
        "entry_conditions": {
            "operator": "AND",
            "conditions": [
                {
                    "category": "indicator",
                    "field": "close",
                    "operator": "AND",  # Invalid in leaf node
                    "threshold": 100.0,
                }
            ],
        },
    }
    res = ASTValidator.validate(raw_dict)

    assert res.status == ValidationStatus.REJECTED
    assert any("SCHEMA_SYNTAX_ERROR" in g for g in res.failed_gates)


def test_ast_validation_within_range_invalid_bounds() -> None:
    raw_dict = {
        "schema_version": "1.0",
        "name": "Inverted Range Strat",
        "underlying": "NIFTY",
        "timeframe": "5m",
        "entry_conditions": {
            "operator": "AND",
            "conditions": [
                {
                    "category": "indicator",
                    "field": "close",
                    "operator": "WITHIN_RANGE",
                    "range_min": 250.0,
                    "range_max": 200.0,  # Min > Max
                }
            ],
        },
    }
    res = ASTValidator.validate(raw_dict)

    assert res.status == ValidationStatus.REJECTED
    assert any("SCHEMA_SYNTAX_ERROR" in g for g in res.failed_gates)


def test_ast_validation_crossover_missing_target() -> None:
    raw_dict = {
        "schema_version": "1.0",
        "name": "Crossover Missing Target",
        "underlying": "NIFTY",
        "timeframe": "5m",
        "entry_conditions": {
            "operator": "AND",
            "conditions": [
                {
                    "category": "indicator",
                    "field": "close",
                    "operator": "CROSSES_ABOVE",
                    # Missing compare_to_field, compare_indicator, and threshold
                }
            ],
        },
    }
    res = ASTValidator.validate(raw_dict)

    assert res.status == ValidationStatus.REJECTED
    assert any("SCHEMA_SYNTAX_ERROR" in g for g in res.failed_gates)


def test_ast_validation_regime_missing_target() -> None:
    raw_dict = {
        "schema_version": "1.0",
        "name": "Regime Missing Target",
        "underlying": "NIFTY",
        "timeframe": "5m",
        "target_regime": None,
        "entry_conditions": {
            "operator": "AND",
            "conditions": [
                {
                    "category": "regime",
                    "operator": "MATCHES_REGIME",
                    "target_regime": None,
                }
            ],
        },
    }
    res = ASTValidator.validate(raw_dict)

    assert res.status == ValidationStatus.REJECTED
    assert any("SCHEMA_SYNTAX_ERROR" in g for g in res.failed_gates)


def test_ast_validation_empty_condition_group() -> None:
    raw_dict = {
        "schema_version": "1.0",
        "name": "Empty Group",
        "underlying": "NIFTY",
        "timeframe": "5m",
        "entry_conditions": {
            "operator": "AND",
            "conditions": [],
        },
    }
    res = ASTValidator.validate(raw_dict)

    assert res.status == ValidationStatus.REJECTED
    assert any("SCHEMA_SYNTAX_ERROR" in g for g in res.failed_gates)


def test_ast_validation_not_operator_cardinality() -> None:
    raw_dict = {
        "schema_version": "1.0",
        "name": "NOT Multi Child",
        "underlying": "NIFTY",
        "timeframe": "5m",
        "entry_conditions": {
            "operator": "NOT",
            "conditions": [
                {
                    "category": "indicator",
                    "field": "close",
                    "operator": "GREATER_THAN",
                    "threshold": 100.0,
                },
                {
                    "category": "indicator",
                    "field": "close",
                    "operator": "LESS_THAN",
                    "threshold": 50.0,
                },
            ],
        },
    }
    res = ASTValidator.validate(raw_dict)

    assert res.status == ValidationStatus.REJECTED
    assert any("SCHEMA_SYNTAX_ERROR" in g for g in res.failed_gates)


def test_ast_validation_absurd_strike_offset() -> None:
    dsl = StrategyDSL(
        schema_version="1.0",
        name="Deep Absurd Strike",
        underlying="NIFTY",
        timeframe="5m",
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
        legs=[
            StrategyLegDefinition(
                contract_type="CE",
                side=OrderSide.BUY,
                strike_offset=90,  # Absurd (> 50)
                lots=1,
            )
        ],
    )
    res = ASTValidator.validate(dsl)

    assert res.status == ValidationStatus.REJECTED
    assert any("STRIKE_OFFSET_BOUNDS" in g for g in res.failed_gates)


def test_ast_validation_contradictory_self_canceling_legs() -> None:
    dsl = StrategyDSL(
        schema_version="1.0",
        name="Self Canceling Strategy",
        underlying="NIFTY",
        timeframe="5m",
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
        legs=[
            StrategyLegDefinition(
                contract_type="CE",
                side=OrderSide.BUY,
                strike_offset=1,
                lots=2,
                expiry_offset=0,
            ),
            StrategyLegDefinition(
                contract_type="CE",
                side=OrderSide.SELL,
                strike_offset=1,
                lots=2,
                expiry_offset=0,
            ),
        ],
    )
    res = ASTValidator.validate(dsl)

    assert res.status == ValidationStatus.REJECTED
    assert any("CONTRADICTORY_SELF_CANCELING_LEGS" in g for g in res.failed_gates)
