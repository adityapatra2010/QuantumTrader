"""AST visitor and evaluation protocols for strategy conditions.

Decouples declarative AST condition structures from domain resolution
and calculation engines. No strategy-specific logic is hardcoded here.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from aditrader.core.models.market_data import Bar
from aditrader.options.models import Greeks
from aditrader.strategy.builder.schema import (
    ASTOperator,
    ConditionGroup,
    ConditionNode,
)


class EvaluationContext(BaseModel):
    """Runtime snapshot context passed into condition evaluators."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    history: list[Bar] = Field(..., min_length=1, description="Historical OHLCV bars leading to current bar")
    current_time: datetime | None = Field(
        default=None, description="Current exchange timestamp (defaults to latest bar timestamp)"
    )
    greeks: Greeks | None = Field(default=None, description="Active position or ATM Greeks snapshot")
    current_premium: float | None = Field(
        default=None, ge=0.0, description="Current live option/strategy premium"
    )
    entry_premium: float | None = Field(
        default=None, ge=0.0, description="Entry execution premium for decay calculations"
    )
    open_interest: int | None = Field(default=None, ge=0, description="Current total open interest")
    put_call_ratio: float | None = Field(default=None, ge=0.0, description="Current Put/Call Ratio")
    market_regime: str | None = Field(
        default=None, description="Active market regime (e.g., 'Low IV Sideways')"
    )
    extra_data: dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary domain metrics for extensibility"
    )

    @property
    def current_bar(self) -> Bar:
        """Convenience accessor for the latest point-in-time bar."""
        return self.history[-1]


class ConditionValueResolver(Protocol):
    """Protocol for resolving operands and indicator values across categories."""

    def resolve_field_value(self, field: str, context: EvaluationContext) -> float | str | None:
        """Extract a scalar field value from context or current bar."""
        ...

    def resolve_indicator_series(
        self, indicator: str, params: dict[str, Any], history: list[Bar]
    ) -> list[float | None]:
        """Compute an indicator time-series over the bar history."""
        ...

    def resolve_regime(self, context: EvaluationContext) -> str | None:
        """Resolve the active market regime identifier."""
        ...


class BaseASTEvaluator(ABC):
    """Abstract base visitor evaluating ConditionNode and ConditionGroup trees."""

    @abstractmethod
    def evaluate_node(self, node: ConditionNode, context: EvaluationContext) -> bool:
        """Evaluate an atomic leaf condition node."""
        ...

    def evaluate_group(self, group: ConditionGroup, context: EvaluationContext) -> bool:
        """Evaluate a composite group node recursively."""
        if group.operator == ASTOperator.NOT:
            child = group.conditions[0]
            return not self.evaluate(child, context)

        if group.operator == ASTOperator.AND:
            return all(self.evaluate(child, context) for child in group.conditions)

        if group.operator == ASTOperator.OR:
            return any(self.evaluate(child, context) for child in group.conditions)

        raise ValueError(f"Unsupported group operator '{group.operator}'")

    def evaluate(
        self, item: ConditionNode | ConditionGroup, context: EvaluationContext
    ) -> bool:
        """Dispatch evaluation to node or group."""
        if isinstance(item, ConditionGroup):
            return self.evaluate_group(item, context)
        if isinstance(item, ConditionNode):
            return self.evaluate_node(item, context)
        raise TypeError(f"Invalid condition item type: {type(item)}")
