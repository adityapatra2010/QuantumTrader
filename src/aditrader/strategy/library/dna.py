"""Strategy DNA classification and vector profiling engine.

Analyzes declarative StrategyDSL specifications and computes quantitative
risk/exposure vectors across Directionality, Greeks, Margin, and Style.
"""

from aditrader.core.models.enums import OrderSide
from aditrader.strategy.builder.schema import StrategyDSL
from aditrader.strategy.library.models import (
    Directionality,
    GammaRisk,
    MarginEfficiency,
    MarketRegime,
    StrategyDNA,
    ThetaExposure,
    TradingStyle,
    VegaExposure,
)


def _approximate_leg_delta(contract_type: str, strike_offset: int) -> float:
    """Approximate delta based on contract type and strike offset relative to ATM.

    ATM call has delta ~0.50, declining by ~0.15 per strike OTM.
    ATM put has delta ~-0.50, increasing towards 0 by ~0.15 per strike OTM.
    """
    if contract_type == "CE":
        # offset 0: 0.50; offset +1 (OTM): 0.35; offset -1 (ITM): 0.65
        approx = 0.50 - 0.15 * strike_offset
        return max(0.05, min(0.95, approx))
    else:
        # offset 0: -0.50; offset -1 (OTM): -0.35; offset +1 (ITM): -0.65
        approx = -0.50 - 0.15 * strike_offset
        return min(-0.05, max(-0.95, approx))


