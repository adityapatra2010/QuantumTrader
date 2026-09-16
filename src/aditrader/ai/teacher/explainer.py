"""Strategy Explainer: Grounded educational breakdown of canonical StrategyDSL.

Per ADR 012 and Phase 7 directives:
- Translates StrategyDSL condition trees and leg geometry into clear, human-readable explanations.
- Grounded strictly in declarative AST logic and deterministic option mechanics.
- Zero hallucinations or fabricated historical claims.
- Carries explicit ProvenanceRecord with source_type=EDUCATIONAL_EXPLANATION.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from aditrader.ai.models import (
    AISourceType,
    DossierSection,
    DossierSectionSourceType,
    ProvenanceRecord,
)
from aditrader.core.models.enums import OrderSide
from aditrader.strategy.builder.schema import (
    ASTOperator,
    ConditionGroup,
    ConditionNode,
    ContractSelectorType,
    StrategyDSL,
    StrategyLegDefinition,
)


class StrategyExplainer:
    """Explains declarative StrategyDSL structures in accessible, grounded terminology."""

    def __init__(
        self,
        model_id: str = "strategy-explainer-v1",
        model_version: str = "1.0.0",
        provider: str = "aditrader-runtime",
    ) -> None:
        self.model_id = model_id
        self.model_version = model_version
        self.provider = provider

    def explain(self, strategy: StrategyDSL) -> DossierSection:
        """Produce a complete, structured DossierSection explaining strategy mechanics."""
        strategy_json = strategy.model_dump_json()
        input_hash = hashlib.sha256(strategy_json.encode("utf-8")).hexdigest()

        provenance = ProvenanceRecord(
            source_type=AISourceType.EDUCATIONAL_EXPLANATION,
            model_id=self.model_id,
            model_version=self.model_version,
            provider=self.provider,
            generated_at=datetime.now(UTC),
            input_hash=input_hash,
            is_deterministic=True,
            confidence=1.0,
        )

        content = self._build_explanation_markdown(strategy)

        return DossierSection(
            title="Strategy Mechanism & Educational Breakdown",
            source_type=DossierSectionSourceType.AI_ADVISORY,
            content=content,
            provenance=provenance,
        )

    def explain_to_text(self, strategy: StrategyDSL) -> str:
        """Convenience method returning markdown text explanation."""
        return self._build_explanation_markdown(strategy)

    def _build_explanation_markdown(self, strategy: StrategyDSL) -> str:
        lines: list[str] = []

        # 1. Executive Summary & Identity
        lines.append(f"### Strategy: {strategy.name}")
        lines.append(f"- **Underlying Asset**: `{strategy.underlying}`")
        lines.append(f"- **Timeframe**: `{strategy.timeframe}`")
        if strategy.target_regime:
            lines.append(f"- **Target Market Regime**: {strategy.target_regime}")
        lines.append(f"- **Schema Version**: `DSL v{strategy.schema_version}`")
        lines.append("")

        # 2. Structural Architecture (Linear vs Multi-Leg Options)
        is_options = bool(strategy.legs)
        if is_options:
            lines.append("#### Instrument Architecture: Multi-Leg Derivative / Options")
            lines.append(
                f"This strategy defines **{len(strategy.legs)} option leg(s)**. "
                "It operates on derivatives contracts rather than direct cash/spot equity."
            )
        else:
            lines.append("#### Instrument Architecture: Directional Linear (Spot / Futures)")
            lines.append(
                "This strategy executes directional positions directly on the underlying asset."
            )
        lines.append("")

        # 3. Entry Mechanism & Conditions
        lines.append("#### Entry Logic & Trigger Conditions")
        entry_desc = self._explain_condition_group(strategy.entry_conditions)
        lines.append(
            f"Position entry is triggered when the following conditions are satisfied:\n{entry_desc}"
        )
        lines.append("")

        # 4. Exit Mechanism & Risk Controls
        lines.append("#### Exit Logic & Risk Controls")
        if strategy.exit_conditions:
            exit_desc = self._explain_condition_group(strategy.exit_conditions)
            lines.append(f"Position exit is triggered when:\n{exit_desc}")
        else:
            lines.append("No explicit secondary condition tree is specified for exit.")

        # Check for trailing stops on legs
        has_leg_stops = False
        if strategy.legs:
            for i, leg in enumerate(strategy.legs, 1):
                if leg.trailing_stop:
                    has_leg_stops = True
                    ts = leg.trailing_stop
                    ratchet_desc = "favorable one-way ratcheting" if ts.ratchet else "floating"
                    lines.append(
                        f"- **Leg {i} Trailing Stop**: Initial gap of ₹{ts.initial_gap:.2f} premium points, "
                        f"ratcheting by ₹{ts.trail_step:.2f} points ({ratchet_desc})."
                    )
        if not has_leg_stops and not strategy.exit_conditions:
            lines.append(
                "- Positions rely on end-of-session square-off, expiry settlement, or external circuit breakers."
            )
        lines.append("")

        # 5. Contract Legs & Ratio Hedge Geometry
        if strategy.legs:
            lines.append("#### Leg Structure & Hedge Geometry")
            short_legs: list[StrategyLegDefinition] = []
            long_legs: list[StrategyLegDefinition] = []
            for i, leg in enumerate(strategy.legs, 1):
                side_str = "SELL (Short)" if leg.side == OrderSide.SELL else "BUY (Long)"
                type_str = leg.contract_type or (
                    leg.contract_selector.option_type if leg.contract_selector else "N/A"
                )
                lots_str = f"{leg.lots} lot(s)"

                # Strike / Selector description
                if leg.contract_selector:
                    sel = leg.contract_selector
                    if sel.type == ContractSelectorType.PREMIUM_TARGET:
                        spec_str = (
                            f"Dynamic selection: Target premium ₹{sel.target_ltp:.2f} "
                            f"(±₹{sel.tolerance:.2f})"
                        )
                    elif sel.type == ContractSelectorType.PREMIUM_RANGE:
                        spec_str = f"Dynamic selection: Premium range [₹{sel.min_ltp:.2f} – ₹{sel.max_ltp:.2f}]"
                    elif sel.type == ContractSelectorType.DELTA_TARGET:
                        spec_str = "Dynamic selection: Delta target matching"
                    else:
                        spec_str = f"Strike offset {leg.strike_offset} from ATM"
                elif leg.strike_offset is not None:
                    if leg.strike_offset == 0:
                        spec_str = "At-The-Money (ATM)"
                    elif leg.strike_offset > 0:
                        spec_str = f"+{leg.strike_offset} strike(s) OTM/ITM"
                    else:
                        spec_str = f"{leg.strike_offset} strike(s) ITM/OTM"
                else:
                    spec_str = "Standard specification"

                expiry_str = (
                    "Near expiry"
                    if leg.expiry_offset == 0
                    else f"Expiry offset +{leg.expiry_offset}"
                )
                lines.append(
                    f"- **Leg {i}**: **{side_str}** {lots_str} of `{type_str}` — *{spec_str}* ({expiry_str})"
                )

                if leg.side == OrderSide.SELL:
                    short_legs.append(leg)
                else:
                    long_legs.append(leg)

            lines.append("")

            # Ratio geometry commentary
            if short_legs and long_legs:
                short_lots = sum(leg.lots for leg in short_legs)
                long_lots = sum(leg.lots for leg in long_legs)
                ratio = f"{short_lots} Short : {long_lots} Long"
                lines.append(
                    f"- **Hedge Ratio**: `{ratio}`. "
                    f"Positions combine short premium collection with long wing protection."
                )
            elif short_legs and not long_legs:
                lines.append(
                    "- ⚠️ **Unhedged Short Position**: All legs are net short; tail risk is uncapped."
                )
            elif long_legs and not short_legs:
                lines.append(
                    "- **Net Debit Structure**: All legs are long; maximum loss is limited to paid premiums."
                )
            lines.append("")

        # 6. Premium Bands & Multi-Level Configuration
        if strategy.premium_bands:
            lines.append("#### Configured Dynamic Premium Bands")
            lines.append(f"Strategy monitors {len(strategy.premium_bands)} active premium tier(s):")
            for b in strategy.premium_bands:
                lines.append(f"- Band: `₹{b.min_ltp:.2f} – ₹{b.max_ltp:.2f}`")
            lines.append("")

        # 7. Defined Risk vs Undefined Risk Profile
        lines.append("#### Risk Profile & Boundary Analysis")
        if not strategy.legs:
            lines.append(
                "- **Linear Asset Risk**: Directional risk proportional to underlying price movements. "
                "Stop-loss discipline is required to limit drawdowns."
            )
        else:
            # Check if all short legs have corresponding protective long legs
            has_naked_short = False
            short_ce_lots = sum(
                leg.lots
                for leg in strategy.legs
                if leg.side == OrderSide.SELL
                and (
                    leg.contract_type == "CE"
                    or (leg.contract_selector and leg.contract_selector.option_type == "CE")
                )
            )
            long_ce_lots = sum(
                leg.lots
                for leg in strategy.legs
                if leg.side == OrderSide.BUY
                and (
                    leg.contract_type == "CE"
                    or (leg.contract_selector and leg.contract_selector.option_type == "CE")
                )
            )
            short_pe_lots = sum(
                leg.lots
                for leg in strategy.legs
                if leg.side == OrderSide.SELL
                and (
                    leg.contract_type == "PE"
                    or (leg.contract_selector and leg.contract_selector.option_type == "PE")
                )
            )
            long_pe_lots = sum(
                leg.lots
                for leg in strategy.legs
                if leg.side == OrderSide.BUY
                and (
                    leg.contract_type == "PE"
                    or (leg.contract_selector and leg.contract_selector.option_type == "PE")
                )
            )

            if short_ce_lots > 0 and long_ce_lots == 0:
                has_naked_short = True
            if short_pe_lots > 0 and long_pe_lots == 0:
                has_naked_short = True

            if has_naked_short:
                lines.append("- **Risk Classification**: ⚠️ **UNDEFINED TAIL RISK**")
                lines.append(
                    "  Contains short options without explicit long hedge contracts. "
                    "Subject to severe gamma risk during sharp market gaps."
                )
            elif short_ce_lots > 0 or short_pe_lots > 0:
                lines.append("- **Risk Classification**: 🛡️ **DEFINED RISK / HEDGED SPREAD**")
                lines.append(
                    "  Short legs are paired with long protective legs. "
                    "Maximum theoretical loss is capped by the spread width minus collected net credit."
                )
            else:
                lines.append("- **Risk Classification**: 🛡️ **DEFINED RISK (DEBIT PURCHASE)**")
                lines.append(
                    "  Maximum possible loss is strictly capped at the total premium paid."
                )
        lines.append("")

        # 8. Assumptions & Operational Boundaries
        lines.append("#### Core Operational Assumptions")
        lines.append(
            "1. **Liquidity**: Assumes adequate bid/ask depth and tight spreads in candidate option contracts."
        )
        lines.append(
            "2. **Execution Timing**: Next-bar open fill model; signals generated at bar close execute on next tick/bar."
        )
        lines.append(
            "3. **Slippage & Impact**: Real-world execution will experience friction and exchange fees (STT, GST, SEBI)."
        )
        lines.append(
            "4. **Session Hours**: Operates strictly within NSE standard trading hours (09:15–15:30 IST)."
        )
        lines.append("")

        # 9. Explicit Exclusions ("What It Does NOT Do")
        lines.append("#### Explicit Limitations (What this strategy does NOT do)")
        lines.append(
            "- ❌ Does **not** route orders to real exchange brokers (air-gapped PaperBroker execution only)."
        )
        lines.append(
            "- ❌ Does **not** dynamically predict macroeconomic or geopolitical gap openings."
        )
        lines.append("- ❌ Does **not** guarantee profit in hostile volatility expansion regimes.")
        lines.append("- ❌ Does **not** bypass institutional risk gates or margin requirements.")

        return "\n".join(lines)

    def _explain_condition_group(self, group: ConditionGroup, depth: int = 0) -> str:
        indent = "  " * depth
        op = group.operator.value

        items: list[str] = []
        for child in group.conditions:
            if isinstance(child, ConditionNode):
                items.append(f"{indent}- {self._explain_condition_node(child)}")
            elif isinstance(child, ConditionGroup):
                sub_desc = self._explain_condition_group(child, depth + 1)
                items.append(f"{indent}- Sub-group ({child.operator.value}):\n{sub_desc}")

        if group.operator == ASTOperator.NOT:
            return f"{indent}NOT ({items[0].lstrip(indent + '- ') if items else 'True'})"
        return f"{indent}Logical combinator **{op}**:\n" + "\n".join(items)

    def _explain_condition_node(self, node: ConditionNode) -> str:
        cat = node.category.value
        op = node.operator.value

        lhs = node.indicator or node.field or "Price"
        if node.indicator and node.indicator_params:
            param_str = ", ".join(f"{k}={v}" for k, v in sorted(node.indicator_params.items()))
            lhs_display = f"`{lhs}({param_str})`"
        elif node.field:
            lhs_display = f"`{lhs}`"
        else:
            lhs_display = f"`{lhs}`"

        if op == ASTOperator.WITHIN_RANGE.value:
            rhs_display = f"[{node.range_min}, {node.range_max}]"
        elif op in (ASTOperator.CROSSES_ABOVE.value, ASTOperator.CROSSES_BELOW.value):
            if node.compare_indicator:
                if node.compare_params:
                    p_str = ", ".join(f"{k}={v}" for k, v in sorted(node.compare_params.items()))
                    rhs_display = f"`{node.compare_indicator}({p_str})`"
                else:
                    rhs_display = f"`{node.compare_indicator}`"
            elif node.compare_to_field:
                rhs_display = f"`{node.compare_to_field}`"
            else:
                rhs_display = f"`{node.threshold}`"
        elif op == ASTOperator.MATCHES_REGIME.value:
            rhs_display = f"`{node.target_regime}`"
        else:
            rhs_display = f"`{node.threshold}`"

        op_translations = {
            ASTOperator.GREATER_THAN.value: "is greater than",
            ASTOperator.LESS_THAN.value: "is less than",
            ASTOperator.EQUALS.value: "equals",
            ASTOperator.CROSSES_ABOVE.value: "crosses above",
            ASTOperator.CROSSES_BELOW.value: "crosses below",
            ASTOperator.WITHIN_RANGE.value: "is within range of",
            ASTOperator.MATCHES_REGIME.value: "matches market regime",
        }
        human_op = op_translations.get(op, op)

        return f"[{cat}] {lhs_display} {human_op} {rhs_display}"
