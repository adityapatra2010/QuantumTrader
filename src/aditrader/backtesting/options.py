"""Architectural boundary placeholder and specification for Options Backtesting.

Options Backtesting Boundary & Current Limitations:
--------------------------------------------------
1. Underlying Candle Execution Limitation:
   The core Phase 5 BacktestRunner executes orders against underlying asset candle
   prices (e.g., NIFTY 50 index spot/futures bars). In production options trading,
   contracts execute at individual strike option premiums governed by supply/demand,
   implied volatility (IV) surfaces, and non-linear Greeks decay.

2. Greeks & Volatility Surface Modeling:
   Multi-leg options strategies (Iron Condors, Straddles, Credit Spreads) require:
   - Dynamic strike ladder selection from Phase 3 (`StrikeLadderCalculator`).
   - Synthetic option pricing via `BlackScholesEngine` when historical tick-level
     option chains are absent, or direct historical option tick replay.
   - IV smile/skew interpolation across deltas.
   - Accelerated intraday theta decay on 0DTE weekly expiry sessions.

3. Execution Friction & Liquidity Boundaries:
   Deep OTM and far-month option contracts exhibit wider bid-ask spreads and liquidity
   haircuts. Simulating these requires strike-specific slippage and open interest (OI)
   liquidity filters.

This module provides `OptionsBacktestRunner` as an architectural placeholder to be
implemented in advanced derivatives backtesting phases (Phase 7/8).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import ConfigDict, Field

from aditrader.backtesting.runner import BacktestConfig, BacktestResult
from aditrader.core.models.market_data import Bar
from aditrader.data.feeds.base import DataFeed
from aditrader.strategy.compiler.engine import ExecutableStrategy


class OptionsBacktestConfig(BacktestConfig):
    """Configuration specific to multi-leg derivative options backtesting."""

    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)

    pricing_mode: str = Field(
        default="black_scholes_synthetic",
        description="Option pricing engine: 'black_scholes_synthetic' or 'historical_ticks'",
    )
    iv_smile_interpolation: bool = Field(
        default=True,
        description="Whether to apply volatility smile/skew adjustment across strikes",
    )
    enforce_oi_liquidity_gate: bool = Field(
        default=True,
        description="Reject fills on illiquid strikes with open interest below threshold",
    )
    min_strike_oi: int = Field(
        default=500,
        ge=0,
        description="Minimum Open Interest required to permit simulated fill",
    )


class OptionsBacktestRunner:
    """Architectural placeholder for multi-leg options backtesting.

    Executes options strategies using either synthetic Black-Scholes pricing or
    historical option chain tick replay.

    NOTE: Full option-chain tick replay is scheduled for future milestones. Calling
    `run()` will raise `NotImplementedError` outlining the required components.
    """

    def __init__(self, config: OptionsBacktestConfig | None = None) -> None:
        self.config = config or OptionsBacktestConfig()

    def run(
        self,
        strategy: ExecutableStrategy,
        data: DataFeed | list[Bar],
        start_time: datetime | None = None,
        end_time: datetime | None = None,
        **kwargs: Any,
    ) -> BacktestResult:
        """Execute options backtest simulation.

        Raises:
            NotImplementedError: OptionsBacktestRunner is reserved for Phase 7/8.
        """
        raise NotImplementedError(
            "OptionsBacktestRunner is an architectural placeholder. "
            "Phase 5 supports deterministic underlying asset replay via BacktestRunner. "
            "Full options backtesting requires OptionChainDataFeed and synthetic IV surface modeling."
        )
