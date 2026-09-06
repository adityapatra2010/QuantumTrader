"""OCR.Space AI Provider adapter.

Per Phase 7, ADR 005, and ADR 012:
- Concrete provider adapter integrating OCR.Space cloud engine.
- Resolves credentials via AICredentialResolver, explicit keys, or environment variables.
- Provider-specific API and transport mechanics are encapsulated inside this adapter and engine.
- Bounded execution: single external call, zero automatic retries that could consume quotas.
"""

import os
from typing import Any

from aditrader.ai.base import OCREngine
from aditrader.ai.catalog import AICapability, ModelCatalog
from aditrader.ai.credentials import AICredentialResolver
from aditrader.ai.errors import AICredentialError, AIUnsupportedCapabilityError
from aditrader.ai.ocr.ocrspace import OCRSpaceEngine, OCRTransportCallable
from aditrader.ai.registry import BaseAIProvider


class OCRSpaceProvider(BaseAIProvider):
    """AI Provider adapter for OCR.Space cloud OCR engine."""

    def __init__(
        self,
        api_key: str | None = None,
        credential_resolver: AICredentialResolver | None = None,
        catalog: ModelCatalog | None = None,
        transport: OCRTransportCallable | None = None,
    ) -> None:
        self._api_key = api_key.strip() if api_key else None
        self._credential_resolver = credential_resolver
        self._catalog = catalog
        self._transport = transport

    @property
    def provider_id(self) -> str:
        return "ocrspace"

    def _resolve_api_key(self) -> str | None:
        """Resolve API key from explicit initialization, credential resolver, or environment."""
        if self._api_key and self._api_key.strip():
            return self._api_key.strip()
        if self._credential_resolver is not None:
            try:
                return self._credential_resolver.get_credential(self.provider_id)
            except AICredentialError:
                pass
        env_val = os.environ.get("OCRSPACE_API_KEY") or os.environ.get("OCR_SPACE_API_KEY")
        if env_val and env_val.strip():
            return env_val.strip()
        return None

    def is_available(self) -> bool:
        """Return True if credentials or API keys are configured and valid.

        Must never raise network or runtime exceptions.
        """
        try:
            return self._resolve_api_key() is not None
        except Exception:
            return False

    def get_ocr_engine(self, model_id: str, **kwargs: Any) -> OCREngine:
        """Instantiate configured OCRSpaceEngine for model_id.

        Args:
            model_id: Target OCR model identifier (e.g. 'ocr-engine-2').
            **kwargs: Configuration overrides (timeout_seconds, transport, api_key, language, scale).

        Returns:
            Configured OCRSpaceEngine instance.

        Raises:
            AIUnsupportedCapabilityError: If model does not support OCR.
        """
        if self._catalog is not None and self._catalog.has_model(self.provider_id, model_id):
            model_meta = self._catalog.get(self.provider_id, model_id)
            if not model_meta.has_capability(AICapability.OCR):
                raise AIUnsupportedCapabilityError(
                    f"Model '{model_id}' under provider '{self.provider_id}' does not support OCR capability"
                )

        api_key = kwargs.get("api_key") or self._resolve_api_key()
        timeout_seconds = float(kwargs.get("timeout_seconds", 30.0))
        transport = kwargs.get("transport") or self._transport
        language = str(kwargs.get("language", "eng"))
        scale = bool(kwargs.get("scale", True))
        model_version = kwargs.get("model_version")

        return OCRSpaceEngine(
            provider=self,
            model_id=model_id,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            transport=transport,
            language=language,
            scale=scale,
            model_version=model_version,
        )
