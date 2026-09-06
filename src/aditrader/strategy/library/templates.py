"""Immutable production templates for institutional option strategies."""

from datetime import UTC, datetime

from aditrader.core.models.enums import OrderSide
from aditrader.strategy.builder.schema import (
    ASTOperator,
    ConditionCategory,
    ConditionGroup,
    ConditionNode,
    StrategyDSL,
    StrategyLegDefinition,
)
from aditrader.strategy.library.dna import profile_strategy_dna
from aditrader.strategy.library.models import StrategyCategory, StrategyRecord


def create_nifty_iron_condor_dsl() -> StrategyDSL:
    """Construct Nifty Weekly Iron Condor declarative DSL."""
    return StrategyDSL(
        schema_version="1.0",
        name="Nifty Weekly Iron Condor",
        underlying="NIFTY",
        timeframe="5m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.TIME,
                    field="time_of_day",
                    operator=ASTOperator.WITHIN_RANGE,
                    range_min="09:20",
                    range_max="11:00",
                ),
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    indicator="RSI",
                    indicator_params={"period": 14},
                    operator=ASTOperator.WITHIN_RANGE,
                    range_min=40.0,
                    range_max=60.0,
                ),
            ],
        ),
        exit_conditions=ConditionGroup(
            operator=ASTOperator.OR,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.TIME,
                    field="time_of_day",
                    operator=ASTOperator.GREATER_THAN,
                    threshold="15:15",
                ),
                ConditionNode(
                    category=ConditionCategory.PREMIUM,
                    field="decay_pct",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=0.50,
                ),
            ],
        ),
        legs=[
            # Short Call Wing
            StrategyLegDefinition(contract_type="CE", side=OrderSide.SELL, strike_offset=1, lots=1),
            # Long Call Hedge
            StrategyLegDefinition(contract_type="CE", side=OrderSide.BUY, strike_offset=2, lots=1),
            # Short Put Wing
            StrategyLegDefinition(
                contract_type="PE", side=OrderSide.SELL, strike_offset=-1, lots=1
            ),
            # Long Put Hedge
            StrategyLegDefinition(contract_type="PE", side=OrderSide.BUY, strike_offset=-2, lots=1),
        ],
        target_regime="Low IV Sideways",
        metadata={"author": "AdiTrader Quantitative Engineering", "tier": "Institutional"},
    )


def create_nifty_long_straddle_dsl() -> StrategyDSL:
    """Construct Nifty Long Straddle declarative DSL."""
    return StrategyDSL(
        schema_version="1.0",
        name="Nifty Long Straddle",
        underlying="NIFTY",
        timeframe="5m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.TIME,
                    field="time_of_day",
                    operator=ASTOperator.WITHIN_RANGE,
                    range_min="09:20",
                    range_max="10:00",
                ),
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    indicator="ATR",
                    indicator_params={"period": 14},
                    operator=ASTOperator.GREATER_THAN,
                    threshold=35.0,
                ),
            ],
        ),
        exit_conditions=ConditionGroup(
            operator=ASTOperator.OR,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.TIME,
                    field="time_of_day",
                    operator=ASTOperator.GREATER_THAN,
                    threshold="15:15",
                ),
            ],
        ),
        legs=[
            StrategyLegDefinition(contract_type="CE", side=OrderSide.BUY, strike_offset=0, lots=1),
            StrategyLegDefinition(contract_type="PE", side=OrderSide.BUY, strike_offset=0, lots=1),
        ],
        target_regime="High IV Expansion",
        metadata={"author": "AdiTrader Quantitative Engineering", "tier": "Institutional"},
    )


def create_nifty_bull_call_spread_dsl() -> StrategyDSL:
    """Construct Nifty Bull Call Spread declarative DSL."""
    return StrategyDSL(
        schema_version="1.0",
        name="Nifty Bull Call Spread",
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
                    threshold=55.0,
                ),
                ConditionNode(
                    category=ConditionCategory.TIME,
                    field="time_of_day",
                    operator=ASTOperator.WITHIN_RANGE,
                    range_min="09:20",
                    range_max="14:30",
                ),
            ],
        ),
        exit_conditions=ConditionGroup(
            operator=ASTOperator.OR,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.TIME,
                    field="time_of_day",
                    operator=ASTOperator.GREATER_THAN,
                    threshold="15:15",
                ),
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    indicator="RSI",
                    indicator_params={"period": 14},
                    operator=ASTOperator.LESS_THAN,
                    threshold=45.0,
                ),
            ],
        ),
        legs=[
            # Long ATM Call
            StrategyLegDefinition(contract_type="CE", side=OrderSide.BUY, strike_offset=0, lots=1),
            # Short OTM Call
            StrategyLegDefinition(contract_type="CE", side=OrderSide.SELL, strike_offset=1, lots=1),
        ],
        target_regime="Trend Following",
        metadata={"author": "AdiTrader Quantitative Engineering", "tier": "Institutional"},
    )


def build_template_record(
    dsl: StrategyDSL,
    template_id: str,
    version: str = "1.0.0",
    validation_score: float = 95.0,
) -> StrategyRecord:
    """Wrap a declarative template into a versioned StrategyRecord with computed DNA."""
    dna = profile_strategy_dna(dsl)
    return StrategyRecord(
        id=template_id,
        name=dsl.name,
        version=version,
        category=StrategyCategory.BUILT_IN,
        creator="System",
        created_at=datetime(2026, 9, 6, 10, 0, 0, tzinfo=UTC),
        validation_score=validation_score,
        dna=dna,
        dsl_definition=dsl,
    )


def get_builtin_templates() -> dict[str, StrategyRecord]:
    """Retrieve catalog of immutable built-in institutional templates."""
    iron_condor_dsl = create_nifty_iron_condor_dsl()
    long_straddle_dsl = create_nifty_long_straddle_dsl()
    bull_call_spread_dsl = create_nifty_bull_call_spread_dsl()

    return {
        "iron_condor": build_template_record(
            iron_condor_dsl,
            template_id="tpl-iron-condor-v1",
            version="1.0.0",
            validation_score=94.0,
        ),
        "long_straddle": build_template_record(
            long_straddle_dsl,
            template_id="tpl-long-straddle-v1",
            version="1.0.0",
            validation_score=90.0,
        ),
        "bull_call_spread": build_template_record(
            bull_call_spread_dsl,
            template_id="tpl-bull-call-spread-v1",
            version="1.0.0",
            validation_score=92.0,
        ),
    }
