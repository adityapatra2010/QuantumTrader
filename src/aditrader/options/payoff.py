"""Pure payoff and mark-to-market curve calculation engine for multi-leg option strategies."""

from typing import Final

from aditrader.core.models.enums import OrderSide
from aditrader.options.iv import DEFAULT_RISK_FREE_RATE, black_scholes_price
from aditrader.options.models import OptionLeg, OptionStrategy, PayoffPoint, PayoffSummary

# ------------------------------------------------------------------------------
# Explicit Numerical Tolerance for Breakeven Interpolation
# ------------------------------------------------------------------------------

PAYOFF_INTERPOLATION_TOLERANCE: Final[float] = 0.01
"""Tolerance in INR for root-finding and breakeven point determination (1 paisa)."""


def calculate_leg_expiry_pnl(leg: OptionLeg, spot_at_expiry: float) -> float:
    """Calculate single leg intrinsic profit or loss at expiration."""
    if leg.option_type == "CE":
        intrinsic = max(0.0, spot_at_expiry - leg.strike)
    else:
        intrinsic = max(0.0, leg.strike - spot_at_expiry)

    if leg.side == OrderSide.BUY:
        pnl_per_unit = intrinsic - leg.entry_price
    else:
        pnl_per_unit = leg.entry_price - intrinsic

    return pnl_per_unit * float(leg.qty)


def calculate_leg_mtm_pnl(
    leg: OptionLeg,
    spot: float,
    dte: int,
    volatility: float = 0.20,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    dividend_yield: float = 0.0,
) -> float:
    """Calculate single leg theoretical mark-to-market profit or loss before expiration."""
    if dte <= 0:
        return calculate_leg_expiry_pnl(leg, spot)

    t_eval = float(dte) / 365.0
    mtm_premium = black_scholes_price(
        spot=spot,
        strike=leg.strike,
        time_to_expiry=t_eval,
        volatility=volatility,
        risk_free_rate=risk_free_rate,
        dividend_yield=dividend_yield,
        option_type=leg.option_type,
    )

    if leg.side == OrderSide.BUY:
        pnl_per_unit = mtm_premium - leg.entry_price
    else:
        pnl_per_unit = leg.entry_price - mtm_premium

    return pnl_per_unit * float(leg.qty)


def calculate_strategy_payoff(
    strategy: OptionStrategy,
    underlying_price_range: list[float],
    dte_slices: list[int] | None = None,
    volatility: float = 0.20,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    dividend_yield: float = 0.0,
) -> tuple[list[PayoffPoint], PayoffSummary]:
    """
    Pure calculation generating the at-expiry and mark-to-market payoff curves.

    Parameters:
    - strategy: Composite multi-leg structure (e.g., Bull Call Spread, Iron Condor)
    - underlying_price_range: Sorted list of evaluation prices
    - dte_slices: Days-to-expiry for intermediate MTM curves (e.g., [7, 3, 1])
    - volatility: Implied volatility assumed for MTM curves
    - risk_free_rate: Annualized risk-free rate for MTM valuation

    Returns:
    - list[PayoffPoint]: Coordinate curve along underlying price spectrum
    - PayoffSummary: Breakevens, max profit, max loss, net cash flow
    """
    if not underlying_price_range:
        raise ValueError("Price range cannot be empty")

    slices = sorted(dte_slices) if dte_slices else []
    points: list[PayoffPoint] = []

    # Net Cash Flow (Positive = Net Credit, Negative = Net Debit)
    net_cash_flow = 0.0
    for leg in strategy.legs:
        leg_turnover = leg.entry_price * float(leg.qty)
        if leg.side == OrderSide.BUY:
            net_cash_flow -= leg_turnover
        else:
            net_cash_flow += leg_turnover

    net_cash_flow = round(net_cash_flow, 2)

    # Evaluate curves across price range
    for price in underlying_price_range:
        pnl_expiry = sum(calculate_leg_expiry_pnl(leg, price) for leg in strategy.legs)

        pnl_mtm: dict[int, float] = {}
        for dte in slices:
            pnl_mtm[dte] = round(
                sum(
                    calculate_leg_mtm_pnl(
                        leg=leg,
                        spot=price,
                        dte=dte,
                        volatility=volatility,
                        risk_free_rate=risk_free_rate,
                        dividend_yield=dividend_yield,
                    )
                    for leg in strategy.legs
                ),
                2,
            )

        points.append(
            PayoffPoint(
                underlying_price=price,
                pnl_at_expiry=round(pnl_expiry, 2),
                pnl_mtm=pnl_mtm,
            )
        )

    # Breakeven point root-finding via linear interpolation
    breakevens: list[float] = []
    for i in range(len(points) - 1):
        p1 = points[i]
        p2 = points[i + 1]

        # Exact zero crossing check
        if abs(p1.pnl_at_expiry) < PAYOFF_INTERPOLATION_TOLERANCE:
            if not any(abs(p1.underlying_price - be) < 0.1 for be in breakevens):
                breakevens.append(round(p1.underlying_price, 2))
        elif (p1.pnl_at_expiry * p2.pnl_at_expiry) < 0.0:
            # Sign change detected: linearly interpolate root
            dy = p2.pnl_at_expiry - p1.pnl_at_expiry
            dx = p2.underlying_price - p1.underlying_price
            if abs(dy) > 1e-6:
                root = p1.underlying_price + (-p1.pnl_at_expiry / dy) * dx
                if not any(abs(root - be) < 0.1 for be in breakevens):
                    breakevens.append(round(root, 2))

    if abs(points[-1].pnl_at_expiry) < PAYOFF_INTERPOLATION_TOLERANCE and not any(
        abs(points[-1].underlying_price - be) < 0.1 for be in breakevens
    ):
        breakevens.append(round(points[-1].underlying_price, 2))

    # Evaluate Max Profit and Max Loss
    min_pnl = min(p.pnl_at_expiry for p in points)
    max_pnl = max(p.pnl_at_expiry for p in points)

    # Slope check at outer boundaries to identify unbounded wings
    left_slope = (points[1].pnl_at_expiry - points[0].pnl_at_expiry) / (
        points[1].underlying_price - points[0].underlying_price
    )
    right_slope = (points[-1].pnl_at_expiry - points[-2].pnl_at_expiry) / (
        points[-1].underlying_price - points[-2].underlying_price
    )

    # Profit expands to infinity if right slope is positive (long call) or left slope is negative (long put)
    is_infinite_profit = right_slope > 0.05 or left_slope < -0.05
    # Loss expands to infinity if right slope is negative (short call)
    is_infinite_loss = right_slope < -0.05

    max_profit: float | None = None if is_infinite_profit else round(max_pnl, 2)
    max_loss: float | None = None if is_infinite_loss else round(abs(min_pnl), 2)

    risk_reward: float | None = None
    if max_profit is not None and max_loss is not None and max_loss > 0.0:
        risk_reward = round(max_profit / max_loss, 2)

    summary = PayoffSummary(
        max_profit=max_profit,
        max_loss=max_loss,
        breakevens=sorted(breakevens),
        net_debit_credit=net_cash_flow,
        risk_reward_ratio=risk_reward,
    )

    return points, summary
