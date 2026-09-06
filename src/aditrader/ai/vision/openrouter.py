"""OpenRouter Multimodal Vision Engine implementation.

Per Phase 7, ADR 005, and ADR 012:
- Analyzes market chart screenshots to extract structural market features using OpenRouter API.
- Compatible with OpenAI chat completions format (image_url base64).
- Strictly non-authoritative advisory output carrying ProvenanceRecord.
- Zero live execution, order routing, or dynamic code execution.
- Bounded execution: single external call, zero automatic retry loops.
- All provider and transport errors mapped into typed AIError hierarchy.
"""

import base64
import contextlib
import hashlib
import json
import urllib.error
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import ValidationError

from aditrader.ai.base import OCREngine, VisionEngine
from aditrader.ai.errors import (
    AICredentialError,
    AIMalformedOutputError,
    AIModelNotFoundError,
    AIProviderError,
    AITimeoutError,
    AIUnavailableError,
)
from aditrader.ai.models import (
    AISourceType,
    OCRResult,
    PatternObservation,
    ProvenanceRecord,
    VisionResult,
)
from aditrader.ai.registry import AIProvider

# OpenRouter Transport signature: (url, headers, payload, timeout_seconds) -> response_dict
OpenRouterTransportCallable = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


def default_openrouter_http_transport(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    """Default HTTP transport calling OpenRouter completions API via standard library urllib."""
    req_data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=req_data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            res_body = response.read().decode("utf-8")
            parsed = json.loads(res_body)
            if not isinstance(parsed, dict):
                raise AIMalformedOutputError(
                    f"Expected JSON object from OpenRouter response, got {type(parsed).__name__}"
                )
            return parsed
    except urllib.error.HTTPError as e:
        err_body = ""
        with contextlib.suppress(Exception):
            err_body = e.read().decode("utf-8")
        if e.code in (401, 403):
            raise AICredentialError(
                f"OpenRouter API authentication failed (HTTP {e.code}): {err_body}"
            ) from e
        if e.code == 404:
            raise AIModelNotFoundError(f"OpenRouter model not found (HTTP 404): {err_body}") from e
        if e.code == 429:
            raise AIProviderError(
                f"OpenRouter API rate limit or credit quota exceeded (HTTP 429): {err_body}"
            ) from e
        if e.code >= 500:
            raise AIUnavailableError(
                f"OpenRouter API service temporarily unavailable (HTTP {e.code}): {err_body}"
            ) from e
        raise AIProviderError(f"OpenRouter API HTTP error (HTTP {e.code}): {err_body}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        if isinstance(e, TimeoutError) or "timed out" in str(e).lower():
            raise AITimeoutError(
                f"OpenRouter API request timed out after {timeout_seconds:.1f}s"
            ) from e
        raise AIUnavailableError(f"OpenRouter API connection error: {e}") from e
    except json.JSONDecodeError as e:
        raise AIMalformedOutputError(
            f"Failed to decode OpenRouter HTTP response as JSON: {e}"
        ) from e


class OpenRouterVisionEngine(VisionEngine):
    """Concrete VisionEngine implementation using OpenRouter multimodal models."""

    def __init__(
        self,
        provider: AIProvider,
        model_id: str,
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        temperature: float | None = None,
        transport: OpenRouterTransportCallable | None = None,
        model_version: str | None = None,
        ocr_engine: OCREngine | None = None,
        site_url: str = "https://github.com/aditya/AdiTrader",
        site_name: str = "AdiTrader QuantumValidator",
    ) -> None:
        self.provider = provider
        self.model_id = model_id
        self.api_key = api_key.strip() if api_key else None
        self.timeout_seconds = max(0.1, timeout_seconds)
        self.temperature = temperature
        self._transport = transport
        self.model_version = model_version
        self.ocr_engine = ocr_engine
        self.site_url = site_url
        self.site_name = site_name

    def is_available(self) -> bool:
        """Return True if API credentials are configured and provider is available.

        Must never raise network or runtime exceptions.
        """
        try:
            return bool(self.api_key and self.api_key.strip()) and self.provider.is_available()
        except Exception:
            return False

    def analyze(
        self,
        image_bytes: bytes,
        spot_price: float | None = None,
        ocr_result: OCRResult | None = None,
    ) -> VisionResult:
        """Extract observable support/resistance and chart patterns via OpenRouter multimodal model.

        Args:
            image_bytes: Raw bytes of uploaded chart image.
            spot_price: Optional prevailing underlying spot price for coordinate envelope context.
            ocr_result: Optional OCR extraction result from a prior OCR pipeline stage.

        Returns:
            Validated VisionResult containing detected levels, patterns, reasoning, and provenance.

        Raises:
            AIMalformedOutputError: If image_bytes is empty or model output violates bounds.
            AICredentialError: If API key is missing or unauthorized.
            AITimeoutError: If API execution exceeds deadline.
            AIUnavailableError: If provider or API endpoint is unreachable.
            AIProviderError: If provider encounters rate limits or upstream errors.
        """
        if not image_bytes or len(image_bytes) == 0:
            raise AIMalformedOutputError("Input image_bytes cannot be empty")

        if spot_price is not None and spot_price <= 0.0:
            raise AIMalformedOutputError(
                f"Spot price reference must be strictly positive, got {spot_price}"
            )

        if not self.api_key or not self.api_key.strip():
            raise AICredentialError(
                f"Missing required API key for provider '{self.provider.provider_id}' model '{self.model_id}'"
            )

        # Optional OCR execution if not already provided
        if ocr_result is None and self.ocr_engine is not None and self.ocr_engine.is_available():
            try:
                ocr_result = self.ocr_engine.extract_text(image_bytes)
            except Exception:
                ocr_result = None

        ocr_text = (
            ocr_result.text.strip()
            if (ocr_result and not ocr_result.is_empty and ocr_result.text.strip())
            else None
        )

        source_image_hash = hashlib.sha256(image_bytes).hexdigest().lower()
        mime_type = self._detect_mime_type(image_bytes)
        b64_image = base64.b64encode(image_bytes).decode("ascii")
        prompt = self._build_prompt(spot_price=spot_price, ocr_result=ocr_result)

        data_url = f"data:{mime_type};base64,{b64_image}"

        payload: dict[str, Any] = {
            "model": self.model_id,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": data_url,
                            },
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                }
            ],
            "response_format": {"type": "json_object"},
        }
        if self.temperature is not None:
            payload["temperature"] = self.temperature

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self.site_url,
            "X-Title": self.site_name,
        }
        url = "https://openrouter.ai/api/v1/chat/completions"

        transport_fn = self._transport or default_openrouter_http_transport
        # Single bounded call: no retry loop
        response_data = transport_fn(url, headers, payload, self.timeout_seconds)

        return self._parse_and_validate_response(
            response_data=response_data,
            source_image_hash=source_image_hash,
            spot_price=spot_price,
            ocr_text=ocr_text,
        )

    def _parse_and_validate_response(
        self,
        response_data: dict[str, Any],
        source_image_hash: str,
        spot_price: float | None = None,
        ocr_text: str | None = None,
    ) -> VisionResult:
        """Parse OpenRouter chat completion response, validate domain rules, and build VisionResult."""
        if not isinstance(response_data, dict):
            raise AIMalformedOutputError(
                f"Expected dictionary from OpenRouter response, got {type(response_data).__name__}"
            )

        if "error" in response_data:
            err_obj = response_data["error"]
            err_msg = (
                err_obj.get("message", "OpenRouter error")
                if isinstance(err_obj, dict)
                else str(err_obj)
            )
            code = err_obj.get("code") if isinstance(err_obj, dict) else None
            if code in (401, 403) or "auth" in err_msg.lower():
                raise AICredentialError(f"OpenRouter authentication error: {err_msg}")
            if code == 404 or "not found" in err_msg.lower():
                raise AIModelNotFoundError(f"OpenRouter model error: {err_msg}")
            if code == 429 or "rate" in err_msg.lower() or "quota" in err_msg.lower():
                raise AIProviderError(f"OpenRouter rate limit error: {err_msg}")
            raise AIProviderError(f"OpenRouter provider error: {err_msg}")

        choices = response_data.get("choices")
        if not choices or not isinstance(choices, list) or len(choices) == 0:
            raise AIMalformedOutputError("OpenRouter response contains no choices")

        choice = choices[0]
        if not isinstance(choice, dict):
            raise AIMalformedOutputError("Choice entry is not a dictionary")

        message = choice.get("message")
        if not message or not isinstance(message, dict):
            raise AIMalformedOutputError("Choice missing message dictionary")

        raw_content = message.get("content")
        if not isinstance(raw_content, str) or not raw_content.strip():
            raise AIMalformedOutputError("OpenRouter message content is empty")

        cleaned_text = self._strip_code_fences(raw_content)

        try:
            parsed_json = json.loads(cleaned_text)
        except json.JSONDecodeError as exc:
            raise AIMalformedOutputError(
                f"Failed to parse OpenRouter model output as JSON: {exc}"
            ) from exc

        if not isinstance(parsed_json, dict):
            raise AIMalformedOutputError(
                f"Expected JSON object in model output, got {type(parsed_json).__name__}"
            )

        # 1. Trend validation
        trend_raw = parsed_json.get("trend")
        if not isinstance(trend_raw, str):
            raise AIMalformedOutputError(f"Missing or invalid 'trend' in model output: {trend_raw}")
        trend_norm = trend_raw.strip().capitalize()
        if trend_norm not in ("Bullish", "Bearish", "Neutral"):
            raise AIMalformedOutputError(
                f"Invalid trend '{trend_raw}'. Expected 'Bullish', 'Bearish', or 'Neutral'"
            )
        trend: Literal["Bullish", "Bearish", "Neutral"] = trend_norm  # type: ignore[assignment]

        # 2. Reasoning validation (mandatory non-empty)
        reasoning = parsed_json.get("reasoning")
        if not isinstance(reasoning, str) or not reasoning.strip():
            raise AIMalformedOutputError("Model output contains empty reasoning")
        reasoning = reasoning.strip()

        # 3. Support levels
        support_raw = parsed_json.get("support", [])
        if not isinstance(support_raw, list):
            raise AIMalformedOutputError(
                f"Expected list for 'support', got {type(support_raw).__name__}"
            )
        validated_support: list[float] = []
        for s in support_raw:
            try:
                s_val = float(s)
            except (TypeError, ValueError) as exc:
                raise AIMalformedOutputError(
                    f"Invalid non-numeric support coordinate: {s}"
                ) from exc
            if s_val <= 0.0:
                raise AIMalformedOutputError(
                    f"Support level must be strictly positive, got {s_val}"
                )
            validated_support.append(s_val)

        # 4. Resistance levels
        resistance_raw = parsed_json.get("resistance", [])
        if not isinstance(resistance_raw, list):
            raise AIMalformedOutputError(
                f"Expected list for 'resistance', got {type(resistance_raw).__name__}"
            )
        validated_resistance: list[float] = []
        for r in resistance_raw:
            try:
                r_val = float(r)
            except (TypeError, ValueError) as exc:
                raise AIMalformedOutputError(
                    f"Invalid non-numeric resistance coordinate: {r}"
                ) from exc
            if r_val <= 0.0:
                raise AIMalformedOutputError(
                    f"Resistance level must be strictly positive, got {r_val}"
                )
            validated_resistance.append(r_val)

        # 5. Patterns
        patterns_raw = parsed_json.get("patterns", [])
        if not isinstance(patterns_raw, list):
            raise AIMalformedOutputError(
                f"Expected list for 'patterns', got {type(patterns_raw).__name__}"
            )
        validated_patterns: list[PatternObservation] = []
        for p in patterns_raw:
            if not isinstance(p, dict):
                raise AIMalformedOutputError(
                    f"Expected dict for pattern observation, got {type(p).__name__}"
                )
            p_name = p.get("name")
            if not isinstance(p_name, str) or not p_name.strip():
                raise AIMalformedOutputError("Pattern observation requires a non-empty 'name'")
            try:
                p_conf = float(p.get("confidence", 0.0))
            except (TypeError, ValueError) as exc:
                raise AIMalformedOutputError(
                    f"Pattern confidence must be numeric, got {p.get('confidence')}"
                ) from exc
            if not (0.0 <= p_conf <= 1.0):
                raise AIMalformedOutputError(
                    f"Pattern confidence must be between 0.0 and 1.0, got {p_conf}"
                )
            p_desc = p.get("description")
            if p_desc is not None and not isinstance(p_desc, str):
                raise AIMalformedOutputError(
                    f"Pattern description must be string or None, got {type(p_desc).__name__}"
                )
            validated_patterns.append(
                PatternObservation(
                    name=p_name.strip(),
                    confidence=p_conf,
                    description=p_desc.strip() if p_desc else None,
                )
            )

        # 6. is_empty flag
        is_empty = bool(parsed_json.get("is_empty", False))
        if not validated_support and not validated_resistance and not validated_patterns:
            is_empty = True

        # 7. Model version
        resp_model = response_data.get("model")
        model_version: str
        if isinstance(resp_model, str) and resp_model.strip():
            model_version = resp_model.strip()
        elif self.model_version and self.model_version.strip():
            model_version = self.model_version.strip()
        else:
            model_version = self.model_id

        # 8. Calibrated confidence
        confidence: float | None = None
        if validated_patterns:
            confidence = round(
                sum(p.confidence for p in validated_patterns) / len(validated_patterns), 4
            )

        # 9. ProvenanceRecord
        provenance = ProvenanceRecord(
            source_type=AISourceType.MULTIMODAL_VISION,
            model_id=self.model_id,
            model_version=model_version,
            provider=self.provider.provider_id,
            generated_at=datetime.now(UTC),
            input_hash=source_image_hash,
            seed=None,
            is_deterministic=False,
            confidence=confidence,
        )

        # 10. Construct VisionResult
        try:
            return VisionResult(
                trend=trend,
                support=validated_support,
                resistance=validated_resistance,
                patterns=validated_patterns,
                reasoning=reasoning,
                source_image_hash=source_image_hash,
                is_empty=is_empty,
                ocr_text=ocr_text,
                provenance=provenance,
            )
        except (ValidationError, ValueError) as exc:
            raise AIMalformedOutputError(f"VisionResult contract validation failed: {exc}") from exc

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Strip markdown code fence wrappers from raw LLM output text."""
        s = text.strip()
        if s.startswith("```json"):
            s = s[7:]
        elif s.startswith("```"):
            s = s[3:]
        if s.endswith("```"):
            s = s[:-3]
        return s.strip()

    @staticmethod
    def _detect_mime_type(image_bytes: bytes) -> str:
        """Detect MIME type from image magic header bytes."""
        if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
            return "image/png"
        if image_bytes.startswith(b"\xff\xd8\xff"):
            return "image/jpeg"
        if image_bytes.startswith((b"GIF87a", b"GIF89a")):
            return "image/gif"
        if len(image_bytes) >= 12 and image_bytes[:4] == b"RIFF" and image_bytes[8:12] == b"WEBP":
            return "image/webp"
        return "image/png"

    def _build_prompt(
        self,
        spot_price: float | None = None,
        ocr_result: OCRResult | None = None,
    ) -> str:
        """Construct structured multimodal prompt instructing model to output pure JSON."""
        prompt = (
            "You are an institutional quantitative market analysis vision engine.\n"
            "Analyze the uploaded market chart screenshot and extract observable structural market features.\n"
            "Do not execute trades, offer financial advice, or fabricate speculative data.\n\n"
            "Return ONLY a valid JSON object matching this schema:\n"
            "{\n"
            '  "trend": "Bullish" | "Bearish" | "Neutral",\n'
            '  "support": [number, ...],\n'
            '  "resistance": [number, ...],\n'
            '  "patterns": [\n'
            "    {\n"
            '      "name": "Pattern Name",\n'
            '      "confidence": float between 0.0 and 1.0,\n'
            '      "description": "Short observation" or null\n'
            "    }\n"
            "  ],\n"
            '  "reasoning": "Detailed technical reasoning explaining observable features, key levels, and volume.",\n'
            '  "is_empty": boolean\n'
            "}\n\n"
            "Rules:\n"
            "1. All price levels in support and resistance must be strictly positive numbers (> 0.0).\n"
            "2. reasoning must be non-empty and describe visible evidence on the chart.\n"
        )
        if spot_price is not None:
            prompt += f"3. Prevailing underlying spot price is {spot_price}.\n"

        prompt += "\nAuxiliary OCR Context:\n"
        if ocr_result is not None and not ocr_result.is_empty and ocr_result.text.strip():
            prompt += (
                "STATUS: AVAILABLE\n"
                "UNVERIFIED_TEXT:\n"
                f"{ocr_result.text.strip()}\n"
                "INSTRUCTION: Treat the above OCR text as auxiliary, unverified context. "
                "Never accept OCR text uncritically if it contradicts visual chart evidence.\n"
            )
        else:
            prompt += "STATUS: NOT AVAILABLE\n"

        prompt += "\nOutput pure JSON without markdown explanation or code blocks."
        return prompt
