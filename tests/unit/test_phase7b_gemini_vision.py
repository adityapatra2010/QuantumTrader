"""Unit tests for Phase 7B: Google Gemini Provider & Multimodal Vision Engine.

Per Phase 7B requirements:
- Tests structured VisionResult construction and Pydantic validation.
- Tests malformed provider output, invalid price coordinates, and empty reasoning.
- Tests credential and availability failure paths without network dependencies.
- Tests unsupported vision capability rejection.
- Tests configuration-driven provider and model resolution via Phase 7A registry.
- Includes one explicitly opt-in real-network smoke test skipped in normal test suite.
"""

import hashlib
import json
import os
from datetime import UTC
from typing import Any

import pytest
from pydantic import ValidationError

from aditrader.ai.catalog import (
    AICapability,
    ModelCatalog,
    ModelMetadata,
    get_default_model_catalog,
)
from aditrader.ai.config import (
    AIServiceConfig,
    AISubsystemsConfig,
    SubsystemModelConfig,
)
from aditrader.ai.credentials import (
    DictCredentialResolver,
    EnvCredentialResolver,
)
from aditrader.ai.errors import (
    AICredentialError,
    AIMalformedOutputError,
    AIProviderError,
    AITimeoutError,
    AIUnavailableError,
    AIUnsupportedCapabilityError,
)
from aditrader.ai.models import (
    AISourceType,
    VisionResult,
)
from aditrader.ai.providers.google import GoogleAIProvider
from aditrader.ai.registry import AIProviderRegistry
from aditrader.ai.service import AIServiceResolver
from aditrader.ai.vision.gemini import GeminiVisionEngine

# Minimal 1x1 transparent PNG bytes for testing
SAMPLE_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00"
    b"\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _create_mock_gemini_response(
    trend: str = "Bullish",
    support: list[float] | None = None,
    resistance: list[float] | None = None,
    patterns: list[dict[str, Any]] | None = None,
    reasoning: str = "Clear bullish continuation channel observed.",
    is_empty: bool = False,
    model_version: str = "gemini-2.0-flash-001",
    wrap_code_fence: bool = False,
) -> dict[str, Any]:
    """Helper creating raw Gemini REST API response structure."""
    if support is None:
        support = [24300.0, 24200.0]
    if resistance is None:
        resistance = [24600.0, 24800.0]
    if patterns is None:
        patterns = [
            {"name": "Bull Flag", "confidence": 0.85, "description": "Continuation pattern"}
        ]

    body_dict = {
        "trend": trend,
        "support": support,
        "resistance": resistance,
        "patterns": patterns,
        "reasoning": reasoning,
        "is_empty": is_empty,
    }
    raw_json = json.dumps(body_dict)
    text_content = f"```json\n{raw_json}\n```" if wrap_code_fence else raw_json

    return {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": text_content}],
                    "role": "model",
                },
                "finishReason": "STOP",
            }
        ],
        "modelVersion": model_version,
    }


