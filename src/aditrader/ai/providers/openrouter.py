"""OpenRouter AI Provider adapter.

Per Phase 7, ADR 005, and ADR 012:
- Concrete provider adapter integrating OpenRouter multimodal/reasoning models.
- Resolves credentials via AICredentialResolver, explicit keys, or environment variables (OPENROUTER_API_KEY).
- Provider-specific API and transport mechanics are encapsulated inside this adapter and vision engine.
- Bounded execution: single external call, zero automatic retries that could consume paid credits.
"""

import os
from typing import Any

from aditrader.ai.base import VisionEngine
from aditrader.ai.catalog import AICapability, ModelCatalog
from aditrader.ai.credentials import AICredentialResolver
from aditrader.ai.errors import AICredentialError, AIUnsupportedCapabilityError
from aditrader.ai.registry import BaseAIProvider
from aditrader.ai.vision.openrouter import (
    OpenRouterTransportCallable,
    OpenRouterVisionEngine,
)


class OpenRouterProvider(BaseAIProvider):
    """AI Provider adapter for OpenRouter multimodal and reasoning models."""

    def __init__(
        self,
        api_key: str | None = None,
        credential_resolver: AICredentialResolver | None = None,
        catalog: ModelCatalog | None = None,
        transport: OpenRouterTransportCallable | None = None,
        site_url: str = "https://github.com/aditya/AdiTrader",
        site_name: str = "AdiTrader QuantumValidator",
    ) -> None:
        self._api_key = api_key.strip() if api_key else None
        self._credential_resolver = credential_resolver
        self._catalog = catalog
        self._transport = transport
        self.site_url = site_url
        self.site_name = site_name

    @property
    def provider_id(self) -> str:
        return "openrouter"

    def _resolve_api_key(self) -> str | None:
        """Resolve API key from explicit initialization, credential resolver, or environment."""
        if self._api_key and self._api_key.strip():
            return self._api_key.strip()
        if self._credential_resolver is not None:
            try:
                return self._credential_resolver.get_credential(self.provider_id)
            except AICredentialError:
                pass
        env_val = os.environ.get("OPENROUTER_API_KEY")
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
        """Instantiate configured OpenRouterVisionEngine for model_id.

        Args:
            model_id: Target OpenRouter model identifier (e.g. 'google/gemma-4-26b-a4b-it').
            **kwargs: Configuration overrides (timeout_seconds, temperature, transport, api_key, ocr_engine).

        Returns:
            Configured OpenRouterVisionEngine instance.

        Raises:
            AIUnsupportedCapabilityError: If model does not support multimodal vision.
        """
        # Capability check via catalog if model is registered
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

        api_key = kwargs.get("api_key") or self._resolve_api_key()
        timeout_seconds = float(kwargs.get("timeout_seconds", 30.0))
        temperature = kwargs.get("temperature")
        transport = kwargs.get("transport") or self._transport
        model_version = kwargs.get("model_version")
        ocr_engine = kwargs.get("ocr_engine")
        site_url = str(kwargs.get("site_url", self.site_url))
        site_name = str(kwargs.get("site_name", self.site_name))

        return OpenRouterVisionEngine(
            provider=self,
            model_id=model_id,
            api_key=api_key,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            transport=transport,
            model_version=model_version,
            ocr_engine=ocr_engine,
            site_url=site_url,
            site_name=site_name,
        )
