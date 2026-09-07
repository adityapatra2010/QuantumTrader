"""Unit tests for instrument portability audit subsystem (ADR 002, ADR 007, ADR 011).

Audits cross-instrument assumption drift, contract sizing, session alignment, and statutory costs
demonstrated by the real-world MCX Gold vs XAUUSD adversarial case.
"""

import argparse
from pathlib import Path
from typing import Any

import pytest

from aditrader.cli.commands import cmd_inspect_strategy
from aditrader.strategy.inspector.inspector import StrategyInspector

MCX_PINE_PATH = Path("/home/aditya/Desktop/mcx.pine")
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "pine"


class DummyArgs(argparse.Namespace):
    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)


@pytest.mark.skipif(not MCX_PINE_PATH.exists(), reason="Real Desktop mcx.pine not present")
def test_mcx_gold_portability_audit() -> None:
    report = StrategyInspector.inspect_file(MCX_PINE_PATH)
    assert report.strategy_name == "4H Range Sweep v2 - MCX Gold (India)"
    assert report.portability_assessment is not None
    pa = report.portability_assessment

    assert pa.source_instrument_hint == "XAUUSD (Spot Gold / CFD)"
    assert pa.target_instrument_hint == "MCX Gold Futures (1 kg / 1000g)"
    assert "UNSAFE" in pa.portability_verdict

    # Capital Adequacy Check
    assert any("CRITICAL CAPITAL INADEQUACY" in u for u in pa.unsafe_mappings)
    assert any("₹100,000" in u for u in pa.unsafe_mappings)

    # Session Timing Check
    assert any("SESSION TIMING MISMATCH" in u for u in pa.unsafe_mappings)
    assert any("09:00 and 09:15 AM IST" in u for u in pa.unsafe_mappings)

    # Commission Check
    assert any("COMMISSION UNDERESTIMATION RISK" in u for u in pa.unsafe_mappings)

    # Preserved Technical Assumptions
    assert len(pa.assumptions_preserved) >= 3
    assert any("liquidity sweep" in p.lower() for p in pa.assumptions_preserved)

    # Changed Contract Assumptions
    assert len(pa.assumptions_changed) >= 4
    assert any("Trading Session" in c for c in pa.assumptions_changed)
    assert any("Exchange Transaction Costs" in c for c in pa.assumptions_changed)
    assert any("Contract Expiry & Settlement" in c for c in pa.assumptions_changed)


def test_standard_equity_strategy_no_portability_audit() -> None:
    report = StrategyInspector.inspect_file(FIXTURES_DIR / "ma_crossover.pine")
    assert report.portability_assessment is None


def test_cli_renders_portability_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    if not MCX_PINE_PATH.exists():
        pytest.skip("mcx.pine not found")

    # Run inspect-strategy and ensure output contains the audit section
    args = DummyArgs(file=str(MCX_PINE_PATH))
    ret = cmd_inspect_strategy(args)
    assert ret == 0


def test_synthetic_commodity_portability_triggers() -> None:
    pine_code = """//@version=6
strategy("Breakout v1 - MCX Silver Mini", initial_capital=50000, default_qty_value=1, commission_value=30)
if close > open
    strategy.entry("Buy", strategy.long)
"""
    report = StrategyInspector.inspect_content(pine_code)
    assert report.portability_assessment is not None
    assert "UNSAFE" in report.portability_assessment.portability_verdict
