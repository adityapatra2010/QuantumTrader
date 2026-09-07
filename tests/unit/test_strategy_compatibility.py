"""Unit tests for strategy format discovery, YAML loading, Pine Script translation, and inspection."""

import argparse
from pathlib import Path

import pytest

from aditrader.cli.commands import cmd_backtest, cmd_inspect_strategy, cmd_validate
from aditrader.core.models.enums import OrderSide
from aditrader.strategy.builder.schema import (
    ASTOperator,
    ConditionCategory,
    ConditionGroup,
    ConditionNode,
    StrategyDSL,
    StrategyLegDefinition,
)
from aditrader.strategy.inspector.detector import StrategyFormatDetector
from aditrader.strategy.inspector.inspector import StrategyInspector
from aditrader.strategy.inspector.models import (
    StrategyFormat,
    StrategyScriptType,
    TranslationStatus,
)
from aditrader.strategy.loader import load_strategy_file
from aditrader.strategy.translators.pine import PineScriptTranslator
from aditrader.strategy.translators.yaml_dsl import YAMLStrategyLoader

# ==============================================================================
# 1. Strategy Format Detector Tests
# ==============================================================================


class TestStrategyFormatDetector:
    """Tests deterministic identification of strategy code/config representations."""

    def test_detect_json_dsl(self) -> None:
        content = """{
            "schema_version": "1.0",
            "name": "JSON MA Test",
            "underlying": "NIFTY",
            "timeframe": "5m",
            "entry_conditions": {
                "operator": "AND",
                "conditions": [
                    {
                        "category": "indicator",
                        "field": "close",
                        "operator": "GREATER_THAN",
                        "threshold": 100.0
                    }
                ]
            }
        }"""
        fmt, lang, ver, stype = StrategyFormatDetector.detect(content, "my_strategy.json")
        assert fmt == StrategyFormat.JSON_DSL
        assert lang == "JSON AST DSL"
        assert ver == "1.0"
        assert stype == StrategyScriptType.STRATEGY

    def test_detect_yaml_dsl(self) -> None:
        content = """
schema_version: "1.0"
name: "YAML Breakout"
underlying: "BANKNIFTY"
timeframe: "15m"
entry_conditions:
  operator: "AND"
  conditions:
    - category: "indicator"
      field: "close"
      operator: "GREATER_THAN"
      threshold: 100.0
"""
        fmt, lang, ver, stype = StrategyFormatDetector.detect(content, "strategy.yaml")
        assert fmt == StrategyFormat.YAML_DSL
        assert lang == "YAML AST DSL"
        assert ver == "1.0"
        assert stype == StrategyScriptType.STRATEGY

    def test_detect_pine_script_v5_strategy(self) -> None:
        content = """
//@version=5
strategy("Moving Average Cross", overlay=true)
fast_ma = ta.sma(close, 9)
slow_ma = ta.sma(close, 21)
if ta.crossover(fast_ma, slow_ma)
    strategy.entry("Long", strategy.long)
"""
        fmt, lang, ver, stype = StrategyFormatDetector.detect(content, "ma_cross.pine")
        assert fmt == StrategyFormat.PINE_SCRIPT
        assert "Pine Script" in lang
        assert ver == "v5"
        assert stype == StrategyScriptType.STRATEGY

    def test_detect_pine_script_v4_indicator(self) -> None:
        content = """
//@version=4
study("My Indicator", overlay=true)
plot(sma(close, 14))
"""
        fmt, lang, ver, stype = StrategyFormatDetector.detect(content, "ind.tv")
        assert fmt == StrategyFormat.PINE_SCRIPT
        assert ver == "v4"
        assert stype == StrategyScriptType.INDICATOR

    def test_detect_easylanguage(self) -> None:
        content = """
Inputs: FastLen(9), SlowLen(21);
Vars: FastMA(0), SlowMA(0);
FastMA = Average(Close, FastLen);
SlowMA = Average(Close, SlowLen);
If FastMA crosses above SlowMA Then
    Buy next bar at market;
"""
        fmt, lang, _, stype = StrategyFormatDetector.detect(content, "strategy.eld")
        assert fmt == StrategyFormat.EASYLANGUAGE
        assert stype == StrategyScriptType.STRATEGY

    def test_detect_amibroker_afl(self) -> None:
        content = """
_SECTION_BEGIN("Price");
Fast = MA(Close, 9);
Slow = MA(Close, 21);
Buy = Cross(Fast, Slow);
Sell = Cross(Slow, Fast);
_SECTION_END();
"""
        fmt, lang, _, stype = StrategyFormatDetector.detect(content, "system.afl")
        assert fmt == StrategyFormat.AMIBROKER_AFL
        assert stype == StrategyScriptType.STRATEGY

    def test_detect_thinkscript(self) -> None:
        content = """
declare lower;
input length = 14;
def rsi = RSI(length);
AddOrder(OrderType.BUY_AUTO, rsi < 30);
AddOrder(OrderType.SELL_AUTO, rsi > 70);
"""
        fmt, lang, _, stype = StrategyFormatDetector.detect(content, "strat.ts")
        assert fmt == StrategyFormat.THINKSCRIPT
        assert stype == StrategyScriptType.STRATEGY

    def test_detect_metatrader_mql4(self) -> None:
        content = """
#property copyright "Author"
#property strict
int OnInit() { return(INIT_SUCCEEDED); }
void OnTick() {
    double ma = iMA(NULL, 0, 14, 0, MODE_SMA, PRICE_CLOSE, 0);
    OrderSend(Symbol(), OP_BUY, 1.0, Ask, 3, 0, 0);
}
"""
        fmt, _, ver, stype = StrategyFormatDetector.detect(content, "expert.mq4")
        assert fmt == StrategyFormat.METATRADER_MQL4
        assert stype == StrategyScriptType.STRATEGY

    def test_detect_ninjascript(self) -> None:
        content = """
namespace NinjaTrader.NinjaScript.Strategies
{
    public class SampleStrategy : Strategy
    {
        protected override void OnBarUpdate()
        {
            if (SMA(14)[0] > SMA(50)[0])
                EnterLong();
        }
    }
}
"""
        fmt, _, _, stype = StrategyFormatDetector.detect(content, "SampleStrategy.cs")
        assert fmt == StrategyFormat.NINJATRADER
        assert stype == StrategyScriptType.STRATEGY

    def test_detect_quantconnect_lean(self) -> None:
        content = """
from AlgorithmImports import *

class BasicTemplateAlgorithm(QCAlgorithm):
    def Initialize(self):
        self.SetStartDate(2023, 1, 1)
        self.AddEquity("SPY", Resolution.Minute)
"""
        fmt, _, _, stype = StrategyFormatDetector.detect(content, "main.py")
        assert fmt == StrategyFormat.QUANTCONNECT_LEAN
        assert stype == StrategyScriptType.STRATEGY

    def test_detect_python_backtrader(self) -> None:
        content = """
import backtrader as bt

class SmaStrategy(bt.Strategy):
    params = (('period', 15),)
    def __init__(self):
        self.sma = bt.indicators.SMA(period=self.p.period)
    def next(self):
        if self.data.close[0] > self.sma[0]:
            self.buy()
"""
        fmt, _, _, stype = StrategyFormatDetector.detect(content, "bt_strategy.py")
        assert fmt == StrategyFormat.PYTHON_BACKTRADER
        assert stype == StrategyScriptType.STRATEGY

    def test_detect_unknown(self) -> None:
        fmt, _, _, stype = StrategyFormatDetector.detect(
            "random unstructured gibberish", "notes.txt"
        )
        assert fmt == StrategyFormat.UNKNOWN
        assert stype == StrategyScriptType.UNKNOWN


