"""Unit tests verifying Strategy DNA classification vectors."""

from aditrader.strategy.library.dna import profile_strategy_dna
from aditrader.strategy.library.models import (
    Directionality,
    GammaRisk,
    MarginEfficiency,
    MarketRegime,
    ThetaExposure,
    TradingStyle,
    VegaExposure,
)
from aditrader.strategy.library.templates import (
    create_nifty_bull_call_spread_dsl,
    create_nifty_iron_condor_dsl,
    create_nifty_long_straddle_dsl,
)


def test_iron_condor_dna_profiling() -> None:
    """Verify Iron Condor DNA: Delta-Neutral, Positive Theta, Negative Vega, Low Tail Risk, High Margin Efficiency."""
    dsl = create_nifty_iron_condor_dsl()
    dna = profile_strategy_dna(dsl)

    assert dna.directionality == Directionality.DELTA_NEUTRAL
    assert dna.theta_exposure == ThetaExposure.HIGH_POSITIVE
    assert dna.vega_exposure == VegaExposure.NEGATIVE
    assert dna.gamma_risk == GammaRisk.LOW  # Hedged with wings
    assert dna.margin_efficiency == MarginEfficiency.HIGH  # Defined-risk spread
    assert dna.style == TradingStyle.INTRADAY
    assert dna.target_regime == MarketRegime.LOW_IV_SIDEWAYS


def test_long_straddle_dna_profiling() -> None:
    """Verify Long Straddle DNA: Delta-Neutral, Negative Theta, Positive Vega, Low Risk (premium capped), High IV Expansion."""
    dsl = create_nifty_long_straddle_dsl()
    dna = profile_strategy_dna(dsl)

    assert dna.directionality == Directionality.DELTA_NEUTRAL
    assert dna.theta_exposure == ThetaExposure.NEGATIVE
    assert dna.vega_exposure == VegaExposure.POSITIVE
    assert dna.gamma_risk == GammaRisk.LOW  # Long options only
    assert dna.margin_efficiency == MarginEfficiency.MODERATE
    assert dna.style == TradingStyle.INTRADAY
    assert dna.target_regime == MarketRegime.HIGH_IV_EXPANSION


def test_bull_call_spread_dna_profiling() -> None:
    """Verify Bull Call Spread DNA: Bullish, Defined-risk hedged, Trend Following."""
    dsl = create_nifty_bull_call_spread_dsl()
    dna = profile_strategy_dna(dsl)

    assert dna.directionality == Directionality.BULLISH
    assert dna.theta_exposure in (ThetaExposure.LOW_POSITIVE, ThetaExposure.NEUTRAL)
    assert dna.gamma_risk == GammaRisk.LOW
    assert dna.margin_efficiency == MarginEfficiency.HIGH
    assert dna.target_regime == MarketRegime.TREND_FOLLOWING
