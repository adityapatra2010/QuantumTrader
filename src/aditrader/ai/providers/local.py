"""Local / Offline AI Provider implementation.

Per Phase 7 and ADR 005:
- Provides zero-network, local inference engines and heuristic fallbacks.
- Strictly offline, zero external API keys or credentials required.
- Standard test suite and offline research operate cleanly through this provider.
"""

from __future__ import annotations

from typing import Any

from aditrader.ai.base import (
    ForecastEngine,
    StrategyReviewer,
    StrategySuggestor,
)
from aditrader.ai.catalog import ModelCatalog
from aditrader.ai.forecasting.chronos import ChronosForecastEngine
from aditrader.ai.forecasting.kronos import KronosForecastEngine
from aditrader.ai.forecasting.mock import HeuristicForecastEngine
from aditrader.ai.registry import BaseAIProvider


class LocalAIProvider(BaseAIProvider):
    """Local offline provider for deterministic and heuristic AI models."""

    def __init__(self, catalog: ModelCatalog | None = None) -> None:
        self._catalog = catalog

    @property
    def provider_id(self) -> str:
        return "local"

    def is_available(self) -> bool:
        """Local provider is always operational offline."""
        return True

    def get_forecast_engine(self, model_id: str, **kwargs: Any) -> ForecastEngine:
        """Instantiate local ForecastEngine for requested model_id."""
        clean_id = model_id.lower().strip()
        if "kronos" in clean_id:
            return KronosForecastEngine(
                model_id=model_id,
                provider=self.provider_id,
                **kwargs,
            )
        if "chronos" in clean_id:
            return ChronosForecastEngine(
                model_id=model_id,
                provider=self.provider_id,
                **kwargs,
            )
        return HeuristicForecastEngine(
            model_id=model_id,
            provider=self.provider_id,
            **kwargs,
        )

    def get_strategy_suggestor(self, model_id: str, **kwargs: Any) -> StrategySuggestor:
        """Instantiate local StrategySuggestor."""
        from aditrader.ai.suggestor.engine import RuleBasedSuggestor

        return RuleBasedSuggestor(
            model_id=model_id,
            provider=self.provider_id,
            **kwargs,
        )

    def get_strategy_reviewer(self, model_id: str, **kwargs: Any) -> StrategyReviewer:
        """Instantiate local StrategyReviewer."""
        from aditrader.ai.reviewer.engine import DeterministicAdvisoryReviewer

        return DeterministicAdvisoryReviewer(
            model_id=model_id,
            provider=self.provider_id,
            **kwargs,
        )
