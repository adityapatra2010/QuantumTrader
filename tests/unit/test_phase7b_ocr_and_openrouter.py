"""Unit tests for Phase 7: OCR.Space Provider, OpenRouter Vision Provider, and Vision+OCR Pipeline.

Per Phase 7 requirements:
- Offline OCR tests: request construction, response normalization, malformed response,
  invalid/missing fields, auth failure, timeout, rate-limit, credential resolution, availability.
- Offline OpenRouter tests: provider registration, credential resolution, capability enforcement,
  structured response parsing, malformed response, image request construction, provider unavailable.
- Integration tests: OCR available -> Vision receives OCR context; OCR unavailable -> Vision operates;
  OCR failure does not crash Vision or fabricate OCR data; provenance integrity across both stages.
- Real-provider smoke tests: OCR.Space and OpenRouter vision (strictly opt-in via RUN_REAL_AI_TESTS=1).
"""

import hashlib
import json
import os
import urllib.parse
from datetime import UTC, datetime
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
    AIModelNotFoundError,
    AIProviderError,
    AITimeoutError,
    AIUnsupportedCapabilityError,
)
from aditrader.ai.models import (
    AISourceType,
    OCRResult,
    ProvenanceRecord,
    VisionResult,
)
from aditrader.ai.ocr.ocrspace import OCRSpaceEngine
from aditrader.ai.providers.ocrspace import OCRSpaceProvider
from aditrader.ai.providers.openrouter import OpenRouterProvider
from aditrader.ai.registry import AIProviderRegistry
from aditrader.ai.service import AIServiceResolver
from aditrader.ai.vision.openrouter import OpenRouterVisionEngine

# Minimal 1x1 transparent PNG bytes for testing
SAMPLE_PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00"
    b"\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


# ==============================================================================
# Helper Mock Factories
# ==============================================================================


def _create_mock_ocrspace_response(
    parsed_text: str = "NIFTY 24500 CE\nSUPPORT 24300",
    lines: list[dict[str, Any]] | None = None,
    exit_code: int = 1,
    is_errored: bool = False,
    error_message: str | list[str] | None = None,
) -> dict[str, Any]:
    """Helper creating raw OCR.Space REST API response structure."""
    if lines is None:
        lines = [
            {
                "Words": [
                    {"WordText": "NIFTY", "Left": 10.0, "Top": 20.0, "Height": 15.0, "Width": 40.0},
                    {"WordText": "24500", "Left": 55.0, "Top": 20.0, "Height": 15.0, "Width": 35.0},
                    {"WordText": "CE", "Left": 95.0, "Top": 20.0, "Height": 15.0, "Width": 20.0},
                ],
                "MaxHeight": 15.0,
                "MinTop": 20.0,
            },
            {
                "Words": [
                    {
                        "WordText": "SUPPORT",
                        "Left": 10.0,
                        "Top": 45.0,
                        "Height": 15.0,
                        "Width": 60.0,
                    },
                    {"WordText": "24300", "Left": 75.0, "Top": 45.0, "Height": 15.0, "Width": 40.0},
                ],
                "MaxHeight": 15.0,
                "MinTop": 45.0,
            },
        ]

    return {
        "ParsedResults": [
            {
                "TextOverlay": {
                    "Lines": lines,
                    "HasOverlay": True,
                    "Message": f"Total lines: {len(lines)}",
                },
                "TextOrientation": "0",
                "FileParseExitCode": exit_code,
                "ParsedText": parsed_text,
                "ErrorMessage": "",
                "ErrorDetails": "",
            }
        ],
        "OCRExitCode": exit_code,
        "IsErroredOnProcessing": is_errored,
        "ErrorMessage": error_message,
        "ErrorDetails": None,
        "ProcessingTimeInMilliseconds": "240",
    }


