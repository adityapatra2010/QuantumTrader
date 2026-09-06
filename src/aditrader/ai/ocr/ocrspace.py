"""OCR.Space OCR Engine implementation.

Per Phase 7, ADR 005, and ADR 012:
- Integrates OCR.Space cloud OCR REST API via standard library urllib.
- Extracts text and bounding regions from chart or document screenshots.
- Strictly non-authoritative auxiliary data with ProvenanceRecord (AISourceType.OCR_EXTRACTION).
- Bounded execution: single external call, zero background polling or infinite retries.
- All provider and transport errors mapped into typed AIError hierarchy.
"""

import base64
import contextlib
import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from aditrader.ai.base import OCREngine
from aditrader.ai.errors import (
    AICredentialError,
    AIMalformedOutputError,
    AIProviderError,
    AITimeoutError,
    AIUnavailableError,
)
from aditrader.ai.models import (
    AISourceType,
    OCRBoundingBox,
    OCRResult,
    OCRTextRegion,
    ProvenanceRecord,
)
from aditrader.ai.registry import AIProvider

# OCR Transport signature: (url, headers, form_data_bytes, timeout_seconds) -> response_dict
OCRTransportCallable = Callable[[str, dict[str, str], bytes, float], dict[str, Any]]


def default_ocrspace_http_transport(
    url: str,
    headers: dict[str, str],
    data: bytes,
    timeout_seconds: float,
) -> dict[str, Any]:
    """Default HTTP transport invoking OCR.Space REST API via standard library urllib."""
    req = urllib.request.Request(
        url,
        data=data,
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
            res_body = response.read().decode("utf-8")
            parsed = json.loads(res_body)
            if not isinstance(parsed, dict):
                raise AIMalformedOutputError(
                    f"Expected JSON object from OCR.Space response, got {type(parsed).__name__}"
                )
            return parsed
    except urllib.error.HTTPError as e:
        err_body = ""
        with contextlib.suppress(Exception):
            err_body = e.read().decode("utf-8")
        if e.code in (401, 403):
            raise AICredentialError(
                f"OCR.Space API authentication failed (HTTP {e.code}): {err_body}"
            ) from e
        if e.code == 429:
            raise AIProviderError(
                f"OCR.Space API rate limit exceeded (HTTP 429): {err_body}"
            ) from e
        if e.code >= 500:
            raise AIUnavailableError(
                f"OCR.Space API service temporarily unavailable (HTTP {e.code}): {err_body}"
            ) from e
        raise AIProviderError(f"OCR.Space API HTTP error (HTTP {e.code}): {err_body}") from e
    except (urllib.error.URLError, TimeoutError) as e:
        if isinstance(e, TimeoutError) or "timed out" in str(e).lower():
            raise AITimeoutError(
                f"OCR.Space API request timed out after {timeout_seconds:.1f}s"
            ) from e
        raise AIUnavailableError(f"OCR.Space API connection error: {e}") from e
    except json.JSONDecodeError as e:
        raise AIMalformedOutputError(
            f"Failed to decode OCR.Space HTTP response as JSON: {e}"
        ) from e


class OCRSpaceEngine(OCREngine):
    """Concrete OCREngine implementation using OCR.Space cloud REST API."""

    def __init__(
        self,
        provider: AIProvider,
        model_id: str = "ocr-engine-2",
        api_key: str | None = None,
        timeout_seconds: float = 30.0,
        transport: OCRTransportCallable | None = None,
        language: str = "eng",
        scale: bool = True,
        model_version: str | None = None,
    ) -> None:
        self.provider = provider
        self.model_id = model_id
        self.api_key = api_key.strip() if api_key else None
        self.timeout_seconds = max(0.1, timeout_seconds)
        self._transport = transport
        self.language = language
        self.scale = scale
        self.model_version = model_version or model_id

    def is_available(self) -> bool:
        """Return True if API credentials are configured and provider is operational.

        Must never raise network or runtime exceptions.
        """
        try:
            return bool(self.api_key and self.api_key.strip()) and self.provider.is_available()
        except Exception:
            return False

    def extract_text(self, image_bytes: bytes) -> OCRResult:
        """Extract text and bounding regions from image bytes via OCR.Space.

        Args:
            image_bytes: Raw bytes of uploaded chart or document image.

        Returns:
            Normalized OCRResult with extracted text, regions, and ProvenanceRecord.

        Raises:
            AIMalformedOutputError: If image_bytes is empty or provider response is corrupted.
            AICredentialError: If API key is missing or unauthorized.
            AITimeoutError: If OCR request exceeds timeout deadline.
            AIUnavailableError: If service is unreachable.
            AIProviderError: If OCR.Space processing encounters an error or rate limit.
        """
        if not image_bytes or len(image_bytes) == 0:
            raise AIMalformedOutputError("Input image_bytes cannot be empty")

        if not self.api_key or not self.api_key.strip():
            raise AICredentialError(
                f"Missing required API key for OCR provider '{self.provider.provider_id}'"
            )

        source_image_hash = hashlib.sha256(image_bytes).hexdigest().lower()
        mime_type = self._detect_mime_type(image_bytes)
        b64_image = base64.b64encode(image_bytes).decode("ascii")

        # Resolve OCR.Space engine number from model_id
        ocr_engine_num = "2" if "2" in self.model_id else "1"

        # OCR.Space accepts urlencoded POST parameters
        form_params = {
            "apikey": self.api_key,
            "base64Image": f"data:{mime_type};base64,{b64_image}",
            "language": self.language,
            "isOverlayRequired": "true",
            "scale": "true" if self.scale else "false",
            "OCREngine": ocr_engine_num,
        }
        form_data_bytes = urllib.parse.urlencode(form_params).encode("utf-8")
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "apikey": self.api_key,
        }
        url = "https://api.ocr.space/parse/image"

        transport_fn = self._transport or default_ocrspace_http_transport
        # Single bounded call: no retry loop
        response_data = transport_fn(url, headers, form_data_bytes, self.timeout_seconds)

        return self._parse_and_validate_response(
            response_data=response_data,
            source_image_hash=source_image_hash,
        )

    def _parse_and_validate_response(
        self,
        response_data: dict[str, Any],
        source_image_hash: str,
    ) -> OCRResult:
        """Parse structured OCR.Space response, normalize text and regions, and build OCRResult."""
        if not isinstance(response_data, dict):
            raise AIMalformedOutputError(
                f"Expected dictionary from OCR provider response, got {type(response_data).__name__}"
            )

        # Check for provider-level errors in OCR.Space payload
        is_errored = bool(response_data.get("IsErroredOnProcessing", False))
        error_message = response_data.get("ErrorMessage")
        exit_code = response_data.get("OCRExitCode")

        if is_errored or (exit_code is not None and exit_code in (3, 4)):
            err_str = self._format_error_message(error_message)
            err_lower = err_str.lower()
            if any(
                k in err_lower
                for k in ("api key", "apikey", "unauthorized", "invalid key", "not registered")
            ):
                raise AICredentialError(f"OCR.Space authentication error: {err_str}")
            if any(k in err_lower for k in ("timeout", "timed out")):
                raise AITimeoutError(f"OCR.Space processing timed out: {err_str}")
            if any(
                k in err_lower
                for k in ("rate limit", "limit reached", "maximum number of requests")
            ):
                raise AIProviderError(f"OCR.Space quota/rate limit exceeded: {err_str}")
            raise AIProviderError(f"OCR.Space processing error: {err_str}")

        parsed_results = response_data.get("ParsedResults")
        if parsed_results is None or not isinstance(parsed_results, list):
            raise AIMalformedOutputError("OCR.Space response missing 'ParsedResults' list")

        combined_text_chunks: list[str] = []
        regions: list[OCRTextRegion] = []

        for item in parsed_results:
            if not isinstance(item, dict):
                continue
            item_text = item.get("ParsedText", "")
            if isinstance(item_text, str) and item_text.strip():
                combined_text_chunks.append(item_text.strip())

            overlay = item.get("TextOverlay")
            if isinstance(overlay, dict):
                lines = overlay.get("Lines", [])
                if isinstance(lines, list):
                    for line in lines:
                        if not isinstance(line, dict):
                            continue
                        words = line.get("Words", [])
                        if not isinstance(words, list) or not words:
                            continue
                        word_texts: list[str] = []
                        lefts: list[float] = []
                        tops: list[float] = []
                        rights: list[float] = []
                        bottoms: list[float] = []

                        for w in words:
                            if not isinstance(w, dict):
                                continue
                            wt = w.get("WordText")
                            if isinstance(wt, str) and wt.strip():
                                word_texts.append(wt.strip())
                            try:
                                wl = float(w.get("Left", 0.0))
                                wt_pos = float(w.get("Top", 0.0))
                                ww = float(w.get("Width", 0.0))
                                wh = float(w.get("Height", 0.0))
                                lefts.append(wl)
                                tops.append(wt_pos)
                                rights.append(wl + ww)
                                bottoms.append(wt_pos + wh)
                            except (TypeError, ValueError):
                                continue

                        if word_texts:
                            line_str = " ".join(word_texts)
                            box: OCRBoundingBox | None = None
                            if lefts and tops and rights and bottoms:
                                b_left = max(0.0, min(lefts))
                                b_top = max(0.0, min(tops))
                                b_width = max(0.0, max(rights) - b_left)
                                b_height = max(0.0, max(bottoms) - b_top)
                                box = OCRBoundingBox(
                                    left=round(b_left, 2),
                                    top=round(b_top, 2),
                                    width=round(b_width, 2),
                                    height=round(b_height, 2),
                                )
                            regions.append(
                                OCRTextRegion(
                                    text=line_str,
                                    confidence=None,
                                    box=box,
                                )
                            )

        full_text = "\n".join(combined_text_chunks).strip()
        is_empty = len(full_text) == 0

        provenance = ProvenanceRecord(
            source_type=AISourceType.OCR_EXTRACTION,
            model_id=self.model_id,
            model_version=self.model_version,
            provider=self.provider.provider_id,
            generated_at=datetime.now(UTC),
            input_hash=source_image_hash,
            seed=None,
            is_deterministic=False,
            confidence=None,
        )

        try:
            return OCRResult(
                text=full_text,
                confidence=None,
                regions=regions,
                source_image_hash=source_image_hash,
                is_empty=is_empty,
                provenance=provenance,
            )
        except (ValidationError, ValueError) as exc:
            raise AIMalformedOutputError(f"OCRResult contract validation failed: {exc}") from exc

    @staticmethod
    def _format_error_message(err: Any) -> str:
        """Format error message field from OCR.Space which can be str or list."""
        if isinstance(err, list):
            return "; ".join(str(e) for e in err if e)
        if isinstance(err, str):
            return err
        return str(err or "Unknown error")

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
