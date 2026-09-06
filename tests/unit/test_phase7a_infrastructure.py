"""Unit tests for Phase 7A AI infrastructure, catalog, registry, and configuration."""

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from aditrader.ai.base import (
    ForecastEngine,
    StrategyReviewer,
    StrategySuggestor,
    VisionEngine,
)
from aditrader.ai.catalog import (
    AICapability,
    ModelCatalog,
    ModelContextLimits,
    ModelMetadata,
    ModelPricing,
)
from aditrader.ai.config import (
    AIBudgetConfig,
    AIServiceConfig,
    AISubsystemsConfig,
    ModelUsageLimit,
    SubsystemModelConfig,
)
from aditrader.ai.credentials import (
    DictCredentialResolver,
    EnvCredentialResolver,
)
from aditrader.ai.errors import (
    AIConfigError,
    AICredentialError,
    AIError,
    AIModelNotFoundError,
    AIProviderNotFoundError,
    AIUnavailableError,
    AIUnsupportedCapabilityError,
)
from aditrader.ai.models import (
    AISourceType,
    BiasCfg,
    DossierSection,
    DossierSectionSourceType,
    ForecastResult,
    ProvenanceRecord,
    SuggestionResult,
    VisionResult,
)
from aditrader.ai.registry import (
    AIProviderRegistry,
    BaseAIProvider,
)
from aditrader.ai.service import AIServiceResolver
from aditrader.core.models.market_data import Bar
from aditrader.strategy.builder.schema import StrategyDSL
from aditrader.strategy.library.templates import create_nifty_iron_condor_dsl
from aditrader.validation.models import (
    ValidationResult,
)


