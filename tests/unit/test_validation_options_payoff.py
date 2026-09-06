"""Unit tests for OptionsTheoreticalValidator verifying theoretical payoff and Greek risk validation."""

import pytest

from aditrader.core.models.enums import OrderSide
from aditrader.strategy.builder.schema import (
    ASTOperator,
    ConditionCategory,
    ConditionGroup,
    ConditionNode,
    StrategyDSL,
    StrategyLegDefinition,
)
from aditrader.validation.institutional.options_payoff import OptionsTheoreticalValidator
from aditrader.validation.models import (
    SampleSizeStatus,
    ValidationScope,
    ValidationStatus,
)
from aditrader.validation.policies import (
    create_institutional_policy,
    create_research_policy,
)


def _build_bull_call_spread() -> StrategyDSL:
    """Defined-risk Bull Call Spread on NIFTY: Buy ATM CE (+0), Sell OTM CE (+2)."""
    return StrategyDSL(
        schema_version="1.0",
        name="Nifty Bull Call Spread",
        underlying="NIFTY",
        timeframe="15m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="rsi",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=50.0,
                )
            ],
        ),
        legs=[
            StrategyLegDefinition(
                contract_type="CE",
                side=OrderSide.BUY,
                strike_offset=0,
                lots=1,
            ),
            StrategyLegDefinition(
                contract_type="CE",
                side=OrderSide.SELL,
                strike_offset=2,
                lots=1,
            ),
        ],
    )


def _build_iron_condor() -> StrategyDSL:
    """Defined-risk Iron Condor on NIFTY."""
    return StrategyDSL(
        schema_version="1.0",
        name="Nifty Iron Condor",
        underlying="NIFTY",
        timeframe="1h",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="iv_rank",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=60.0,
                )
            ],
        ),
        legs=[
            StrategyLegDefinition(
                contract_type="PE",
                side=OrderSide.BUY,
                strike_offset=-4,
                lots=1,
            ),
            StrategyLegDefinition(
                contract_type="PE",
                side=OrderSide.SELL,
                strike_offset=-2,
                lots=1,
            ),
            StrategyLegDefinition(
                contract_type="CE",
                side=OrderSide.SELL,
                strike_offset=2,
                lots=1,
            ),
            StrategyLegDefinition(
                contract_type="CE",
                side=OrderSide.BUY,
                strike_offset=4,
                lots=1,
            ),
        ],
    )


def _build_naked_short_call() -> StrategyDSL:
    """Undefined-risk Naked Short Call: Sell OTM CE (+1) without wings."""
    return StrategyDSL(
        schema_version="1.0",
        name="Naked Short Call",
        underlying="NIFTY",
        timeframe="15m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="rsi",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=70.0,
                )
            ],
        ),
        legs=[
            StrategyLegDefinition(
                contract_type="CE",
                side=OrderSide.SELL,
                strike_offset=1,
                lots=1,
            ),
        ],
    )


def test_options_payoff_defined_risk_bull_call_spread() -> None:
    dsl = _build_bull_call_spread()
    res = OptionsTheoreticalValidator.validate(dsl)

    assert res.status == ValidationStatus.APPROVED
    assert res.validation_scope == ValidationScope.THEORETICAL
    assert res.historical_vs_theoretical == "THEORETICAL"
    assert res.sample_size_status == SampleSizeStatus.NOT_APPLICABLE
    assert res.metrics["is_defined_risk"] is True
    assert res.metrics["max_loss"] is not None
    assert res.metrics["max_profit"] is not None
    assert "DEFINED_RISK_ARCHITECTURE" not in res.failed_gates
    assert len(res.failed_gates) == 0

    # Ensure no historical metrics are emitted
    assert "expectancy" not in res.metrics
    assert "sharpe_ratio" not in res.metrics
    assert "profit_factor" not in res.metrics
    assert "win_rate" not in res.metrics


def test_options_payoff_iron_condor_approval() -> None:
    dsl = _build_iron_condor()
    res = OptionsTheoreticalValidator.validate(dsl)

    assert res.status == ValidationStatus.APPROVED
    assert res.validation_scope == ValidationScope.THEORETICAL
    assert res.metrics["is_defined_risk"] is True
    assert len(res.metrics["breakevens"]) == 2


def test_options_payoff_naked_short_rejected_by_institutional_policy() -> None:
    dsl = _build_naked_short_call()
    policy = create_institutional_policy()
    res = OptionsTheoreticalValidator.validate(dsl, policy=policy)

    assert res.status == ValidationStatus.REJECTED
    assert "DEFINED_RISK_ARCHITECTURE" in res.failed_gates
    assert res.metrics["is_defined_risk"] is False
    assert any("undefined tail risk" in w for w in res.warnings)


def test_options_payoff_naked_short_under_research_policy() -> None:
    dsl = _build_naked_short_call()
    policy = create_research_policy()
    res = OptionsTheoreticalValidator.validate(dsl, policy=policy)

    assert res.metrics["is_defined_risk"] is False
    assert any("undefined tail risk" in w for w in res.warnings)


def test_options_payoff_risk_reward_threshold_breach() -> None:
    dsl = _build_bull_call_spread()
    policy = create_institutional_policy()
    strict_policy = policy.model_copy(update={"max_theoretical_risk_reward_ratio": 0.01})
    res = OptionsTheoreticalValidator.validate(dsl, policy=strict_policy)

    assert "THEORETICAL_RISK_REWARD_RATIO" in res.failed_gates
    assert res.status in (ValidationStatus.REJECTED, ValidationStatus.NOT_RECOMMENDED)


def test_options_payoff_refuses_linear_strategy() -> None:
    linear_dsl = StrategyDSL(
        schema_version="1.0",
        name="Linear Strategy",
        underlying="INFY",
        timeframe="5m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="close",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=1500.0,
                )
            ],
        ),
        legs=[],
    )

    with pytest.raises(ValueError, match="has no option legs"):
        OptionsTheoreticalValidator.validate(linear_dsl)
