"""Unit tests verifying pure payoff curve calculations, breakevens, and multi-DTE MTM curves."""

from datetime import UTC, datetime

import pytest

from aditrader.core.models.enums import OrderSide
from aditrader.options.models import OptionLeg, OptionStrategy
from aditrader.options.payoff import (
    PAYOFF_INTERPOLATION_TOLERANCE,
    calculate_strategy_payoff,
)


def test_long_call_payoff_bounds_and_breakeven() -> None:
    """Verify Long Call has bounded max loss (premium) and unbounded max profit."""
    exp = datetime(2024, 12, 26, 15, 30, tzinfo=UTC)
    leg = OptionLeg(
        underlying="NIFTY",
        expiry=exp,
        strike=24000.0,
        option_type="CE",
        side=OrderSide.BUY,
        qty=50,
        entry_price=100.0,
        lot_size=25,
    )
    strat = OptionStrategy(id="LC-01", name="Long Call", legs=[leg])

    price_range = [float(x) for x in range(23500, 24600, 50)]
    points, summary = calculate_strategy_payoff(strat, price_range)

    # Net debit = 50 * 100 = 5000 INR
    assert summary.net_debit_credit == -5000.0
    # Max loss = 5000 INR
    assert summary.max_loss == 5000.0
    # Max profit = None (unbounded)
    assert summary.max_profit is None

    # Breakeven = strike + premium = 24000 + 100 = 24100
    assert len(summary.breakevens) == 1
    assert summary.breakevens[0] == pytest.approx(24100.0, abs=PAYOFF_INTERPOLATION_TOLERANCE)


def test_long_straddle_payoff_bounds() -> None:
    """Verify Long Straddle (Long Call + Long Put) creates symmetrical V-shape payoff."""
    exp = datetime(2024, 12, 26, 15, 30, tzinfo=UTC)
    call_leg = OptionLeg(
        underlying="NIFTY",
        expiry=exp,
        strike=24000.0,
        option_type="CE",
        side=OrderSide.BUY,
        qty=25,
        entry_price=150.0,
        lot_size=25,
    )
    put_leg = OptionLeg(
        underlying="NIFTY",
        expiry=exp,
        strike=24000.0,
        option_type="PE",
        side=OrderSide.BUY,
        qty=25,
        entry_price=150.0,
        lot_size=25,
    )
    strat = OptionStrategy(id="STRADDLE-01", name="Long Straddle", legs=[call_leg, put_leg])

    price_range = [float(x) for x in range(23000, 25100, 25)]
    points, summary = calculate_strategy_payoff(strat, price_range)

    # Total premium = 300 * 25 = 7500 INR
    assert summary.net_debit_credit == -7500.0
    assert summary.max_loss == 7500.0
    # Two breakevens: 24000 - 300 = 23700 and 24000 + 300 = 24300
    assert len(summary.breakevens) == 2
    assert summary.breakevens[0] == pytest.approx(23700.0, abs=1.0)
    assert summary.breakevens[1] == pytest.approx(24300.0, abs=1.0)


def test_iron_condor_bounded_payoff() -> None:
    """Verify Iron Condor has bounded max profit, bounded max loss, and two breakeven points."""
    exp = datetime(2024, 12, 26, 15, 30, tzinfo=UTC)

    # Put Wing: Buy 23600 PE, Sell 23800 PE (200 width)
    put_long = OptionLeg(
        underlying="NIFTY",
        expiry=exp,
        strike=23600.0,
        option_type="PE",
        side=OrderSide.BUY,
        qty=50,
        entry_price=30.0,
        lot_size=25,
    )
    put_short = OptionLeg(
        underlying="NIFTY",
        expiry=exp,
        strike=23800.0,
        option_type="PE",
        side=OrderSide.SELL,
        qty=50,
        entry_price=70.0,
        lot_size=25,
    )

    # Call Wing: Sell 24200 CE, Buy 24400 CE (200 width)
    call_short = OptionLeg(
        underlying="NIFTY",
        expiry=exp,
        strike=24200.0,
        option_type="CE",
        side=OrderSide.SELL,
        qty=50,
        entry_price=80.0,
        lot_size=25,
    )
    call_long = OptionLeg(
        underlying="NIFTY",
        expiry=exp,
        strike=24400.0,
        option_type="CE",
        side=OrderSide.BUY,
        qty=50,
        entry_price=35.0,
        lot_size=25,
    )

    strat = OptionStrategy(
        id="IC-01",
        name="Iron Condor",
        legs=[put_long, put_short, call_short, call_long],
    )

    # Net credit per share = (70 - 30) + (80 - 35) = 40 + 45 = 85 INR
    # Total net credit = 85 * 50 = 4250 INR
    price_range = [float(x) for x in range(23400, 24600, 20)]
    points, summary = calculate_strategy_payoff(strat, price_range)

    assert summary.net_debit_credit == 4250.0
    assert summary.max_profit == 4250.0

    # Max loss per share = 200 (wing width) - 85 (credit) = 115 INR
    # Total max loss = 115 * 50 = 5750 INR
    assert summary.max_loss == 5750.0
    assert summary.risk_reward_ratio == pytest.approx(4250.0 / 5750.0, abs=0.01)

    # Breakevens:
    # Lower BE = 23800 - 85 = 23715
    # Upper BE = 24200 + 85 = 24285
    assert len(summary.breakevens) == 2
    assert summary.breakevens[0] == pytest.approx(23715.0, abs=1.0)
    assert summary.breakevens[1] == pytest.approx(24285.0, abs=1.0)


def test_multi_dte_mark_to_market_convergence() -> None:
    """Verify MTM curves smoothly approach the at-expiry payoff curve as DTE decreases."""
    exp = datetime(2024, 12, 26, 15, 30, tzinfo=UTC)
    leg = OptionLeg(
        underlying="NIFTY",
        expiry=exp,
        strike=24000.0,
        option_type="CE",
        side=OrderSide.BUY,
        qty=50,
        entry_price=100.0,
        lot_size=25,
    )
    strat = OptionStrategy(id="LC-MTM", name="Long Call", legs=[leg])

    price_range = [23800.0, 24000.0, 24200.0]
    points, _ = calculate_strategy_payoff(
        strat, price_range, dte_slices=[14, 7, 1], volatility=0.15
    )

    # At Spot=24000 (ATM at strike):
    # At expiry: intrinsic = 0 -> P&L = -5000 INR
    atm_pt = next(p for p in points if p.underlying_price == 24000.0)
    assert atm_pt.pnl_at_expiry == -5000.0

    # Before expiry (DTE=14, 7, 1): option has extrinsic value, so MTM P&L > at-expiry P&L
    assert atm_pt.pnl_mtm[14] > atm_pt.pnl_mtm[7] > atm_pt.pnl_mtm[1] > atm_pt.pnl_at_expiry
