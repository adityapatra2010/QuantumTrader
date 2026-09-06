"""Provider-agnostic AI provider registry.

Per Phase 7A:
- Providers are dynamically selectable by configuration.
- Adapters remain strictly behind existing domain interfaces.
- Zero hardcoded single-vendor dependencies.
"""

from abc import ABC, abstractmethod
from typing import Any

from aditrader.ai.base import (
    ForecastEngine,
    StrategyReviewer,
    StrategySuggestor,
    VisionEngine,
)
from aditrader.ai.errors import (
    AIConfigError,
    AIProviderNotFoundError,
    AIUnsupportedCapabilityError,
)


class AIProvider(ABC):
    """Abstract interface representing an AI provider infrastructure backend."""

    @property
    @abstractmethod
    def provider_id(self) -> str:
        """Unique lowercase identifier for this provider (e.g., 'google', 'local', 'amazon')."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if backend, credentials, or compute resources are operational.

        Must never raise network or runtime exceptions.
        """
        ...

    @abstractmethod
    def get_forecast_engine(self, model_id: str, **kwargs: Any) -> ForecastEngine:
        """Instantiate or return ForecastEngine for model_id.

        Raises:
            AIUnsupportedCapabilityError: If this provider does not support time-series forecasting.
        """
        ...

    @abstractmethod
    def get_vision_engine(self, model_id: str, **kwargs: Any) -> VisionEngine:
        """Instantiate or return VisionEngine for model_id.

        Raises:
            AIUnsupportedCapabilityError: If this provider does not support multimodal vision.
        """
        ...

    @abstractmethod
    def get_strategy_suggestor(self, model_id: str, **kwargs: Any) -> StrategySuggestor:
        """Instantiate or return StrategySuggestor for model_id.

        Raises:
            AIUnsupportedCapabilityError: If this provider does not support strategy suggestion.
        """
        ...

    @abstractmethod
    def get_strategy_reviewer(self, model_id: str, **kwargs: Any) -> StrategyReviewer:
        """Instantiate or return StrategyReviewer for model_id.

        Raises:
            AIUnsupportedCapabilityError: If this provider does not support strategy review.
        """
        ...


class BaseAIProvider(AIProvider):
    """Convenience base class providing default unsupported capability rejections."""

    def get_forecast_engine(self, model_id: str, **kwargs: Any) -> ForecastEngine:
        raise AIUnsupportedCapabilityError(
            f"Provider '{self.provider_id}' does not support forecasting engine"
        )

    def get_vision_engine(self, model_id: str, **kwargs: Any) -> VisionEngine:
        raise AIUnsupportedCapabilityError(
            f"Provider '{self.provider_id}' does not support vision engine"
        )

    def get_strategy_suggestor(self, model_id: str, **kwargs: Any) -> StrategySuggestor:
        raise AIUnsupportedCapabilityError(
            f"Provider '{self.provider_id}' does not support strategy suggestion"
        )

    def get_strategy_reviewer(self, model_id: str, **kwargs: Any) -> StrategyReviewer:
        raise AIUnsupportedCapabilityError(
            f"Provider '{self.provider_id}' does not support strategy review"
        )


class AIProviderRegistry:
    """Registry managing available AI provider implementations."""

    def __init__(self) -> None:
        self._providers: dict[str, AIProvider] = {}

    def register_provider(self, provider: AIProvider, overwrite: bool = False) -> None:
        """Register an AI provider.

        Args:
            provider: AIProvider instance.
            overwrite: If True, allow replacing existing registration.
                       If False, raise AIConfigError on collision.
        """
        pid = provider.provider_id.lower().strip()
        if not pid:
            raise AIConfigError("Provider provider_id cannot be empty")
        if pid in self._providers and not overwrite:
            raise AIConfigError(f"AI Provider '{pid}' is already registered")
        self._providers[pid] = provider

    def get_provider(self, provider_id: str) -> AIProvider:
        """Retrieve registered AI provider by ID.

        Raises:
            AIProviderNotFoundError: If provider is not registered.
        """
        pid = provider_id.lower().strip()
        if pid not in self._providers:
            raise AIProviderNotFoundError(f"AI Provider '{provider_id}' is not registered")
        return self._providers[pid]

    def has_provider(self, provider_id: str) -> bool:
        """Check if provider is registered."""
        return provider_id.lower().strip() in self._providers

    def list_providers(self) -> list[str]:
        """Return deterministic sorted list of registered provider IDs."""
        return sorted(self._providers.keys())

    def unregister_provider(self, provider_id: str) -> None:
        """Remove a provider from the registry if present."""
        self._providers.pop(provider_id.lower().strip(), None)

    def count(self) -> int:
        """Return total number of registered providers."""
        return len(self._providers)