def _create_mock_openrouter_response(
    trend: str = "Bullish",
    support: list[float] | None = None,
    resistance: list[float] | None = None,
    patterns: list[dict[str, Any]] | None = None,
    reasoning: str = "Gemma 4 observed ascending triangle pattern.",
    is_empty: bool = False,
    model_name: str = "google/gemma-4-26b-a4b-it",
    wrap_code_fence: bool = True,
) -> dict[str, Any]:
    """Helper creating raw OpenRouter chat completion response structure."""
    if support is None:
        support = [24300.0, 24150.0]
    if resistance is None:
        resistance = [24600.0, 24750.0]
    if patterns is None:
        patterns = [
            {
                "name": "Ascending Triangle",
                "confidence": 0.88,
                "description": "Continuation pattern",
            }
        ]

    content_dict = {
        "trend": trend,
        "support": support,
        "resistance": resistance,
        "patterns": patterns,
        "reasoning": reasoning,
        "is_empty": is_empty,
    }
    raw_json = json.dumps(content_dict)
    text_content = f"```json\n{raw_json}\n```" if wrap_code_fence else raw_json

    return {
        "id": "gen-test-openrouter-123",
        "model": model_name,
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": text_content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 80, "total_tokens": 200},
    }


# ==============================================================================
# OCR.Space Offline Tests
# ==============================================================================


def test_ocrspace_request_construction_and_success_normalization() -> None:
    """Verify OCRSpaceEngine constructs valid urlencoded POST request and normalizes response."""
    captured_calls: list[tuple[str, dict[str, str], bytes, float]] = []

    def mock_transport(
        url: str, headers: dict[str, str], data: bytes, timeout: float
    ) -> dict[str, Any]:
        captured_calls.append((url, headers, data, timeout))
        return _create_mock_ocrspace_response()

    provider = OCRSpaceProvider(api_key="test-ocr-key", transport=mock_transport)
    engine = provider.get_ocr_engine("ocr-engine-2", timeout_seconds=12.0)

    assert engine.is_available() is True
    result = engine.extract_text(SAMPLE_PNG_BYTES)

    # 1. Verify single external call executed
    assert len(captured_calls) == 1
    url, headers, data, timeout = captured_calls[0]
    assert url == "https://api.ocr.space/parse/image"
    assert headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert headers["apikey"] == "test-ocr-key"
    assert timeout == 12.0

    # Parse and verify form parameters
    parsed_form = urllib.parse.parse_qs(data.decode("utf-8"))
    assert parsed_form["apikey"] == ["test-ocr-key"]
    assert parsed_form["isOverlayRequired"] == ["true"]
    assert parsed_form["OCREngine"] == ["2"]
    assert parsed_form["language"] == ["eng"]
    assert parsed_form["scale"] == ["true"]
    assert parsed_form["base64Image"][0].startswith("data:image/png;base64,")

    # 2. Verify normalized OCRResult
    assert result.is_empty is False
    assert "NIFTY 24500 CE" in result.text
    assert "SUPPORT 24300" in result.text
    assert len(result.regions) == 2
    assert result.regions[0].text == "NIFTY 24500 CE"
    assert result.regions[0].box is not None
    assert result.regions[0].box.left == 10.0
    assert result.regions[0].box.top == 20.0
    assert result.regions[0].box.width == 105.0  # (95+20) - 10
    assert result.regions[0].box.height == 15.0

    # 3. Verify provenance
    expected_hash = hashlib.sha256(SAMPLE_PNG_BYTES).hexdigest().lower()
    assert result.source_image_hash == expected_hash
    assert result.provenance.input_hash == expected_hash
    assert result.provenance.source_type == AISourceType.OCR_EXTRACTION
    assert result.provenance.provider == "ocrspace"
    assert result.provenance.model_id == "ocr-engine-2"
    assert result.provenance.is_deterministic is False


def test_ocrspace_empty_result_normalization() -> None:
    """Verify OCR returns empty text normalized to is_empty=True without error."""

    def mock_transport(
        url: str, headers: dict[str, str], data: bytes, timeout: float
    ) -> dict[str, Any]:
        return _create_mock_ocrspace_response(parsed_text="", lines=[])

    provider = OCRSpaceProvider(api_key="key", transport=mock_transport)
    engine = provider.get_ocr_engine("ocr-engine-2")
    result = engine.extract_text(SAMPLE_PNG_BYTES)

    assert result.is_empty is True
    assert result.text == ""
    assert result.regions == []
    assert result.provenance.source_type == AISourceType.OCR_EXTRACTION


