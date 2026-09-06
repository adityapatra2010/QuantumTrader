"""Google Gemini AI Provider adapter.

Per Phase 7B, ADR 005, and ADR 012:
- Concrete provider adapter integrating Google Gemini models.
- Resolves credentials via AICredentialResolver, explicit keys, or environment variables.
- Provider-specific API and SDK mechanics are encapsulated inside this adapter and vision engine.
- Bounded execution: zero automatic retries that could consume paid API credits.
"""

import os
from typing import Any

from aditrader.ai.base import VisionEngine
from aditrader.ai.catalog import AICapability, ModelCatalog
from aditrader.ai.credentials import AICredentialResolver
from aditrader.ai.errors import AICredentialError, AIUnsupportedCapabilityError
from aditrader.ai.registry import BaseAIProvider
from aditrader.ai.vision.gemini import GeminiVisionEngine, TransportCallable


class GoogleAIProvider(BaseAIProvider):
    """AI Provider adapter for Google Gemini models."""

    def __init__(
        self,
        api_key: str | None = None,
        credential_resolver: AICredentialResolver | None = None,
        catalog: ModelCatalog | None = None,
        transport: TransportCallable | None = None,
    ) -> None:
        self._api_key = api_key.strip() if api_key else None
        self._credential_resolver = credential_resolver
        self._catalog = catalog
        self._transport = transport

    @property
    def provider_id(self) -> str:
        return "google"

    def _resolve_api_key(self) -> str | None:
        """Resolve API key from explicit initialization, credential resolver, or environment."""
        if self._api_key and self._api_key.strip():
            return self._api_key.strip()
        if self._credential_resolver is not None:
            try:
                return self._credential_resolver.get_credential(self.provider_id)
            except AICredentialError:
                pass
        env_val = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
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

    def get_vision_engine(self, model_id: str, **kwargs: Any) -> VisionEngine:
        """Instantiate configured GeminiVisionEngine for model_id.

        Args:
            model_id: Target Gemini model identifier (e.g. 'gemini-2.0-flash').
            **kwargs: Configuration overrides (timeout_seconds, temperature, transport, api_key).

        Returns:
            Configured GeminiVisionEngine instance.

        Raises:
            AIUnsupportedCapabilityError: If target model does not support multimodal vision.
        """
        # 1. Capability verification
        if self._catalog is not None and self._catalog.has_model(self.provider_id, model_id):
            model_meta = self._catalog.get(self.provider_id, model_id)
            if not model_meta.has_capability(AICapability.VISION):
                raise AIUnsupportedCapabilityError(
                    f"Model '{model_id}' under provider '{self.provider_id}' does not support vision capability"
                )
        elif "embedding" in model_id.lower():
            raise AIUnsupportedCapabilityError(
                f"Model '{model_id}' under provider '{self.provider_id}' does not support vision capability"
            )

        # 2. Extract configuration parameters
        api_key = kwargs.get("api_key") or self._resolve_api_key()
        timeout_seconds = float(kwargs.get("timeout_seconds", 30.0))
        temperature = kwargs.get("temperature")
        transport = kwargs.get("transport") or self._transport
        model_version = kwargs.get("model_version")
        ocr_engine = kwargs.get("ocr_engine")

        return GeminiVisionEngine(
            provider=self,
            model_id=model_id,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            transport=transport,
            model_version=model_version,
            ocr_engine=ocr_engine,
        )
