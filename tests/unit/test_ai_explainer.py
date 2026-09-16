"""Unit tests for StrategyExplainer educational breakdown."""

from aditrader.ai.models import AISourceType, DossierSectionSourceType
from aditrader.ai.teacher.explainer import StrategyExplainer
from aditrader.strategy.library.templates import (
    create_nifty_bull_call_spread_dsl,
    create_nifty_ce_premium_ladder_dsl,
    create_nifty_iron_condor_dsl,
    create_test_ma_crossover_dsl,
)


def test_explainer_linear_strategy() -> None:
    """Explainer correctly identifies and formats linear equity/futures strategy."""
    dsl = create_test_ma_crossover_dsl()
    explainer = StrategyExplainer()
    section = explainer.explain(dsl)

    assert section.title == "Strategy Mechanism & Educational Breakdown"
    assert section.source_type == DossierSectionSourceType.AI_ADVISORY
    assert section.provenance is not None
    assert section.provenance.source_type == AISourceType.EDUCATIONAL_EXPLANATION
    assert section.provenance.is_deterministic is True
    assert len(section.provenance.input_hash) == 64

    text = section.content
    assert "Directional Linear (Spot / Futures)" in text
    assert dsl.underlying in text
    assert "close" in text
    assert "is greater than" in text
    assert "What this strategy does NOT do" in text


def test_explainer_options_iron_condor() -> None:
    """Explainer correctly parses 4-leg Iron Condor with defined risk."""
    dsl = create_nifty_iron_condor_dsl()
    explainer = StrategyExplainer()
    section = explainer.explain(dsl)

    assert section.provenance is not None
    text = section.content
    assert "Multi-Leg Derivative / Options" in text
    assert "4 option leg(s)" in text
    assert "DEFINED RISK / HEDGED SPREAD" in text
    assert "Hedge Ratio" in text


def test_explainer_nifty_ce_premium_ladder() -> None:
    """Explainer accurately explains NIFTY CE dynamic selector and trailing stop ratchets."""
    dsl = create_nifty_ce_premium_ladder_dsl()
    explainer = StrategyExplainer()
    section = explainer.explain(dsl)

    text = section.content
    assert "Trailing Stop" in text
    assert "ratcheting" in text
    assert "Dynamic selection" in text
    assert "Hedge Ratio" in text
    assert "Configured Dynamic Premium Bands" in text


def test_explainer_bull_call_spread() -> None:
    """Explainer parses 2-leg Bull Call Spread with vertical strike offsets."""
    dsl = create_nifty_bull_call_spread_dsl()
    explainer = StrategyExplainer()
    section = explainer.explain(dsl)

    text = section.content
    assert "At-The-Money (ATM)" in text
    assert "+1 strike(s) OTM/ITM" in text
    assert "DEFINED RISK / HEDGED SPREAD" in text