# ==============================================================================
# 2. YAML Strategy Loader Tests
# ==============================================================================


class TestYAMLStrategyLoader:
    """Tests declarative YAML loading and AST validation."""

    def test_load_valid_yaml(self, tmp_path: Path) -> None:
        yaml_content = """
schema_version: "1.0"
name: "YAML Golden Cross"
underlying: "NIFTY"
timeframe: "5m"
target_regime: "Trending"
entry_conditions:
  operator: "AND"
  conditions:
    - category: "INDICATOR"
      indicator: "SMA"
      indicator_params:
        period: 50
      operator: "CROSSES_ABOVE"
      compare_indicator: "SMA"
      compare_params:
        period: 200
exit_conditions:
  operator: "OR"
  conditions:
    - category: "INDICATOR"
      indicator: "SMA"
      indicator_params:
        period: 50
      operator: "CROSSES_BELOW"
      compare_indicator: "SMA"
      compare_params:
        period: 200
"""
        yaml_file = tmp_path / "golden_cross.yaml"
        yaml_file.write_text(yaml_content, encoding="utf-8")

        dsl = YAMLStrategyLoader.load_from_file(yaml_file)
        assert dsl.name == "YAML Golden Cross"
        assert dsl.schema_version == "1.0"
        assert dsl.underlying == "NIFTY"
        assert dsl.timeframe == "5m"
        assert len(dsl.entry_conditions.conditions) == 1

    def test_reject_unsupported_schema_version(self) -> None:
        yaml_content = """
schema_version: "2.0"
name: "Future Version"
underlying: "NIFTY"
timeframe: "5m"
entry_conditions:
  operator: "AND"
  conditions: []
"""
        with pytest.raises(ValueError, match="Unsupported schema_version '2.0'"):
            YAMLStrategyLoader.load_from_str(yaml_content)

    def test_reject_malformed_yaml(self) -> None:
        with pytest.raises(ValueError, match="Failed to parse YAML content"):
            YAMLStrategyLoader.load_from_str(":::invalid: yaml: [")


