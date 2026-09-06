"""Unit tests verifying closed-form Black-Scholes Greeks against analytical benchmark values."""

import pytest

from aditrader.options.greeks import GREEK_CALCULATION_TOLERANCE, calculate_greeks


def test_greeks_known_benchmark_values() -> None:
    """
    Verify Greeks against Hull analytical benchmark values.

    Parameters: Spot=100.0, Strike=100.0, T=1.0 yr, r=5% (0.05), sigma=20% (0.20), q=0.0
    Known theoretical values:
    - Call Delta: 0.63683
    - Put Delta: -0.36317
    - Gamma: 0.01876
    - Vega (1% vol): 0.3752
    - Call Theta (calendar day): -0.0176
    - Call Rho (1% rate): 0.5323
    - Put Rho (1% rate): -0.4189
    """
    spot = 100.0
    strike = 100.0
    t = 1.0
    r = 0.05
    vol = 0.20
    q = 0.0

    call_greeks = calculate_greeks(spot, strike, t, vol, r, q, "CE")
    put_greeks = calculate_greeks(spot, strike, t, vol, r, q, "PE")

    # Verify against benchmark figures within GREEK_CALCULATION_TOLERANCE
    assert call_greeks.delta == pytest.approx(0.63683, abs=GREEK_CALCULATION_TOLERANCE)
    assert put_greeks.delta == pytest.approx(-0.36317, abs=GREEK_CALCULATION_TOLERANCE)
    assert call_greeks.gamma == pytest.approx(0.01876, abs=GREEK_CALCULATION_TOLERANCE)
    assert put_greeks.gamma == pytest.approx(0.01876, abs=GREEK_CALCULATION_TOLERANCE)
    assert call_greeks.vega == pytest.approx(0.3752, abs=GREEK_CALCULATION_TOLERANCE)
    assert put_greeks.vega == pytest.approx(0.3752, abs=GREEK_CALCULATION_TOLERANCE)
    assert call_greeks.theta == pytest.approx(-0.0176, abs=GREEK_CALCULATION_TOLERANCE)
    assert call_greeks.rho == pytest.approx(0.5323, abs=GREEK_CALCULATION_TOLERANCE)
    assert put_greeks.rho == pytest.approx(-0.4189, abs=GREEK_CALCULATION_TOLERANCE)


def test_delta_relationship_and_bounds() -> None:
    """Verify Delta bounds (Call in [0, 1], Put in [-1, 0]) and parity: Delta_call - Delta_put = 1.0."""
    spot = 24000.0
    strike = 24000.0
    t = 10.0 / 365.0
    r = 0.07
    vol = 0.15

    call_g = calculate_greeks(spot, strike, t, vol, r, 0.0, "CE")
    put_g = calculate_greeks(spot, strike, t, vol, r, 0.0, "PE")

    assert 0.0 <= call_g.delta <= 1.0
    assert -1.0 <= put_g.delta <= 0.0
    assert (call_g.delta - put_g.delta) == pytest.approx(1.0, abs=GREEK_CALCULATION_TOLERANCE)


def test_greeks_expiration_boundary() -> None:
    """Verify Greeks at expiration (T=0) collapse to step functions without numerical error."""
    spot = 24050.0
    strike = 24000.0  # ITM for Call, OTM for Put

    itm_call = calculate_greeks(spot, strike, 0.0, 0.20, 0.07, 0.0, "CE")
    assert itm_call.delta == 1.0
    assert itm_call.gamma == 0.0
    assert itm_call.theta == 0.0
    assert itm_call.vega == 0.0

    otm_put = calculate_greeks(spot, strike, 0.0, 0.20, 0.07, 0.0, "PE")
    assert otm_put.delta == 0.0
    assert otm_put.gamma == 0.0
    assert otm_put.theta == 0.0
    assert otm_put.vega == 0.0


def test_deep_itm_and_otm_limits() -> None:
    """Verify asymptotic Greek limits for deep ITM and deep OTM contracts."""
    spot = 24000.0
    t = 30.0 / 365.0
    r = 0.07
    vol = 0.15

    # Deep OTM Call (Strike 30000)
    deep_otm_call = calculate_greeks(spot, 30000.0, t, vol, r, 0.0, "CE")
    assert deep_otm_call.delta < 0.001
    assert deep_otm_call.gamma < 0.001

    # Deep ITM Call (Strike 18000)
    deep_itm_call = calculate_greeks(spot, 18000.0, t, vol, r, 0.0, "CE")
    assert deep_itm_call.delta > 0.999
