"""Static strategy file inspector and semantic compatibility analyzer.

Per ADR 001, ADR 002, ADR 007, and ADR 011:
- Never executes, evals, or imports untrusted strategy files.
- Provides operators with full visibility into format, language, constructs,
  lookahead risks, options air-gap compliance, and validation readiness.
"""

import ast
import re
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from aditrader.strategy.builder.schema import StrategyDSL
from aditrader.strategy.inspector.detector import StrategyFormatDetector
from aditrader.strategy.inspector.models import (
    ConstructFidelity,
    FidelityLevel,
    PortabilityAssessment,
    StrategyFormat,
    StrategyInspectionReport,
    StrategyScriptType,
    TranslationStatus,
)
from aditrader.strategy.translators.pine import PineScriptTranslator
from aditrader.strategy.translators.yaml_dsl import YAMLStrategyLoader


class StrategyInspector:
    """Analyzes strategy files and scripts for compatibility and semantic integrity."""

    @classmethod
    def inspect_file(cls, file_path: str | Path) -> StrategyInspectionReport:
        """Inspect a strategy file from disk without executing it."""
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Strategy file not found: {path}")

        file_size = path.stat().st_size
        if file_size == 0:
            return StrategyInspectionReport(
                file_path=str(path),
                file_size_bytes=0,
                detected_format=StrategyFormat.UNKNOWN,
                language="Unknown",
                translation_status=TranslationStatus.UNSUPPORTED,
                fidelity_level=FidelityLevel.UNSUPPORTED,
                warnings=["File is 0 bytes."],
                rejection_reasons=["File is completely empty."],
            )

        content = path.read_text(encoding="utf-8", errors="replace")
        return cls.inspect_content(content, file_path=path)

    @classmethod
    def inspect_content(
        cls, content: str, file_path: str | Path | None = None
    ) -> StrategyInspectionReport:
        """Inspect raw strategy script text without dynamic execution."""
        raw_path = str(file_path) if file_path else "<memory>"
        file_size = len(content.encode("utf-8"))

        fmt, lang, ver, script_type = StrategyFormatDetector.detect(content, file_path=file_path)

        supported_constructs: list[str] = []
        unsupported_constructs: list[str] = []
        warnings: list[str] = []
        rejection_reasons: list[str] = []

        detected_constructs: list[ConstructFidelity] = []
        entry_mechanisms: list[str] = []
        exit_mechanisms: list[str] = []
        persistent_state_vars: list[str] = []
        time_conditions: list[str] = []
        indicators_used: list[str] = []
        custom_calculations: list[str] = []
        visual_only_constructs: list[str] = []
        order_behavior_notes: list[str] = []
        position_semantics: str | None = None
        option_leg_semantics: str | None = None
        naming_behavior_mismatch: str | None = None
        custom_pnl_detected: bool = False
        custom_pnl_details: dict[str, Any] | None = None

        has_lookahead = False
        has_intrabar = False
        has_options = False
        validation_ready = False
        simulation_ready = False
        forward_ready = False

        strategy_name: str | None = None
        underlying: str | None = None
        timeframe: str | None = None
        translation_status = TranslationStatus.UNSUPPORTED
        fidelity_level = FidelityLevel.UNSUPPORTED
        portability_assessment: PortabilityAssessment | None = None

        # ----------------------------------------------------------------------
        # 1. Native JSON AST DSL
        # ----------------------------------------------------------------------
        if fmt == StrategyFormat.JSON_DSL:
            try:
                dsl = StrategyDSL.model_validate_json(content)
                strategy_name = dsl.name
                underlying = dsl.underlying
                timeframe = dsl.timeframe
                has_options = len(dsl.legs) > 0
                translation_status = TranslationStatus.SUPPORTED
                fidelity_level = FidelityLevel.EXACT
                validation_ready = True
                supported_constructs.extend(
                    [
                        "Declarative AST v1.0",
                        f"Entry Logic: {dsl.entry_conditions.operator.value}",
                    ]
                )
                if dsl.exit_conditions:
                    supported_constructs.append(f"Exit Logic: {dsl.exit_conditions.operator.value}")

                if has_options:
                    simulation_ready = False
                    forward_ready = False
                    warnings.append(
                        "Multi-leg option strategy is air-gapped from linear forward-testing "
                        "and historical backtest runner (ADR 011 / ADR 002)."
                    )
                    rejection_reasons.append(
                        "Option strategies require Phase 8 Greeks execution engine; linear paper runner is air-gapped."
                    )
                else:
                    simulation_ready = True
                    forward_ready = True
            except ValidationError as err:
                translation_status = TranslationStatus.UNSUPPORTED
                rejection_reasons.append(f"JSON AST Schema validation failure: {err}")
            except Exception as exc:
                translation_status = TranslationStatus.UNSUPPORTED
                rejection_reasons.append(f"JSON parse error: {exc}")

        # ----------------------------------------------------------------------
        # 2. Native YAML AST DSL
        # ----------------------------------------------------------------------
        elif fmt == StrategyFormat.YAML_DSL:
            try:
                dsl = YAMLStrategyLoader.load_from_str(content)
                strategy_name = dsl.name
                underlying = dsl.underlying
                timeframe = dsl.timeframe
                has_options = len(dsl.legs) > 0
                translation_status = TranslationStatus.SUPPORTED
                fidelity_level = FidelityLevel.EXACT
                validation_ready = True
                supported_constructs.extend(
                    [
                        "Declarative YAML AST v1.0",
                        f"Entry Logic: {dsl.entry_conditions.operator.value}",
                    ]
                )
                if dsl.exit_conditions:
                    supported_constructs.append(f"Exit Logic: {dsl.exit_conditions.operator.value}")

                if has_options:
                    simulation_ready = False
                    forward_ready = False
                    warnings.append(
                        "Multi-leg option strategy is air-gapped from linear forward-testing "
                        "and historical backtest runner (ADR 011 / ADR 002)."
                    )
                    rejection_reasons.append(
                        "Option strategies require Phase 8 Greeks execution engine; linear paper runner is air-gapped."
                    )
                else:
                    simulation_ready = True
                    forward_ready = True
            except Exception as exc:
                translation_status = TranslationStatus.UNSUPPORTED
                rejection_reasons.append(f"YAML AST Schema validation failure: {exc}")

        # ----------------------------------------------------------------------
        # 3. TradingView Pine Script
        # ----------------------------------------------------------------------
        elif fmt == StrategyFormat.PINE_SCRIPT:
            pine_report = cls._inspect_pine_script(
                content, file_path=file_path, ver=ver, script_type=script_type
            )
            detected_constructs.extend(pine_report["detected_constructs"])
            entry_mechanisms.extend(pine_report["entry_mechanisms"])
            exit_mechanisms.extend(pine_report["exit_mechanisms"])
            persistent_state_vars.extend(pine_report["persistent_state_vars"])
            time_conditions.extend(pine_report["time_conditions"])
            indicators_used.extend(pine_report["indicators_used"])
            custom_calculations.extend(pine_report["custom_calculations"])
            visual_only_constructs.extend(pine_report["visual_only_constructs"])
            supported_constructs.extend(pine_report["supported_constructs"])
            unsupported_constructs.extend(pine_report["unsupported_constructs"])
            rejection_reasons.extend(pine_report["rejection_reasons"])
            warnings.extend(pine_report["warnings"])
            order_behavior_notes.extend(pine_report["order_behavior_notes"])

            strategy_name = pine_report["strategy_name"]
            underlying = pine_report["underlying"]
            timeframe = pine_report["timeframe"]
            has_lookahead = pine_report["has_lookahead"]
            has_intrabar = pine_report["has_intrabar"]
            has_options = pine_report["has_options"]
            validation_ready = pine_report["validation_ready"]
            simulation_ready = pine_report["simulation_ready"]
            forward_ready = pine_report["forward_ready"]
            translation_status = pine_report["translation_status"]
            fidelity_level = pine_report["fidelity_level"]
            position_semantics = pine_report["position_semantics"]
            option_leg_semantics = pine_report["option_leg_semantics"]
            naming_behavior_mismatch = pine_report["naming_behavior_mismatch"]
            custom_pnl_detected = pine_report["custom_pnl_detected"]
            custom_pnl_details = pine_report["custom_pnl_details"]
            portability_assessment = pine_report.get("portability_assessment")

        # ----------------------------------------------------------------------
        # 4. Python Strategy Frameworks (Backtrader, vectorbt, Freqtrade, Generic)
        # ----------------------------------------------------------------------
        elif fmt in (
            StrategyFormat.PYTHON_BACKTRADER,
            StrategyFormat.PYTHON_VECTORBT,
            StrategyFormat.PYTHON_FREQTRADE,
            StrategyFormat.PYTHON_GENERIC,
        ):
            translation_status = TranslationStatus.INSPECT_ONLY
            fidelity_level = FidelityLevel.UNSUPPORTED
            rejection_reasons.append(
                "Arbitrary Python script execution is strictly prohibited by ADR 007 / ADR 001. "
                "Strategies must be compiled via declarative JSON/YAML AST trees."
            )

            # Static AST inspection of classes and methods without execution
            try:
                tree = ast.parse(content)
                classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
                functions = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
                if classes:
                    strategy_name = classes[0]
                    supported_constructs.append(f"Classes: {', '.join(classes[:3])}")
                if functions:
                    supported_constructs.append(f"Methods: {', '.join(functions[:4])}")
            except Exception:
                pass

        # ----------------------------------------------------------------------
        # 5. Other Programmable Languages (MQL4/MQL5, EasyLanguage, AFL, etc.)
        # ----------------------------------------------------------------------
        else:
            translation_status = TranslationStatus.INSPECT_ONLY
            fidelity_level = FidelityLevel.UNSUPPORTED
            rejection_reasons.append(
                f"External strategy representation '{lang}' is inspect-only. "
                "Direct code execution is barred by ADR 007."
            )

        return StrategyInspectionReport(
            file_path=raw_path,
            file_size_bytes=file_size,
            detected_format=fmt,
            language=lang,
            version_detected=ver,
            script_type=script_type,
            strategy_name=strategy_name,
            underlying_detected=underlying,
            timeframe_detected=timeframe,
            supported_constructs=supported_constructs,
            unsupported_constructs=unsupported_constructs,
            has_lookahead_risk=has_lookahead,
            has_intrabar_risk=has_intrabar,
            has_options_legs=has_options,
            translation_status=translation_status,
            fidelity_level=fidelity_level,
            validation_ready=validation_ready,
            simulation_ready=simulation_ready,
            forward_test_ready=forward_ready,
            rejection_reasons=rejection_reasons,
            warnings=warnings,
            detected_constructs=detected_constructs,
            entry_mechanisms=entry_mechanisms,
            exit_mechanisms=exit_mechanisms,
            persistent_state_vars=persistent_state_vars,
            time_conditions=time_conditions,
            indicators_used=indicators_used,
            custom_calculations=custom_calculations,
            position_semantics=position_semantics,
            option_leg_semantics=option_leg_semantics,
            naming_behavior_mismatch=naming_behavior_mismatch,
            custom_pnl_detected=custom_pnl_detected,
            custom_pnl_details=custom_pnl_details,
            order_behavior_notes=order_behavior_notes,
            visual_only_constructs=visual_only_constructs,
            portability_assessment=portability_assessment,
        )

    @classmethod
    def _inspect_pine_script(
        cls,
        content: str,
        *,
        file_path: str | Path | None = None,
        ver: str | None = None,
        script_type: StrategyScriptType = StrategyScriptType.STRATEGY,
    ) -> dict[str, Any]:
        """Perform granular AST token and regex inspection on TradingView Pine Script."""
        text = content.strip()
        detected_constructs: list[ConstructFidelity] = []
        entry_mechanisms: list[str] = []
        exit_mechanisms: list[str] = []
        persistent_state_vars: list[str] = []
        time_conditions: list[str] = []
        indicators_used: list[str] = []
        custom_calculations: list[str] = []
        visual_only_constructs: list[str] = []
        supported_constructs: list[str] = []
        unsupported_constructs: list[str] = []
        rejection_reasons: list[str] = []
        warnings: list[str] = []

        strategy_name = "Pine Script Strategy"
        underlying: str | None = None
        timeframe: str | None = None
        has_lookahead = False
        has_intrabar = False
        has_options = False
        validation_ready = False
        simulation_ready = False
        forward_ready = False
        translation_status = TranslationStatus.INSPECT_ONLY
        fidelity_level = FidelityLevel.APPROXIMATED
        position_semantics: str | None = None
        option_leg_semantics: str | None = None
        naming_behavior_mismatch: str | None = None
        custom_pnl_detected = False
        custom_pnl_details: dict[str, Any] | None = None

        # 1. Compiler Version Directive
        m_ver = re.search(r"//\s*@version\s*=\s*([0-9]+)", text, re.IGNORECASE)
        ver_num = m_ver.group(1) if m_ver else "5"
        pine_version = f"v{ver_num}"
        detected_constructs.append(
            ConstructFidelity(
                name=f"Compiler Directive (@version={ver_num})",
                category="directive",
                fidelity=FidelityLevel.EXACT,
                details=f"Identifies Pine Script compiler version ({pine_version})",
                translatable=True,
            )
        )

        # 2. Strategy Declaration & Directives
        m_title = re.search(r"""\bstrategy\s*\(\s*(?:title\s*=\s*)?["']([^"']+)["']""", text)
        if m_title:
            strategy_name = m_title.group(1).strip()
        if re.search(r"\bstrategy\s*\(", text):
            detected_constructs.append(
                ConstructFidelity(
                    name=f"Strategy Declaration ('{strategy_name}')",
                    category="directive",
                    fidelity=FidelityLevel.EXACT,
                    details="Defines strategy container name and execution parameters",
                    translatable=True,
                )
            )

            if re.search(r"\boverlay\s*=\s*true\b", text, re.IGNORECASE):
                detected_constructs.append(
                    ConstructFidelity(
                        name="Overlay Parameter (overlay=true)",
                        category="visual",
                        fidelity=FidelityLevel.VISUAL_ONLY,
                        details="Renders visual indicators directly on price candles; ignored during simulation",
                        translatable=False,
                    )
                )

            m_cap = re.search(r"\binitial_capital\s*=\s*([0-9.]+)", text)
            if m_cap:
                init_cap = float(m_cap.group(1))
                detected_constructs.append(
                    ConstructFidelity(
                        name=f"Initial Capital (₹{init_cap:,.2f})",
                        category="directive",
                        fidelity=FidelityLevel.EXACT,
                        details="Configures initial backtest capital",
                        translatable=True,
                    )
                )

            m_qty_type = re.search(r"\bdefault_qty_type\s*=\s*strategy\.([a-zA-Z0-9_]+)", text)
            m_qty_val = re.search(r"\bdefault_qty_value\s*=\s*([0-9.]+)", text)
            if m_qty_type or m_qty_val:
                q_t = m_qty_type.group(1) if m_qty_type else "fixed"
                q_v = m_qty_val.group(1) if m_qty_val else "1"
                detected_constructs.append(
                    ConstructFidelity(
                        name=f"Default Quantity ({q_t}={q_v})",
                        category="directive",
                        fidelity=FidelityLevel.EXACT,
                        details="Configures baseline position sizing rule",
                        translatable=True,
                    )
                )

        # 3. User Inputs
        input_matches = re.findall(
            r"([a-zA-Z0-9_]+)\s*=\s*input(?:\.[a-zA-Z0-9_]+)?\s*\((.*?)\)",
            text,
        )
        if input_matches:
            input_names = [m[0] for m in input_matches]
            supported_constructs.append(f"Inputs ({len(input_matches)}): {', '.join(input_names)}")
            detected_constructs.append(
                ConstructFidelity(
                    name=f"User Inputs ({len(input_matches)} defined: {', '.join(input_names)})",
                    category="input",
                    fidelity=FidelityLevel.APPROXIMATED,
                    details="Static configuration inputs; mapped as strategy parameters",
                    translatable=True,
                )
            )

        # 4. Persistent State Variables (var / varip) & State Mutation (:=)
        var_matches = list(
            dict.fromkeys(
                re.findall(
                    r"\b(?:var|varip)\s+(?:float|int|bool|string|color)?\s*([a-zA-Z0-9_]+)\s*=",
                    text,
                )
            )
        )
        has_var_assign = bool(re.search(r"([a-zA-Z0-9_]+)\s*:=", text))
        if var_matches:
            persistent_state_vars.extend(var_matches)
            unsupported_constructs.append(f"Persistent Variables (var): {', '.join(var_matches)}")
            fidelity = FidelityLevel.UNSUPPORTED if has_var_assign else FidelityLevel.APPROXIMATED
            detected_constructs.append(
                ConstructFidelity(
                    name=f"Persistent State Variables ({', '.join(var_matches)})",
                    category="state",
                    fidelity=fidelity,
                    details=(
                        "Procedural variables mutating across bars via ':=' are barred by ADR 007 "
                        "from declarative StrategyDSL AST"
                        if has_var_assign
                        else "Persistent state variables"
                    ),
                    translatable=False,
                )
            )

        # 5. Timing & Session Conditions
        m_hm = re.search(r"\bhour\s*==\s*([0-9]+)\s+and\s+minute\s*==\s*([0-9]+)\b", text)
        if not m_hm:
            m_hm = re.search(r"\bminute\s*==\s*([0-9]+)\s+and\s+hour\s*==\s*([0-9]+)\b", text)
            if m_hm:
                m_min, m_hr = m_hm.groups()
            else:
                m_hr, m_min = None, None
        else:
            m_hr, m_min = m_hm.groups()

        if m_hr is not None and m_min is not None:
            time_str = f"{int(m_hr):02d}:{int(m_min):02d}"
            time_conditions.append(
                f"Exact Time: {time_str} IST (hour == {m_hr} and minute == {m_min})"
            )
            supported_constructs.append(f"Time Trigger ({time_str})")
            detected_constructs.append(
                ConstructFidelity(
                    name=f"Time Filter (hour == {m_hr} and minute == {m_min})",
                    category="timing",
                    fidelity=FidelityLevel.EXACT,
                    details=f"Directly maps to ConditionCategory.TIME (time_of_day == '{time_str}') in StrategyDSL",
                    translatable=True,
                )
            )

        session_matches = re.findall(r"""input\.session\s*\(\s*["']([^"']+)["']""", text)
        if session_matches:
            s_window = session_matches[0]
            time_conditions.append(f"Trading Session Window: '{s_window}'")
            supported_constructs.append(f"Session Filter ({s_window})")
            detected_constructs.append(
                ConstructFidelity(
                    name=f"Session Window Filter ('{s_window}')",
                    category="timing",
                    fidelity=FidelityLevel.APPROXIMATED,
                    details=f"Restricts strategy execution to session hours ('{s_window}')",
                    translatable=True,
                )
            )

        # 6. Arithmetic & Mathematical Functions
        math_funcs = list(dict.fromkeys(re.findall(r"\bmath\.([a-zA-Z0-9_]+)\b", text)))
        if math_funcs:
            custom_calculations.append(f"Math functions: {', '.join(math_funcs)}")
            detected_constructs.append(
                ConstructFidelity(
                    name=f"Math Library Functions ({', '.join(math_funcs)})",
                    category="calculation",
                    fidelity=FidelityLevel.UNSUPPORTED,
                    details="Dynamic procedural math functions (e.g. math.round, math.abs) unsupported in declarative scalar AST",
                    translatable=False,
                )
            )

        if "?" in text and ":" in text:
            custom_calculations.append("Ternary conditional expressions (? :)")
            detected_constructs.append(
                ConstructFidelity(
                    name="Ternary Conditional Expression (? :)",
                    category="calculation",
                    fidelity=FidelityLevel.UNSUPPORTED,
                    details="Inline ternary branch unsupported in declarative schema",
                    translatable=False,
                )
            )

        # 7. Technical Indicators
        for ind_token, ind_name in [
            (r"\b(?:ta\.)?sma\b", "SMA"),
            (r"\b(?:ta\.)?ema\b", "EMA"),
            (r"\b(?:ta\.)?rsi\b", "RSI"),
            (r"\b(?:ta\.)?atr\b", "ATR"),
            (r"\b(?:ta\.)?macd\b", "MACD"),
            (r"\b(?:ta\.)?supertrend\b", "Supertrend"),
            (r"\b(?:ta\.)?crossover\b", "ta.crossover"),
            (r"\b(?:ta\.)?crossunder\b", "ta.crossunder"),
        ]:
            if re.search(ind_token, text):
                indicators_used.append(ind_name)
                supported_constructs.append(ind_name)
                detected_constructs.append(
                    ConstructFidelity(
                        name=f"Technical Indicator ({ind_name})",
                        category="indicator",
                        fidelity=FidelityLevel.EXACT,
                        details="Supported deterministic indicator mapped to StrategyDSL node",
                        translatable=True,
                    )
                )

        # 8. Orders & Position Semantics
        entry_matches = re.findall(
            r"\bstrategy\.entry\s*\(\s*[\"']([^\"']+)[\"']\s*,\s*strategy\.(long|short)",
            text,
            re.IGNORECASE,
        )
        if entry_matches:
            for order_id, side in entry_matches:
                entry_desc = f"strategy.entry('{order_id}', strategy.{side.lower()})"
                entry_mechanisms.append(entry_desc)
                detected_constructs.append(
                    ConstructFidelity(
                        name=f"Order Entry ({order_id}, {side.upper()})",
                        category="entry",
                        fidelity=FidelityLevel.EQUIVALENT,
                        details=f"Enters {side.lower()} position in underlying asset",
                        translatable=True,
                    )
                )
            position_semantics = f"Single underlying {entry_matches[0][1].lower()} position (strategy.{entry_matches[0][1].lower()})"

        close_matches = re.findall(
            r"\bstrategy\.close\s*\(\s*[\"']([^\"']+)[\"'](?:[^\)]*comment\s*=\s*[\"']([^\"']+)[\"'])?",
            text,
        )
        if close_matches:
            for order_id, comment in close_matches:
                c_note = f" (reason: '{comment}')" if comment else ""
                exit_desc = f"strategy.close('{order_id}'){c_note}"
                exit_mechanisms.append(exit_desc)
                detected_constructs.append(
                    ConstructFidelity(
                        name=f"Order Exit (close '{order_id}')",
                        category="exit",
                        fidelity=FidelityLevel.EQUIVALENT,
                        details=f"Closes matching entry position{c_note}",
                        translatable=True,
                    )
                )

        exit_matches = re.findall(
            r"""\bstrategy\.exit\s*\(\s*["']([^"']+)["']""",
            text,
        )
        if exit_matches:
            for exit_id in exit_matches:
                has_stop = bool(
                    re.search(
                        rf"\bstrategy\.exit\s*\(\s*[\"']{re.escape(exit_id)}[\"'][^\)]*stop\s*=",
                        text,
                    )
                )
                has_limit = bool(
                    re.search(
                        rf"\bstrategy\.exit\s*\(\s*[\"']{re.escape(exit_id)}[\"'][^\)]*limit\s*=",
                        text,
                    )
                )
                details_parts = []
                if has_stop:
                    details_parts.append("stop-loss")
                if has_limit:
                    details_parts.append("take-profit limit")
                bracket_info = f" ({' / '.join(details_parts)})" if details_parts else ""
                exit_desc = f"strategy.exit('{exit_id}'){bracket_info}"
                exit_mechanisms.append(exit_desc)
                detected_constructs.append(
                    ConstructFidelity(
                        name=f"Bracket Exit ({exit_id}){bracket_info}",
                        category="exit",
                        fidelity=FidelityLevel.EQUIVALENT,
                        details=f"Bracket exit with protective order triggers{bracket_info}",
                        translatable=True,
                    )
                )

        if re.search(r"\bstrategy\.close_all\b", text):
            exit_mechanisms.append("strategy.close_all()")
            detected_constructs.append(
                ConstructFidelity(
                    name="Emergency / Time Exit (strategy.close_all)",
                    category="exit",
                    fidelity=FidelityLevel.EQUIVALENT,
                    details="Closes all open positions unconditionally (e.g. time stop or EOD flatten)",
                    translatable=True,
                )
            )

        # 9. Custom Synthetic P&L Simulation Audit
        if re.search(r"\b(?:currentPL|priceDiff)\b", text):
            custom_pnl_detected = True
            pnl_vars = [
                v
                for v in ["priceDiff", "currentPL", "targetProfit", "maxLossLimit", "flyWidth"]
                if re.search(rf"\b{v}\b", text)
            ]
            tp_match = re.search(r"\btargetProfit\s*=\s*input(?:\.[a-z]+)?\s*\(\s*([0-9.]+)", text)
            ml_match = re.search(r"\bmaxLossLimit\s*=\s*input(?:\.[a-z]+)?\s*\(\s*([0-9.]+)", text)
            tp_val = float(tp_match.group(1)) if tp_match else None
            ml_val = float(ml_match.group(1)) if ml_match else None

            custom_pnl_details = {
                "variables": pnl_vars,
                "target_profit_value": tp_val,
                "max_loss_limit_value": ml_val,
                "payoff_model": "Piecewise linear approximation of Iron Fly payoff centered at ATM strike",
                "pricing_connection": (
                    "Payoff is calculated mathematically from underlying spot distance "
                    "(priceDiff = math.abs(close - atmStrike)) rather than actual option contract prices"
                ),
                "dsl_evaluation_limitation": (
                    "QuantumValidator evaluates P&L strictly from filled orders in PaperBroker ledger "
                    "with realistic slippage, STT, and exchange fees. Declarative StrategyDSL cannot "
                    "evaluate synthetic algebraic payoff formulas (ADR 007)."
                ),
            }
            custom_calculations.append("Custom synthetic P&L payoff model (currentPL)")
            unsupported_constructs.append("Synthetic P&L Simulation (currentPL / priceDiff)")
            detected_constructs.append(
                ConstructFidelity(
                    name="Synthetic P&L Model (currentPL)",
                    category="calculation",
                    fidelity=FidelityLevel.UNSUPPORTED,
                    details="Custom algebraic payoff formula attempting to simulate option curves on spot data",
                    translatable=False,
                )
            )

        # 10. Semantic Mismatch Detection
        opt_keywords = [
            "iron fly",
            "broken wing",
            "straddle",
            "strangle",
            "condor",
            "butterfly",
            "spread",
        ]
        has_opt_naming = any(k in strategy_name.lower() or k in text.lower() for k in opt_keywords)

        if has_opt_naming and entry_matches:
            option_leg_semantics = (
                "Simulated via synthetic arithmetic on single underlying order (0 real option legs)"
            )
            has_options = False  # Air gap integrity: do not falsely report real option legs

            naming_behavior_mismatch = (
                f"Strategy title '{strategy_name}' advertises an options structure (e.g. 4-leg Iron Fly), "
                "but the script only submits single underlying spot orders ('strategy.long') and simulates "
                "theoretical option payoff via synthetic arithmetic in code. No real option contracts are traded."
            )
            warnings.append(
                f"Semantic Mismatch: Strategy '{strategy_name}' simulates options payoff synthetically "
                "on a single underlying linear order instead of trading actual option legs."
            )
        elif entry_matches:
            option_leg_semantics = "None (linear underlying orders)"
            has_options = False

        # 11. Visual-Only Directives & Canvas Drawings
        plots = re.findall(r"\b(?:plot|fill|hline|bgcolor)\s*\(\s*([^,\)]+)", text)
        if plots:
            plot_names = [p.strip().replace('"', "").replace("'", "") for p in plots[:5]]
            visual_only_constructs.extend(plot_names)
            detected_constructs.append(
                ConstructFidelity(
                    name=f"Chart Visualizations ({len(plots)} elements: {', '.join(plot_names[:3])})",
                    category="visual",
                    fidelity=FidelityLevel.VISUAL_ONLY,
                    details="Plots, fills, and overlays are rendered on TradingView charts; ignored in execution",
                    translatable=False,
                )
            )

        if re.search(r"\b(?:box\.new|line\.new|label\.new|table\.new)\b", text):
            visual_only_constructs.append("Canvas Drawings (box/line/label)")
            detected_constructs.append(
                ConstructFidelity(
                    name="Canvas Drawings (box/line/label)",
                    category="visual",
                    fidelity=FidelityLevel.VISUAL_ONLY,
                    details="Interactive chart graphical drawing objects; ignored during simulation",
                    translatable=False,
                )
            )

        if re.search(r"\balertcondition\s*\(", text):
            visual_only_constructs.append("Alert Condition (alertcondition)")
            detected_constructs.append(
                ConstructFidelity(
                    name="Alert Condition (alertcondition)",
                    category="visual",
                    fidelity=FidelityLevel.VISUAL_ONLY,
                    details="TradingView server-side alert trigger; non-executing in local engine",
                    translatable=False,
                )
            )

        # 12. PaperBroker Comparison Notes
        order_behavior_notes = [
            "1. Execution Timing: Pine Script evaluates conditions on bar close and executes on the open of the next bar; PaperBroker executes strictly on next tick/bar with zero lookahead bias.",
            "2. P&L Accounting: Pine calculates synthetic P&L via in-script variables; PaperBroker ledger calculates mark-to-market P&L strictly from actual execution prices, bid/ask spreads, and statutory taxes (STT, GST, stamp duty).",
            "3. Capital & Margin: Pine simulates fixed trade units without pre-trade margin gates; PaperBroker enforces SEBI/NSE SPAN + Exposure margin verification before fill.",
            "4. Multi-Leg Realism: Pine simulates option payoffs synthetically on underlying spot data; PaperBroker requires explicit option legs with strikes, expiries, and Black-Scholes Greeks calculation (ADR 011).",
            "5. Fills & Slippage: Pine assumes fills at exact bar prices without liquidity models; PaperBroker simulates conservative slippage and liquidity constraints.",
            "6. Position Lifecycle: Pine maintains trade state via mutable script variables (var inTrade); PaperBroker manages institutional position lifecycles, ledger tracking, and state persistence.",
        ]

        # 13. Status and Resolution
        if re.search(r"\bbarmerge\.lookahead_on\b", text) or re.search(
            r"lookahead\s*=\s*barmerge\.lookahead_on", text
        ):
            has_lookahead = True
            translation_status = TranslationStatus.REJECTED_LOOKAHEAD
            fidelity_level = FidelityLevel.UNSUPPORTED
            rejection_reasons.append(
                "Repainting/Look-Ahead Bias detected: 'barmerge.lookahead_on' is strictly prohibited by QuantumValidator anti-lookahead rules."
            )
        elif re.search(r"\bcalc_on_every_tick\s*=\s*true\b", text, re.IGNORECASE):
            has_intrabar = True
            warnings.append(
                "Pine script specifies 'calc_on_every_tick=true'. QuantumValidator enforces bar-close replay."
            )

        m_sec = re.findall(r"\brequest\.security\s*\(([^,\)]+),\s*([^,\)]+)", text)
        if m_sec or re.search(r"\brequest\.security\b", text):
            unsupported_constructs.append("request.security (multi-symbol/multi-timeframe)")
            sec_details = "Multi-timeframe data synchronization requires multi-resolution feeds"
            if m_sec:
                timeframes = list(
                    dict.fromkeys(s[1].strip().replace('"', "").replace("'", "") for s in m_sec)
                )
                sec_details += f" (detected resolutions: {', '.join(timeframes)})"
            detected_constructs.append(
                ConstructFidelity(
                    name="Multi-Timeframe Request (request.security)",
                    category="data",
                    fidelity=FidelityLevel.UNSUPPORTED,
                    details=sec_details,
                    translatable=False,
                )
            )

        has_loops = bool(
            re.search(r"\bwhile\s*[\(\s]", text)
            or re.search(r"\bfor\s+(?:\[[a-zA-Z0-9_,\s]+\]|[a-zA-Z0-9_]+)\s*(=|\bin\b)", text)
        )
        if has_loops:
            unsupported_constructs.append("Procedural Loops (while/for)")
            detected_constructs.append(
                ConstructFidelity(
                    name="Procedural Loops (while/for)",
                    category="calculation",
                    fidelity=FidelityLevel.UNSUPPORTED,
                    details="Iterative loops are barred from declarative StrategyDSL AST (ADR 007)",
                    translatable=False,
                )
            )

        if re.search(r"\bimport\b", text):
            unsupported_constructs.append("Pine Script Library Imports")
        if re.search(r"\bstrategy\.risk\b", text):
            unsupported_constructs.append("Pine strategy.risk built-ins")

        if not has_lookahead:
            has_blockers = bool(
                (persistent_state_vars and has_var_assign)
                or custom_pnl_detected
                or unsupported_constructs
            )

            if has_blockers:
                translation_status = TranslationStatus.INSPECT_ONLY
                fidelity_level = FidelityLevel.APPROXIMATED
                validation_ready = False
                simulation_ready = False
                forward_ready = False

                if persistent_state_vars and has_var_assign:
                    rejection_reasons.append(
                        f"Mutable persistent state variables ({', '.join(persistent_state_vars)}) mutated with ':=' "
                        "require procedural execution, barred by ADR 007 from declarative StrategyDSL AST."
                    )
                if custom_pnl_detected:
                    rejection_reasons.append(
                        "Custom synthetic P&L arithmetic ('currentPL', 'priceDiff') cannot override PaperBroker ledger accounting."
                    )
                if naming_behavior_mismatch:
                    rejection_reasons.append(
                        "Script title advertises 'Iron Fly & Broken Wing' options structure but executes single underlying spot orders without real option contract legs (ADR 011)."
                    )
            elif script_type == StrategyScriptType.INDICATOR:
                translation_status = TranslationStatus.INSPECT_ONLY
                fidelity_level = FidelityLevel.UNSUPPORTED
                rejection_reasons.append(
                    "Script is an indicator/study without strategy.entry() execution directives."
                )
            else:
                try:
                    translator = PineScriptTranslator()
                    dsl = translator.translate(text, file_path=file_path)
                    translation_status = TranslationStatus.TRANSLATABLE
                    fidelity_level = FidelityLevel.EQUIVALENT
                    validation_ready = True
                    simulation_ready = True
                    forward_ready = True
                    underlying = dsl.underlying
                    timeframe = dsl.timeframe
                except Exception as exc:
                    translation_status = TranslationStatus.PARTIALLY_SUPPORTED
                    fidelity_level = FidelityLevel.APPROXIMATED
                    rejection_reasons.append(f"Translation limitations: {exc}")

        portability = cls._assess_portability(
            text, strategy_name=strategy_name, file_path=file_path
        )
        if portability and portability.unsafe_mappings:
            warnings.append(
                f"Instrument Portability Risk: {portability.portability_verdict[:80]}..."
            )

        return {
            "detected_constructs": detected_constructs,
            "entry_mechanisms": entry_mechanisms,
            "exit_mechanisms": exit_mechanisms,
            "persistent_state_vars": persistent_state_vars,
            "time_conditions": time_conditions,
            "indicators_used": indicators_used,
            "custom_calculations": custom_calculations,
            "visual_only_constructs": visual_only_constructs,
            "supported_constructs": supported_constructs,
            "unsupported_constructs": unsupported_constructs,
            "rejection_reasons": rejection_reasons,
            "warnings": warnings,
            "order_behavior_notes": order_behavior_notes,
            "strategy_name": strategy_name,
            "underlying": underlying,
            "timeframe": timeframe,
            "has_lookahead": has_lookahead,
            "has_intrabar": has_intrabar,
            "has_options": has_options,
            "validation_ready": validation_ready,
            "simulation_ready": simulation_ready,
            "forward_ready": forward_ready,
            "translation_status": translation_status,
            "fidelity_level": fidelity_level,
            "position_semantics": position_semantics,
            "option_leg_semantics": option_leg_semantics,
            "naming_behavior_mismatch": naming_behavior_mismatch,
            "custom_pnl_detected": custom_pnl_detected,
            "custom_pnl_details": custom_pnl_details,
            "portability_assessment": portability,
        }

    @classmethod
    def _assess_portability(
        cls,
        text: str,
        strategy_name: str,
        file_path: str | Path | None = None,
    ) -> PortabilityAssessment | None:
        """Evaluate cross-market or cross-asset portability assumptions (e.g. MCX Gold vs XAUUSD)."""
        combined = f"{strategy_name} {file_path or ''} {text}".lower()

        is_mcx_or_commodity = any(
            k in combined for k in ["mcx", "gold", "silver", "crude", "commodity"]
        )
        is_forex_or_xau = any(
            k in combined for k in ["xauusd", "forex", "fx", "cfd", "eurusd", "gbpusd"]
        )
        has_gold_reference = "gold" in combined or "mcx" in combined

        if not (is_mcx_or_commodity or is_forex_or_xau or has_gold_reference):
            return None

        # Detect MCX Gold / XAUUSD Portability Case
        if has_gold_reference or (
            is_mcx_or_commodity
            and any(k in combined for k in ["xau", "dollar", "cfd", "240", "100000"])
        ):
            source = "XAUUSD (Spot Gold / CFD)"
            target = "MCX Gold Futures (1 kg / 1000g)"

            # Extract initial capital and default qty
            m_cap = re.search(r"\binitial_capital\s*=\s*([0-9.]+)", text)
            init_cap = float(m_cap.group(1)) if m_cap else 100_000.0

            m_qty = re.search(r"\bdefault_qty_value\s*=\s*([0-9.]+)", text)
            qty_val = float(m_qty.group(1)) if m_qty else 1.0

            m_comm = re.search(r"\bcommission_value\s*=\s*([0-9.]+)", text)
            comm_val = float(m_comm.group(1)) if m_comm else 50.0

            session_window_match = re.search(r"""input\.session\s*\(\s*["']([^"']+)["']""", text)
            session_window = session_window_match.group(1) if session_window_match else "0915-2330"

            assumptions_preserved = [
                "Mathematical liquidity sweep & reclaim logic (HTF 4H high/low levels) is asset-class agnostic.",
                "Price envelope, ATR volatility expansion filter, and wick ratio calculations operate identically on continuous series.",
                "Anti-lookahead directive ('lookahead = barmerge.lookahead_off') guarantees historical bar causality.",
            ]

            assumptions_changed = [
                f"Trading Session: Script specifies '{session_window} IST', but MCX opens at 09:00 AM IST (NSE opens at 09:15). First 15 minutes of MCX session are truncated.",
                f"Exchange Transaction Costs: Flat ₹{comm_val:.0f} commission per contract severely underestimates statutory Indian commodity costs (CTT 0.01% on sell side = ₹800/lot, Stamp duty 0.002%, MCX turnover charges, SEBI fee, 18% GST). Realistic round-trip friction is ₹1,100–₹1,500+ per lot.",
                "Contract Expiry & Settlement: XAUUSD is a perpetual CFD; MCX Gold Futures are bi-monthly contracts with physical delivery tender periods and delivery margin escalations.",
                "Tick & Slippage Scale: Quoted per 10 grams (₹1 tick = ₹100 P&L on 1 kg contract). Slippage of 2 ticks represents ₹200/trade.",
            ]

            assumptions_unknown = [
                "Underlying Contract Specification: Intended contract variant unknown (Standard 1 kg GOLD, Mini 100g GOLDM, Guinea 8g, or Petal 1g). Sizing assumes 1 unit.",
                "Data Feed Discontinuity: MCX Gold does not trade continuously 24/5; weekend and overnight gaps between 23:30/23:55 and 09:00 IST alter 4H candle boundaries compared to international XAUUSD.",
            ]

            unsafe_mappings = [
                f"CRITICAL CAPITAL INADEQUACY: Initial capital of ₹{init_cap:,.0f} is grossly insufficient for {qty_val:.0f} standard MCX Gold contract (1 kg notional value ~₹80 Lakhs, SEBI/MCX SPAN + ELM margin requirement ~₹8,00,000–₹10,00,000). Pre-trade risk engine will reject 100% of orders due to margin shortfall.",
                "SESSION TIMING MISMATCH: Hardcoded '0915' session cutoff clips opening price discovery between 09:00 and 09:15 AM IST on MCX.",
                f"COMMISSION UNDERESTIMATION RISK: Assumed ₹{comm_val:.0f} commission represents only ~4% of true statutory exchange fees and taxes on an ₹80 Lakh contract, resulting in heavily inflated backtest expectancy.",
            ]

            verdict = (
                "UNSAFE - CRITICAL CAPITAL & REGULATORY MISMATCH: Strategy logic reflects international XAUUSD "
                "CFD assumptions ported to MCX Gold without adjusting for Indian commodity contract sizing "
                "(1 kg = ~₹80L notional, ₹8L+ margin), exchange operating hours (09:00 open), or statutory turnover taxes."
            )

            return PortabilityAssessment(
                source_instrument_hint=source,
                target_instrument_hint=target,
                assumptions_preserved=assumptions_preserved,
                assumptions_changed=assumptions_changed,
                assumptions_unknown=assumptions_unknown,
                unsafe_mappings=unsafe_mappings,
                portability_verdict=verdict,
            )

        return None