# ==============================================================================
# 3. Pine Script Translator Tests
# ==============================================================================


class TestPineScriptTranslator:
    """Tests static translation of Pine Script strategies into StrategyDSL."""

    def test_translate_ma_crossover_strategy(self) -> None:
        script = """
//@version=5
strategy("Dual EMA System", overlay=true)

ema_fast = ta.ema(close, 9)
ema_slow = ta.ema(close, 21)

if ta.crossover(ema_fast, ema_slow)
    strategy.entry("Long", strategy.long)

if ta.crossunder(ema_fast, ema_slow)
    strategy.close("Long")
"""
        translator = PineScriptTranslator()
        dsl = translator.translate(script, default_underlying="BANKNIFTY", default_timeframe="15m")

        assert dsl.name == "Dual EMA System"
        assert dsl.underlying == "BANKNIFTY"
        assert dsl.timeframe == "15m"
        assert dsl.schema_version == "1.0"
        assert len(dsl.entry_conditions.conditions) >= 1
        assert dsl.exit_conditions is not None
        assert len(dsl.exit_conditions.conditions) >= 1

        first_entry = dsl.entry_conditions.conditions[0]
        assert isinstance(first_entry, ConditionNode)
        assert first_entry.operator == ASTOperator.CROSSES_ABOVE
        assert first_entry.indicator == "EMA"
        assert first_entry.indicator_params == {"period": 9}
        assert first_entry.compare_indicator == "EMA"
        assert first_entry.compare_params == {"period": 21}

    def test_translate_rsi_threshold_strategy(self) -> None:
        script = """
//@version=5
strategy("RSI Reversal", overlay=false)

rsi_val = ta.rsi(close, 14)

if rsi_val < 30
    strategy.entry("Buy", strategy.long)

if rsi_val > 70
    strategy.close("Buy")
"""
        translator = PineScriptTranslator()
        dsl = translator.translate(script)

        assert dsl.name == "RSI Reversal"
        assert len(dsl.entry_conditions.conditions) >= 1
        first_entry = dsl.entry_conditions.conditions[0]
        assert isinstance(first_entry, ConditionNode)
        assert first_entry.operator == ASTOperator.LESS_THAN
        assert first_entry.indicator == "RSI"
        assert first_entry.threshold == 30.0

    def test_reject_lookahead_bias(self) -> None:
        script = """
//@version=5
strategy("Repainting MTF", overlay=true)
htf_close = request.security(syminfo.tickerid, "1D", close, lookahead=barmerge.lookahead_on)
if ta.crossover(close, htf_close)
    strategy.entry("Long", strategy.long)
"""
        translator = PineScriptTranslator()
        with pytest.raises(ValueError, match="Repainting/Look-Ahead Bias detected"):
            translator.translate(script)

    def test_reject_indicator_without_strategy(self) -> None:
        script = """
//@version=5
indicator("Pure Indicator", overlay=true)
plot(ta.sma(close, 20))
"""
        translator = PineScriptTranslator()
        with pytest.raises(ValueError, match="does not define an executable strategy"):
            translator.translate(script)

    def test_reject_procedural_loops(self) -> None:
        script = """
//@version=5
strategy("Loop Strategy", overlay=true)
for i = 0 to 10
    strategy.entry("Long", strategy.long)
"""
        translator = PineScriptTranslator()
        with pytest.raises(ValueError, match="Procedural loops"):
            translator.translate(script)


