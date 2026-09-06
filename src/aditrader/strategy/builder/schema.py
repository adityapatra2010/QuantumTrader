"""Versioned declarative JSON AST schema for Strategy Builder.

Per ADR 001 and ADR 007:
- All strategy logic is expressed as declarative AST trees.
- Raw Python execution (eval, exec, compile) is strictly prohibited.
- Schema versioning is pinned to '1.0'.
"""

from enum import StrEnum
from typing import Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from aditrader.core.models.enums import OrderSide


class ASTOperator(StrEnum):
    """Allowed declarative AST comparison and logical operators."""

    # Leaf Comparison Operators
    GREATER_THAN = "GREATER_THAN"
    LESS_THAN = "LESS_THAN"
    EQUALS = "EQUALS"
    WITHIN_RANGE = "WITHIN_RANGE"
    CROSSES_ABOVE = "CROSSES_ABOVE"
    CROSSES_BELOW = "CROSSES_BELOW"
    MATCHES_REGIME = "MATCHES_REGIME"

    # Composite Logical Combinators
    AND = "AND"
    OR = "OR"
    NOT = "NOT"


class ConditionCategory(StrEnum):
    """Domain categorization for condition nodes."""

    INDICATOR = "indicator"
    TIME = "time"
    GREEKS = "greeks"
    PREMIUM = "premium"
    OPEN_INTEREST = "open_interest"
    MARKET_STRUCTURE = "market_structure"
    REGIME = "regime"


class StrategyLegDefinition(BaseModel):
    """Option leg template in a strategy specification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    contract_type: Literal["CE", "PE"] = Field(
        ..., description="Option type: CE (Call) or PE (Put)"
    )
    side: OrderSide = Field(..., description="Order side: BUY (Long) or SELL (Short)")
    strike_offset: int = Field(
        ...,
        description="Strike ladder offset relative to ATM (0=ATM, +1=1 strike OTM Call/ITM Put, -1=1 strike ITM Call/OTM Put)",
    )
    lots: int = Field(default=1, gt=0, description="Quantity in multiples of exchange lot size")
    expiry_offset: int = Field(
        default=0,
        ge=0,
        description="Expiry offset index (0=current near-week/month, 1=next expiry, etc.)",
    )


class ConditionNode(BaseModel):
    """Leaf condition node representing an atomic logical rule."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    category: ConditionCategory = Field(..., description="Condition domain category")
    operator: ASTOperator = Field(..., description="Leaf comparison operator")

    # Target field or indicator specification
    field: str | None = Field(default=None, description="Data field name (e.g., 'close', 'delta')")
    indicator: str | None = Field(
        default=None, description="Technical indicator name (e.g., 'RSI', 'SMA')"
    )
    indicator_params: dict[str, Any] = Field(
        default_factory=dict, description="Parameters for indicator calculation"
    )

    # Comparison operands
    threshold: float | str | None = Field(
        default=None, description="Scalar threshold for comparison"
    )
    range_min: float | str | None = Field(
        default=None, description="Minimum value for WITHIN_RANGE"
    )
    range_max: float | str | None = Field(
        default=None, description="Maximum value for WITHIN_RANGE"
    )
    target_regime: str | None = Field(
        default=None, description="Expected market regime name for MATCHES_REGIME"
    )

    # Cross-over operands (e.g., EMA9 crosses above EMA21)
    compare_to_field: str | None = Field(
        default=None, description="Field to compare against in crossover"
    )
    compare_indicator: str | None = Field(
        default=None, description="Indicator to compare against in crossover"
    )
    compare_params: dict[str, Any] = Field(
        default_factory=dict, description="Parameters for compare indicator"
    )

    @field_validator("operator")
    @classmethod
    def validate_leaf_operator(cls, op: ASTOperator) -> ASTOperator:
        """Ensure logical combinators are not placed in leaf condition nodes."""
        if op in (ASTOperator.AND, ASTOperator.OR, ASTOperator.NOT):
            raise ValueError(
                f"Logical operator {op.value} cannot be used as a leaf operator. "
                "Use ConditionGroup for logical combinations."
            )
        return op

    @model_validator(mode="after")
    def validate_node_operands(self) -> "ConditionNode":
        """Validate required parameters per leaf operator."""
        if self.operator == ASTOperator.WITHIN_RANGE:
            if self.range_min is None or self.range_max is None:
                raise ValueError(
                    "Operator WITHIN_RANGE requires both 'range_min' and 'range_max' to be defined."
                )
            if (
                isinstance(self.range_min, (int, float))
                and isinstance(self.range_max, (int, float))
                and self.range_min > self.range_max
            ):
                raise ValueError(
                    f"range_min ({self.range_min}) cannot be greater than range_max ({self.range_max})."
                )

        elif self.operator == ASTOperator.MATCHES_REGIME:
            if not self.target_regime:
                raise ValueError("Operator MATCHES_REGIME requires 'target_regime' to be defined.")

        elif self.operator in (ASTOperator.CROSSES_ABOVE, ASTOperator.CROSSES_BELOW):
            has_compare_target = (
                self.compare_to_field is not None
                or self.compare_indicator is not None
                or self.threshold is not None
            )
            if not has_compare_target:
                raise ValueError(
                    f"Operator {self.operator.value} requires 'threshold', 'compare_to_field', or 'compare_indicator'."
                )

        elif self.operator in (ASTOperator.GREATER_THAN, ASTOperator.LESS_THAN, ASTOperator.EQUALS):
            if self.threshold is None and self.compare_indicator is None and self.compare_to_field is None:
                raise ValueError(
                    f"Operator {self.operator.value} requires a 'threshold', 'compare_to_field', or 'compare_indicator'."
                )

        # Must have either a field or an indicator or target_regime
        if self.field is None and self.indicator is None and self.target_regime is None:
            raise ValueError("ConditionNode must specify either 'field', 'indicator', or 'target_regime'.")

        return self