def test_ocrspace_malformed_response_handling() -> None:
    """Verify malformed JSON or missing ParsedResults raises AIMalformedOutputError."""

    def make_engine(mock_resp: Any) -> OCRSpaceEngine:
        def transport(
            url: str, headers: dict[str, str], data: bytes, timeout: float
        ) -> dict[str, Any]:
            return mock_resp  # type: ignore[no-any-return]

        return OCRSpaceProvider(api_key="key", transport=transport).get_ocr_engine(  # type: ignore[return-value]
            "ocr-engine-2"
        )

    # Non-dict response
    with pytest.raises(AIMalformedOutputError, match="Expected dictionary"):
        make_engine("invalid-string").extract_text(SAMPLE_PNG_BYTES)

    # Missing ParsedResults
    with pytest.raises(AIMalformedOutputError, match="missing 'ParsedResults'"):
        make_engine({"OCRExitCode": 1}).extract_text(SAMPLE_PNG_BYTES)


def test_ocrspace_authentication_failure() -> None:
    """Verify OCR.Space authentication error messages raise AICredentialError."""

    def mock_transport(
        url: str, headers: dict[str, str], data: bytes, timeout: float
    ) -> dict[str, Any]:
        return {
            "OCRExitCode": 99,
            "IsErroredOnProcessing": True,
            "ErrorMessage": ["API key is invalid", "Please register for a valid key"],
            "ParsedResults": [],
        }

    provider = OCRSpaceProvider(api_key="bad-key", transport=mock_transport)
    engine = provider.get_ocr_engine("ocr-engine-2")

    with pytest.raises(AICredentialError, match="OCR.Space authentication error"):
        engine.extract_text(SAMPLE_PNG_BYTES)


def test_ocrspace_timeout_and_rate_limit_handling() -> None:
    """Verify OCR.Space timeouts and rate limits map to typed errors."""

    # Timeout
    def timeout_transport(
        url: str, headers: dict[str, str], data: bytes, timeout: float
    ) -> dict[str, Any]:
        raise AITimeoutError(f"OCR request timed out after {timeout}s")

    engine_timeout = OCRSpaceProvider(api_key="key", transport=timeout_transport).get_ocr_engine(
        "ocr-engine-2"
    )
    with pytest.raises(AITimeoutError, match="timed out"):
        engine_timeout.extract_text(SAMPLE_PNG_BYTES)

    # Rate limit (HTTP 429)
    def rate_limit_transport(
        url: str, headers: dict[str, str], data: bytes, timeout: float
    ) -> dict[str, Any]:
        raise AIProviderError("Rate limit exceeded (HTTP 429)")

    engine_rate = OCRSpaceProvider(api_key="key", transport=rate_limit_transport).get_ocr_engine(
        "ocr-engine-2"
    )
    with pytest.raises(AIProviderError, match="Rate limit exceeded"):
        engine_rate.extract_text(SAMPLE_PNG_BYTES)

    # Processing error payload
    def error_payload_transport(
        url: str, headers: dict[str, str], data: bytes, timeout: float
    ) -> dict[str, Any]:
        return {
            "OCRExitCode": 3,
            "IsErroredOnProcessing": True,
            "ErrorMessage": "Engine execution failure",
            "ParsedResults": [],
        }

    engine_err = OCRSpaceProvider(api_key="key", transport=error_payload_transport).get_ocr_engine(
        "ocr-engine-2"
    )
    with pytest.raises(AIProviderError, match="OCR.Space processing error"):
        engine_err.extract_text(SAMPLE_PNG_BYTES)


def test_ocrspace_credential_resolution() -> None:
    """Verify OCR.Space credential resolution via DictCredentialResolver and EnvCredentialResolver."""
    # 1. Unconfigured -> is_available() is False
    provider_none = OCRSpaceProvider()
    assert provider_none.is_available() is False
    engine_none = provider_none.get_ocr_engine("ocr-engine-2")
    assert engine_none.is_available() is False
    with pytest.raises(AICredentialError, match="Missing required API key"):
        engine_none.extract_text(SAMPLE_PNG_BYTES)

    # 2. DictCredentialResolver
    dict_resolver = DictCredentialResolver({"ocrspace": {"api_key": "dict-ocr-secret"}})
    provider_dict = OCRSpaceProvider(credential_resolver=dict_resolver)
    assert provider_dict.is_available() is True
    engine_dict = provider_dict.get_ocr_engine("ocr-engine-2")
    assert engine_dict.is_available() is True
    assert isinstance(engine_dict, OCRSpaceEngine)
    assert engine_dict.api_key == "dict-ocr-secret"

    # 3. EnvCredentialResolver with OCRSPACE_API_KEY
    os.environ["OCRSPACE_API_KEY"] = "env-ocr-key-123"
    try:
        env_resolver = EnvCredentialResolver()
        assert env_resolver.has_credential("ocrspace") is True
        assert env_resolver.get_credential("ocrspace") == "env-ocr-key-123"

        provider_env = OCRSpaceProvider(credential_resolver=env_resolver)
        assert provider_env.is_available() is True
        engine_env = provider_env.get_ocr_engine("ocr-engine-2")
        assert isinstance(engine_env, OCRSpaceEngine)
        assert engine_env.api_key == "env-ocr-key-123"
    finally:
        os.environ.pop("OCRSPACE_API_KEY", None)

    # 4. EnvCredentialResolver with OCR_SPACE_API_KEY fallback
    os.environ["OCR_SPACE_API_KEY"] = "env-ocr-fallback-456"
    try:
        env_resolver2 = EnvCredentialResolver()
        assert env_resolver2.has_credential("ocrspace") is True
        assert env_resolver2.get_credential("ocrspace") == "env-ocr-fallback-456"
    finally:
        os.environ.pop("OCR_SPACE_API_KEY", None)


