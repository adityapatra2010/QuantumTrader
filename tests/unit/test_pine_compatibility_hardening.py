"""Unit tests for hardened Pine Script inspection, construct discovery, and diagnostic reporting.

Tests verify:
- Semantic integrity and construct classification on real-world adversarial scripts (myst.pine).
- Separation of concerns: inspect-strategy returns 0 (inspectable), validate returns 1 (fail closed).
- Naming vs behavior mismatch detection (simulated Iron Fly on spot vs real option legs).
- Custom P&L arithmetic audit (currentPL, priceDiff, targetProfit, maxLossLimit).
- Exact time condition mapping (hour == 10 and minute == 0 -> ConditionCategory.TIME).
- Execution behavior notes comparing Pine emulator with PaperBroker.
"""

import argparse
from pathlib import Path

import pytest

from aditrader.cli.commands import cmd_inspect_strategy, cmd_validate
from aditrader.strategy.builder.schema import ASTOperator, ConditionCategory, ConditionNode
from aditrader.strategy.inspector import (
    FidelityLevel,
    StrategyFormat,
    StrategyFormatDetector,
    StrategyInspector,
    StrategyScriptType,
    TranslationStatus,
)
from aditrader.strategy.translators.pine import PineScriptTranslator

MYST_PINE_PATH = Path("/home/aditya/Desktop/myst.pine")


@pytest.fixture
def myst_pine_content() -> str:
    """Read contents of adversarial myst.pine file."""
    assert MYST_PINE_PATH.is_file(), f"Expected {MYST_PINE_PATH} to exist"
    return MYST_PINE_PATH.read_text(encoding="utf-8")


class TestMystPineInspection:
    """Verification suite for inspecting ~/Desktop/myst.pine."""

    def test_detector_identifies_v6_strategy(self, myst_pine_content: str) -> None:
        fmt, lang, ver, script_type = StrategyFormatDetector.detect(
            myst_pine_content, file_path=MYST_PINE_PATH
        )
        assert fmt == StrategyFormat.PINE_SCRIPT
        assert "Pine Script" in lang
        assert ver == "v6"
        assert script_type == StrategyScriptType.STRATEGY

    def test_inspection_report_metadata_and_status(self) -> None:
        report = StrategyInspector.inspect_file(MYST_PINE_PATH)

        assert report.detected_format == StrategyFormat.PINE_SCRIPT
        assert report.strategy_name == "Iron Fly & Broken Wing Strategy"
        assert report.version_detected == "v6"
        assert report.translation_status == TranslationStatus.INSPECT_ONLY
        assert report.fidelity_level == FidelityLevel.APPROXIMATED
        assert report.validation_ready is False
        assert report.simulation_ready is False
        assert report.forward_test_ready is False
        assert report.has_options_legs is False  # Zero real option legs

    def test_semantic_mismatch_detected(self) -> None:
        report = StrategyInspector.inspect_file(MYST_PINE_PATH)

        assert report.naming_behavior_mismatch is not None
        assert "Iron Fly & Broken Wing" in report.naming_behavior_mismatch
        assert "synthetic arithmetic" in report.naming_behavior_mismatch

        assert report.position_semantics is not None
        assert "Single underlying long" in report.position_semantics

        assert report.option_leg_semantics is not None
        assert "0 real option legs" in report.option_leg_semantics

        # Warning emitted
        assert any("Semantic Mismatch" in w for w in report.warnings)

    def test_custom_pnl_simulation_audit(self) -> None:
        report = StrategyInspector.inspect_file(MYST_PINE_PATH)

        assert report.custom_pnl_detected is True
        assert report.custom_pnl_details is not None

        pnl = report.custom_pnl_details
        assert "priceDiff" in pnl["variables"]
        assert "currentPL" in pnl["variables"]
        assert "targetProfit" in pnl["variables"]
        assert "maxLossLimit" in pnl["variables"]
        assert pnl["target_profit_value"] == 19000.0
        assert pnl["max_loss_limit_value"] == 3000.0
        assert "distance" in pnl["pricing_connection"].lower()
        assert "paperbroker" in pnl["dsl_evaluation_limitation"].lower()

    def test_constructs_classification_matrix(self) -> None:
        report = StrategyInspector.inspect_file(MYST_PINE_PATH)
        constructs = report.detected_constructs
        assert len(constructs) >= 10

        # Directive
        assert any(
            c.category == "directive" and c.fidelity == FidelityLevel.EXACT
            for c in constructs
            if "@version=6" in c.name
        )

        # Strategy declaration
        assert any(
            c.category == "directive" and c.fidelity == FidelityLevel.EXACT
            for c in constructs
            if "Strategy Declaration" in c.name
        )

        # Visual overlay
        assert any(
            c.category == "visual" and c.fidelity == FidelityLevel.VISUAL_ONLY
            for c in constructs
            if "Overlay" in c.name
        )

        # Inputs
        assert any(
            c.category == "input" and c.fidelity == FidelityLevel.APPROXIMATED
            for c in constructs
            if "User Inputs" in c.name
        )

        # Persistent state
        assert any(
            c.category == "state" and c.fidelity == FidelityLevel.UNSUPPORTED
            for c in constructs
            if "Persistent State Variables" in c.name
        )

        # Timing
        assert any(
            c.category == "timing" and c.fidelity == FidelityLevel.EXACT
            for c in constructs
            if "Time Filter" in c.name
        )

        # Math library functions
        assert any(
            c.category == "calculation" and c.fidelity == FidelityLevel.UNSUPPORTED
            for c in constructs
            if "Math Library Functions" in c.name
        )

        # Order entries & exits
        assert any(
            c.category == "entry" and c.fidelity == FidelityLevel.EQUIVALENT
            for c in constructs
            if "Order Entry" in c.name
        )
        assert any(
            c.category == "exit" and c.fidelity == FidelityLevel.EQUIVALENT
            for c in constructs
            if "Order Exit" in c.name
        )

        # Visual charts / fills
        assert any(
            c.category == "visual" and c.fidelity == FidelityLevel.VISUAL_ONLY
            for c in constructs
            if "Chart Visualizations" in c.name
        )

    def test_order_behavior_notes_comparison(self) -> None:
        report = StrategyInspector.inspect_file(MYST_PINE_PATH)
        assert len(report.order_behavior_notes) == 6
        assert any("Execution Timing" in n for n in report.order_behavior_notes)
        assert any("P&L Accounting" in n for n in report.order_behavior_notes)
        assert any("Capital & Margin" in n for n in report.order_behavior_notes)
        assert any("Multi-Leg Realism" in n for n in report.order_behavior_notes)
        assert any("Fills & Slippage" in n for n in report.order_behavior_notes)
        assert any("Position Lifecycle" in n for n in report.order_behavior_notes)