def _create_test_provenance(source_type: AISourceType) -> ProvenanceRecord:
    return ProvenanceRecord(
        source_type=source_type,
        model_id="test-model",
        model_version="1.0.0",
        provider="mock",
        generated_at=datetime(2026, 9, 6, 12, 0, tzinfo=UTC),
        input_hash="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    )


class MockForecastEngine(ForecastEngine):
    def forecast(self, history: list[Bar], horizon_bars: int = 5) -> ForecastResult:
        cutoff = datetime(2026, 9, 6, 9, 30, tzinfo=UTC)
        return ForecastResult(
            cutoff_timestamp=cutoff,
            horizon_bars=1,
            timestamps=[datetime(2026, 9, 6, 9, 35, tzinfo=UTC)],
            predicted_close=[24500.0],
            predicted_high=[24550.0],
            predicted_low=[24450.0],
            confidence_spread=0.01,
            provenance=_create_test_provenance(AISourceType.PROBABILISTIC_FORECAST),
        )

    def is_available(self) -> bool:
        return True


class MockVisionEngine(VisionEngine):
    def analyze(self, image_bytes: bytes, spot_price: float | None = None) -> VisionResult:
        return VisionResult(
            trend="Bullish",
            support=[24000.0],
            resistance=[25000.0],
            reasoning="Clear ascending consolidation channel.",
            source_image_hash="a591a6d40bf420404a011733cfb7b190d62c65bf0bcda32b57b277d9ad9f146e",
            provenance=_create_test_provenance(AISourceType.MULTIMODAL_VISION),
        )

    def is_available(self) -> bool:
        return True


class MockStrategySuggestor(StrategySuggestor):
    def suggest(
        self,
        regime: str,
        bias: BiasCfg,
        forecast: ForecastResult | None = None,
        vision: VisionResult | None = None,
    ) -> SuggestionResult:
        dsl = create_nifty_iron_condor_dsl()
        return SuggestionResult(
            strategy_dsl=dsl,
            provenance=_create_test_provenance(AISourceType.STRATEGY_SUGGESTION),
            bias_applied=bias,
            regime_context=regime,
            rationale="Sample test rationale",
        )


class MockStrategyReviewer(StrategyReviewer):
    def _generate_review(
        self,
        strategy: StrategyDSL,
        validation_result: ValidationResult,
    ) -> DossierSection:
        return DossierSection(
            title="Advisory Risk Review",
            source_type=DossierSectionSourceType.AI_ADVISORY,
            content="Risk review content",
            provenance=_create_test_provenance(AISourceType.STRATEGY_REVIEW),
        )


class MockFullProvider(BaseAIProvider):
    def __init__(self, provider_id: str = "mock", available: bool = True) -> None:
        self._provider_id = provider_id
        self._available = available

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def is_available(self) -> bool:
        return self._available

    def get_forecast_engine(self, model_id: str, **kwargs: Any) -> ForecastEngine:
        return MockForecastEngine()

    def get_vision_engine(self, model_id: str, **kwargs: Any) -> VisionEngine:
        return MockVisionEngine()

    def get_strategy_suggestor(self, model_id: str, **kwargs: Any) -> StrategySuggestor:
        return MockStrategySuggestor()

    def get_strategy_reviewer(self, model_id: str, **kwargs: Any) -> StrategyReviewer:
        return MockStrategyReviewer()


def _create_sample_subsystems_config(provider: str = "mock") -> AISubsystemsConfig:
    return AISubsystemsConfig(
        vision=SubsystemModelConfig(provider=provider, model_id="vision-model"),
        forecasting=SubsystemModelConfig(provider=provider, model_id="forecast-model"),
        strategy_suggestor=SubsystemModelConfig(provider=provider, model_id="suggest-model"),
        strategy_reviewer=SubsystemModelConfig(provider=provider, model_id="review-model"),
        ocr=SubsystemModelConfig(provider=provider, model_id="ocr-model"),
    )


def test_provider_registration_and_listing() -> None:
    """Verify provider registration, inquiry, and removal."""
    registry = AIProviderRegistry()
    provider = MockFullProvider("google")

    assert registry.count() == 0
    assert not registry.has_provider("google")

    registry.register_provider(provider)
    assert registry.count() == 1
    assert registry.has_provider("google")
    assert registry.has_provider("GOOGLE")  # Case-insensitive
    assert registry.get_provider("google") is provider
    assert registry.list_providers() == ["google"]

    registry.unregister_provider("google")
    assert registry.count() == 0
    assert not registry.has_provider("google")


def test_duplicate_provider_handling() -> None:
    """Verify duplicate provider registration is rejected unless overwrite=True."""
    registry = AIProviderRegistry()
    p1 = MockFullProvider("google")
    p2 = MockFullProvider("google")

    registry.register_provider(p1)
    with pytest.raises(AIConfigError, match="already registered"):
        registry.register_provider(p2, overwrite=False)

    # Overwrite allowed
    registry.register_provider(p2, overwrite=True)
    assert registry.get_provider("google") is p2


def test_missing_provider_error() -> None:
    """Verify querying missing provider raises AIProviderNotFoundError."""
    registry = AIProviderRegistry()
    with pytest.raises(AIProviderNotFoundError, match="is not registered"):
        registry.get_provider("unknown_provider")

    # Inherits from AIConfigError and AIError
    assert issubclass(AIProviderNotFoundError, AIConfigError)
    assert issubclass(AIProviderNotFoundError, AIError)


def test_model_registration_and_lookup() -> None:
    """Verify model registration, case-insensitive lookup, and collision handling."""
    catalog = ModelCatalog()
    meta = ModelMetadata(
        provider="google",
        model_id="gemini-2.0-flash",
        display_name="Gemini 2.0 Flash",
        capabilities={AICapability.VISION, AICapability.STRUCTURED_OUTPUT},
        context_limits=ModelContextLimits(max_context_tokens=1048576, max_output_tokens=8192),
        pricing=ModelPricing(input_cost_per_1k_tokens=0.0001, output_cost_per_1k_tokens=0.0004),
    )

    catalog.register(meta)
    assert catalog.count() == 1
    assert catalog.has_model("google", "gemini-2.0-flash")
    assert catalog.has_model("GOOGLE", "GEMINI-2.0-FLASH")

    found = catalog.get("google", "gemini-2.0-flash")
    assert found.display_name == "Gemini 2.0 Flash"
    assert found.context_limits is not None
    assert found.context_limits.max_context_tokens == 1048576

    # Missing model
    with pytest.raises(AIModelNotFoundError, match="not found in catalog"):
        catalog.get("google", "nonexistent")

    # Duplicate model collision
    with pytest.raises(AIConfigError, match="already registered"):
        catalog.register(meta, overwrite=False)

    # Overwrite
    catalog.register(meta, overwrite=True)
    assert catalog.count() == 1


def test_capability_checking_and_filtering() -> None:
    """Verify capability inspection, string conversion, and catalog filtering."""
    catalog = ModelCatalog()
    vision_model = ModelMetadata(
        provider="google",
        model_id="gemini-2.0-flash",
        display_name="Gemini 2.0 Flash",
        capabilities={AICapability.VISION, AICapability.STRUCTURED_OUTPUT, AICapability.REASONING},
    )
    forecast_model = ModelMetadata(
        provider="amazon",
        model_id="chronos-t5-large",
        display_name="Chronos T5 Large",
        capabilities={AICapability.FORECASTING},
    )
    catalog.register(vision_model)
    catalog.register(forecast_model)

    assert vision_model.has_capability(AICapability.VISION) is True
    assert vision_model.has_capability("vision") is True
    assert vision_model.has_capability(AICapability.FORECASTING) is False
    assert vision_model.has_capability("invalid_cap") is False

    assert (
        vision_model.has_capabilities([AICapability.VISION, AICapability.STRUCTURED_OUTPUT]) is True
    )
    assert vision_model.has_capabilities([AICapability.VISION, AICapability.FORECASTING]) is False

    # Filter catalog by capability
    vision_models = catalog.list_models(capability=AICapability.VISION)
    assert len(vision_models) == 1
    assert vision_models[0].model_id == "gemini-2.0-flash"

    forecast_models = catalog.list_models(capability=AICapability.FORECASTING)
    assert len(forecast_models) == 1
    assert forecast_models[0].model_id == "chronos-t5-large"


def test_per_subsystem_model_configuration() -> None:
    """Verify typed per-subsystem model and provider configuration."""
    subsystems = AISubsystemsConfig(
        vision=SubsystemModelConfig(provider="google", model_id="gemini-2.0-flash"),
        forecasting=SubsystemModelConfig(provider="local", model_id="chronos-t5-large"),
        strategy_suggestor=SubsystemModelConfig(provider="google", model_id="gemini-2.0-flash"),
        strategy_reviewer=SubsystemModelConfig(provider="anthropic", model_id="claude-3-5-sonnet"),
        ocr=SubsystemModelConfig(provider="google", model_id="gemini-2.0-flash"),
    )

    assert subsystems.vision.provider == "google"
    assert subsystems.forecasting.provider == "local"
    assert subsystems.strategy_reviewer.provider == "anthropic"

    # Immutability
    with pytest.raises(ValidationError):
        setattr(subsystems.vision, "provider", "other")


def test_service_resolver_successful_resolution() -> None:
    """Verify AIServiceResolver validates and resolves functional engines."""
    registry = AIProviderRegistry()
    catalog = ModelCatalog()
    provider = MockFullProvider("mock")
    registry.register_provider(provider)

    for sub, cap in [
        ("vision-model", AICapability.VISION),
        ("forecast-model", AICapability.FORECASTING),
        ("suggest-model", AICapability.REASONING),
        ("review-model", AICapability.REASONING),
        ("ocr-model", AICapability.OCR),
    ]:
        catalog.register(
            ModelMetadata(
                provider="mock",
                model_id=sub,
                display_name=sub,
                capabilities={cap, AICapability.STRUCTURED_OUTPUT},
            )
        )

    creds = DictCredentialResolver({"mock": {"api_key": "test_secret_key"}})
    config = AIServiceConfig(subsystems=_create_sample_subsystems_config("mock"))

    resolver = AIServiceResolver(config, registry, catalog, creds)
    resolved = resolver.validate_all_subsystems()
    assert len(resolved) == 5
    assert resolved["vision"].model_id == "vision-model"

    v_engine = resolver.resolve_vision_engine()
    assert isinstance(v_engine, VisionEngine)

    f_engine = resolver.resolve_forecast_engine()
    assert isinstance(f_engine, ForecastEngine)

    s_suggestor = resolver.resolve_strategy_suggestor()
    assert isinstance(s_suggestor, StrategySuggestor)

    s_reviewer = resolver.resolve_strategy_reviewer()
    assert isinstance(s_reviewer, StrategyReviewer)


def test_unsupported_capability_error() -> None:
    """Verify attempting to resolve a subsystem with a model lacking capability fails."""
    registry = AIProviderRegistry()
    catalog = ModelCatalog()
    provider = MockFullProvider("mock")
    registry.register_provider(provider)

    # Forecasting model registered WITHOUT Vision capability
    catalog.register(
        ModelMetadata(
            provider="mock",
            model_id="text-only-model",
            display_name="Text Only Model",
            capabilities={AICapability.TEXT_GENERATION},
        )
    )

    creds = DictCredentialResolver({"mock": {"api_key": "key"}})
    subsystems = _create_sample_subsystems_config("mock")
    # Point vision subsystem to text-only model
    invalid_subsystems = AISubsystemsConfig(
        vision=SubsystemModelConfig(provider="mock", model_id="text-only-model"),
        forecasting=subsystems.forecasting,
        strategy_suggestor=subsystems.strategy_suggestor,
        strategy_reviewer=subsystems.strategy_reviewer,
        ocr=subsystems.ocr,
    )
    config = AIServiceConfig(subsystems=invalid_subsystems)
    resolver = AIServiceResolver(config, registry, catalog, creds)

    with pytest.raises(
        AIUnsupportedCapabilityError, match="does not support required capability 'vision'"
    ):
        resolver.resolve_vision_engine()


def test_missing_credentials_error() -> None:
    """Verify missing credentials produce explicit AICredentialError."""
    registry = AIProviderRegistry()
    catalog = ModelCatalog()
    provider = MockFullProvider("google")
    registry.register_provider(provider)

    catalog.register(
        ModelMetadata(
            provider="google",
            model_id="gemini-2.0-flash",
            display_name="Gemini 2.0 Flash",
            capabilities={AICapability.VISION},
        )
    )

    # Empty credentials resolver
    creds = DictCredentialResolver()
    subsystems = _create_sample_subsystems_config("google")
    invalid_subsystems = AISubsystemsConfig(
        vision=SubsystemModelConfig(provider="google", model_id="gemini-2.0-flash"),
        forecasting=subsystems.forecasting,
        strategy_suggestor=subsystems.strategy_suggestor,
        strategy_reviewer=subsystems.strategy_reviewer,
        ocr=subsystems.ocr,
    )
    config = AIServiceConfig(subsystems=invalid_subsystems)
    resolver = AIServiceResolver(config, registry, catalog, creds)

    with pytest.raises(AICredentialError, match="Missing required credential"):
        resolver.resolve_vision_engine(require_credentials=True)

    # EnvCredentialResolver check with non-existent env var
    env_creds = EnvCredentialResolver()
    env_resolver = AIServiceResolver(config, registry, catalog, env_creds)
    with pytest.raises(AICredentialError, match="Environment variable 'GOOGLE_API_KEY' is not set"):
        env_resolver.resolve_vision_engine(require_credentials=True)


def test_provider_unavailable_error() -> None:
    """Verify offline provider raises AIUnavailableError."""
    registry = AIProviderRegistry()
    catalog = ModelCatalog()
    # Offline provider (is_available() == False)
    provider = MockFullProvider("mock", available=False)
    registry.register_provider(provider)

    catalog.register(
        ModelMetadata(
            provider="mock",
            model_id="vision-model",
            display_name="Vision Model",
            capabilities={AICapability.VISION},
        )
    )

    creds = DictCredentialResolver({"mock": {"api_key": "key"}})
    config = AIServiceConfig(subsystems=_create_sample_subsystems_config("mock"))
    resolver = AIServiceResolver(config, registry, catalog, creds)

    with pytest.raises(AIUnavailableError, match="is currently unavailable"):
        resolver.resolve_vision_engine()


def test_budget_configuration_validation() -> None:
    """Verify AIBudgetConfig and ModelUsageLimit validate bounds and reject invalid values."""
    # Valid budget
    budget = AIBudgetConfig(
        max_total_spend=100.0,
        max_total_requests=5000,
        currency="USD",
        warn_spend_threshold_pct=0.85,
        model_limits={
            "gemini-2.0-flash": ModelUsageLimit(max_requests=1000, max_spend=25.0),
        },
    )
    assert budget.max_total_spend == 100.0
    assert budget.model_limits["gemini-2.0-flash"].max_requests == 1000

    # Negative total spend
    with pytest.raises(ValidationError):
        AIBudgetConfig(max_total_spend=-10.0)

    # Zero requests
    with pytest.raises(ValidationError):
        AIBudgetConfig(max_total_requests=0)

    # Threshold > 1.0
    with pytest.raises(ValidationError):
        AIBudgetConfig(warn_spend_threshold_pct=1.5)

    # Model limit negative spend
    with pytest.raises(ValidationError):
        ModelUsageLimit(max_spend=-5.0)


def test_deterministic_registry_and_catalog_behavior() -> None:
    """Verify registry and catalog listings are deterministic and alphabetically sorted."""
    registry = AIProviderRegistry()
    registry.register_provider(MockFullProvider("zebra"))
    registry.register_provider(MockFullProvider("apple"))
    registry.register_provider(MockFullProvider("mango"))

    # Must be sorted alphabetically
    assert registry.list_providers() == ["apple", "mango", "zebra"]

    catalog = ModelCatalog()
    catalog.register(
        ModelMetadata(
            provider="google",
            model_id="z-model",
            display_name="Z Model",
            capabilities={AICapability.TEXT_GENERATION},
        )
    )
    catalog.register(
        ModelMetadata(
            provider="anthropic",
            model_id="a-model",
            display_name="A Model",
            capabilities={AICapability.TEXT_GENERATION},
        )
    )
    catalog.register(
        ModelMetadata(
            provider="google",
            model_id="a-model",
            display_name="A Model",
            capabilities={AICapability.TEXT_GENERATION},
        )
    )

    models = catalog.list_models()
    keys = [(m.provider, m.model_id) for m in models]
    assert keys == [
        ("anthropic", "a-model"),
        ("google", "a-model"),
        ("google", "z-model"),
    ]


def test_globally_disabled_ai_service() -> None:
    """Verify globally disabled AI config rejects subsystem resolution cleanly."""
    registry = AIProviderRegistry()
    catalog = ModelCatalog()
    config = AIServiceConfig(
        enabled=False,
        subsystems=_create_sample_subsystems_config("mock"),
    )
    resolver = AIServiceResolver(config, registry, catalog)
    with pytest.raises(AIConfigError, match="globally disabled"):
        resolver.resolve_vision_engine()