# ==============================================================================
# OpenRouter Offline Tests
# ==============================================================================


def test_openrouter_provider_registration_and_catalog() -> None:
    """Verify OpenRouterProvider registers in AIProviderRegistry and catalog includes Gemma 4 26B."""
    registry = AIProviderRegistry()
    provider = OpenRouterProvider(api_key="openrouter-test-key")
    registry.register_provider(provider)

    assert registry.has_provider("openrouter") is True
    assert registry.get_provider("openrouter").provider_id == "openrouter"

    # Verify default model catalog has Gemma 4 26B A4B
    catalog = get_default_model_catalog()
    assert catalog.has_model("openrouter", "google/gemma-4-26b-a4b-it") is True
    meta = catalog.get("openrouter", "google/gemma-4-26b-a4b-it")
    assert meta.has_capability(AICapability.VISION) is True
    assert meta.has_capability(AICapability.STRUCTURED_OUTPUT) is True
    assert meta.context_limits is not None
    assert meta.context_limits.max_context_tokens == 262144

    # Free tier model
    assert catalog.has_model("openrouter", "google/gemma-4-26b-a4b-it:free") is True
    meta_free = catalog.get("openrouter", "google/gemma-4-26b-a4b-it:free")
    assert meta_free.has_capability(AICapability.VISION) is True


def test_openrouter_credential_resolution() -> None:
    """Verify OpenRouter credential resolution via explicit key, dict resolver, and env var."""
    # 1. Missing credentials
    provider_none = OpenRouterProvider()
    assert provider_none.is_available() is False
    engine_none = provider_none.get_vision_engine("google/gemma-4-26b-a4b-it")
    assert engine_none.is_available() is False
    with pytest.raises(AICredentialError, match="Missing required API key"):
        engine_none.analyze(SAMPLE_PNG_BYTES)

    # 2. OPENROUTER_API_KEY in environment
    os.environ["OPENROUTER_API_KEY"] = "sk-or-test-env-key"
    try:
        env_resolver = EnvCredentialResolver()
        assert env_resolver.has_credential("openrouter") is True
        assert env_resolver.get_credential("openrouter") == "sk-or-test-env-key"

        provider_env = OpenRouterProvider(credential_resolver=env_resolver)
        assert provider_env.is_available() is True
        engine_env = provider_env.get_vision_engine("google/gemma-4-26b-a4b-it")
        assert isinstance(engine_env, OpenRouterVisionEngine)
        assert engine_env.api_key == "sk-or-test-env-key"
    finally:
        os.environ.pop("OPENROUTER_API_KEY", None)


def test_openrouter_capability_enforcement() -> None:
    """Verify models lacking VISION capability raise AIUnsupportedCapabilityError."""
    catalog = ModelCatalog()
    catalog.register(
        ModelMetadata(
            provider="openrouter",
            model_id="anthropic/claude-text-only",
            display_name="Text Only Model",
            capabilities={AICapability.TEXT_GENERATION},
        )
    )
    provider = OpenRouterProvider(api_key="key", catalog=catalog)

    with pytest.raises(AIUnsupportedCapabilityError, match="does not support vision capability"):
        provider.get_vision_engine("anthropic/claude-text-only")

    # Name-based heuristic fallback
    provider_no_cat = OpenRouterProvider(api_key="key")
    with pytest.raises(AIUnsupportedCapabilityError, match="does not support vision capability"):
        provider_no_cat.get_vision_engine("text-embedding-3-small")