def test_successful_structured_vision_result_construction() -> None:
    """Verify GeminiVisionEngine executes request and returns validated VisionResult with Provenance."""
    captured_calls: list[tuple[str, dict[str, Any], float]] = []

    def mock_transport(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        captured_calls.append((url, payload, timeout))
        return _create_mock_gemini_response(
            trend="Bullish",
            support=[24350.0, 24200.0],
            resistance=[24650.0, 24800.0],
            patterns=[
                {
                    "name": "Ascending Channel",
                    "confidence": 0.90,
                    "description": "Bullish structure",
                },
                {"name": "Hammer", "confidence": 0.80, "description": "Reversal candlestick"},
            ],
            reasoning="Price is respecting the ascending channel support with a clean hammer rejection.",
            is_empty=False,
            model_version="gemini-2.0-flash-001",
            wrap_code_fence=True,
        )

    provider = GoogleAIProvider(api_key="test-key", transport=mock_transport)
    engine = provider.get_vision_engine("gemini-2.0-flash", timeout_seconds=15.0, temperature=0.1)

    assert engine.is_available() is True
    result = engine.analyze(SAMPLE_PNG_BYTES, spot_price=24400.0)

    # Verify single call executed (bounded call count)
    assert len(captured_calls) == 1
    url, payload, timeout = captured_calls[0]
    assert "models/gemini-2.0-flash:generateContent" in url
    assert timeout == 15.0
    assert payload["generationConfig"]["temperature"] == 0.1
    assert payload["generationConfig"]["responseMimeType"] == "application/json"

    # Verify VisionResult domain fields
    assert result.trend == "Bullish"
    assert result.support == [24350.0, 24200.0]
    assert result.resistance == [24650.0, 24800.0]
    assert len(result.patterns) == 2
    assert result.patterns[0].name == "Ascending Channel"
    assert result.patterns[0].confidence == 0.90
    assert result.patterns[1].name == "Hammer"
    assert (
        result.reasoning
        == "Price is respecting the ascending channel support with a clean hammer rejection."
    )
    assert result.is_empty is False

    # Verify source image hash and provenance mirror
    expected_hash = hashlib.sha256(SAMPLE_PNG_BYTES).hexdigest().lower()
    assert result.source_image_hash == expected_hash
    assert result.provenance.input_hash == expected_hash
    assert result.provenance.source_type == AISourceType.MULTIMODAL_VISION
    assert result.provenance.provider == "google"
    assert result.provenance.model_id == "gemini-2.0-flash"
    assert result.provenance.model_version == "gemini-2.0-flash-001"
    assert result.provenance.is_deterministic is False
    assert result.provenance.confidence == 0.85  # average of 0.90 and 0.80
    assert result.provenance.generated_at.tzinfo == UTC


def test_malformed_provider_output_rejection() -> None:
    """Verify malformed JSON, empty candidates, safety blocks, and missing fields raise AIMalformedOutputError."""

    def make_engine(mock_resp: dict[str, Any]) -> GeminiVisionEngine:
        def transport(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
            return mock_resp

        provider = GoogleAIProvider(api_key="test-key", transport=transport)
        return provider.get_vision_engine("gemini-2.0-flash")  # type: ignore[return-value]

    # 1. Non-JSON string in candidate text
    engine1 = make_engine(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "I am an AI, not able to output valid JSON here."}]
                    },
                    "finishReason": "STOP",
                }
            ]
        }
    )
    with pytest.raises(AIMalformedOutputError, match="Failed to parse Gemini model output as JSON"):
        engine1.analyze(SAMPLE_PNG_BYTES)

    # 2. Empty candidate list
    engine2 = make_engine({"candidates": []})
    with pytest.raises(AIMalformedOutputError, match="Gemini response contains no candidates"):
        engine2.analyze(SAMPLE_PNG_BYTES)

    # 3. Terminated prematurely by safety filter
    engine3 = make_engine({"candidates": [{"finishReason": "SAFETY"}]})
    with pytest.raises(AIMalformedOutputError, match="terminated prematurely"):
        engine3.analyze(SAMPLE_PNG_BYTES)

    # 4. Missing trend field
    engine4 = make_engine(
        _create_mock_gemini_response(trend="", reasoning="Valid reasoning but no trend")
    )
    with pytest.raises(AIMalformedOutputError, match="Invalid trend"):
        engine4.analyze(SAMPLE_PNG_BYTES)

    # 5. Invalid trend value
    engine5 = make_engine(
        _create_mock_gemini_response(trend="Sideways", reasoning="Valid reasoning")
    )
    with pytest.raises(AIMalformedOutputError, match="Invalid trend"):
        engine5.analyze(SAMPLE_PNG_BYTES)

    # 6. Empty reasoning
    engine6 = make_engine(_create_mock_gemini_response(trend="Bullish", reasoning="   "))
    with pytest.raises(AIMalformedOutputError, match="empty reasoning"):
        engine6.analyze(SAMPLE_PNG_BYTES)


