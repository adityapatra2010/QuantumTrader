"""Adversarial regression test suite covering the synthetic Pine Script corpus.

Tests fidelity classification, format detection, translation status, fail-closed guards,
lookahead rejections, and CLI inspection outputs across 12 canonical Pine constructs.
"""

import argparse
from pathlib import Path
from typing import Any

import pytest

from aditrader.cli.commands import cmd_inspect_strategy
from aditrader.strategy.inspector.inspector import StrategyInspector
from aditrader.strategy.inspector.models import (
    FidelityLevel,
    StrategyFormat,
    TranslationStatus,
)
from aditrader.strategy.translators.pine import PineScriptTranslator

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "pine"


class DummyArgs(argparse.Namespace):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)


def test_fixtures_exist() -> None:
    """Verify all 12 corpus fixtures exist on disk."""
    expected_files = [
        "ma_crossover.pine",
        "rsi_threshold.pine",
        "crossover_volume.pine",
        "time_entry.pine",
        "session_filter.pine",
        "bracket_exit.pine",
        "multi_conditions.pine",
        "persistent_state.pine",
        "multi_timeframe.pine",
        "lookahead_bias.pine",
        "unsupported_loops.pine",
        "simulated_options.pine",
    ]
    for filename in expected_files:
        p = FIXTURES_DIR / filename
        assert p.is_file(), f"Fixture missing: {p}"


def test_translatable_ma_crossover() -> None:
    report = StrategyInspector.inspect_file(FIXTURES_DIR / "ma_crossover.pine")
    assert report.detected_format == StrategyFormat.PINE_SCRIPT
    assert report.translation_status == TranslationStatus.TRANSLATABLE
    assert report.fidelity_level == FidelityLevel.EQUIVALENT
    assert report.validation_ready is True
    assert report.simulation_ready is True
    assert report.has_lookahead_risk is False

    translator = PineScriptTranslator()
    dsl = translator.translate((FIXTURES_DIR / "ma_crossover.pine").read_text())
    assert dsl.name == "Moving Average Crossover"


def test_translatable_rsi_threshold() -> None:
    report = StrategyInspector.inspect_file(FIXTURES_DIR / "rsi_threshold.pine")
    assert report.detected_format == StrategyFormat.PINE_SCRIPT
    assert report.translation_status == TranslationStatus.TRANSLATABLE
    assert report.fidelity_level == FidelityLevel.EQUIVALENT
    assert report.validation_ready is True


def test_translatable_time_entry() -> None:
    report = StrategyInspector.inspect_file(FIXTURES_DIR / "time_entry.pine")
    assert report.detected_format == StrategyFormat.PINE_SCRIPT
    assert report.translation_status == TranslationStatus.TRANSLATABLE
    assert report.fidelity_level == FidelityLevel.EQUIVALENT
    assert any("Time Trigger (10:00)" in s for s in report.supported_constructs)


def test_session_filter_construct_detection() -> None:
    report = StrategyInspector.inspect_file(FIXTURES_DIR / "session_filter.pine")
    assert report.detected_format == StrategyFormat.PINE_SCRIPT
    assert any("Session Filter (0915-1530)" in s for s in report.supported_constructs)


def test_bracket_exit_construct_detection() -> None:
    report = StrategyInspector.inspect_file(FIXTURES_DIR / "bracket_exit.pine")
    assert report.detected_format == StrategyFormat.PINE_SCRIPT
    assert any("TP_SL" in e for e in report.exit_mechanisms)


def test_persistent_state_rejection() -> None:
    report = StrategyInspector.inspect_file(FIXTURES_DIR / "persistent_state.pine")
    assert report.detected_format == StrategyFormat.PINE_SCRIPT
    assert report.translation_status == TranslationStatus.INSPECT_ONLY
    assert report.validation_ready is False
    assert report.simulation_ready is False
    assert "bar_count" in report.persistent_state_vars
    assert any("ADR 007" in r for r in report.rejection_reasons)

    translator = PineScriptTranslator()
    with pytest.raises(ValueError, match="Mutable persistent state variables"):
        translator.translate((FIXTURES_DIR / "persistent_state.pine").read_text())


def test_multi_timeframe_request_rejection() -> None:
    report = StrategyInspector.inspect_file(FIXTURES_DIR / "multi_timeframe.pine")
    assert report.detected_format == StrategyFormat.PINE_SCRIPT
    assert report.translation_status == TranslationStatus.INSPECT_ONLY
    assert any("request.security" in u for u in report.unsupported_constructs)


def test_lookahead_bias_fatal_rejection() -> None:
    report = StrategyInspector.inspect_file(FIXTURES_DIR / "lookahead_bias.pine")
    assert report.detected_format == StrategyFormat.PINE_SCRIPT
    assert report.has_lookahead_risk is True
    assert report.translation_status == TranslationStatus.REJECTED_LOOKAHEAD
    assert report.fidelity_level == FidelityLevel.UNSUPPORTED
    assert report.validation_ready is False
    assert any("Repainting/Look-Ahead Bias detected" in r for r in report.rejection_reasons)

    args = DummyArgs(file=str(FIXTURES_DIR / "lookahead_bias.pine"))
    assert cmd_inspect_strategy(args) == 1


def test_unsupported_procedural_loops() -> None:
    report = StrategyInspector.inspect_file(FIXTURES_DIR / "unsupported_loops.pine")
    assert report.detected_format == StrategyFormat.PINE_SCRIPT
    assert report.translation_status == TranslationStatus.INSPECT_ONLY
    assert any("Procedural Loops" in u for u in report.unsupported_constructs)


def test_simulated_options_semantics() -> None:
    report = StrategyInspector.inspect_file(FIXTURES_DIR / "simulated_options.pine")
    assert report.detected_format == StrategyFormat.PINE_SCRIPT
    assert report.custom_pnl_detected is True
    assert report.naming_behavior_mismatch is not None
    assert report.has_options_legs is False
    assert report.translation_status == TranslationStatus.INSPECT_ONLY


def test_cli_inspect_all_fixtures_return_codes() -> None:
    """Verify CLI exit codes: 0 for all non-lookahead fixtures, 1 for lookahead."""
    for fixture in FIXTURES_DIR.glob("*.pine"):
        args = DummyArgs(file=str(fixture))
        ret = cmd_inspect_strategy(args)
        if fixture.name == "lookahead_bias.pine":
            assert ret == 1, f"Expected exit code 1 for lookahead {fixture.name}"
        else:
            assert ret == 0, f"Expected exit code 0 for {fixture.name}, got {ret}"