def test_openrouter_image_request_construction_and_structured_parsing() -> None:
    """Verify OpenRouterVisionEngine constructs valid OpenAI-compatible image payload and parses VisionResult."""
    captured_calls: list[tuple[str, dict[str, str], dict[str, Any], float]] = []

    def mock_transport(
        url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        captured_calls.append((url, headers, payload, timeout))
        return _create_mock_openrouter_response(
            trend="Bullish",
            support=[24250.0, 24100.0],
            resistance=[24650.0, 24800.0],
            patterns=[
                {
                    "name": "Ascending Triangle",
                    "confidence": 0.85,
                    "description": "Breakout pattern",
                }
            ],
            reasoning="OpenRouter Gemma 4 model observed clean higher lows into horizontal resistance.",
            is_empty=False,
            model_name="google/gemma-4-26b-a4b-it",
            wrap_code_fence=True,
        )

    provider = OpenRouterProvider(api_key="sk-openrouter-key", transport=mock_transport)
    engine = provider.get_vision_engine(
        "google/gemma-4-26b-a4b-it", timeout_seconds=25.0, temperature=0.2
    )

    result = engine.analyze(SAMPLE_PNG_BYTES, spot_price=24350.0)

    # 1. Verify single external call and payload format
    assert len(captured_calls) == 1
    url, headers, payload, timeout = captured_calls[0]
    assert url == "https://openrouter.ai/api/v1/chat/completions"
    assert headers["Authorization"] == "Bearer sk-openrouter-key"
    assert headers["HTTP-Referer"] == "https://github.com/aditya/AdiTrader"
    assert headers["X-Title"] == "AdiTrader QuantumValidator"
    assert timeout == 25.0

    assert payload["model"] == "google/gemma-4-26b-a4b-it"
    assert payload["temperature"] == 0.2
    assert payload["response_format"] == {"type": "json_object"}

    messages = payload["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
    content_parts = messages[0]["content"]
    assert content_parts[0]["type"] == "image_url"
    assert content_parts[0]["image_url"]["url"].startswith("data:image/png;base64,")
    assert content_parts[1]["type"] == "text"
    assert "Prevailing underlying spot price is 24350.0" in content_parts[1]["text"]

    # 2. Verify VisionResult domain fields
    assert result.trend == "Bullish"
    assert result.support == [24250.0, 24100.0]
    assert result.resistance == [24650.0, 24800.0]
    assert len(result.patterns) == 1
    assert result.patterns[0].name == "Ascending Triangle"
    assert result.patterns[0].confidence == 0.85
    assert (
        result.reasoning
        == "OpenRouter Gemma 4 model observed clean higher lows into horizontal resistance."
    )
    assert result.is_empty is False

    # 3. Verify provenance
    expected_hash = hashlib.sha256(SAMPLE_PNG_BYTES).hexdigest().lower()
    assert result.source_image_hash == expected_hash
    assert result.provenance.input_hash == expected_hash
    assert result.provenance.source_type == AISourceType.MULTIMODAL_VISION
    assert result.provenance.provider == "openrouter"
    assert result.provenance.model_id == "google/gemma-4-26b-a4b-it"
    assert result.provenance.confidence == 0.85
    assert result.provenance.is_deterministic is False


def test_openrouter_malformed_response_and_errors() -> None:
    """Verify OpenRouter error payloads and malformed outputs raise appropriate typed errors."""

    def make_engine(mock_resp: dict[str, Any]) -> OpenRouterVisionEngine:
        def transport(
            url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float
        ) -> dict[str, Any]:
            return mock_resp

        provider = OpenRouterProvider(api_key="key", transport=transport)
        return provider.get_vision_engine("google/gemma-4-26b-a4b-it")  # type: ignore[return-value]

    # 1. Authentication error in JSON payload
    engine_auth = make_engine({"error": {"message": "Invalid API Key", "code": 401}})
    with pytest.raises(AICredentialError, match="OpenRouter authentication error"):
        engine_auth.analyze(SAMPLE_PNG_BYTES)

    # 2. Model not found
    engine_404 = make_engine({"error": {"message": "Model not found", "code": 404}})
    with pytest.raises(AIModelNotFoundError, match="OpenRouter model error"):
        engine_404.analyze(SAMPLE_PNG_BYTES)

    # 3. Rate limit
    engine_429 = make_engine({"error": {"message": "User rate limit exceeded", "code": 429}})
    with pytest.raises(AIProviderError, match="OpenRouter rate limit error"):
        engine_429.analyze(SAMPLE_PNG_BYTES)

    # 4. Empty choices
    engine_empty = make_engine({"choices": []})
    with pytest.raises(AIMalformedOutputError, match="contains no choices"):
        engine_empty.analyze(SAMPLE_PNG_BYTES)

    # 5. Non-JSON message content
    engine_bad_json = make_engine(
        {"choices": [{"message": {"role": "assistant", "content": "I cannot parse chart."}}]}
    )
    with pytest.raises(AIMalformedOutputError, match="Failed to parse OpenRouter model output"):
        engine_bad_json.analyze(SAMPLE_PNG_BYTES)

    # 6. Negative price levels
    bad_price_json = json.dumps(
        {
            "trend": "Bullish",
            "support": [-24000.0],
            "resistance": [25000.0],
            "reasoning": "Valid reasoning",
        }
    )
    engine_bad_price = make_engine(
        {"choices": [{"message": {"role": "assistant", "content": bad_price_json}}]}
    )
    with pytest.raises(AIMalformedOutputError, match="Support level must be strictly positive"):
        engine_bad_price.analyze(SAMPLE_PNG_BYTES)


# ==============================================================================
# Vision + OCR Pipeline Integration Tests
# ==============================================================================


def test_vision_pipeline_with_ocr_available() -> None:
    """Verify Vision engine passes OCR text to model prompt and populates ocr_text in VisionResult."""
    captured_vision_calls: list[dict[str, Any]] = []

    # Mock OCR transport returning structured OCR text
    def ocr_transport(
        url: str, headers: dict[str, str], data: bytes, timeout: float
    ) -> dict[str, Any]:
        return _create_mock_ocrspace_response(parsed_text="NIFTY 24500 CE\nSUPPORT 24200")

    ocr_provider = OCRSpaceProvider(api_key="ocr-key", transport=ocr_transport)
    ocr_engine = ocr_provider.get_ocr_engine("ocr-engine-2")

    # Mock OpenRouter transport inspecting prompt
    def vision_transport(
        url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        captured_vision_calls.append(payload)
        return _create_mock_openrouter_response(
            trend="Bullish",
            support=[24200.0],
            resistance=[24600.0],
            reasoning="Observed support level coinciding with OCR-detected strike 24200.",
        )

    vision_provider = OpenRouterProvider(api_key="openrouter-key", transport=vision_transport)
    vision_engine = vision_provider.get_vision_engine(
        "google/gemma-4-26b-a4b-it", ocr_engine=ocr_engine
    )

    result = vision_engine.analyze(SAMPLE_PNG_BYTES)

    # 1. Verify Vision prompt received OCR context
    assert len(captured_vision_calls) == 1
    prompt_text = captured_vision_calls[0]["messages"][0]["content"][1]["text"]
    assert "Auxiliary OCR Context:" in prompt_text
    assert "STATUS: AVAILABLE" in prompt_text
    assert "NIFTY 24500 CE" in prompt_text
    assert "SUPPORT 24200" in prompt_text
    assert "Treat the above OCR text as auxiliary, unverified context" in prompt_text

    # 2. Verify VisionResult captures ocr_text
    assert result.ocr_text == "NIFTY 24500 CE\nSUPPORT 24200"
    assert result.provenance.source_type == AISourceType.MULTIMODAL_VISION
    assert result.provenance.provider == "openrouter"


def test_vision_pipeline_with_ocr_unavailable() -> None:
    """Verify Vision engine operates cleanly when OCR is unavailable or unconfigured."""
    captured_prompts: list[str] = []

    def mock_gemini_transport(url: str, payload: dict[str, Any], timeout: float) -> dict[str, Any]:
        captured_prompts.append(payload["contents"][0]["parts"][1]["text"])
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "text": json.dumps(
                                    {
                                        "trend": "Neutral",
                                        "support": [24000.0],
                                        "resistance": [25000.0],
                                        "patterns": [],
                                        "reasoning": "Pure visual chart reading without OCR.",
                                        "is_empty": False,
                                    }
                                )
                            }
                        ],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                }
            ],
            "modelVersion": "gemini-2.0-flash-001",
        }

    # Vision engine with NO ocr_engine attached
    from aditrader.ai.providers.google import GoogleAIProvider

    google_provider = GoogleAIProvider(api_key="key", transport=mock_gemini_transport)
    engine = google_provider.get_vision_engine("gemini-2.0-flash")

    result = engine.analyze(SAMPLE_PNG_BYTES)

    # Verify prompt clearly states OCR is NOT AVAILABLE
    assert len(captured_prompts) == 1
    assert "STATUS: NOT AVAILABLE" in captured_prompts[0]
    assert result.ocr_text is None
    assert result.trend == "Neutral"
    assert result.reasoning == "Pure visual chart reading without OCR."


