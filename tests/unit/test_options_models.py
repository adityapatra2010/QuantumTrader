"""Unit tests verifying OptionLeg, OptionStrategy, Greeks, and Chain domain models."""

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from aditrader.core.models.enums import OrderSide
from aditrader.options.models import (
    ChainRow,
    ChainStrikeData,
    Greeks,
    OptionLeg,
    OptionStrategy,
    PayoffPoint,
    PayoffSummary,
)


def test_option_leg_immutability_and_lot_multiple_validation() -> None:
    """Verify OptionLeg rejects invalid lot sizes and enforces immutability."""
    exp = datetime(2024, 12, 26, 15, 30, tzinfo=UTC)

    # Valid: qty=50 is multiple of lot_size=25 (NIFTY lot size)
    leg = OptionLeg(
        underlying="NIFTY",
        expiry=exp,
        strike=24000.0,
        option_type="CE",
        side=OrderSide.BUY,
        qty=50,
        entry_price=120.0,
        lot_size=25,
    )
    assert leg.qty == 50
    assert leg.lot_size == 25

    # Invalid: qty=30 is NOT a multiple of lot_size=25 -> must raise ValidationError
    with pytest.raises(ValidationError, match="must be an integer multiple of exchange lot size"):
        OptionLeg(
            underlying="NIFTY",
            expiry=exp,
            strike=24000.0,
            option_type="CE",
            side=OrderSide.BUY,
            qty=30,
            entry_price=120.0,
            lot_size=25,
        )

    # Immutability check
    with pytest.raises(ValidationError):
        setattr(leg, "entry_price", 150.0)


def test_greeks_immutability_and_types() -> None:
    """Verify Greeks model enforces types and immutability."""
    greeks = Greeks(
        delta=0.5234,
        gamma=0.0012,
        theta=-12.5,
        theta_trading=-18.1,
        vega=45.2,
        rho=8.1,
    )
    assert greeks.delta == 0.5234
    assert greeks.gamma == 0.0012

    with pytest.raises(ValidationError):
        setattr(greeks, "delta", 0.6)


def test_option_strategy_aggregation() -> None:
    """Verify OptionStrategy constructs a multi-leg container."""
    exp = datetime(2024, 12, 26, 15, 30, tzinfo=UTC)
    leg_call = OptionLeg(
        underlying="NIFTY",
        expiry=exp,
        strike=24000.0,
        option_type="CE",
        side=OrderSide.BUY,
        qty=25,
        entry_price=100.0,
        lot_size=25,
    )
    leg_put = OptionLeg(
        underlying="NIFTY",
        expiry=exp,
        strike=24000.0,
        option_type="PE",
        side=OrderSide.BUY,
        qty=25,
        entry_price=80.0,
        lot_size=25,
    )

    strategy = OptionStrategy(
        id="STRAT-STRADDLE-01",
        name="Long Straddle",
        legs=[leg_call, leg_put],
        dna_tags=["volatility_buying", "neutral"],
    )
    assert strategy.id == "STRAT-STRADDLE-01"
    assert len(strategy.legs) == 2


def test_chain_models() -> None:
    """Verify ChainRow and ChainStrikeData structures."""
    exp = datetime(2024, 12, 26, 15, 30, tzinfo=UTC)
    greeks = Greeks(delta=0.5, gamma=0.01, theta=-5.0, theta_trading=-7.0, vega=20.0, rho=4.0)

    call_data = ChainStrikeData(
        ltp=150.0, bid=149.5, ask=150.5, volume=1000, oi=50000, iv=0.18, greeks=greeks
    )
    row = ChainRow(strike=24000.0, expiry=exp, call=call_data, put=None)

    assert row.strike == 24000.0
    assert row.call is not None
    assert row.call.ltp == 150.0
    assert row.put is None


def test_payoff_models() -> None:
    """Verify PayoffPoint and PayoffSummary models."""
    point = PayoffPoint(underlying_price=24000.0, pnl_at_expiry=500.0, pnl_mtm={7: 250.0})
    assert point.underlying_price == 24000.0
    assert point.pnl_at_expiry == 500.0
    assert point.pnl_mtm[7] == 250.0

    summary = PayoffSummary(
        max_profit=2500.0,
        max_loss=5000.0,
        breakevens=[23900.0, 24100.0],
        net_debit_credit=-2500.0,
        risk_reward_ratio=0.5,
    )
    assert summary.max_profit == 2500.0
    assert summary.net_debit_credit == -2500.0
    assert summary.breakevens == [23900.0, 24100.0]