class TestPineTranslatorHardening:
    """Verification suite for PineScriptTranslator error reporting and time mapping."""

    def test_fail_closed_structured_error_on_myst_pine(self, myst_pine_content: str) -> None:
        translator = PineScriptTranslator()
        with pytest.raises(ValueError) as exc_info:
            translator.translate(myst_pine_content, file_path=MYST_PINE_PATH)

        err_msg = str(exc_info.value)
        # Clear, structured failure explanation instead of generic message
        assert (
            "Cannot translate Pine Script strategy 'Iron Fly & Broken Wing Strategy' (v6)"
            in err_msg
        )
        assert "[BLOCKER]" in err_msg
        assert "Mutable persistent state variables" in err_msg
        assert "Synthetic custom P&L calculations" in err_msg
        assert "Semantic mismatch" in err_msg
        assert "aditrader inspect-strategy" in err_msg

    def test_translate_pure_time_condition_strategy(self) -> None:
        """StrategyDSL can natively evaluate exact time conditions."""
        pure_time_pine = """//@version=5
strategy("Time Only Entry", overlay=true)
if hour == 10 and minute == 0
    strategy.entry("MorningTrade", strategy.long)
if hour == 15 and minute == 15
    strategy.close("MorningTrade")
"""
        translator = PineScriptTranslator()
        dsl = translator.translate(pure_time_pine)

        assert dsl.name == "Time Only Entry"
        assert len(dsl.entry_conditions.conditions) > 0

        # Find time condition node
        time_nodes = [
            c
            for c in dsl.entry_conditions.conditions
            if isinstance(c, ConditionNode) and c.category == ConditionCategory.TIME
        ]
        assert len(time_nodes) == 1
        tn = time_nodes[0]
        assert tn.field == "time_of_day"
        assert tn.operator == ASTOperator.EQUALS
        assert tn.threshold == "10:00"


class TestCLIInspectAndValidateCommands:
    """Verification of CLI exit codes and behavior separation."""

    def test_cli_inspect_strategy_returns_zero_on_myst_pine(self) -> None:
        args = argparse.Namespace(file=str(MYST_PINE_PATH))
        code = cmd_inspect_strategy(args)
        assert code == 0  # Inspection succeeds on valid Pine script

    def test_cli_validate_returns_one_on_myst_pine(self) -> None:
        args = argparse.Namespace(
            file=str(MYST_PINE_PATH),
            strategy=None,
            policy="institutional",
        )
        code = cmd_validate(args)
        assert code == 1  # Validation fails closed

    def test_cli_inspect_strategy_returns_one_on_lookahead_bias(self, tmp_path: Path) -> None:
        lookahead_script = tmp_path / "lookahead.pine"
        lookahead_script.write_text(
            """//@version=5
strategy("Lookahead Cheat")
data = request.security(syminfo.tickerid, "D", close, lookahead=barmerge.lookahead_on)
if data > 100
    strategy.entry("Cheater", strategy.long)
"""
        )
        args = argparse.Namespace(file=str(lookahead_script))
        code = cmd_inspect_strategy(args)
        assert code == 1  # Lookahead bias is fatal
