"""Black-Scholes European option pricing and robust numerical Implied Volatility (IV) solver."""

import math
from typing import Final, Literal

# ------------------------------------------------------------------------------
# Explicit Numerical Tolerances & Boundary Parameters
# ------------------------------------------------------------------------------

IV_SOLVER_CONVERGENCE_TOLERANCE: Final[float] = 1e-5
"""Convergence threshold for successive volatility updates in the IV solver."""

IV_PRICE_TOLERANCE: Final[float] = 0.01
"""Maximum acceptable difference in INR between model price and market premium (1 paisa)."""

MAX_IV_ITERATIONS: Final[int] = 100
"""Maximum number of solver iterations before terminating."""

MIN_VOLATILITY: Final[float] = 0.001
"""Minimum annualized volatility boundary (0.1%)."""

MAX_VOLATILITY: Final[float] = 5.0
"""Maximum annualized volatility boundary (500%)."""

DEFAULT_RISK_FREE_RATE: Final[float] = 0.07
"""Default Indian risk-free rate (7.0% based on RBI 91-day T-Bills benchmark)."""


# ------------------------------------------------------------------------------
# Standard Normal Distribution Helpers
# ------------------------------------------------------------------------------


def standard_normal_cdf(x: float) -> float:
    """
    Cumulative distribution function for standard normal distribution N(0, 1).

    Computed analytically using math.erf for high numerical precision.
    """
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def standard_normal_pdf(x: float) -> float:
    """Probability density function for standard normal distribution N'(0, 1)."""
    return (1.0 / math.sqrt(2.0 * math.pi)) * math.exp(-0.5 * x * x)


# ------------------------------------------------------------------------------
# Black-Scholes European Option Pricing Engine
# ------------------------------------------------------------------------------


def black_scholes_price(
    spot: float,
    strike: float,
    time_to_expiry: float,
    volatility: float,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    dividend_yield: float = 0.0,
    option_type: Literal["CE", "PE"] = "CE",
) -> float:
    """
    Calculate theoretical European option price via the analytical Black-Scholes-Merton model.

    Indian Market Specifics:
    All NSE index options (NIFTY, BANKNIFTY) and stock options operate on European exercise
    conventions (SEBI mandate). Early exercise is not permissible.

    Parameters:
    - spot: Current price of the underlying asset
    - strike: Strike price of the option contract
    - time_to_expiry: Time to expiration in years (e.g. 30/365)
    - volatility: Annualized implied volatility as a decimal (e.g. 0.15 for 15%)
    - risk_free_rate: Continuous annualized risk-free rate
    - dividend_yield: Continuous annualized dividend yield
    - option_type: "CE" for Call, "PE" for Put
    """
    if spot <= 0.0 or strike <= 0.0:
        raise ValueError("Spot and Strike prices must be strictly positive")

    # At or past expiration
    if time_to_expiry <= 0.0:
        if option_type == "CE":
            return max(0.0, spot - strike)
        else:
            return max(0.0, strike - spot)

    # Extreme low volatility: price equals discounted intrinsic / forward value
    if volatility <= 1e-7:
        forward = spot * math.exp((risk_free_rate - dividend_yield) * time_to_expiry)
        discount = math.exp(-risk_free_rate * time_to_expiry)
        if option_type == "CE":
            return max(0.0, discount * (forward - strike))
        else:
            return max(0.0, discount * (strike - forward))

    sqrt_t = math.sqrt(time_to_expiry)
    d1 = (
        math.log(spot / strike)
        + (risk_free_rate - dividend_yield + 0.5 * volatility * volatility) * time_to_expiry
    ) / (volatility * sqrt_t)
    d2 = d1 - volatility * sqrt_t

    df_div = math.exp(-dividend_yield * time_to_expiry)
    df_rf = math.exp(-risk_free_rate * time_to_expiry)

    if option_type == "CE":
        price = (spot * df_div * standard_normal_cdf(d1)) - (
            strike * df_rf * standard_normal_cdf(d2)
        )
    else:
        price = (strike * df_rf * standard_normal_cdf(-d2)) - (
            spot * df_div * standard_normal_cdf(-d1)
        )

    return max(0.0, price)


