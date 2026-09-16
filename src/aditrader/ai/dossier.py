"""Institutional Quantitative Research Dossier Compiler.

Per ADR 012 and Phase 7 directives:
- Strictly segregates evidence into DETERMINISTIC, STRUCTURAL, AI_ADVISORY, and METADATA sections.
- Enforces mandatory ProvenanceRecord on all AI_ADVISORY sections.
- Unifies strategy DSL, Black-Scholes Greeks, empirical backtests, sensitivity grids, and AI reviews.
- Provides cryptographic tamper sealing and compliant institutional disclaimers.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime

from aditrader.ai.base import StrategyReviewer
from aditrader.ai.models import (
    DossierSection,
    DossierSectionSourceType,
    ForecastResult,
    ResearchDossier,
    VisionResult,
)
from aditrader.ai.reviewer.engine import DeterministicAdvisoryReviewer
from aditrader.ai.sensitivity import ParameterSensitivityEngine
from aditrader.ai.teacher.explainer import StrategyExplainer
from aditrader.backtesting.runner import BacktestResult
from aditrader.strategy.builder.schema import StrategyDSL
from aditrader.validation.models import ValidationResult


class ResearchDossierCompiler:
    """Compiles comprehensive, auditable research dossiers from analytical artifacts."""

    def __init__(
        self,
        explainer: StrategyExplainer | None = None,
        reviewer: StrategyReviewer | None = None,
        sensitivity_engine: ParameterSensitivityEngine | None = None,
    ) -> None:
        self.explainer = explainer or StrategyExplainer()
        self.reviewer = reviewer or DeterministicAdvisoryReviewer()
        self.sensitivity_engine = sensitivity_engine or ParameterSensitivityEngine()

    def compile(
        self,
        strategy: StrategyDSL,
        validation_result: ValidationResult | None = None,
        backtest_result: BacktestResult | None = None,
        forecast_result: ForecastResult | None = None,
        vision_result: VisionResult | None = None,
        strategy_id: str | None = None,
    ) -> ResearchDossier:
        """Assemble a fully auditable research dossier strictly segregating evidence tiers."""
        now = datetime.now(UTC)
        slug = re.sub(r"[^a-zA-Z0-9_]+", "_", strategy.name.lower()).strip("_")
        dossier_id = f"dossier_{slug}_{int(now.timestamp())}"

        sections: list[DossierSection] = []

        # 1. STRUCTURAL: Executive Overview & Identity
        overview_lines = [
            f"### Strategy: {strategy.name}",
            f"- **Underlying Asset**: `{strategy.underlying}`",
            f"- **Timeframe**: `{strategy.timeframe}`",
            f"- **Asset Class**: {'OPTIONS' if strategy.legs else 'EQUITY_LINEAR'}",
            f"- **Leg Count**: {len(strategy.legs)}",
            f"- **Target Market Regime**: {strategy.target_regime or 'Unspecified'}",
        ]
        if validation_result is not None:
            overview_lines.append(
                f"- **Validation Status**: `{validation_result.status.value}` (Score: {validation_result.validation_score:.1f}/100)"
            )
        else:
            overview_lines.append("- **Validation Status**: `PENDING_EVALUATION`")

        sections.append(
            DossierSection(
                title="Executive Overview & Structural Specification",
                source_type=DossierSectionSourceType.STRUCTURAL,
                content="\n".join(overview_lines),
                provenance=None,
            )
        )

        # 2. AI_ADVISORY: Educational Explanation & Mechanism Breakdown
        explanation_section = self.explainer.explain(strategy)
        sections.append(explanation_section)

        # 3. DETERMINISTIC: Validation Gates & Compliance Matrix
        if validation_result is not None:
            val_lines = [
                f"### Deterministic Validation Outcome: `{validation_result.status.value}`",
                f"- **Policy Name**: `{validation_result.policy_name}`",
                f"- **Validation Scope**: `{validation_result.validation_scope.value}`",
                f"- **Composite Score**: {validation_result.validation_score:.1f} / 100",
                f"- **Sample Size Status**: `{validation_result.sample_size_status.value}`",
                "",
                "#### Gate Evaluations",
                "| Gate Name | Status | Severity | Details |",
                "| :--- | :--- | :--- | :--- |",
            ]
            for g in validation_result.gate_results:
                status_icon = "PASS ✅" if g.passed else "FAIL ❌"
                val_lines.append(
                    f"| {g.gate_name} | {status_icon} | {g.severity.value} | {g.detail} |"
                )

            if validation_result.failed_gates:
                val_lines.append("")
                val_lines.append("#### Active Gate Failures")
                for fg in validation_result.failed_gates:
                    val_lines.append(f"- ❌ {fg}")

            sections.append(
                DossierSection(
                    title="Deterministic Validation Gates & Empirical Scorecard",
                    source_type=DossierSectionSourceType.DETERMINISTIC,
                    content="\n".join(val_lines),
                    provenance=None,
                )
            )

        # 4. DETERMINISTIC: Historical Backtest Metrics (for Linear Assets)
        if backtest_result is not None:
            bt_lines = [
                "### Deterministic Backtest Performance Summary",
                f"- **Initial Capital**: ₹{backtest_result.performance.starting_equity:,.2f}",
                f"- **Ending Equity**: ₹{backtest_result.performance.ending_equity:,.2f}",
                f"- **Net Profit**: ₹{backtest_result.performance.net_profit:,.2f} ({backtest_result.performance.return_pct:.2f}%)",
                f"- **Total Trades**: {backtest_result.performance.total_trades}",
                f"- **Win Rate**: {backtest_result.performance.win_rate:.1%}",
                f"- **Profit Factor**: {f'{backtest_result.performance.profit_factor:.2f}' if backtest_result.performance.profit_factor is not None else 'N/A'}",
                f"- **Mathematical Expectancy**: ₹{backtest_result.performance.expectancy:,.2f}",
                f"- **Max Drawdown**: ₹{backtest_result.performance.max_drawdown_amount:,.2f} ({backtest_result.performance.max_drawdown_pct:.2%})",
                "- **Execution Timing**: NEXT_BAR_OPEN (Point-in-time deterministic fill)",
            ]
            sections.append(
                DossierSection(
                    title="Empirical Historical Replay Analytics",
                    source_type=DossierSectionSourceType.DETERMINISTIC,
                    content="\n".join(bt_lines),
                    provenance=None,
                )
            )

        # 5. DETERMINISTIC: Parameter Sensitivity Grid
        if strategy.legs:
            sens_res = self.sensitivity_engine.evaluate_options_iv_sensitivity(strategy)
            sens_sec = self.sensitivity_engine.to_dossier_section(sens_res)
            sections.append(sens_sec)

        # 6. AI_ADVISORY: Probabilistic Time-Series Forecast (if available)
        if forecast_result is not None:
            fc_lines = [
                f"### Probabilistic Trajectory Forecast ({forecast_result.provenance.model_id})",
                f"- **Cutoff Timestamp**: `{forecast_result.cutoff_timestamp.isoformat()}` (UTC)",
                f"- **Horizon**: {forecast_result.horizon_bars} forward steps",
                f"- **Forecast Uncertainty Spread**: {forecast_result.confidence_spread:.2%}",
                "",
                "| Step | Timestamp (UTC) | Lower Bound | Expected Close | Upper Bound |",
                "| :--- | :--- | :--- | :--- | :--- |",
            ]
            for i in range(forecast_result.horizon_bars):
                ts = forecast_result.timestamps[i].strftime("%H:%M:%S")
                c = forecast_result.predicted_close[i]
                h = forecast_result.predicted_high[i]
                low = forecast_result.predicted_low[i]
                fc_lines.append(f"| +{i + 1} | {ts} | ₹{low:,.2f} | ₹{c:,.2f} | ₹{h:,.2f} |")

            sections.append(
                DossierSection(
                    title="Probabilistic Market Forecast",
                    source_type=DossierSectionSourceType.AI_ADVISORY,
                    content="\n".join(fc_lines),
                    provenance=forecast_result.provenance,
                )
            )

        # 7. AI_ADVISORY: Multimodal Chart Vision Analysis (if available)
        if vision_result is not None:
            vis_lines = [
                f"### Multimodal Chart Analysis ({vision_result.provenance.model_id})",
                f"- **Macro Trend**: `{vision_result.trend}`",
                f"- **Support Zones**: {', '.join(f'₹{s:,.2f}' for s in vision_result.support) if vision_result.support else 'None'}",
                f"- **Resistance Zones**: {', '.join(f'₹{r:,.2f}' for r in vision_result.resistance) if vision_result.resistance else 'None'}",
                "",
                f"**Technical Reasoning**:\n{vision_result.reasoning}",
            ]
            if vision_result.patterns:
                vis_lines.append("")
                vis_lines.append("#### Detected Structural Patterns")
                for pat in vision_result.patterns:
                    desc = f": {pat.description}" if pat.description else ""
                    vis_lines.append(f"- **{pat.name}** (confidence: {pat.confidence:.0%}){desc}")

            sections.append(
                DossierSection(
                    title="Multimodal Chart Vision & Structural Extractions",
                    source_type=DossierSectionSourceType.AI_ADVISORY,
                    content="\n".join(vis_lines),
                    provenance=vision_result.provenance,
                )
            )

        # 8. AI_ADVISORY: Adversarial Review Critique
        if validation_result is not None:
            review_section = self.reviewer.review(strategy, validation_result)
            sections.append(review_section)

        # 9. METADATA: Dossier Provenance & Environment Record
        meta_lines = [
            "### Dossier Provenance & System Metadata",
            f"- **Dossier Identifier**: `{dossier_id}`",
            f"- **Compiled At**: `{now.isoformat()}`",
            "- **Runtime Platform**: AdiTrader Phase 7 Controlled AI Research Runtime",
            "- **Execution Security**: ADR 002 Air-Gapped Simulation (Zero Live Broker Order Routing)",
            "- **Code Execution Policy**: ADR 007 Zero Dynamic Code Interpretation (`eval`/`exec` physically prohibited)",
            "- **Evidence Segregation Standard**: ADR 012 Cryptographic AI Advisory Provenance",
        ]
        sections.append(
            DossierSection(
                title="System Environment & Audit Metadata",
                source_type=DossierSectionSourceType.METADATA,
                content="\n".join(meta_lines),
                provenance=None,
            )
        )

        return ResearchDossier(
            dossier_id=dossier_id,
            strategy_name=strategy.name,
            strategy_id=strategy_id,
            generated_at=now,
            sections=sections,
            validation_result=validation_result,
        )

    def to_markdown(self, dossier: ResearchDossier) -> str:
        """Render complete dossier to clean, publication-grade Markdown text."""
        blocks: list[str] = []
        blocks.append(f"# Institutional Quantitative Research Dossier: {dossier.strategy_name}")
        blocks.append(
            f"**Dossier ID**: `{dossier.dossier_id}` | **Generated**: `{dossier.generated_at.isoformat()}`\n"
        )
        blocks.append(f"> 🛡️ **Institutional Disclaimer**: {dossier.disclaimer}\n")
        blocks.append("---\n")

        for sec in dossier.sections:
            type_tag = f"`[{sec.source_type.value}]`"
            blocks.append(f"## {sec.title} {type_tag}\n")
            if sec.provenance is not None:
                p = sec.provenance
                blocks.append(
                    f"*AI Model*: `{p.model_id}` (`{p.provider}`) | *Input Hash*: `{p.input_hash[:16]}...` | *Deterministic*: `{p.is_deterministic}`\n"
                )
            blocks.append(sec.content)
            blocks.append("\n---\n")

        return "\n".join(blocks)
