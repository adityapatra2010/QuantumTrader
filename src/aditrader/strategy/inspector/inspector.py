"""Static strategy file inspector and semantic compatibility analyzer.

Per ADR 001, ADR 002, ADR 007, and ADR 011:
- Never executes, evals, or imports untrusted strategy files.
- Provides operators with full visibility into format, language, constructs,
  lookahead risks, options air-gap compliance, and validation readiness.
"""

import ast
import re
from pathlib import Path

from pydantic import ValidationError

from aditrader.strategy.builder.schema import StrategyDSL
from aditrader.strategy.inspector.detector import StrategyFormatDetector
from aditrader.strategy.inspector.models import (
    FidelityLevel,
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
            # Check lookahead & repainting
            if re.search(r"\bbarmerge\.lookahead_on\b", content) or re.search(
                r"lookahead\s*=\s*barmerge\.lookahead_on", content
            ):
                has_lookahead = True
                translation_status = TranslationStatus.REJECTED_LOOKAHEAD
                rejection_reasons.append(
                    "Script uses 'barmerge.lookahead_on', which introduces severe look-ahead "
                    "bias and historical repainting. Prohibited by QuantumValidator."
                )

            # Check intrabar execution
            if re.search(r"calc_on_every_tick\s*=\\s*true", content, re.IGNORECASE):
                has_intrabar = True
                warnings.append(
                    "Script specifies calc_on_every_tick=true. QuantumValidator simulates point-in-time "
                    "closed bars (on_bar) rather than intrabar tick order queues."
                )

            # Detect indicators
            for ind_name, pattern in [
                ("SMA", r"(?:ta\.)?sma\s*\("),
                ("EMA", r"(?:ta\.)?ema\s*\("),
                ("RSI", r"(?:ta\.)?rsi\s*\("),
                ("ATR", r"(?:ta\.)?atr\s*\("),
                ("Bollinger Bands", r"(?:ta\.)?bb\s*\("),
                ("Supertrend", r"(?:ta\.)?supertrend\s*\("),
                ("Crossover", r"(?:ta\.)?crossover\s*\("),
                ("Crossunder", r"(?:ta\.)?crossunder\s*\("),
            ]:
                if re.search(pattern, content):
                    supported_constructs.append(ind_name)

            # Detect unsupported features
            if re.search(r"\brequest\.security\b", content):
                unsupported_constructs.append("request.security (multi-symbol/multi-timeframe)")
            if re.search(r"\bwhile\b|\bfor\b", content):
                unsupported_constructs.append("Procedural Loops (while/for)")
            if re.search(r"\bimport\b", content):
                unsupported_constructs.append("Pine Script Library Imports")
            if re.search(r"\bstrategy\.risk\b", content):
                unsupported_constructs.append("Pine strategy.risk built-ins")

            m_name = re.search(r"\bstrategy\s*\(\s*[\"']([^\"']+)[\"']", content)
            strategy_name = m_name.group(1).strip() if m_name else "Pine Script"

            if has_lookahead:
                translation_status = TranslationStatus.REJECTED_LOOKAHEAD
            elif script_type == StrategyScriptType.INDICATOR:
                translation_status = TranslationStatus.INSPECT_ONLY
                rejection_reasons.append(
                    "Script is an indicator/study without strategy.entry() execution directives."
                )
            else:
                # Attempt dry-run translation
                try:
                    translator = PineScriptTranslator()
                    dsl = translator.translate(content, file_path=file_path)
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
        )