def test_vision_pipeline_ocr_failure_resilience() -> None:
    """Verify that OCR failure does not fail Vision analysis, and does not fabricate OCR data."""

    # Faulty OCR engine raising AIProviderError
    def failing_ocr_transport(
        url: str, headers: dict[str, str], data: bytes, timeout: float
    ) -> dict[str, Any]:
        raise AIProviderError("OCR.Space 500 Internal Server Error")

    faulty_ocr_provider = OCRSpaceProvider(api_key="ocr-key", transport=failing_ocr_transport)
    faulty_ocr_engine = faulty_ocr_provider.get_ocr_engine("ocr-engine-2")

    captured_prompts: list[str] = []

    def vision_transport(
        url: str, headers: dict[str, str], payload: dict[str, Any], timeout: float
    ) -> dict[str, Any]:
        captured_prompts.append(payload["messages"][0]["content"][1]["text"])
        return _create_mock_openrouter_response(
            trend="Bearish",
            support=[23800.0],
            resistance=[24400.0],
            reasoning="Visual analysis proceeded despite OCR outage.",
        )

    openrouter_provider = OpenRouterProvider(api_key="or-key", transport=vision_transport)
    vision_engine = openrouter_provider.get_vision_engine(
        "google/gemma-4-26b-a4b-it", ocr_engine=faulty_ocr_engine
    )

    # Analysis must succeed without crashing!
    result = vision_engine.analyze(SAMPLE_PNG_BYTES)

    assert result.trend == "Bearish"
    assert result.ocr_text is None  # Never fabricate OCR data
    assert "STATUS: NOT AVAILABLE" in captured_prompts[0]