def black_scholes_vega(
    spot: float,
    strike: float,
    time_to_expiry: float,
    volatility: float,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    dividend_yield: float = 0.0,
) -> float:
    """
    Compute raw Black-Scholes Vega (dPrice / dSigma).

    Vega is identical for European Calls and Puts.
    """
    if time_to_expiry <= 0.0 or spot <= 0.0 or strike <= 0.0 or volatility <= 0.0:
        return 0.0

    sqrt_t = math.sqrt(time_to_expiry)
    d1 = (
        math.log(spot / strike)
        + (risk_free_rate - dividend_yield + 0.5 * volatility * volatility) * time_to_expiry
    ) / (volatility * sqrt_t)

    df_div = math.exp(-dividend_yield * time_to_expiry)
    return spot * df_div * sqrt_t * standard_normal_pdf(d1)


# ------------------------------------------------------------------------------
# Robust Numerical Implied Volatility Solver
# ------------------------------------------------------------------------------


def solve_implied_volatility(
    market_price: float,
    spot: float,
    strike: float,
    time_to_expiry: float,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    dividend_yield: float = 0.0,
    option_type: Literal["CE", "PE"] = "CE",
    initial_guess: float = 0.20,
) -> float | None:
    """
    Compute Implied Volatility (IV) from observed market premium using a hybrid Newton-Raphson / Bisection solver.

    Returns:
    - Annualized volatility as float (e.g. 0.185 for 18.5% IV)
    - None if market price breaches no-arbitrage bounds or fails to converge
    """
    if market_price <= 0.0 or spot <= 0.0 or strike <= 0.0 or time_to_expiry <= 0.0:
        return None

    # Theoretical lower bound check (intrinsic value discounted)
    df_rf = math.exp(-risk_free_rate * time_to_expiry)
    df_div = math.exp(-dividend_yield * time_to_expiry)
    if option_type == "CE":
        intrinsic_lower = max(0.0, (spot * df_div) - (strike * df_rf))
    else:
        intrinsic_lower = max(0.0, (strike * df_rf) - (spot * df_div))

    if market_price < intrinsic_lower - IV_PRICE_TOLERANCE:
        # Market price is below theoretical minimum (violates no-arbitrage)
        return None

    # Upper bound check (Call <= spot, Put <= strike * df)
    upper_bound = spot if option_type == "CE" else strike * df_rf
    if market_price > upper_bound + IV_PRICE_TOLERANCE:
        return None

    # 1. Primary Attempt: Newton-Raphson
    vol = max(MIN_VOLATILITY, min(MAX_VOLATILITY, initial_guess))
    for _ in range(MAX_IV_ITERATIONS):
        price = black_scholes_price(
            spot, strike, time_to_expiry, vol, risk_free_rate, dividend_yield, option_type
        )
        diff = price - market_price

        if abs(diff) < IV_PRICE_TOLERANCE:
            return round(vol, 6)

        vega = black_scholes_vega(spot, strike, time_to_expiry, vol, risk_free_rate, dividend_yield)
        if vega < 1e-6:
            # Vega is too small for reliable Newton step; break to bisection
            break

        step = diff / vega
        vol -= step

        if abs(step) < IV_SOLVER_CONVERGENCE_TOLERANCE:
            return round(vol, 6)

        if vol < MIN_VOLATILITY or vol > MAX_VOLATILITY:
            # Stepped out of realistic bounds; fallback to bisection
            break

    # 2. Fallback: Bisection Root-Finding
    low_vol = MIN_VOLATILITY
    high_vol = MAX_VOLATILITY

    price_low = black_scholes_price(
        spot, strike, time_to_expiry, low_vol, risk_free_rate, dividend_yield, option_type
    )
    price_high = black_scholes_price(
        spot, strike, time_to_expiry, high_vol, risk_free_rate, dividend_yield, option_type
    )

    if (price_low - market_price) * (price_high - market_price) > 0.0:
        # Solution does not lie within [MIN_VOLATILITY, MAX_VOLATILITY]
        return None

    for _ in range(MAX_IV_ITERATIONS):
        mid_vol = 0.5 * (low_vol + high_vol)
        price_mid = black_scholes_price(
            spot, strike, time_to_expiry, mid_vol, risk_free_rate, dividend_yield, option_type
        )
        diff = price_mid - market_price

        if abs(diff) < IV_PRICE_TOLERANCE or (high_vol - low_vol) < IV_SOLVER_CONVERGENCE_TOLERANCE:
            return round(mid_vol, 6)

        if diff > 0.0:
            high_vol = mid_vol
        else:
            low_vol = mid_vol

    return round(0.5 * (low_vol + high_vol), 6)
