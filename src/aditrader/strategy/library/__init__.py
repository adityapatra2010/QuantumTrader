"""Strategy Library catalog, templates, registry, and DNA profiling."""

from aditrader.strategy.library.dna import profile_strategy_dna
from aditrader.strategy.library.models import (
    Directionality,
    GammaRisk,
    MarginEfficiency,
    MarketRegime,
    StrategyCategory,
    StrategyDNA,
    StrategyRecord,
    ThetaExposure,
    TradingStyle,
    VegaExposure,
)
from aditrader.strategy.library.registry import (
    StrategyNotFoundError,
    StrategyRegistry,
    StrategyRegistryError,
    StrategyVersionExistsError,
)
from aditrader.strategy.library.templates import (
    create_nifty_bull_call_spread_dsl,
    create_nifty_iron_condor_dsl,
    create_nifty_long_straddle_dsl,
    get_builtin_templates,
)

__all__ = [
    "Directionality",
    "GammaRisk",
    "MarginEfficiency",
    "MarketRegime",
    "StrategyCategory",
    "StrategyDNA",
    "StrategyNotFoundError",
    "StrategyRecord",
    "StrategyRegistry",
    "StrategyRegistryError",
    "StrategyVersionExistsError",
    "ThetaExposure",
    "TradingStyle",
    "VegaExposure",
    "create_nifty_bull_call_spread_dsl",
    "create_nifty_iron_condor_dsl",
    "create_nifty_long_straddle_dsl",
    "get_builtin_templates",
    "profile_strategy_dna",
]