# ==============================================================================
# 4. Strategy Inspector Tests
# ==============================================================================


class TestStrategyInspector:
    """Tests static inspection reports across different strategy types."""

    def test_inspect_json_linear_strategy(self, tmp_path: Path) -> None:
        dsl = StrategyDSL(
            schema_version="1.0",
            name="Test JSON Linear",
            underlying="RELIANCE",
            timeframe="5m",
            entry_conditions=ConditionGroup(
                operator=ASTOperator.AND,
                conditions=[
                    ConditionNode(
                        category=ConditionCategory.INDICATOR,
                        indicator="SMA",
                        indicator_params={"period": 20},
                        operator=ASTOperator.CROSSES_ABOVE,
                        compare_to_field="close",
                    )
                ],
            ),
            legs=[],
        )
        json_file = tmp_path / "linear.json"
        json_file.write_text(dsl.model_dump_json(indent=2), encoding="utf-8")

        report = StrategyInspector.inspect_file(json_file)
        assert report.detected_format == StrategyFormat.JSON_DSL
        assert report.strategy_name == "Test JSON Linear"
        assert report.underlying_detected == "RELIANCE"
        assert report.validation_ready is True
        assert report.simulation_ready is True
        assert report.forward_test_ready is True
        assert report.has_options_legs is False

    def test_inspect_json_options_strategy_air_gap(self, tmp_path: Path) -> None:
        dsl = StrategyDSL(
            schema_version="1.0",
            name="Test Iron Condor",
            underlying="NIFTY",
            timeframe="15m",
            entry_conditions=ConditionGroup(
                operator=ASTOperator.AND,
                conditions=[
                    ConditionNode(
                        category=ConditionCategory.INDICATOR,
                        field="close",
                        operator=ASTOperator.GREATER_THAN,
                        threshold=100.0,
                    )
                ],
            ),
            legs=[
                StrategyLegDefinition(
                    contract_type="CE",
                    side=OrderSide.SELL,
                    strike_offset=1,
                    lots=1,
                )
            ],
        )
        json_file = tmp_path / "iron_condor.json"
        json_file.write_text(dsl.model_dump_json(indent=2), encoding="utf-8")

        report = StrategyInspector.inspect_file(json_file)
        assert report.has_options_legs is True
        assert report.validation_ready is True
        assert report.simulation_ready is False
        assert report.forward_test_ready is False
        assert any("air-gapped" in w.lower() for w in report.warnings)

    def test_inspect_pine_script_lookahead_flagged(self) -> None:
        content = """
//@version=5
strategy("Lookahead Bug", overlay=true)
x = request.security(syminfo.tickerid, "60", close, lookahead=barmerge.lookahead_on)
if close > x
    strategy.entry("Buy", strategy.long)
"""
        report = StrategyInspector.inspect_content(content)
        assert report.detected_format == StrategyFormat.PINE_SCRIPT
        assert report.has_lookahead_risk is True
        assert report.translation_status == TranslationStatus.REJECTED_LOOKAHEAD
        assert report.validation_ready is False

    def test_inspect_python_backtrader_safe_inspection(self) -> None:
        content = """
import backtrader as bt

class GoldenCross(bt.Strategy):
    def __init__(self):
        self.sma = bt.indicators.SMA(period=50)

    def next(self):
        if self.data.close[0] > self.sma[0]:
            self.buy()
"""
        report = StrategyInspector.inspect_content(content)
        assert report.detected_format == StrategyFormat.PYTHON_BACKTRADER
        assert report.translation_status == TranslationStatus.INSPECT_ONLY
        assert report.validation_ready is False
        assert report.simulation_ready is False
        assert report.strategy_name == "GoldenCross"
        assert any("prohibited" in r.lower() for r in report.rejection_reasons)


# ==============================================================================
# 5. Unified load_strategy_file Tests
# ==============================================================================


