"""Category evaluators and AST node visitor for strategy execution.

Per ADR 007, evaluation uses statically compiled dispatch routines with
strictly typed AST operators. No dynamic code (eval/exec) is permitted.
"""

from typing import Any

from aditrader.core.models.market_data import Bar
from aditrader.strategy.builder.conditions import BaseASTEvaluator, EvaluationContext
from aditrader.strategy.builder.schema import (
    ASTOperator,
    ConditionCategory,
    ConditionNode,
)
from aditrader.strategy.compiler.indicators import (
    calculate_atr,
    calculate_bollinger_bands,
    calculate_ema,
    calculate_rsi,
    calculate_sma,
    calculate_supertrend,
)


def _compare_scalars(
    operator: ASTOperator,
    current_val: float,
    threshold: float | None = None,
    range_min: float | None = None,
    range_max: float | None = None,
    prev_val: float | None = None,
    current_ref: float | None = None,
    prev_ref: float | None = None,
) -> bool:
    """Evaluate leaf numerical comparison operator."""
    target_ref = current_ref if current_ref is not None else threshold

    if operator == ASTOperator.GREATER_THAN:
        if target_ref is None:
            return False
        return current_val > target_ref

    if operator == ASTOperator.LESS_THAN:
        if target_ref is None:
            return False
        return current_val < target_ref

    if operator == ASTOperator.EQUALS:
        if target_ref is None:
            return False
        return abs(current_val - target_ref) < 1e-6

    if operator == ASTOperator.WITHIN_RANGE:
        if range_min is None or range_max is None:
            return False
        return range_min <= current_val <= range_max

    if operator == ASTOperator.CROSSES_ABOVE:
        if prev_val is None or target_ref is None:
            return False
        ref_prev = prev_ref if prev_ref is not None else target_ref
        ref_curr = current_ref if current_ref is not None else target_ref
        return prev_val <= ref_prev and current_val > ref_curr

    if operator == ASTOperator.CROSSES_BELOW:
        if prev_val is None or target_ref is None:
            return False
        ref_prev = prev_ref if prev_ref is not None else target_ref
        ref_curr = current_ref if current_ref is not None else target_ref
        return prev_val >= ref_prev and current_val < ref_curr

    return False


def _resolve_indicator_series(
    indicator: str, params: dict[str, Any], history: list[Bar]
) -> list[float | None]:
    """Resolve indicator name and parameters against bar history."""
    ind = indicator.upper()
    closes = [b.close for b in history]
    highs = [b.high for b in history]
    lows = [b.low for b in history]

    if ind == "SMA":
        period = int(params.get("period", 14))
        return calculate_sma(closes, period=period)

    if ind == "EMA":
        period = int(params.get("period", 14))
        return calculate_ema(closes, period=period)

    if ind == "RSI":
        period = int(params.get("period", 14))
        return calculate_rsi(closes, period=period)

    if ind == "ATR":
        period = int(params.get("period", 14))
        return calculate_atr(highs, lows, closes, period=period)

    if ind in ("BOLLINGER_BANDS", "BOLLINGER", "BB"):
        period = int(params.get("period", 20))
        std_dev = float(params.get("std_dev", 2.0))
        band = str(params.get("band", "middle")).lower()
        bb_res = calculate_bollinger_bands(closes, period=period, std_dev=std_dev)
        if band == "upper":
            return [b.upper for b in bb_res]
        if band == "lower":
            return [b.lower for b in bb_res]
        return [b.middle for b in bb_res]

    if ind in ("SUPERTREND", "ST"):
        period = int(params.get("period", 10))
        multiplier = float(params.get("multiplier", 3.0))
        st_res = calculate_supertrend(highs, lows, closes, period=period, multiplier=multiplier)
        output_type = str(params.get("output", "value")).lower()
        if output_type == "direction":
            return [float(st.direction) if st.direction is not None else None for st in st_res]
        return [st.value for st in st_res]

    raise ValueError(f"Unsupported indicator '{indicator}'. Must be statically registered.")


