"""Executable strategy compiler engine.

Converts declarative JSON AST trees into stateless, deterministic execution
objects implementing on_bar(history: list[Bar]) -> Signal | None.

Per ADR 002 and ADR 007:
- Zero dynamic code execution (eval, exec).
- Generates pure Signal objects; contains zero broker order routing code.
"""

from typing import Any

from aditrader.core.models.enums import SignalDirection
from aditrader.core.models.market_data import Bar
from aditrader.core.models.trade_signal import Signal
from aditrader.options.models import Greeks
from aditrader.strategy.builder.conditions import EvaluationContext
from aditrader.strategy.builder.schema import StrategyDSL
from aditrader.strategy.compiler.evaluators import DefaultASTEvaluator


class ExecutableStrategy:
    """Compiled state machine executing strategy AST rules against bar updates."""

    def __init__(self, dsl: StrategyDSL, evaluator: DefaultASTEvaluator | None = None) -> None:
        self.dsl = dsl
        self.evaluator = evaluator or DefaultASTEvaluator()
        self._position_active: bool = False

    @property
    def position_active(self) -> bool:
        """Indicates whether an active entry position has been triggered."""
        return self._position_active

    def reset(self) -> None:
        """Reset internal state machine to initial position."""
        self._position_active = False

    def evaluate_entry(self, context: EvaluationContext) -> bool:
        """Stateless evaluation of entry condition tree."""
        return self.evaluator.evaluate(self.dsl.entry_conditions, context)

    def evaluate_exit(self, context: EvaluationContext) -> bool:
        """Stateless evaluation of exit condition tree."""
        if self.dsl.exit_conditions is None:
            return False
        return self.evaluator.evaluate(self.dsl.exit_conditions, context)

    def on_bar(
        self,
        history: list[Bar],
        *,
        greeks: Greeks | None = None,
        current_premium: float | None = None,
        entry_premium: float | None = None,
        open_interest: int | None = None,
        put_call_ratio: float | None = None,
        market_regime: str | None = None,
        extra_data: dict[str, Any] | None = None,
    ) -> Signal | None:
        """Process a point-in-time bar update and emit a trading Signal if conditions match.

        Args:
            history: Chronological list of historical bars up to and including current bar.
            greeks: Optional live Greek sensitivities.
            current_premium: Optional current option/spread premium.
            entry_premium: Optional entry execution premium.
            open_interest: Optional current open interest.
            put_call_ratio: Optional current PCR.
            market_regime: Optional market regime classifier string.
            extra_data: Optional supplementary metadata.

        Returns:
            Signal object if an entry or exit condition triggers, else None.
        """
        if not history:
            return None

        current_bar = history[-1]
        context = EvaluationContext(
            history=history,
            current_time=current_bar.timestamp,
            greeks=greeks,
            current_premium=current_premium,
            entry_premium=entry_premium,
            open_interest=open_interest,
            put_call_ratio=put_call_ratio,
            market_regime=market_regime or self.dsl.target_regime,
            extra_data=extra_data or {},
        )

        if not self._position_active:
            if self.evaluate_entry(context):
                self._position_active = True
                return Signal(
                    timestamp=current_bar.timestamp,
                    symbol=self.dsl.underlying,
                    direction=SignalDirection.BUY,
                    confidence=1.0,
                    metadata={
                        "strategy_name": self.dsl.name,
                        "action": "ENTRY",
                        "timeframe": self.dsl.timeframe,
                        "legs": [leg.model_dump() for leg in self.dsl.legs],
                        "target_regime": self.dsl.target_regime,
                    },
                )
        else:
            if self.evaluate_exit(context):
                self._position_active = False
                return Signal(
                    timestamp=current_bar.timestamp,
                    symbol=self.dsl.underlying,
                    direction=SignalDirection.SELL,
                    confidence=1.0,
                    metadata={
                        "strategy_name": self.dsl.name,
                        "action": "EXIT",
                        "reason": "exit_conditions_satisfied",
                    },
                )

        return None


def compile_strategy(dsl: StrategyDSL) -> ExecutableStrategy:
    """Compile declarative StrategyDSL into an executable state machine.

    Args:
        dsl: Validated declarative Strategy AST specification.

    Returns:
        ExecutableStrategy instance ready for deterministic simulation.
    """
    return ExecutableStrategy(dsl=dsl)
