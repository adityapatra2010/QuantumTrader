"""Unit tests verifying Black-Scholes pricing and IV solver against analytical benchmarks."""

import math

import pytest

from aditrader.options.iv import (
    IV_PRICE_TOLERANCE,
    IV_SOLVER_CONVERGENCE_TOLERANCE,
    black_scholes_price,
    black_scholes_vega,
    solve_implied_volatility,
)


def test_black_scholes_known_benchmark_values() -> None:
    """
    Verify Black-Scholes European prices against Hull benchmark values.

    Parameters: Spot=100.0, Strike=100.0, T=1.0 yr, r=5% (0.05), sigma=20% (0.20), q=0.0
    Known theoretical values:
    - Call: 10.450584
    - Put: 5.573526
    """
    spot = 100.0
    strike = 100.0
    t = 1.0
    r = 0.05
    vol = 0.20
    q = 0.0

    call_price = black_scholes_price(spot, strike, t, vol, r, q, option_type="CE")
    put_price = black_scholes_price(spot, strike, t, vol, r, q, option_type="PE")

    # Verify against benchmark figures within 1e-4 tolerance
    assert call_price == pytest.approx(10.450584, abs=1e-4)
    assert put_price == pytest.approx(5.573526, abs=1e-4)


def test_put_call_parity_exact() -> None:
    """Verify Put-Call Parity: C - P = S * e^(-qT) - K * e^(-rT)."""
    spot = 24150.0
    strike = 24000.0
    t = 30.0 / 365.0
    r = 0.07
    vol = 0.16
    q = 0.0

    c = black_scholes_price(spot, strike, t, vol, r, q, "CE")
    p = black_scholes_price(spot, strike, t, vol, r, q, "PE")

    lhs = c - p
    rhs = (spot * math.exp(-q * t)) - (strike * math.exp(-r * t))
    assert lhs == pytest.approx(rhs, abs=1e-4)


def test_implied_volatility_solver_convergence_across_strikes() -> None:
    """Verify IV solver recovers the exact known volatility across ITM, ATM, and OTM strikes."""
    spot = 24000.0
    t = 45.0 / 365.0
    r = 0.07
    true_vols = [0.12, 0.18, 0.25, 0.35]
    strikes = [23500.0, 24000.0, 24500.0]

    from typing import Literal

    opt_types: list[Literal["CE", "PE"]] = ["CE", "PE"]
    for true_vol in true_vols:
        for strike in strikes:
            for opt_type in opt_types:
                market_price = black_scholes_price(
                    spot=spot,
                    strike=strike,
                    time_to_expiry=t,
                    volatility=true_vol,
                    risk_free_rate=r,
                    dividend_yield=0.0,
                    option_type=opt_type,
                )

                recovered_iv = solve_implied_volatility(
                    market_price=market_price,
                    spot=spot,
                    strike=strike,
                    time_to_expiry=t,
                    risk_free_rate=r,
                    dividend_yield=0.0,
                    option_type=opt_type,
                )

                assert recovered_iv is not None
                # Check convergence within IV solver tolerance
                assert recovered_iv == pytest.approx(true_vol, abs=IV_SOLVER_CONVERGENCE_TOLERANCE)

                # Recomputed price matches market premium within price tolerance (1 paisa)
                recomputed_price = black_scholes_price(
                    spot,
                    strike,
                    t,
                    recovered_iv,
                    r,
                    0.0,
                    opt_type,
                )
                assert abs(recomputed_price - market_price) < IV_PRICE_TOLERANCE


def test_iv_arbitrage_bound_rejection() -> None:
    """Verify IV solver returns None for market prices below intrinsic value or outside arbitrage bounds."""
    spot = 24000.0
    strike = 23000.0  # Deep ITM Call, intrinsic = 1000 INR
    t = 15.0 / 365.0
    r = 0.07

    # Price below discounted intrinsic value -> impossible
    impossible_low_price = 500.0
    iv_low = solve_implied_volatility(impossible_low_price, spot, strike, t, r, 0.0, "CE")
    assert iv_low is None

    # Negative price -> impossible
    iv_neg = solve_implied_volatility(-10.0, spot, strike, t, r, 0.0, "CE")
    assert iv_neg is None

    # Price higher than underlying spot -> impossible
    impossible_high_price = 25000.0
    iv_high = solve_implied_volatility(impossible_high_price, spot, strike, t, r, 0.0, "CE")
    assert iv_high is None


def test_black_scholes_vega_properties() -> None:
    """Verify Black-Scholes Vega is strictly positive and peaks at ATM."""
    spot = 100.0
    t = 0.5
    r = 0.05
    vol = 0.20

    vega_atm = black_scholes_vega(spot, 100.0, t, vol, r)
    vega_otm = black_scholes_vega(spot, 120.0, t, vol, r)
    vega_itm = black_scholes_vega(spot, 80.0, t, vol, r)

    assert vega_atm > 0.0
    assert vega_atm > vega_otm
    assert vega_atm > vega_itm