class ConditionGroup(BaseModel):
    """Composite condition node combining child conditions via boolean logic."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    operator: Literal[ASTOperator.AND, ASTOperator.OR, ASTOperator.NOT] = Field(
        ..., description="Logical combinator: AND, OR, or NOT"
    )
    conditions: list[Union[ConditionNode, "ConditionGroup"]] = Field(
        ..., description="List of child conditions or nested condition groups"
    )

    @model_validator(mode="after")
    def validate_group_structure(self) -> "ConditionGroup":
        """Validate logical combinator constraints."""
        if self.operator == ASTOperator.NOT:
            if len(self.conditions) != 1:
                raise ValueError("Operator NOT must contain exactly one child condition.")
        else:
            if len(self.conditions) < 1:
                raise ValueError(
                    f"Logical operator {self.operator.value} requires at least one child condition."
                )
        return self


class StrategyDSL(BaseModel):
    """Root declarative Strategy AST specification."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["1.0"] = Field(
        default="1.0",
        description="Versioned AST schema identifier (pinned to '1.0' per ADR 001)",
    )
    name: str = Field(..., min_length=1, description="Human-readable strategy name")
    underlying: str = Field(
        ..., min_length=1, description="Underlying trading asset symbol (e.g., 'NIFTY')"
    )
    timeframe: str = Field(
        default="5m", description="Bar aggregation timeframe (e.g., '1m', '5m', '15m', '1d')"
    )

    entry_conditions: ConditionGroup = Field(
        ..., description="Composite condition tree determining position entry"
    )
    exit_conditions: ConditionGroup | None = Field(
        default=None, description="Optional composite condition tree determining position exit"
    )

    legs: list[StrategyLegDefinition] = Field(
        default_factory=list,
        description="Option legs to construct upon entry signal",
    )

    target_regime: str | None = Field(
        default=None, description="Optimal target market regime for this strategy"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Additional descriptive metadata"
    )

    @field_validator("schema_version")
    @classmethod
    def validate_schema_version(cls, v: str) -> str:
        """Enforce strict schema version pinning."""
        if v != "1.0":
            raise ValueError(
                f"Unsupported schema_version '{v}'. Only '1.0' is supported in this release."
            )
        return v
