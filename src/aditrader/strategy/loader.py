"""Unified, safe strategy file loader supporting JSON, YAML, and translatable Pine Script."""

from pathlib import Path

from aditrader.strategy.builder.schema import StrategyDSL
from aditrader.strategy.inspector.detector import StrategyFormatDetector
from aditrader.strategy.inspector.models import StrategyFormat
from aditrader.strategy.translators.pine import PineScriptTranslator
from aditrader.strategy.translators.yaml_dsl import YAMLStrategyLoader


def load_strategy_file(
    file_path: str | Path,
    *,
    default_underlying: str = "NIFTY",
    default_timeframe: str = "5m",
) -> StrategyDSL:
    """Safely load and validate a strategy file into canonical StrategyDSL.

    Supports:
    - .json: Declarative StrategyDSL AST (schema_version: "1.0")
    - .yaml / .yml: Declarative StrategyDSL YAML (schema_version: "1.0")
    - .pine / .tv: Deterministic TradingView Pine Script translated into StrategyDSL

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If format is unsupported, malformed, or violates anti-lookahead rules.
    """
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Strategy file not found: {path}")

    content = path.read_text(encoding="utf-8", errors="replace")
    fmt, lang, _, _ = StrategyFormatDetector.detect(content, file_path=path)

    if fmt == StrategyFormat.JSON_DSL:
        try:
            return StrategyDSL.model_validate_json(content)
        except Exception as exc:
            raise ValueError(f"Failed to parse JSON StrategyDSL from '{path.name}': {exc}") from exc

    if fmt == StrategyFormat.YAML_DSL:
        return YAMLStrategyLoader.load_from_str(content)

    if fmt == StrategyFormat.PINE_SCRIPT:
        translator = PineScriptTranslator()
        return translator.translate(
            content,
            default_underlying=default_underlying,
            default_timeframe=default_timeframe,
            file_path=path,
        )

    raise ValueError(
        f"Strategy file '{path.name}' is classified as {fmt.value} ({lang}), "
        "which cannot be directly executed as an AST state machine. "
        f"Use 'aditrader inspect-strategy {path}' to audit its syntax and compatibility."
    )