def profile_strategy_dna(dsl: StrategyDSL) -> StrategyDNA:
    """Compute multi-dimensional StrategyDNA profile from a declarative StrategyDSL.

    Args:
        dsl: Strategy AST specification.

    Returns:
        Immutable StrategyDNA instance.
    """
    legs = dsl.legs

    # Default profile for pure equity / indicator strategies
    if not legs:
        style = _infer_style(dsl.timeframe, dsl.name)
        return StrategyDNA(
            directionality=Directionality.BULLISH,
            theta_exposure=ThetaExposure.NEUTRAL,
            vega_exposure=VegaExposure.NEUTRAL,
            gamma_risk=GammaRisk.LOW,
            margin_efficiency=MarginEfficiency.HIGH,
            style=style,
            target_regime=MarketRegime.TREND_FOLLOWING,
        )

    # 1. Directionality Analysis using strike-weighted delta proxy
    net_delta_sum = 0.0
    for leg in legs:
        leg_delta = _approximate_leg_delta(leg.contract_type, leg.strike_offset)
        signed_delta = leg_delta if leg.side == OrderSide.BUY else -leg_delta
        net_delta_sum += signed_delta * leg.lots

    if net_delta_sum > 0.05:
        directionality = Directionality.BULLISH
    elif net_delta_sum < -0.05:
        directionality = Directionality.BEARISH
    else:
        directionality = Directionality.DELTA_NEUTRAL

    # 2. Vega & Theta Exposure
    total_long_lots = sum(leg.lots for leg in legs if leg.side == OrderSide.BUY)
    total_short_lots = sum(leg.lots for leg in legs if leg.side == OrderSide.SELL)

    # Iron Condor / Credit Spreads check: equal long and short legs, but short legs closer to ATM
    if total_long_lots == total_short_lots and total_short_lots > 0:
        # Check average strike distance from ATM (abs strike offset)
        avg_short_offset = sum(
            abs(leg.strike_offset) for leg in legs if leg.side == OrderSide.SELL
        ) / total_short_lots
        avg_long_offset = sum(
            abs(leg.strike_offset) for leg in legs if leg.side == OrderSide.BUY
        ) / total_long_lots

        if avg_short_offset < avg_long_offset:
            # Short legs are closer to ATM (Credit Spread / Iron Condor)
            vega_exposure = VegaExposure.NEGATIVE
            theta_exposure = ThetaExposure.HIGH_POSITIVE
        elif avg_short_offset > avg_long_offset:
            # Long legs closer to ATM (Debit Spread)
            vega_exposure = VegaExposure.POSITIVE
            theta_exposure = ThetaExposure.LOW_POSITIVE
        else:
            vega_exposure = VegaExposure.NEUTRAL
            theta_exposure = ThetaExposure.NEUTRAL
    elif total_long_lots > total_short_lots:
        vega_exposure = VegaExposure.POSITIVE
        theta_exposure = ThetaExposure.NEGATIVE
    elif total_short_lots > total_long_lots:
        vega_exposure = VegaExposure.NEGATIVE
        theta_exposure = ThetaExposure.HIGH_POSITIVE
    else:
        vega_exposure = VegaExposure.NEUTRAL
        theta_exposure = ThetaExposure.NEUTRAL

    # 3. Gamma Risk & Margin Efficiency
    # Check if all short positions are covered by long positions
    short_call_lots = sum(leg.lots for leg in legs if leg.contract_type == "CE" and leg.side == OrderSide.SELL)
    long_call_lots = sum(leg.lots for leg in legs if leg.contract_type == "CE" and leg.side == OrderSide.BUY)
    short_put_lots = sum(leg.lots for leg in legs if leg.contract_type == "PE" and leg.side == OrderSide.SELL)
    long_put_lots = sum(leg.lots for leg in legs if leg.contract_type == "PE" and leg.side == OrderSide.BUY)

    has_uncovered_short = (short_call_lots > long_call_lots) or (short_put_lots > long_put_lots)

    if has_uncovered_short:
        gamma_risk = GammaRisk.HIGH
        margin_efficiency = MarginEfficiency.LOW
    elif total_short_lots > 0:
        # Fully hedged short options (e.g. Iron Condor, Bull Call Spread)
        gamma_risk = GammaRisk.LOW
        margin_efficiency = MarginEfficiency.HIGH
    else:
        # Long options only (loss strictly capped to premium paid)
        gamma_risk = GammaRisk.LOW
        margin_efficiency = MarginEfficiency.MODERATE

    # 4. Trading Style
    style = _infer_style(dsl.timeframe, dsl.name)

    # 5. Target Regime
    if dsl.target_regime:
        tr_lower = dsl.target_regime.lower()
        if "low iv" in tr_lower or "sideways" in tr_lower:
            target_regime = MarketRegime.LOW_IV_SIDEWAYS
        elif "high iv" in tr_lower or "expansion" in tr_lower:
            target_regime = MarketRegime.HIGH_IV_EXPANSION
        elif "trend" in tr_lower:
            target_regime = MarketRegime.TREND_FOLLOWING
        else:
            target_regime = MarketRegime.RANGEBOUND
    else:
        if directionality == Directionality.DELTA_NEUTRAL and vega_exposure == VegaExposure.NEGATIVE:
            target_regime = MarketRegime.LOW_IV_SIDEWAYS
        elif directionality == Directionality.DELTA_NEUTRAL and vega_exposure == VegaExposure.POSITIVE:
            target_regime = MarketRegime.HIGH_IV_EXPANSION
        elif directionality in (Directionality.BULLISH, Directionality.BEARISH):
            target_regime = MarketRegime.TREND_FOLLOWING
        else:
            target_regime = MarketRegime.RANGEBOUND

    return StrategyDNA(
        directionality=directionality,
        theta_exposure=theta_exposure,
        vega_exposure=vega_exposure,
        gamma_risk=gamma_risk,
        margin_efficiency=margin_efficiency,
        style=style,
        target_regime=target_regime,
    )


def _infer_style(timeframe: str, name: str) -> TradingStyle:
    """Infer TradingStyle from timeframe string and strategy name."""
    name_lower = name.lower()
    if "expiry" in name_lower or "0dte" in name_lower:
        return TradingStyle.EXPIRY_DAY
    if "scalp" in name_lower or timeframe in ("1m", "2m"):
        return TradingStyle.SCALPING
    if timeframe in ("3m", "5m", "15m", "30m"):
        return TradingStyle.INTRADAY
    return TradingStyle.POSITIONAL
