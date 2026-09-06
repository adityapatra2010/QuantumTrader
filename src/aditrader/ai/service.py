"""AI Service Resolution and orchestration gateway.

Per Phase 7A:
- Minimal resolution layer connecting configuration, catalog, credentials, and provider registry.
- Performs capability assertions, model existence checks, and provider availability verification.
- Zero network calls or runtime model executions.
"""

from typing import Literal

from aditrader.ai.base import (
    ForecastEngine,
    StrategyReviewer,
    StrategySuggestor,
    VisionEngine,
)
from aditrader.ai.catalog import AICapability, ModelCatalog, ModelMetadata
from aditrader.ai.config import AIServiceConfig, SubsystemModelConfig
from aditrader.ai.credentials import AICredentialResolver
from aditrader.ai.errors import (
    AIConfigError,
    AIUnavailableError,
    AIUnsupportedCapabilityError,
)
from aditrader.ai.registry import AIProviderRegistry

SubsystemName = Literal["vision", "forecasting", "strategy_suggestor", "strategy_reviewer", "ocr"]


class AIServiceResolver:
    """Resolves and validates AI subsystem components based on active configuration."""

    def __init__(
        self,
        config: AIServiceConfig,
        registry: AIProviderRegistry,
        catalog: ModelCatalog,
        credential_resolver: AICredentialResolver | None = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.catalog = catalog
        self.credential_resolver = credential_resolver

    def get_subsystem_config(self, subsystem: SubsystemName) -> SubsystemModelConfig:
        """Retrieve typed configuration for a specific subsystem."""
        if subsystem == "vision":
            return self.config.subsystems.vision
        if subsystem == "forecasting":
            return self.config.subsystems.forecasting
        if subsystem == "strategy_suggestor":
            return self.config.subsystems.strategy_suggestor
        if subsystem == "strategy_reviewer":
            return self.config.subsystems.strategy_reviewer
        if subsystem == "ocr":
            return self.config.subsystems.ocr
        raise AIConfigError(f"Unknown AI subsystem '{subsystem}'")

    def validate_subsystem_resolution(
        self,
        subsystem: SubsystemName,
        expected_capability: AICapability | None = None,
        require_credentials: bool = True,
    ) -> ModelMetadata:
        """Validate that configured subsystem provider, model, and capabilities resolve cleanly.

        Args:
            subsystem: Name of the subsystem ('vision', 'forecasting', etc.)
            expected_capability: Required AICapability (e.g. AICapability.VISION).
            require_credentials: If True, assert credential exists via credential_resolver.

        Returns:
            ModelMetadata of the successfully resolved model.

        Raises:
            AIConfigError: If AI features are disabled globally.
            AIProviderNotFoundError: If configured provider is unregistered.
            AIModelNotFoundError: If configured model is unregistered in catalog.
            AIUnsupportedCapabilityError: If model lacks required capability.
            AICredentialError: If required credentials are missing.
            AIUnavailableError: If provider reports is_available() == False.
        """
        if not self.config.enabled:
            raise AIConfigError(
                f"AI advisory features are globally disabled; cannot resolve '{subsystem}'"
            )

        sub_cfg = self.get_subsystem_config(subsystem)

        # 1. Check provider registration
        provider = self.registry.get_provider(sub_cfg.provider)

        # 2. Check model registration in catalog
        model_meta = self.catalog.get(sub_cfg.provider, sub_cfg.model_id)

        # 3. Check expected capability
        if expected_capability is not None and not model_meta.has_capability(expected_capability):
            raise AIUnsupportedCapabilityError(
                f"Model '{model_meta.model_id}' under provider '{model_meta.provider}' "
                f"does not support required capability '{expected_capability.value}' for subsystem '{subsystem}'"
            )

        # 4. Check subsystem declared required_capabilities
        for req_cap in sub_cfg.required_capabilities:
            if not model_meta.has_capability(req_cap):
                raise AIUnsupportedCapabilityError(
                    f"Model '{model_meta.model_id}' lacks explicitly configured required capability '{req_cap.value}'"
                )

        # 5. Check credentials if resolver provided and required
        if require_credentials and self.credential_resolver is not None:
            self.credential_resolver.get_credential(sub_cfg.provider)

        # 6. Check provider availability
        if not provider.is_available():
            raise AIUnavailableError(
                f"AI Provider '{sub_cfg.provider}' is currently unavailable or unconfigured"
            )

        return model_meta

    def validate_all_subsystems(self, require_credentials: bool = True) -> dict[str, ModelMetadata]:
        """Validate all five functional subsystems in active configuration.

        Returns:
            Dictionary mapping subsystem name to resolved ModelMetadata.
        """
        results: dict[str, ModelMetadata] = {}
        results["vision"] = self.validate_subsystem_resolution(
            "vision", AICapability.VISION, require_credentials=require_credentials
        )
        results["forecasting"] = self.validate_subsystem_resolution(
            "forecasting", AICapability.FORECASTING, require_credentials=require_credentials
        )
        results["strategy_suggestor"] = self.validate_subsystem_resolution(
            "strategy_suggestor", require_credentials=require_credentials
        )
        results["strategy_reviewer"] = self.validate_subsystem_resolution(
            "strategy_reviewer", require_credentials=require_credentials
        )
        results["ocr"] = self.validate_subsystem_resolution(
            "ocr", AICapability.OCR, require_credentials=require_credentials
        )
        return results

    def resolve_forecast_engine(self, require_credentials: bool = True) -> ForecastEngine:
        """Resolve and instantiate configured ForecastEngine."""
        self.validate_subsystem_resolution(
            "forecasting", AICapability.FORECASTING, require_credentials=require_credentials
        )
        sub_cfg = self.get_subsystem_config("forecasting")
        provider = self.registry.get_provider(sub_cfg.provider)
        return provider.get_forecast_engine(
            sub_cfg.model_id,
            timeout_seconds=sub_cfg.timeout_seconds,
            max_retries=sub_cfg.max_retries,
            **sub_cfg.extra_params,
        )

    def resolve_vision_engine(self, require_credentials: bool = True) -> VisionEngine:
        """Resolve and instantiate configured VisionEngine."""
        self.validate_subsystem_resolution(
            "vision", AICapability.VISION, require_credentials=require_credentials
        )
        sub_cfg = self.get_subsystem_config("vision")
        provider = self.registry.get_provider(sub_cfg.provider)
        return provider.get_vision_engine(
            sub_cfg.model_id,
            timeout_seconds=sub_cfg.timeout_seconds,
            max_retries=sub_cfg.max_retries,
            **sub_cfg.extra_params,
        )

    def resolve_strategy_suggestor(self, require_credentials: bool = True) -> StrategySuggestor:
        """Resolve and instantiate configured StrategySuggestor."""
        self.validate_subsystem_resolution(
            "strategy_suggestor", require_credentials=require_credentials
        )
        sub_cfg = self.get_subsystem_config("strategy_suggestor")
        provider = self.registry.get_provider(sub_cfg.provider)
        return provider.get_strategy_suggestor(
            sub_cfg.model_id,
            timeout_seconds=sub_cfg.timeout_seconds,
            max_retries=sub_cfg.max_retries,
            **sub_cfg.extra_params,
        )

    def resolve_strategy_reviewer(self, require_credentials: bool = True) -> StrategyReviewer:
        """Resolve and instantiate configured StrategyReviewer."""
        self.validate_subsystem_resolution(
            "strategy_reviewer", require_credentials=require_credentials
        )
        sub_cfg = self.get_subsystem_config("strategy_reviewer")
        provider = self.registry.get_provider(sub_cfg.provider)
        return provider.get_strategy_reviewer(
            sub_cfg.model_id,
            timeout_seconds=sub_cfg.timeout_seconds,
            max_retries=sub_cfg.max_retries,
            **sub_cfg.extra_params,
        )