def test_invalid_price_levels_rejection() -> None:
    """Verify negative and non-numeric price levels in support or resistance raise AIMalformedOutputError."""

    def make_engine(support: list[Any], resistance: list[Any]) -> GeminiVisionEngine:
        def transport(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
            return _create_mock_gemini_response(support=support, resistance=resistance)

        provider = GoogleAIProvider(api_key="test-key", transport=transport)
        return provider.get_vision_engine("gemini-2.0-flash")  # type: ignore[return-value]

    # Negative support
    with pytest.raises(AIMalformedOutputError, match="Support level must be strictly positive"):
        make_engine(support=[-24000.0], resistance=[25000.0]).analyze(SAMPLE_PNG_BYTES)

    # Zero support
    with pytest.raises(AIMalformedOutputError, match="Support level must be strictly positive"):
        make_engine(support=[0.0], resistance=[25000.0]).analyze(SAMPLE_PNG_BYTES)

    # Negative resistance
    with pytest.raises(AIMalformedOutputError, match="Resistance level must be strictly positive"):
        make_engine(support=[24000.0], resistance=[-25000.0]).analyze(SAMPLE_PNG_BYTES)

    # Non-numeric support
    with pytest.raises(AIMalformedOutputError, match="Invalid non-numeric support coordinate"):
        make_engine(support=["two_four_zero"], resistance=[25000.0]).analyze(SAMPLE_PNG_BYTES)


def test_missing_and_resolved_credentials() -> None:
    """Verify behavior when API credentials are missing vs provided."""
    # 1. No credentials provided
    provider_no_key = GoogleAIProvider()
    assert provider_no_key.is_available() is False

    engine_no_key = provider_no_key.get_vision_engine("gemini-2.0-flash")
    assert engine_no_key.is_available() is False
    with pytest.raises(AICredentialError, match="Missing required API key"):
        engine_no_key.analyze(SAMPLE_PNG_BYTES)

    # 2. Resolved via DictCredentialResolver
    cred_resolver = DictCredentialResolver({"google": {"api_key": "secret-dict-key"}})
    provider_with_dict = GoogleAIProvider(credential_resolver=cred_resolver)
    assert provider_with_dict.is_available() is True
    engine_with_dict = provider_with_dict.get_vision_engine("gemini-2.0-flash")
    assert engine_with_dict.is_available() is True
    assert isinstance(engine_with_dict, GeminiVisionEngine)
    assert engine_with_dict.api_key == "secret-dict-key"

    # 3. Resolved via EnvCredentialResolver with GEMINI_API_KEY fallback
    os.environ["GEMINI_API_KEY"] = "gemini-env-secret-123"
    try:
        env_resolver = EnvCredentialResolver()
        assert env_resolver.has_credential("google") is True
        assert env_resolver.get_credential("google") == "gemini-env-secret-123"

        provider_env = GoogleAIProvider(credential_resolver=env_resolver)
        assert provider_env.is_available() is True
        engine_env = provider_env.get_vision_engine("gemini-2.0-flash")
        assert engine_env.is_available() is True
        assert isinstance(engine_env, GeminiVisionEngine)
        assert engine_env.api_key == "gemini-env-secret-123"
    finally:
        os.environ.pop("GEMINI_API_KEY", None)


def test_unavailable_provider_and_network_errors() -> None:
    """Verify transport errors (HTTP 503, HTTP 429, timeout, network failure) map to typed AI errors."""

    # Timeout
    def timeout_transport(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        raise AITimeoutError(f"Request timed out after {timeout}s")

    engine_timeout = GoogleAIProvider(api_key="key", transport=timeout_transport).get_vision_engine(
        "gemini-2.0-flash"
    )
    with pytest.raises(AITimeoutError, match="timed out"):
        engine_timeout.analyze(SAMPLE_PNG_BYTES)

    # 503 Service Unavailable
    def unavailable_transport(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        raise AIUnavailableError("Service temporarily unavailable (HTTP 503)")

    engine_unavail = GoogleAIProvider(
        api_key="key", transport=unavailable_transport
    ).get_vision_engine("gemini-2.0-flash")
    with pytest.raises(AIUnavailableError, match="HTTP 503"):
        engine_unavail.analyze(SAMPLE_PNG_BYTES)

    # 429 Quota Exceeded
    def quota_transport(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        raise AIProviderError("Rate limit exceeded (HTTP 429)")

    engine_quota = GoogleAIProvider(api_key="key", transport=quota_transport).get_vision_engine(
        "gemini-2.0-flash"
    )
    with pytest.raises(AIProviderError, match="HTTP 429"):
        engine_quota.analyze(SAMPLE_PNG_BYTES)


def test_unsupported_vision_capability_rejection() -> None:
    """Verify models without VISION capability cannot be instantiated as a VisionEngine."""
    catalog = ModelCatalog()
    catalog.register(
        ModelMetadata(
            provider="google",
            model_id="text-embedding-004",
            display_name="Text Embedding 004",
            capabilities={AICapability.TEXT_GENERATION},  # No VISION capability
        )
    )
    provider = GoogleAIProvider(api_key="test-key", catalog=catalog)

    # Attempting to get vision engine for non-vision model raises AIUnsupportedCapabilityError
    with pytest.raises(AIUnsupportedCapabilityError, match="does not support vision capability"):
        provider.get_vision_engine("text-embedding-004")

    # Name-based heuristic also blocks embedding models without catalog
    provider_no_cat = GoogleAIProvider(api_key="test-key")
    with pytest.raises(AIUnsupportedCapabilityError, match="does not support vision capability"):
        provider_no_cat.get_vision_engine("text-embedding-gecko")


def test_configuration_driven_provider_and_model_resolution() -> None:
    """Verify configuration-driven resolution through Phase 7A registry and AIServiceResolver."""
    registry = AIProviderRegistry()
    catalog = get_default_model_catalog()
    cred_resolver = DictCredentialResolver({"google": {"api_key": "res-secret-key"}})

    # Register concrete GoogleAIProvider
    provider = GoogleAIProvider(credential_resolver=cred_resolver, catalog=catalog)
    registry.register_provider(provider)

    # Create service config with vision assigned to google / gemini-2.0-flash
    config = AIServiceConfig(
        enabled=True,
        subsystems=AISubsystemsConfig(
            vision=SubsystemModelConfig(
                provider="google",
                model_id="gemini-2.0-flash",
                temperature=0.15,
                timeout_seconds=20.0,
            ),
            forecasting=SubsystemModelConfig(provider="mock", model_id="dummy"),
            strategy_suggestor=SubsystemModelConfig(provider="mock", model_id="dummy"),
            strategy_reviewer=SubsystemModelConfig(provider="mock", model_id="dummy"),
            ocr=SubsystemModelConfig(provider="mock", model_id="dummy"),
        ),
    )

    resolver = AIServiceResolver(
        config=config,
        registry=registry,
        catalog=catalog,
        credential_resolver=cred_resolver,
    )

    # Resolve vision engine
    engine = resolver.resolve_vision_engine(require_credentials=True)
    assert isinstance(engine, GeminiVisionEngine)
    assert engine.model_id == "gemini-2.0-flash"
    assert engine.api_key == "res-secret-key"
    assert engine.timeout_seconds == 20.0
    assert engine.temperature == 0.15
    assert engine.is_available() is True


def test_empty_input_and_invalid_spot_price_rejection() -> None:
    """Verify empty image bytes and negative spot price references are immediately rejected."""
    provider = GoogleAIProvider(api_key="test-key")
    engine = provider.get_vision_engine("gemini-2.0-flash")

    # Empty bytes
    with pytest.raises(AIMalformedOutputError, match="image_bytes cannot be empty"):
        engine.analyze(b"")

    # Negative spot price
    with pytest.raises(
        AIMalformedOutputError, match="Spot price reference must be strictly positive"
    ):
        engine.analyze(SAMPLE_PNG_BYTES, spot_price=-100.0)


def test_provenance_and_hash_integrity() -> None:
    """Verify ProvenanceRecord adheres strictly to ADR 012 invariants."""
    raw_response = _create_mock_gemini_response(
        trend="Neutral",
        support=[24000.0],
        resistance=[25000.0],
        patterns=[{"name": "Doji", "confidence": 0.70}],
        reasoning="Market is in an equilibrium consolidation zone.",
        is_empty=False,
        model_version="gemini-2.0-flash",
    )

    def transport(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        return raw_response

    provider = GoogleAIProvider(api_key="key", transport=transport)
    engine = provider.get_vision_engine("gemini-2.0-flash")
    result = engine.analyze(SAMPLE_PNG_BYTES)

    # Validate provenance record
    prov = result.provenance
    assert prov.source_type == AISourceType.MULTIMODAL_VISION
    assert prov.model_id == "gemini-2.0-flash"
    assert prov.model_version == "gemini-2.0-flash"
    assert prov.provider == "google"
    assert len(prov.input_hash) == 64
    assert prov.input_hash == hashlib.sha256(SAMPLE_PNG_BYTES).hexdigest().lower()
    assert result.source_image_hash == prov.input_hash
    assert prov.confidence == 0.70
    assert prov.is_deterministic is False

    # Immutability
    with pytest.raises(ValidationError):
        setattr(result, "trend", "Bullish")
    with pytest.raises(ValidationError):
        setattr(prov, "confidence", 0.99)


@pytest.mark.skipif(
    not os.environ.get("RUN_REAL_AI_TESTS")
    or not (os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")),
    reason="Explicit opt-in real network test; requires RUN_REAL_AI_TESTS=1 and GEMINI_API_KEY",
)
def test_real_gemini_vision_network_smoke() -> None:
    """Opt-in real provider smoke test executing one live inference call to Google Gemini.

    SKIPPED by default in standard CI and test suite runs. Only executed when explicitly
    configured with valid real credentials and RUN_REAL_AI_TESTS=1.
    """
    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    assert api_key is not None

    provider = GoogleAIProvider(api_key=api_key)
    assert provider.is_available() is True

    engine = provider.get_vision_engine("gemini-2.0-flash", timeout_seconds=30.0)
    assert engine.is_available() is True

    # Real call to Google Gemini endpoint with 1x1 test image
    result = engine.analyze(SAMPLE_PNG_BYTES, spot_price=24500.0)

    assert isinstance(result, VisionResult)
    assert result.trend in ("Bullish", "Bearish", "Neutral")
    assert len(result.reasoning) > 0
    assert result.source_image_hash == hashlib.sha256(SAMPLE_PNG_BYTES).hexdigest().lower()
    assert result.provenance.provider == "google"
    assert result.provenance.source_type == AISourceType.MULTIMODAL_VISION
