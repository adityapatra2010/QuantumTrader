"""Deterministic strategy format and language detection engine.

Per ADR 007 and institutional security guidelines:
- Never executes or imports code.
- Operates strictly on static text, tokens, and regular expressions.
"""

import json
import re
from pathlib import Path

import yaml

from aditrader.strategy.inspector.models import StrategyFormat, StrategyScriptType


class StrategyFormatDetector:
    """Classifies strategy files and text content into known strategy language ecosystems."""

    @classmethod
    def detect(
        cls, content: str, file_path: str | Path | None = None
    ) -> tuple[StrategyFormat, str, str | None, StrategyScriptType]:
        """Detect strategy format, language, version (if detectable), and script type.

        Returns:
            (StrategyFormat, language_name, version_str, StrategyScriptType)
        """
        fname = Path(file_path).name.lower() if file_path else ""
        clean_text = content.strip()

        # ----------------------------------------------------------------------
        # 1. Native JSON AST DSL Check
        # ----------------------------------------------------------------------
        if clean_text.startswith("{") and clean_text.endswith("}"):
            try:
                data = json.loads(clean_text)
                if isinstance(data, dict):
                    schema_ver = str(data.get("schema_version", ""))
                    if schema_ver or ("entry_conditions" in data and "underlying" in data):
                        return (
                            StrategyFormat.JSON_DSL,
                            "JSON AST DSL",
                            schema_ver if schema_ver else "1.0",
                            StrategyScriptType.STRATEGY,
                        )
            except Exception:
                pass

        # ----------------------------------------------------------------------
        # 2. Native YAML AST DSL Check
        # ----------------------------------------------------------------------
        if fname.endswith((".yaml", ".yml")) or (
            "schema_version:" in clean_text and "entry_conditions:" in clean_text
        ):
            try:
                data = yaml.safe_load(clean_text)
                if isinstance(data, dict):
                    schema_ver = str(data.get("schema_version", ""))
                    if schema_ver or ("entry_conditions" in data and "underlying" in data):
                        return (
                            StrategyFormat.YAML_DSL,
                            "YAML AST DSL",
                            schema_ver if schema_ver else "1.0",
                            StrategyScriptType.STRATEGY,
                        )
            except Exception:
                pass

        # ----------------------------------------------------------------------
        # 3. TradingView Pine Script Check
        # ----------------------------------------------------------------------
        has_pine_pragma = bool(
            re.search(r"//\s*@version\s*=\s*([0-9]+)", clean_text, re.IGNORECASE)
        )
        has_pine_func = bool(
            re.search(
                r"(?:strategy|indicator|study)\s*\(|ta\.(?:sma|ema|rsi|atr|crossover|crossunder)|strategy\.(?:entry|close|exit)",
                clean_text,
            )
        )
        if fname.endswith((".pine", ".tv")) or has_pine_pragma or has_pine_func:
            # Extract version
            m_ver = re.search(r"//\s*@version\s*=\s*([0-9]+)", clean_text, re.IGNORECASE)
            version_str = f"v{m_ver.group(1)}" if m_ver else "v5 (inferred)"

            # Strategy vs Indicator
            is_strat = bool(
                re.search(r"\bstrategy\s*\(|\bstrategy\.(?:entry|order|close)\b", clean_text)
            )
            script_type = StrategyScriptType.STRATEGY if is_strat else StrategyScriptType.INDICATOR
            return (
                StrategyFormat.PINE_SCRIPT,
                "TradingView Pine Script",
                version_str,
                script_type,
            )

        # ----------------------------------------------------------------------
        # 4. TradeStation / MultiCharts EasyLanguage / PowerLanguage
        # ----------------------------------------------------------------------
        if fname.endswith((".eld", ".ela", ".els")) or (
            re.search(r"\b(?:Inputs|Vars|Variables)\s*:", clean_text, re.IGNORECASE)
            and re.search(
                r"\b(?:Buy|Sell|ExitLong|ExitShort)\s+(?:next\s+bar|at\s+market|at\s+stop)\b",
                clean_text,
                re.IGNORECASE,
            )
        ):
            return (
                StrategyFormat.EASYLANGUAGE,
                "TradeStation EasyLanguage",
                None,
                StrategyScriptType.STRATEGY,
            )

        # ----------------------------------------------------------------------
        # 5. AmiBroker AFL
        # ----------------------------------------------------------------------
        if fname.endswith(".afl") or (
            re.search(r"\b(?:_SECTION_BEGIN|_SECTION_END)\b", clean_text)
            or (
                re.search(r"\bBuy\s*=", clean_text)
                and re.search(r"\bSell\s*=", clean_text)
                and re.search(r"\b(?:Cross|MA|EMA|RSI)\s*\(", clean_text)
            )
        ):
            is_strat = bool(re.search(r"\b(?:Buy|Sell|Short|Cover)\s*=", clean_text))
            return (
                StrategyFormat.AMIBROKER_AFL,
                "AmiBroker AFL",
                None,
                StrategyScriptType.STRATEGY if is_strat else StrategyScriptType.INDICATOR,
            )

        # ----------------------------------------------------------------------
        # 6. ThinkOrSwim thinkScript
        # ----------------------------------------------------------------------
        if fname.endswith((".ts", ".thinkscript")) or (
            re.search(r"\b(?:AddOrder|declare\s+lower|plot\s+)", clean_text)
            and re.search(r"\bdef\s+[a-zA-Z0-9_]+\s*=", clean_text)
        ):
            is_strat = bool(re.search(r"\bAddOrder\s*\(", clean_text))
            return (
                StrategyFormat.THINKSCRIPT,
                "ThinkOrSwim thinkScript",
                None,
                StrategyScriptType.STRATEGY if is_strat else StrategyScriptType.INDICATOR,
            )

        # ----------------------------------------------------------------------
        # 7. MetaTrader MQL4 / MQL5
        # ----------------------------------------------------------------------
        if fname.endswith((".mq4", ".ex4")):
            return (
                StrategyFormat.METATRADER_MQL4,
                "MetaTrader MQL4",
                "MQL4",
                StrategyScriptType.STRATEGY,
            )
        if fname.endswith((".mq5", ".ex5")):
            return (
                StrategyFormat.METATRADER_MQL5,
                "MetaTrader MQL5",
                "MQL5",
                StrategyScriptType.STRATEGY,
            )
        if re.search(r"#property\s+(?:copyright|link|version|strict)", clean_text) or re.search(
            r"\b(?:OnTick|OnInit|OnBar|OrderSend|iMA|iRSI)\s*\(", clean_text
        ):
            ver = "MQL5" if "OnTick" in clean_text and "OnInit" in clean_text else "MQL4"
            fmt = (
                StrategyFormat.METATRADER_MQL5 if ver == "MQL5" else StrategyFormat.METATRADER_MQL4
            )
            return (fmt, f"MetaTrader {ver}", ver, StrategyScriptType.STRATEGY)

        # ----------------------------------------------------------------------
        # 8. NinjaTrader NinjaScript (C#)
        # ----------------------------------------------------------------------
        if "NinjaTrader.NinjaScript" in clean_text or (
            re.search(r":\s*Strategy\b", clean_text) and "OnBarUpdate" in clean_text
        ):
            return (
                StrategyFormat.NINJATRADER,
                "NinjaTrader NinjaScript (C#)",
                None,
                StrategyScriptType.STRATEGY,
            )

        # ----------------------------------------------------------------------
        # 9. QuantConnect LEAN (Python or C#)
        # ----------------------------------------------------------------------
        if "AlgorithmImports" in clean_text or "QCAlgorithm" in clean_text:
            lang = "LEAN Python" if "def Initialize" in clean_text else "LEAN C#"
            return (
                StrategyFormat.QUANTCONNECT_LEAN,
                f"QuantConnect {lang}",
                None,
                StrategyScriptType.STRATEGY,
            )

        # ----------------------------------------------------------------------
        # 10. Python Strategy Frameworks
        # ----------------------------------------------------------------------
        if "backtrader" in clean_text or "bt.Strategy" in clean_text:
            return (
                StrategyFormat.PYTHON_BACKTRADER,
                "Python (Backtrader)",
                "Python 3",
                StrategyScriptType.STRATEGY,
            )
        if "vectorbt" in clean_text or "vbt.Portfolio" in clean_text:
            return (
                StrategyFormat.PYTHON_VECTORBT,
                "Python (vectorbt)",
                "Python 3",
                StrategyScriptType.STRATEGY,
            )
        if "freqtrade" in clean_text or "IStrategy" in clean_text:
            return (
                StrategyFormat.PYTHON_FREQTRADE,
                "Python (Freqtrade)",
                "Python 3",
                StrategyScriptType.STRATEGY,
            )
        if fname.endswith(".py") or re.search(
            r"\bclass\s+[A-Za-z0-9_]+.*def\s+on_bar\b", clean_text
        ):
            return (
                StrategyFormat.PYTHON_GENERIC,
                "Python (Custom/Generic)",
                "Python 3",
                StrategyScriptType.STRATEGY,
            )

        return (StrategyFormat.UNKNOWN, "Unknown Format", None, StrategyScriptType.UNKNOWN)