def _resolve_bar_field(field: str, bar: Bar) -> float:
    """Extract standard numeric field from Bar."""
    f = field.lower()
    if f == "close":
        return bar.close
    if f == "open":
        return bar.open
    if f == "high":
        return bar.high
    if f == "low":
        return bar.low
    if f == "volume":
        return float(bar.volume)
    if f in ("oi", "open_interest"):
        return float(bar.oi)
    raise ValueError(f"Unknown bar field '{field}'")


class DefaultASTEvaluator(BaseASTEvaluator):
    """Complete, statically registered AST evaluator for all condition categories."""

    def evaluate_node(self, node: ConditionNode, context: EvaluationContext) -> bool:
        """Evaluate an atomic condition node against the evaluation context."""
        category = node.category

        if category == ConditionCategory.INDICATOR:
            return self._evaluate_indicator(node, context)
        if category == ConditionCategory.TIME:
            return self._evaluate_time(node, context)
        if category == ConditionCategory.GREEKS:
            return self._evaluate_greeks(node, context)
        if category == ConditionCategory.PREMIUM:
            return self._evaluate_premium(node, context)
        if category == ConditionCategory.OPEN_INTEREST:
            return self._evaluate_oi(node, context)
        if category == ConditionCategory.REGIME:
            return self._evaluate_regime(node, context)
        if category == ConditionCategory.MARKET_STRUCTURE:
            return self._evaluate_market_structure(node, context)

    def _evaluate_indicator(self, node: ConditionNode, context: EvaluationContext) -> bool:
        """Evaluate technical indicator condition."""
        if not node.indicator:
            # Maybe a field comparison (e.g. close > threshold)
            if not node.field:
                return False
            curr_val = _resolve_bar_field(node.field, context.current_bar)
            prev_val = (
                _resolve_bar_field(node.field, context.history[-2])
                if len(context.history) >= 2
                else None
            )
        else:
            series = _resolve_indicator_series(node.indicator, node.indicator_params, context.history)
            if not series or series[-1] is None:
                return False
            curr_val = series[-1]
            prev_val = series[-2] if len(series) >= 2 and series[-2] is not None else None

        # Resolve comparison target (another indicator or field or static threshold)
        curr_ref: float | None = None
        prev_ref: float | None = None

        if node.compare_indicator:
            comp_series = _resolve_indicator_series(
                node.compare_indicator, node.compare_params, context.history
            )
            if not comp_series or comp_series[-1] is None:
                return False
            curr_ref = comp_series[-1]
            prev_ref = comp_series[-2] if len(comp_series) >= 2 and comp_series[-2] is not None else None
        elif node.compare_to_field:
            curr_ref = _resolve_bar_field(node.compare_to_field, context.current_bar)
            prev_ref = (
                _resolve_bar_field(node.compare_to_field, context.history[-2])
                if len(context.history) >= 2
                else None
            )

        thresh = float(node.threshold) if node.threshold is not None else None
        r_min = float(node.range_min) if node.range_min is not None else None
        r_max = float(node.range_max) if node.range_max is not None else None

        return _compare_scalars(
            operator=node.operator,
            current_val=curr_val,
            threshold=thresh,
            range_min=r_min,
            range_max=r_max,
            prev_val=prev_val,
            current_ref=curr_ref,
            prev_ref=prev_ref,
        )

    def _evaluate_time(self, node: ConditionNode, context: EvaluationContext) -> bool:
        """Evaluate time and session condition."""
        bar_time = context.current_time or context.current_bar.timestamp
        time_str = bar_time.strftime("%H:%M")

        if node.operator == ASTOperator.WITHIN_RANGE:
            min_str = str(node.range_min) if node.range_min is not None else ""
            max_str = str(node.range_max) if node.range_max is not None else ""
            return min_str <= time_str <= max_str

        if node.operator == ASTOperator.GREATER_THAN:
            target = str(node.threshold) if node.threshold is not None else ""
            return time_str > target

        if node.operator == ASTOperator.LESS_THAN:
            target = str(node.threshold) if node.threshold is not None else ""
            return time_str < target

        if node.operator == ASTOperator.EQUALS:
            target = str(node.threshold) if node.threshold is not None else ""
            return time_str == target

        return False

    def _evaluate_greeks(self, node: ConditionNode, context: EvaluationContext) -> bool:
        """Evaluate option Greeks conditions (Delta, Gamma, Theta, Vega)."""
        if context.greeks is None:
            return False

        f = (node.field or "").lower()
        if f == "delta":
            val = context.greeks.delta
        elif f == "gamma":
            val = context.greeks.gamma
        elif f == "theta":
            val = context.greeks.theta
        elif f == "vega":
            val = context.greeks.vega
        elif f == "rho":
            val = context.greeks.rho
        else:
            return False

        thresh = float(node.threshold) if node.threshold is not None else None
        r_min = float(node.range_min) if node.range_min is not None else None
        r_max = float(node.range_max) if node.range_max is not None else None

        return _compare_scalars(
            operator=node.operator,
            current_val=val,
            threshold=thresh,
            range_min=r_min,
            range_max=r_max,
        )

    def _evaluate_premium(self, node: ConditionNode, context: EvaluationContext) -> bool:
        """Evaluate option premium and decay conditions."""
        f = (node.field or "current_premium").lower()
        if f == "current_premium":
            if context.current_premium is None:
                return False
            val = context.current_premium
        elif f in ("decay_pct", "combined_decay_pct"):
            if context.current_premium is None or context.entry_premium is None or context.entry_premium <= 0:
                return False
            val = (context.entry_premium - context.current_premium) / context.entry_premium
        elif f == "entry_premium":
            if context.entry_premium is None:
                return False
            val = context.entry_premium
        else:
            return False

        thresh = float(node.threshold) if node.threshold is not None else None
        r_min = float(node.range_min) if node.range_min is not None else None
        r_max = float(node.range_max) if node.range_max is not None else None

        return _compare_scalars(
            operator=node.operator,
            current_val=val,
            threshold=thresh,
            range_min=r_min,
            range_max=r_max,
        )

    def _evaluate_oi(self, node: ConditionNode, context: EvaluationContext) -> bool:
        """Evaluate open interest and PCR conditions."""
        f = (node.field or "oi").lower()
        if f in ("pcr", "put_call_ratio"):
            if context.put_call_ratio is None:
                return False
            val = context.put_call_ratio
        elif f in ("oi", "open_interest"):
            val = (
                float(context.open_interest)
                if context.open_interest is not None
                else float(context.current_bar.oi)
            )
        else:
            return False

        thresh = float(node.threshold) if node.threshold is not None else None
        r_min = float(node.range_min) if node.range_min is not None else None
        r_max = float(node.range_max) if node.range_max is not None else None

        return _compare_scalars(
            operator=node.operator,
            current_val=val,
            threshold=thresh,
            range_min=r_min,
            range_max=r_max,
        )

    def _evaluate_regime(self, node: ConditionNode, context: EvaluationContext) -> bool:
        """Evaluate market regime match condition."""
        if not context.market_regime or not node.target_regime:
            return False
        if node.operator == ASTOperator.MATCHES_REGIME:
            return context.market_regime.strip().lower() == node.target_regime.strip().lower()
        return False

    def _evaluate_market_structure(self, node: ConditionNode, context: EvaluationContext) -> bool:
        """Evaluate market structure conditions (swing high/low breakout)."""
        f = (node.field or "").lower()
        lookback = int(node.indicator_params.get("lookback", 10))
        if len(context.history) < lookback + 1:
            return False

        prior_bars = context.history[-lookback - 1 : -1]
        if f == "swing_high":
            ref_level = max(b.high for b in prior_bars)
        elif f == "swing_low":
            ref_level = min(b.low for b in prior_bars)
        else:
            return False

        curr_close = context.current_bar.close
        return _compare_scalars(
            operator=node.operator,
            current_val=curr_close,
            threshold=ref_level,
        )
