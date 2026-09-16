"""Chronos time-series foundation model adapter.

Per ADR 005 and ADR 012:
- Encapsulates Chronos (T5-based probabilistic time-series model) behind ForecastEngine.
- Point-in-time anti-lookahead validation.
- Pluggable inference backend with offline deterministic fallback.
- Never executes trading commands.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from aditrader.ai.base import ForecastEngine
from aditrader.ai.errors import (
    AIMalformedOutputError,
    AITimeoutError,
    AIUnavailableError,
)
from aditrader.ai.forecasting.mock import HeuristicForecastEngine, compute_bars_hash
from aditrader.ai.models import AISourceType, ForecastResult, ProvenanceRecord
from aditrader.core.models.market_data import Bar

ChronosInferenceCallable = Callable[[list[Bar], int, dict[str, Any]], ForecastResult]


class ChronosForecastEngine(ForecastEngine):
    """Adapter for Chronos probabilistic time-series foundation models."""

    def __init__(
        self,
        model_id: str = "chronos-t5-base",
        model_version: str = "1.0.0",
        provider: str = "amazon",
        inference_backend: ChronosInferenceCallable | None = None,
        timeout_seconds: float = 30.0,
        max_retries: int = 2,
        enable_heuristic_fallback: bool = True,
        seed: int | None = 100,
    ) -> None:
        self.model_id = model_id
        self.model_version = model_version
        self.provider = provider
        self._inference_backend = inference_backend
        self.timeout_seconds = timeout_seconds
        self.max_retries = max_retries
        self.enable_heuristic_fallback = enable_heuristic_fallback
        self.seed = seed
        self._fallback_engine = HeuristicForecastEngine(
            model_id=f"{model_id}-heuristic",
            model_version=model_version,
            provider=provider,
            volatility_multiplier=1.8,  # Slightly wider quantiles for Chronos probabilistic bands
        )

    def is_available(self) -> bool:
        """Return True if inference backend is active or offline heuristic fallback is enabled."""
        if self._inference_backend is not None:
            return True
        return self.enable_heuristic_fallback

    def forecast(self, history: list[Bar], horizon_bars: int = 5) -> ForecastResult:
        """Generate probabilistic price trajectory using Chronos."""
        if not history:
            raise AIMalformedOutputError(
                "Cannot generate forecast from empty historical bar series"
            )
        if horizon_bars <= 0:
            raise AIMalformedOutputError(f"horizon_bars must be positive, got {horizon_bars}")

        if self._inference_backend is not None:
            try:
                result = self._inference_backend(
                    history,
                    horizon_bars,
                    {"seed": self.seed, "timeout_seconds": self.timeout_seconds},
                )
                if not isinstance(result, ForecastResult):
                    raise AIMalformedOutputError(
                        f"Inference backend returned {type(result).__name__}, expected ForecastResult"
                    )
                return result
            except Exception as e:
                if isinstance(e, (AIMalformedOutputError, AITimeoutError, AIUnavailableError)):
                    raise
                raise AIUnavailableError(f"Chronos inference execution failed: {e}") from e

        if not self.enable_heuristic_fallback:
            raise AIUnavailableError(
                f"Chronos model backend for '{self.model_id}' is not loaded and fallback is disabled"
            )

        base_result = self._fallback_engine.forecast(history, horizon_bars)

        input_hash = compute_bars_hash(history)
        provenance = ProvenanceRecord(
            source_type=AISourceType.PROBABILISTIC_FORECAST,
            model_id=f"{self.model_id}-heuristic-fallback",
            model_version=self.model_version,
            provider="heuristic-fallback",
            generated_at=datetime.now(UTC),
            input_hash=input_hash,
            seed=self.seed,
            is_deterministic=True,
            confidence=0.70,
        )

        return ForecastResult(
            cutoff_timestamp=base_result.cutoff_timestamp,
            horizon_bars=horizon_bars,
            timestamps=base_result.timestamps,
            predicted_close=base_result.predicted_close,
            predicted_high=base_result.predicted_high,
            predicted_low=base_result.predicted_low,
            confidence_spread=base_result.confidence_spread,
            provenance=provenance,
            warning="Custom Chronos backend weights not loaded; deterministic heuristic baseline applied (ADR 012).",
        )