def test_end_to_end_service_resolver_configuration() -> None:
    """Verify AIServiceResolver can independently configure Vision and OCR providers."""
    registry = AIProviderRegistry()
    catalog = get_default_model_catalog()
    cred_resolver = DictCredentialResolver(
        {
            "openrouter": {"api_key": "secret-or-key"},
            "ocrspace": {"api_key": "secret-ocr-key"},
        }
    )

    or_provider = OpenRouterProvider(credential_resolver=cred_resolver, catalog=catalog)
    ocr_provider = OCRSpaceProvider(credential_resolver=cred_resolver, catalog=catalog)

    registry.register_provider(or_provider)
    registry.register_provider(ocr_provider)

    # User configuration: Vision -> OpenRouter (Gemma 4), OCR -> OCR.Space (ocr-engine-2)
    config = AIServiceConfig(
        enabled=True,
        subsystems=AISubsystemsConfig(
            vision=SubsystemModelConfig(
                provider="openrouter",
                model_id="google/gemma-4-26b-a4b-it",
                temperature=0.1,
            ),
            ocr=SubsystemModelConfig(
                provider="ocrspace",
                model_id="ocr-engine-2",
                timeout_seconds=15.0,
            ),
            forecasting=SubsystemModelConfig(provider="mock", model_id="dummy"),
            strategy_suggestor=SubsystemModelConfig(provider="mock", model_id="dummy"),
            strategy_reviewer=SubsystemModelConfig(provider="mock", model_id="dummy"),
        ),
    )

    resolver = AIServiceResolver(
        config=config,
        registry=registry,
        catalog=catalog,
        credential_resolver=cred_resolver,
    )

    # 1. Resolve OCR Engine independently
    resolved_ocr = resolver.resolve_ocr_engine()
    assert isinstance(resolved_ocr, OCRSpaceEngine)
    assert resolved_ocr.model_id == "ocr-engine-2"
    assert resolved_ocr.api_key == "secret-ocr-key"
    assert resolved_ocr.timeout_seconds == 15.0

    # 2. Resolve Vision Engine with integrated OCR
    resolved_vision = resolver.resolve_vision_engine(with_ocr=True)
    assert isinstance(resolved_vision, OpenRouterVisionEngine)
    assert resolved_vision.model_id == "google/gemma-4-26b-a4b-it"
    assert resolved_vision.api_key == "secret-or-key"
    assert resolved_vision.ocr_engine is not None
    assert isinstance(resolved_vision.ocr_engine, OCRSpaceEngine)


