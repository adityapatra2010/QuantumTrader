"""Options derivatives, volatility, Greeks, and payoff analytics exports."""

from aditrader.options.chain import OptionChainEngine
from aditrader.options.chain_replay import (
    AmbiguousOptionContractError,
    NoEligibleOptionContractError,
    OptionsReplayError,
    PointInTimeOptionChain,
    PointInTimeOptionContract,
    StaleOptionQuoteError,
)
from aditrader.options.greeks import GREEK_CALCULATION_TOLERANCE, calculate_greeks
from aditrader.options.iv import (
    DEFAULT_RISK_FREE_RATE,
    IV_PRICE_TOLERANCE,
    IV_SOLVER_CONVERGENCE_TOLERANCE,
    black_scholes_price,
    black_scholes_vega,
    solve_implied_volatility,
    standard_normal_cdf,
    standard_normal_pdf,
)
from aditrader.options.models import (
    ChainRow,
    ChainStrikeData,
    Greeks,
    OptionLeg,
    OptionStrategy,
    PayoffPoint,
    PayoffSummary,
)
from aditrader.options.payoff import (
    PAYOFF_INTERPOLATION_TOLERANCE,
    calculate_leg_expiry_pnl,
    calculate_leg_mtm_pnl,
    calculate_strategy_payoff,
)
from aditrader.options.position_group import (
    OptionPositionGroup,
    PositionGroupLeg,
    PositionGroupStatus,
)
from aditrader.options.trailing_stop import (
    PremiumTrailingStop,
    TrailingStopEvent,
    TrailingStopEventType,
    TrailingStopState,
)

__all__ = [
    "AmbiguousOptionContractError",
    "ChainRow",
    "ChainStrikeData",
    "DEFAULT_RISK_FREE_RATE",
    "GREEK_CALCULATION_TOLERANCE",
    "Greeks",
    "IV_PRICE_TOLERANCE",
    "IV_SOLVER_CONVERGENCE_TOLERANCE",
    "NoEligibleOptionContractError",
    "OptionChainEngine",
    "OptionLeg",
    "OptionPositionGroup",
    "OptionStrategy",
    "OptionsReplayError",
    "PAYOFF_INTERPOLATION_TOLERANCE",
    "PayoffPoint",
    "PayoffSummary",
    "PointInTimeOptionChain",
    "PointInTimeOptionContract",
    "PositionGroupLeg",
    "PositionGroupStatus",
    "PremiumTrailingStop",
    "StaleOptionQuoteError",
    "TrailingStopEvent",
    "TrailingStopEventType",
    "TrailingStopState",
    "black_scholes_price",
    "black_scholes_vega",
    "calculate_greeks",
    "calculate_leg_expiry_pnl",
    "calculate_leg_mtm_pnl",
    "calculate_strategy_payoff",
    "solve_implied_volatility",
    "standard_normal_cdf",
    "standard_normal_pdf",
]
