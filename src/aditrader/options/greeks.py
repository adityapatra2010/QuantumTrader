"""Closed-form analytical Black-Scholes Greeks calculation engine."""

import math
from typing import Final, Literal

from aditrader.options.iv import (
    DEFAULT_RISK_FREE_RATE,
    standard_normal_cdf,
    standard_normal_pdf,
)
from aditrader.options.models import Greeks

# ------------------------------------------------------------------------------
# Explicit Numerical Tolerance for Greeks Verification
# ------------------------------------------------------------------------------

GREEK_CALCULATION_TOLERANCE: Final[float] = 1e-4
"""Tolerance for analytical benchmark Greek tests."""


def calculate_greeks(
    spot: float,
    strike: float,
    time_to_expiry: float,
    volatility: float,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    dividend_yield: float = 0.0,
    option_type: Literal["CE", "PE"] = "CE",
) -> Greeks:
    """
    Compute closed-form Black-Scholes Greeks for European index and equity options.

    Returns Greeks model with:
    - delta: Sensitivity to 1 INR move in underlying price (Call: [0, 1], Put: [-1, 0])
    - gamma: Sensitivity of Delta to 1 INR move in underlying price (always >= 0)
    - theta: Daily time decay in INR (calendar day / 365)
    - theta_trading: Daily time decay in INR (trading day / 252)
    - vega: Sensitivity to 1% (0.01) increase in implied volatility
    - rho: Sensitivity to 1% (0.01) increase in risk-free interest rate
    """
    if spot <= 0.0 or strike <= 0.0:
        raise ValueError("Spot and Strike prices must be strictly positive")

    # Boundary: At or past expiration
    if time_to_expiry <= 1e-7:
        if option_type == "CE":
            delta = 1.0 if spot > strike else (0.5 if spot == strike else 0.0)
        else:
            delta = -1.0 if spot < strike else (-0.5 if spot == strike else 0.0)

        return Greeks(
            delta=delta,
            gamma=0.0,
            theta=0.0,
            theta_trading=0.0,
            vega=0.0,
            rho=0.0,
        )

    # Boundary: Degenerate zero volatility
    if volatility <= 1e-7:
        df_rf = math.exp(-risk_free_rate * time_to_expiry)
        forward = spot * math.exp((risk_free_rate - dividend_yield) * time_to_expiry)
        if option_type == "CE":
            delta = math.exp(-dividend_yield * time_to_expiry) if forward > strike else 0.0
        else:
            delta = -math.exp(-dividend_yield * time_to_expiry) if forward < strike else 0.0

        return Greeks(
            delta=delta,
            gamma=0.0,
            theta=0.0,
            theta_trading=0.0,
            vega=0.0,
            rho=0.0,
        )

    sqrt_t = math.sqrt(time_to_expiry)
    d1 = (
        math.log(spot / strike)
        + (risk_free_rate - dividend_yield + 0.5 * volatility * volatility) * time_to_expiry
    ) / (volatility * sqrt_t)
    d2 = d1 - volatility * sqrt_t

    df_div = math.exp(-dividend_yield * time_to_expiry)
    df_rf = math.exp(-risk_free_rate * time_to_expiry)
    pdf_d1 = standard_normal_pdf(d1)

    # 1. Delta
    if option_type == "CE":
        delta = df_div * standard_normal_cdf(d1)
    else:
        delta = -df_div * standard_normal_cdf(-d1)

    # 2. Gamma (identical for Call and Put)
    gamma = (df_div * pdf_d1) / (spot * volatility * sqrt_t)

    # 3. Vega (per 1% change in vol)
    vega = (spot * df_div * sqrt_t * pdf_d1) / 100.0

    # 4. Theta (annual rate, scaled to 1 calendar day and 1 trading day)
    term1 = -(spot * df_div * pdf_d1 * volatility) / (2.0 * sqrt_t)

    if option_type == "CE":
        term2 = -risk_free_rate * strike * df_rf * standard_normal_cdf(d2)
        term3 = dividend_yield * spot * df_div * standard_normal_cdf(d1)
        theta_annual = term1 + term2 + term3
    else:
        term2 = risk_free_rate * strike * df_rf * standard_normal_cdf(-d2)
        term3 = -dividend_yield * spot * df_div * standard_normal_cdf(-d1)
        theta_annual = term1 + term2 + term3

    theta_cal = theta_annual / 365.0
    theta_trading = theta_annual / 252.0

    # 5. Rho (per 1% change in risk-free rate)
    if option_type == "CE":
        rho = (strike * time_to_expiry * df_rf * standard_normal_cdf(d2)) / 100.0
    else:
        rho = (-strike * time_to_expiry * df_rf * standard_normal_cdf(-d2)) / 100.0

    return Greeks(
        delta=round(delta, 5),
        gamma=round(gamma, 7),
        theta=round(theta_cal, 4),
        theta_trading=round(theta_trading, 4),
        vega=round(vega, 4),
        rho=round(rho, 4),
    )
