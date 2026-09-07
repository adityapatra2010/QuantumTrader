"""TradingView Pine Script (v4/v5/v6) deterministic AST translator.

Per ADR 001 and ADR 007:
- Parses Pine Script source statically via regular expressions and token rules.
- Zero dynamic code execution (no Node.js/JS execution, no eval/exec).
- Enforces strict anti-lookahead checks: explicitly rejects barmerge.lookahead_on.
- Maps deterministic indicators (SMA, EMA, RSI, ATR, BB, Supertrend) to StrategyDSL.
"""

import contextlib
import re
from pathlib import Path
from typing import Any

from aditrader.strategy.builder.schema import (
    ASTOperator,
    ConditionCategory,
    ConditionGroup,
    ConditionNode,
    StrategyDSL,
)
from aditrader.strategy.translators.base import BaseStrategyTranslator


class PineScriptTranslator(BaseStrategyTranslator):
    """Translates common deterministic TradingView Pine Script strategies into StrategyDSL."""

    def translate(
        self,
        content: str,
        *,
        default_underlying: str = "NIFTY",
        default_timeframe: str = "5m",
        file_path: str | Path | None = None,
    ) -> StrategyDSL:
        """Translate Pine Script source code into validated StrategyDSL."""
        text = content.strip()

        # ----------------------------------------------------------------------
        # 1. Anti-Lookahead & Repainting Guard
        # ----------------------------------------------------------------------
        if re.search(r"\bbarmerge\.lookahead_on\b", text) or re.search(
            r"lookahead\s*=\s*barmerge\.lookahead_on", text
        ):
            raise ValueError(
                "Repainting/Look-Ahead Bias detected: 'barmerge.lookahead_on' is strictly "
                "prohibited by QuantumValidator anti-lookahead rules. Historical replays must use "
                "point-in-time closed bars."
            )

        # ----------------------------------------------------------------------
        # 2. Strategy vs Indicator Check
        # ----------------------------------------------------------------------
        has_strategy_decl = bool(re.search(r"\bstrategy\s*\(", text))
        has_entry = bool(re.search(r"\bstrategy\.entry\s*\(", text))

        if not has_strategy_decl and not has_entry:
            raise ValueError(
                "Pine Script does not define an executable strategy (missing strategy() declaration "
                "or strategy.entry() orders). Indicators/studies cannot be translated into execution AST."
            )

        # ----------------------------------------------------------------------
        # 3. Strategy Title & Version Extraction
        # ----------------------------------------------------------------------
        m_name = re.search(r"""\bstrategy\s*\(\s*["']([^"']+)["']""", text)
        strategy_name = m_name.group(1).strip() if m_name else "Pine Translated Strategy"

        m_ver = re.search(r"//\s*@version\s*=\s*([0-9]+)", text, re.IGNORECASE)
        pine_version = f"v{m_ver.group(1)}" if m_ver else "v5"

        # Check for intrabar calculation notice
        has_intrabar = bool(re.search(r"calc_on_every_tick\s*=\s*true", text, re.IGNORECASE))

        # Check for procedural loops (unsupported in declarative AST)
        if re.search(r"\bwhile\s*\(", text) or re.search(r"\bfor\s+[a-zA-Z0-9_]+\s*=", text):
            raise ValueError(
                "Procedural loops (for/while) mutating external state cannot be translated into "
                "declarative JSON AST. Strategy must use vectorized indicator rules."
            )

        # ----------------------------------------------------------------------
        # 4. Extract Variables and Indicator Definitions
        # ----------------------------------------------------------------------
        # Map variable names to indicators/values
        var_indicators: dict[str, dict[str, Any]] = {}

        # Look for SMA: var = ta.sma(close, period) or sma(close, period)
        for m in re.finditer(
            r"([a-zA-Z0-9_]+)\s*=\s*(?:ta\.)?sma\s*\(\s*([a-zA-Z0-9_]+)\s*,\s*([0-9]+)\s*\)",
            text,
        ):
            var_name, src, period = m.groups()
            var_indicators[var_name] = {
                "indicator": "SMA",
                "params": {"period": int(period)},
                "field": src.lower(),
            }

        # Look for EMA: var = ta.ema(close, period) or ema(close, period)
        for m in re.finditer(
            r"([a-zA-Z0-9_]+)\s*=\s*(?:ta\.)?ema\s*\(\s*([a-zA-Z0-9_]+)\s*,\s*([0-9]+)\s*\)",
            text,
        ):
            var_name, src, period = m.groups()
            var_indicators[var_name] = {
                "indicator": "EMA",
                "params": {"period": int(period)},
                "field": src.lower(),
            }

        # Look for RSI: var = ta.rsi(close, period) or rsi(close, period)
        for m in re.finditer(
            r"([a-zA-Z0-9_]+)\s*=\s*(?:ta\.)?rsi\s*\(\s*([a-zA-Z0-9_]+)\s*,\s*([0-9]+)\s*\)",
            text,
        ):
            var_name, src, period = m.groups()
            var_indicators[var_name] = {
                "indicator": "RSI",
                "params": {"period": int(period)},
                "field": src.lower(),
            }

        # Look for ATR: var = ta.atr(period) or atr(period)
        for m in re.finditer(
            r"([a-zA-Z0-9_]+)\s*=\s*(?:ta\.)?atr\s*\(\s*([0-9]+)\s*\)",
            text,
        ):
            var_name, period = m.groups()
            var_indicators[var_name] = {
                "indicator": "ATR",
                "params": {"period": int(period)},
                "field": "close",
            }

        # Look for Supertrend: [st, dir] = ta.supertrend(multiplier, period)
        for m in re.finditer(
            r"\[?\s*([a-zA-Z0-9_]+)(?:\s*,\s*([a-zA-Z0-9_]+))?\s*\]?\s*=\s*(?:ta\.)?supertrend\s*\(\s*([0-9.]+)\s*,\s*([0-9]+)\s*\)",
            text,
        ):
            st_val_name, st_dir_name, mult, period = m.groups()
            if st_val_name:
                var_indicators[st_val_name] = {
                    "indicator": "SUPERTREND",
                    "params": {"period": int(period), "multiplier": float(mult), "output": "value"},
                    "field": "close",
                }
            if st_dir_name:
                var_indicators[st_dir_name] = {
                    "indicator": "SUPERTREND",
                    "params": {
                        "period": int(period),
                        "multiplier": float(mult),
                        "output": "direction",
                    },
                    "field": "close",
                }

        # ----------------------------------------------------------------------
        # 5. Extract Entry Conditions
        # ----------------------------------------------------------------------
        entry_nodes: list[ConditionNode | ConditionGroup] = []
        exit_nodes: list[ConditionNode | ConditionGroup] = []

        # Look for crossover: ta.crossover(a, b)
        for m in re.finditer(
            r"(?:ta\.)?crossover\s*\(\s*([a-zA-Z0-9_.]+)\s*,\s*([a-zA-Z0-9_.]+)\s*\)",
            text,
        ):
            var_a, var_b = m.groups()
            node = self._create_crossover_node(
                var_a, var_b, ASTOperator.CROSSES_ABOVE, var_indicators
            )
            if node:
                entry_nodes.append(node)

        # Look for crossunder: ta.crossunder(a, b)
        for m in re.finditer(
            r"(?:ta\.)?crossunder\s*\(\s*([a-zA-Z0-9_.]+)\s*,\s*([a-zA-Z0-9_.]+)\s*\)",
            text,
        ):
            var_a, var_b = m.groups()
            node = self._create_crossover_node(
                var_a, var_b, ASTOperator.CROSSES_BELOW, var_indicators
            )
            if node:
                exit_nodes.append(node)

        # Look for scalar comparisons: e.g. rsi < 30 or rsi > 70 or close > ema
        for m in re.finditer(
            r"([a-zA-Z0-9_]+)\s*(<|>|<=|>=|==)\s*([0-9.]+|[a-zA-Z0-9_]+)",
            text,
        ):
            left, op, right = m.groups()
            # Skip loop indices or syntax keywords
            if left in ("version", "for", "while", "if"):
                continue

            node = self._create_comparison_node(left, op, right, var_indicators)
            if node:
                # If comparison looks like oversold (< 30), it is typically entry
                # If comparison looks like overbought (> 70), it is typically exit
                try:
                    num_val = float(right)
                    if num_val <= 45.0 and op in ("<", "<="):
                        entry_nodes.append(node)
                    elif num_val >= 55.0 and op in (">", ">="):
                        exit_nodes.append(node)
                    else:
                        entry_nodes.append(node)
                except ValueError:
                    entry_nodes.append(node)

        if not entry_nodes:
            # Fallback: create default price envelope entry if standard patterns not matched
            raise ValueError(
                "Could not extract supported entry condition logic from Pine Script. "
                "Supported patterns include ta.crossover, ta.crossunder, ta.sma/ema/rsi/atr, "
                "and scalar threshold comparisons."
            )

        entry_group = ConditionGroup(operator=ASTOperator.AND, conditions=entry_nodes[:4])
        exit_group = (
            ConditionGroup(operator=ASTOperator.OR, conditions=exit_nodes[:4])
            if exit_nodes
            else None
        )

        metadata: dict[str, Any] = {
            "source": "TradingView Pine Script",
            "pine_version": pine_version,
            "intrabar_risk_flagged": has_intrabar,
        }
        if file_path:
            metadata["source_file"] = str(file_path)

        return StrategyDSL(
            schema_version="1.0",
            name=strategy_name,
            underlying=default_underlying,
            timeframe=default_timeframe,
            entry_conditions=entry_group,
            exit_conditions=exit_group,
            legs=[],
            target_regime="Trend Following",
            metadata=metadata,
        )

    def _create_crossover_node(
        self,
        var_a: str,
        var_b: str,
        operator: ASTOperator,
        var_indicators: dict[str, dict[str, Any]],
    ) -> ConditionNode | None:
        """Map crossover(a, b) operands into ConditionNode."""
        ind_a = var_indicators.get(var_a)
        ind_b = var_indicators.get(var_b)

        if ind_a and ind_b:
            return ConditionNode(
                category=ConditionCategory.INDICATOR,
                indicator=ind_a["indicator"],
                indicator_params=ind_a["params"],
                operator=operator,
                compare_indicator=ind_b["indicator"],
                compare_params=ind_b["params"],
            )

        if ind_a and not ind_b:
            # var_b is a bar field (e.g. close)
            return ConditionNode(
                category=ConditionCategory.INDICATOR,
                indicator=ind_a["indicator"],
                indicator_params=ind_a["params"],
                operator=operator,
                compare_to_field=var_b.lower(),
            )

        if not ind_a and ind_b:
            # var_a is a bar field (e.g. close)
            return ConditionNode(
                category=ConditionCategory.INDICATOR,
                field=var_a.lower(),
                operator=operator,
                compare_indicator=ind_b["indicator"],
                compare_params=ind_b["params"],
            )

        # Both are bar fields
        return ConditionNode(
            category=ConditionCategory.INDICATOR,
            field=var_a.lower(),
            operator=operator,
            compare_to_field=var_b.lower(),
        )

    def _create_comparison_node(
        self,
        left: str,
        op_str: str,
        right: str,
        var_indicators: dict[str, dict[str, Any]],
    ) -> ConditionNode | None:
        """Map scalar comparison into ConditionNode."""
        op_map = {
            ">": ASTOperator.GREATER_THAN,
            ">=": ASTOperator.GREATER_THAN,
            "<": ASTOperator.LESS_THAN,
            "<=": ASTOperator.LESS_THAN,
            "==": ASTOperator.EQUALS,
        }
        operator = op_map.get(op_str)
        if not operator:
            return None

        # Check if right is float
        threshold: float | None = None
        with contextlib.suppress(ValueError):
            threshold = float(right)

        ind_info = var_indicators.get(left)
        if ind_info and threshold is not None:
            return ConditionNode(
                category=ConditionCategory.INDICATOR,
                indicator=ind_info["indicator"],
                indicator_params=ind_info["params"],
                operator=operator,
                threshold=threshold,
            )

        if threshold is not None and left.lower() in ("close", "open", "high", "low", "volume"):
            return ConditionNode(
                category=ConditionCategory.INDICATOR,
                field=left.lower(),
                operator=operator,
                threshold=threshold,
            )

        return None
