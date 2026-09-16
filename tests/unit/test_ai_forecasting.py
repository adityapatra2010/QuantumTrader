"""Unit tests for Phase 7 forecasting runtime (Kronos, Chronos, and Heuristic)."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from aditrader.ai.catalog import AICapability, get_default_model_catalog
from aditrader.ai.config import (
    AIServiceConfig,
    AISubsystemsConfig,
    SubsystemModelConfig,
)
from aditrader.ai.errors import AIMalformedOutputError
from aditrader.ai.forecasting.chronos import ChronosForecastEngine
from aditrader.ai.forecasting.kronos import KronosForecastEngine
from aditrader.ai.forecasting.mock import HeuristicForecastEngine
from aditrader.ai.models import AISourceType, ForecastResult
from aditrader.ai.registry import get_default_provider_registry
from aditrader.ai.service import AIServiceResolver
from aditrader.core.models.market_data import Bar


def make_sample_bars(n: int = 10, start_price: float = 24000.0) -> list[Bar]:
    """Generate deterministic sequence of closed OHLCV bars."""
    bars: list[Bar] = []
    base_time = datetime(2026, 6, 1, 9, 15, tzinfo=UTC)
    price = start_price
    for i in range(n):
        ts = base_time + timedelta(minutes=5 * i)
        c = price + (i * 10.0)
        bars.append(
            Bar(
                timestamp=ts,
                open=c - 5.0,
                high=c + 15.0,
                low=c - 10.0,
                close=c,
                volume=1000 + i * 100,
            )
        )
    return bars


def test_heuristic_forecast_engine_valid_projection() -> None:
    """Heuristic engine produces strictly monotonic, future, envelope-consistent forecasts."""
    bars = make_sample_bars(20)
    engine = HeuristicForecastEngine()
    assert engine.is_available() is True

    result = engine.forecast(bars, horizon_bars=5)

    assert isinstance(result, ForecastResult)
    assert result.horizon_bars == 5
    assert len(result.timestamps) == 5
    assert len(result.predicted_close) == 5
    assert len(result.predicted_high) == 5
    assert len(result.predicted_low) == 5

    # Anti-lookahead checks
    assert result.cutoff_timestamp == bars[-1].timestamp
    for ts in result.timestamps:
        assert ts > result.cutoff_timestamp

    # Envelope validation
    for i in range(5):
        assert result.predicted_low[i] <= result.predicted_close[i] <= result.predicted_high[i]

    # Provenance checks
    assert result.provenance.source_type == AISourceType.PROBABILISTIC_FORECAST
    assert len(result.provenance.input_hash) == 64
    assert result.provenance.is_deterministic is True


def test_heuristic_forecast_engine_empty_history_rejection() -> None:
    """Empty history raises AIMalformedOutputError."""
    engine = HeuristicForecastEngine()
    with pytest.raises(AIMalformedOutputError, match="empty historical bar series"):
        engine.forecast([])


def test_heuristic_forecast_engine_invalid_horizon_rejection() -> None:
    """Non-positive horizon raises AIMalformedOutputError."""
    bars = make_sample_bars(5)
    engine = HeuristicForecastEngine()
    with pytest.raises(AIMalformedOutputError, match="horizon_bars must be positive"):
        engine.forecast(bars, horizon_bars=0)


def test_kronos_forecast_engine_offline() -> None:
    """Kronos engine operates offline via deterministic fallback with Kronos provenance."""
    bars = make_sample_bars(15)
    engine = KronosForecastEngine(model_id="kronos-base", seed=42)
    assert engine.is_available() is True

    result1 = engine.forecast(bars, horizon_bars=4)
    result2 = engine.forecast(bars, horizon_bars=4)

    assert result1.provenance.model_id == "kronos-base-heuristic-fallback"
    assert result1.provenance.provider == "heuristic-fallback"
    assert result1.provenance.confidence == 0.70
    assert result1.provenance.seed == 42
    assert result1.horizon_bars == 4
    # Deterministic bit-for-bit repeatability with same seed and input
    assert result1.predicted_close == result2.predicted_close
    assert result1.provenance.input_hash == result2.provenance.input_hash


def test_kronos_forecast_engine_custom_backend() -> None:
    """Kronos engine calls custom inference backend when supplied."""
    bars = make_sample_bars(5)
    called = False

    def mock_backend(h: list[Bar], horizon: int, params: dict[str, Any]) -> ForecastResult:
        nonlocal called
        called = True
        engine = HeuristicForecastEngine(model_id="mock-kronos-backend")
        return engine.forecast(h, horizon)

    engine = KronosForecastEngine(
        model_id="kronos-large",
        inference_backend=mock_backend,
    )
    result = engine.forecast(bars, horizon_bars=3)
    assert called is True
    assert result.horizon_bars == 3


def test_chronos_forecast_engine_offline() -> None:
    """Chronos engine operates offline via deterministic fallback with truthful fallback provenance."""
    bars = make_sample_bars(15)
    engine = ChronosForecastEngine(model_id="chronos-t5-base", seed=99)
    assert engine.is_available() is True

    result = engine.forecast(bars, horizon_bars=6)

    assert result.provenance.model_id == "chronos-t5-base-heuristic-fallback"
    assert result.provenance.provider == "heuristic-fallback"
    assert result.provenance.confidence == 0.70
    assert result.provenance.seed == 99
    assert result.horizon_bars == 6
    assert len(result.predicted_close) == 6
    for i in range(6):
        assert result.predicted_low[i] <= result.predicted_close[i] <= result.predicted_high[i]


def test_ai_service_resolver_forecasting_resolution() -> None:
    """AIServiceResolver cleanly resolves and instantiates configured Kronos forecast engine."""
    catalog = get_default_model_catalog()
    registry = get_default_provider_registry(catalog=catalog)

    config = AIServiceConfig(
        enabled=True,
        subsystems=AISubsystemsConfig(
            vision=SubsystemModelConfig(
                provider="google",
                model_id="gemini-2.0-flash",
                required_capabilities={AICapability.VISION},
            ),
            forecasting=SubsystemModelConfig(
                provider="local",
                model_id="kronos-base",
                required_capabilities={AICapability.FORECASTING},
            ),
            strategy_suggestor=SubsystemModelConfig(
                provider="local",
                model_id="rule-suggestor-v1",
            ),
            strategy_reviewer=SubsystemModelConfig(
                provider="local",
                model_id="adversarial-reviewer-v1",
            ),
            ocr=SubsystemModelConfig(
                provider="ocrspace",
                model_id="ocr-engine-2",
                required_capabilities={AICapability.OCR},
            ),
        ),
    )

    resolver = AIServiceResolver(config=config, registry=registry, catalog=catalog)

    # Resolution without credentials check
    engine = resolver.resolve_forecast_engine(require_credentials=False)
    assert isinstance(engine, KronosForecastEngine)
    assert engine.model_id == "kronos-base"

    bars = make_sample_bars(10)
    result = engine.forecast(bars, horizon_bars=5)
    assert result.horizon_bars == 5