class TestUnifiedStrategyLoader:
    """Tests load_strategy_file across supported file formats."""

    def test_load_json_file(self, tmp_path: Path) -> None:
        dsl = StrategyDSL(
            schema_version="1.0",
            name="JSON Load Test",
            underlying="INFY",
            timeframe="15m",
            entry_conditions=ConditionGroup(
                operator=ASTOperator.AND,
                conditions=[
                    ConditionNode(
                        category=ConditionCategory.INDICATOR,
                        field="close",
                        operator=ASTOperator.GREATER_THAN,
                        threshold=100.0,
                    )
                ],
            ),
            legs=[],
        )
        p = tmp_path / "test.json"
        p.write_text(dsl.model_dump_json(), encoding="utf-8")

        loaded = load_strategy_file(p)
        assert loaded.name == "JSON Load Test"
        assert loaded.underlying == "INFY"

    def test_load_yaml_file(self, tmp_path: Path) -> None:
        yaml_content = """
schema_version: "1.0"
name: "YAML Load Test"
underlying: "TCS"
timeframe: "1h"
entry_conditions:
  operator: "AND"
  conditions:
    - category: "indicator"
      field: "close"
      operator: "GREATER_THAN"
      threshold: 100.0
"""
        p = tmp_path / "test.yaml"
        p.write_text(yaml_content, encoding="utf-8")

        loaded = load_strategy_file(p)
        assert loaded.name == "YAML Load Test"
        assert loaded.underlying == "TCS"

    def test_load_pine_file(self, tmp_path: Path) -> None:
        pine_content = """
//@version=5
strategy("Pine Load Test", overlay=true)
fast = ta.sma(close, 10)
slow = ta.sma(close, 30)
if ta.crossover(fast, slow)
    strategy.entry("Long", strategy.long)
"""
        p = tmp_path / "test.pine"
        p.write_text(pine_content, encoding="utf-8")

        loaded = load_strategy_file(p, default_underlying="NIFTY")
        assert loaded.name == "Pine Load Test"
        assert loaded.underlying == "NIFTY"

    def test_load_unsupported_format_fails_closed(self, tmp_path: Path) -> None:
        py_content = "import backtrader as bt\nclass MyStrat(bt.Strategy): pass"
        p = tmp_path / "test.py"
        p.write_text(py_content, encoding="utf-8")

        with pytest.raises(ValueError, match="classified as PYTHON_BACKTRADER"):
            load_strategy_file(p)


# ==============================================================================
# 6. CLI Integration Tests
# ==============================================================================


class TestCLIStrategyCommands:
    """Tests CLI integration of inspect-strategy, validate, and backtest with multi-format files."""

    def test_cli_inspect_strategy_command(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        yaml_content = """
schema_version: "1.0"
name: "CLI Inspect Target"
underlying: "NIFTY"
timeframe: "5m"
entry_conditions:
  operator: "AND"
  conditions:
    - category: "indicator"
      field: "close"
      operator: "GREATER_THAN"
      threshold: 100.0
"""
        p = tmp_path / "cli_test.yaml"
        p.write_text(yaml_content, encoding="utf-8")

        args = argparse.Namespace(file=str(p))
        rc = cmd_inspect_strategy(args)
        assert rc == 0

        captured = capsys.readouterr()
        assert "Strategy Compatibility Inspector" in captured.out
        assert "Detected Format:    YAML_DSL" in captured.out
        assert "Validation Ready:   YES" in captured.out

    def test_cli_validate_yaml_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        yaml_content = """
schema_version: "1.0"
name: "CLI Validate Target"
underlying: "NIFTY"
timeframe: "5m"
entry_conditions:
  operator: "AND"
  conditions:
    - category: "INDICATOR"
      indicator: "SMA"
      indicator_params:
        period: 20
      operator: "CROSSES_ABOVE"
      compare_to_field: "close"
"""
        p = tmp_path / "cli_val.yaml"
        p.write_text(yaml_content, encoding="utf-8")

        args = argparse.Namespace(strategy=None, file=str(p), policy="research")
        rc = cmd_validate(args)
        assert rc in (0, 1)
        captured = capsys.readouterr()
        assert "Validating Strategy: 'CLI Validate Target'" in captured.out

    def test_cli_backtest_pine_file(self, tmp_path: Path) -> None:
        pine_content = """
//@version=5
strategy("CLI Pine Backtest", overlay=true)
fast = ta.sma(close, 5)
slow = ta.sma(close, 15)
if ta.crossover(fast, slow)
    strategy.entry("Long", strategy.long)
"""
        p = tmp_path / "cli_bt.pine"
        p.write_text(pine_content, encoding="utf-8")

        args = argparse.Namespace(
            strategy=None,
            file=str(p),
            bars=50,
            csv=None,
            capital=1_000_000.0,
            slippage_bps=2.5,
        )
        rc = cmd_backtest(args)
        assert rc == 0