def test_provenance_integrity_across_ocr_and_vision() -> None:
    """Verify ProvenanceRecord preserves ADR 012 invariants and input hash mirrors image."""
    img_hash = hashlib.sha256(SAMPLE_PNG_BYTES).hexdigest().lower()

    # Valid OCRResult
    ocr_prov = ProvenanceRecord(
        source_type=AISourceType.OCR_EXTRACTION,
        model_id="ocr-engine-2",
        model_version="ocrspace",
        provider="ocrspace",
        generated_at=datetime.now(UTC),
        input_hash=img_hash,
        seed=None,
        is_deterministic=False,
    )
    ocr_res = OCRResult(
        text="TEST TEXT",
        source_image_hash=img_hash,
        is_empty=False,
        provenance=ocr_prov,
    )
    assert ocr_res.source_image_hash == ocr_prov.input_hash

    # Hash mismatch between source_image_hash and provenance.input_hash is rejected
    with pytest.raises(ValidationError):
        OCRResult(
            text="TEST TEXT",
            source_image_hash="0" * 64,
            is_empty=False,
            provenance=ocr_prov,
        )


# ==============================================================================
# Real Provider Opt-in Smoke Tests
# ==============================================================================


@pytest.mark.skipif(
    not os.environ.get("RUN_REAL_AI_TESTS")
    or not (os.environ.get("OCRSPACE_API_KEY") or os.environ.get("OCR_SPACE_API_KEY")),
    reason="Explicit opt-in real network test; requires RUN_REAL_AI_TESTS=1 and OCRSPACE_API_KEY",
)
def test_real_ocrspace_network_smoke() -> None:
    """Opt-in real provider smoke test executing one live OCR request to OCR.Space.

    SKIPPED by default in standard CI and test suite runs. Only executed when explicitly
    configured with valid real credentials and RUN_REAL_AI_TESTS=1.
    """
    api_key = os.environ.get("OCRSPACE_API_KEY") or os.environ.get("OCR_SPACE_API_KEY")
    assert api_key is not None

    provider = OCRSpaceProvider(api_key=api_key)
    assert provider.is_available() is True

    engine = provider.get_ocr_engine("ocr-engine-2", timeout_seconds=30.0)
    assert engine.is_available() is True

    # Real call to OCR.Space with 1x1 test image
    result = engine.extract_text(SAMPLE_PNG_BYTES)

    assert isinstance(result, OCRResult)
    assert result.source_image_hash == hashlib.sha256(SAMPLE_PNG_BYTES).hexdigest().lower()
    assert result.provenance.provider == "ocrspace"
    assert result.provenance.source_type == AISourceType.OCR_EXTRACTION


@pytest.mark.skipif(
    not os.environ.get("RUN_REAL_AI_TESTS") or not os.environ.get("OPENROUTER_API_KEY"),
    reason="Explicit opt-in real network test; requires RUN_REAL_AI_TESTS=1 and OPENROUTER_API_KEY",
)
def test_real_openrouter_vision_network_smoke() -> None:
    """Opt-in real provider smoke test executing one live multimodal inference call to OpenRouter.

    SKIPPED by default in standard CI and test suite runs. Only executed when explicitly
    configured with valid real credentials and RUN_REAL_AI_TESTS=1.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    assert api_key is not None

    provider = OpenRouterProvider(api_key=api_key)
    assert provider.is_available() is True

    # Use Gemma 4 26B model
    engine = provider.get_vision_engine("google/gemma-4-26b-a4b-it", timeout_seconds=30.0)
    assert engine.is_available() is True

    # Real call to OpenRouter with 1x1 test image
    result = engine.analyze(SAMPLE_PNG_BYTES, spot_price=24500.0)

    assert isinstance(result, VisionResult)
    assert result.trend in ("Bullish", "Bearish", "Neutral")
    assert len(result.reasoning) > 0
    assert result.source_image_hash == hashlib.sha256(SAMPLE_PNG_BYTES).hexdigest().lower()
    assert result.provenance.provider == "openrouter"
    assert result.provenance.source_type == AISourceType.MULTIMODAL_VISION
