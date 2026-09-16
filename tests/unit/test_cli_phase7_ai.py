"""Unit tests for Phase 7 AI CLI subcommands.

Verifies:
- explain-strategy
- suggest-strategy
- review-strategy
- forecast
- research-dossier
"""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from pathlib import Path

from aditrader.cli import main


def test_cli_explain_strategy_success() -> None:
    """Verify explain-strategy outputs educational explanation with ADR 012 provenance."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main(["explain-strategy", "--strategy", "Nifty Bull Call Spread"])
    output = buf.getvalue()

    assert exit_code == 0
    assert "Educational Strategy Explanation: 'Nifty Bull Call Spread'" in output
    assert "Provenance Hash:" in output
    assert "ADR 012 ADVISORY NOTICE" in output
    assert "Defined Risk" in output or "DEFINED RISK" in output


def test_cli_explain_strategy_not_found() -> None:
    """Verify explain-strategy returns error on non-existent strategy."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main(["explain-strategy", "--strategy", "NonExistentStrategy"])
    output = buf.getvalue()

    assert exit_code == 1
    assert "not found" in output.lower()


def test_cli_suggest_strategy_advisory() -> None:
    """Verify suggest-strategy proposes strategy matching regime and bias."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main(["suggest-strategy", "--regime", "NORMAL_VOLATILITY"])
    output = buf.getvalue()

    assert exit_code == 0
    assert "Strategy Suggestion Engine" in output
    assert "Prior Bias Enforced: 60% Selling / 40% Buying" in output
    assert "Suggested Strategy:" in output
    assert "UNVALIDATED" in output


def test_cli_suggest_strategy_with_validation(tmp_path: Path) -> None:
    """Verify suggest-strategy with --validate evaluates institutional validation gates and saves output."""
    out_file = tmp_path / "suggested_strat.json"
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main(
            [
                "suggest-strategy",
                "--regime",
                "HIGH_VOLATILITY",
                "--validate",
                "--out",
                str(out_file),
            ]
        )
    output = buf.getvalue()

    assert exit_code == 0
    assert "INSTITUTIONAL APPROVED" in output
    assert out_file.is_file()
    assert '"name": "Nifty Long Straddle"' in out_file.read_text(encoding="utf-8")


def test_cli_review_strategy_success() -> None:
    """Verify review-strategy outputs adversarial critique with deterministic validation status."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main(["review-strategy", "--strategy", "Nifty Weekly Iron Condor"])
    output = buf.getvalue()

    assert exit_code == 0
    assert "Strategy Advisory Review: 'Nifty Weekly Iron Condor'" in output
    assert "Deterministic Validation: APPROVED" in output
    assert "Adversarial Structural Review" in output
    assert "Provenance Hash:" in output


def test_cli_forecast_success() -> None:
    """Verify forecast CLI generates point-in-time trajectory without lookahead."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main(["forecast", "--symbol", "NIFTY", "--bars", "40", "--horizon", "4"])
    output = buf.getvalue()

    assert exit_code == 0
    assert "Time-Series Market Forecast: NIFTY" in output
    assert "Current Close:" in output
    assert "Target Close:" in output
    assert "Step-by-Step Trajectory:" in output
    assert "+1" in output
    assert "+4" in output
    assert "Point-in-Time Assurance:" in output


def test_cli_forecast_insufficient_bars() -> None:
    """Verify forecast CLI rejects fewer than 10 bars."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main(["forecast", "--symbol", "NIFTY", "--bars", "5"])
    output = buf.getvalue()

    assert exit_code == 1
    assert "Insufficient bars" in output


def test_cli_forecast_invalid_horizon() -> None:
    """Verify forecast CLI rejects non-positive horizon."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main(["forecast", "--symbol", "NIFTY", "--bars", "20", "--horizon", "0"])
    output = buf.getvalue()

    assert exit_code == 1
    assert "Forecast horizon must be a positive integer" in output


def test_cli_research_dossier_success(tmp_path: Path) -> None:
    """Verify research-dossier compiles complete institutional dossier and writes to disk."""
    out_file = tmp_path / "nifty_dossier.md"
    buf = io.StringIO()
    with redirect_stdout(buf):
        exit_code = main(
            [
                "research-dossier",
                "--strategy",
                "Nifty Weekly Iron Condor",
                "--output",
                str(out_file),
            ]
        )
    output = buf.getvalue()

    assert exit_code == 0
    assert out_file.is_file()
    content = out_file.read_text(encoding="utf-8")
    assert "# Institutional Quantitative Research Dossier: Nifty Weekly Iron Condor" in content
    assert "[STRUCTURAL]" in content
    assert "[AI_ADVISORY]" in content
    assert "[DETERMINISTIC]" in content
    assert "[METADATA]" in content
    assert "Research Dossier written to:" in output
