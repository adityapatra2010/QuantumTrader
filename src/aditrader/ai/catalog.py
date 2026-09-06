"""Model catalog, typed metadata, and capability indexing for AI Subsystems.

Per Phase 7A:
- Capabilities are explicit, enum-typed, and queryable.
- Models do not assume universal capability support.
- Pricing and context limits are typed and optional.
"""

from collections.abc import Iterable
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from aditrader.ai.errors import AIConfigError, AIModelNotFoundError


class AICapability(StrEnum):
    """Explicit functional capabilities that AI models may support."""

    VISION = "vision"
    STRUCTURED_OUTPUT = "structured_output"
    TOOL_CALLING = "tool_calling"
    FORECASTING = "forecasting"
    REASONING = "reasoning"
    TEXT_GENERATION = "text_generation"
    OCR = "ocr"


class ModelPricing(BaseModel):
    """Pricing metadata for model inference accounting."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    input_cost_per_1k_tokens: float | None = Field(
        default=None, ge=0.0, description="Cost per 1,000 input/prompt tokens"
    )
    output_cost_per_1k_tokens: float | None = Field(
        default=None, ge=0.0, description="Cost per 1,000 output/completion tokens"
    )
    cost_per_image: float | None = Field(
        default=None, ge=0.0, description="Cost per input chart image"
    )
    currency: str = Field(default="USD", min_length=1, description="Currency code (e.g., USD, INR)")


class ModelContextLimits(BaseModel):
    """Context window and token boundary limits for a model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    max_context_tokens: int | None = Field(
        default=None, gt=0, description="Maximum total context window size in tokens"
    )
    max_output_tokens: int | None = Field(
        default=None, gt=0, description="Maximum completion/output tokens per request"
    )


class ModelMetadata(BaseModel):
    """Typed metadata and capability profile for a single AI model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    provider: str = Field(min_length=1, description="Provider identifier (e.g., 'google', 'local')")
    model_id: str = Field(min_length=1, description="Model identifier (e.g., 'gemini-2.0-flash')")
    display_name: str = Field(min_length=1, description="Human-readable model name")
    capabilities: set[AICapability] = Field(
        description="Explicit functional capabilities supported by this model"
    )
    availability: bool = Field(
        default=True, description="Whether this model is currently active/available"
    )
    context_limits: ModelContextLimits | None = Field(
        default=None, description="Optional context window and output limits"
    )
    pricing: ModelPricing | None = Field(
        default=None, description="Optional pricing and cost accounting metadata"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Arbitrary provider-specific or runtime metadata"
    )

    def has_capability(self, capability: AICapability | str) -> bool:
        """Check if the model supports a specific capability."""
        if isinstance(capability, AICapability):
            return capability in self.capabilities
        try:
            return AICapability(capability) in self.capabilities
        except ValueError:
            return False

    def has_capabilities(self, capabilities: Iterable[AICapability | str]) -> bool:
        """Check if the model supports all requested capabilities."""
        return all(self.has_capability(c) for c in capabilities)


class ModelCatalog:
    """In-memory catalog of available AI models with capability-based query indexing."""

    def __init__(self) -> None:
        self._models: dict[tuple[str, str], ModelMetadata] = {}

    def register(self, model: ModelMetadata, overwrite: bool = False) -> None:
        """Register model metadata into the catalog.

        Args:
            model: ModelMetadata instance to register.
            overwrite: If True, replace existing model with same (provider, model_id).
                       If False, raise AIConfigError on collision.
        """
        key = (model.provider.lower(), model.model_id.lower())
        if key in self._models and not overwrite:
            raise AIConfigError(
                f"Model '{model.model_id}' for provider '{model.provider}' is already registered"
            )
        self._models[key] = model

    def get(self, provider: str, model_id: str) -> ModelMetadata:
        """Retrieve model metadata by provider and model_id.

        Raises:
            AIModelNotFoundError: If model is not found in the catalog.
        """
        key = (provider.lower(), model_id.lower())
        if key not in self._models:
            raise AIModelNotFoundError(
                f"Model '{model_id}' under provider '{provider}' not found in catalog"
            )
        return self._models[key]

    def has_model(self, provider: str, model_id: str) -> bool:
        """Check whether a model is registered."""
        return (provider.lower(), model_id.lower()) in self._models

    def list_models(
        self,
        provider: str | None = None,
        capability: AICapability | str | None = None,
        only_available: bool = False,
    ) -> list[ModelMetadata]:
        """List models matching optional filters."""
        results: list[ModelMetadata] = []
        for model in self._models.values():
            if provider is not None and model.provider.lower() != provider.lower():
                continue
            if only_available and not model.availability:
                continue
            if capability is not None and not model.has_capability(capability):
                continue
            results.append(model)
        # Deterministic sorting by provider then model_id
        return sorted(results, key=lambda m: (m.provider, m.model_id))

    def count(self) -> int:
        """Return total number of registered models."""
        return len(self._models)

    def register_defaults(self) -> None:
        """Register default known foundation models into catalog."""
        # Google Gemini 2.0 Flash
        self.register(
            ModelMetadata(
                provider="google",
                model_id="gemini-2.0-flash",
                display_name="Gemini 2.0 Flash",
                capabilities={
                    AICapability.VISION,
                    AICapability.STRUCTURED_OUTPUT,
                    AICapability.TEXT_GENERATION,
                    AICapability.REASONING,
                    AICapability.OCR,
                },
                context_limits=ModelContextLimits(
                    max_context_tokens=1048576,
                    max_output_tokens=8192,
                ),
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.0001,
                    output_cost_per_1k_tokens=0.0004,
                    cost_per_image=0.00002,
                    currency="USD",
                ),
            ),
            overwrite=True,
        )
        # Google Gemini 1.5 Flash
        self.register(
            ModelMetadata(
                provider="google",
                model_id="gemini-1.5-flash",
                display_name="Gemini 1.5 Flash",
                capabilities={
                    AICapability.VISION,
                    AICapability.STRUCTURED_OUTPUT,
                    AICapability.TEXT_GENERATION,
                    AICapability.REASONING,
                    AICapability.OCR,
                },
                context_limits=ModelContextLimits(
                    max_context_tokens=1048576,
                    max_output_tokens=8192,
                ),
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.000075,
                    output_cost_per_1k_tokens=0.0003,
                    cost_per_image=0.00002,
                    currency="USD",
                ),
            ),
            overwrite=True,
        )
        # Google Gemini 1.5 Pro
        self.register(
            ModelMetadata(
                provider="google",
                model_id="gemini-1.5-pro",
                display_name="Gemini 1.5 Pro",
                capabilities={
                    AICapability.VISION,
                    AICapability.STRUCTURED_OUTPUT,
                    AICapability.TEXT_GENERATION,
                    AICapability.REASONING,
                    AICapability.OCR,
                },
                context_limits=ModelContextLimits(
                    max_context_tokens=2097152,
                    max_output_tokens=8192,
                ),
            ),
            overwrite=True,
        )
        # Google Text Embedding 004 (non-vision model for capability testing)
        self.register(
            ModelMetadata(
                provider="google",
                model_id="text-embedding-004",
                display_name="Text Embedding 004",
                capabilities={
                    AICapability.TEXT_GENERATION,
                },
            ),
            overwrite=True,
        )
        # OCR.Space Engine 2
        self.register(
            ModelMetadata(
                provider="ocrspace",
                model_id="ocr-engine-2",
                display_name="OCR.Space Engine 2",
                capabilities={
                    AICapability.OCR,
                },
                pricing=ModelPricing(
                    cost_per_image=0.0,
                    currency="USD",
                ),
            ),
            overwrite=True,
        )
        # OpenRouter - Gemma 4 26B A4B
        self.register(
            ModelMetadata(
                provider="openrouter",
                model_id="google/gemma-4-26b-a4b-it",
                display_name="Gemma 4 26B A4B (OpenRouter)",
                capabilities={
                    AICapability.VISION,
                    AICapability.STRUCTURED_OUTPUT,
                    AICapability.TEXT_GENERATION,
                    AICapability.REASONING,
                },
                context_limits=ModelContextLimits(
                    max_context_tokens=262144,
                    max_output_tokens=8192,
                ),
            ),
            overwrite=True,
        )
        # OpenRouter - Gemma 4 26B A4B Free tier
        self.register(
            ModelMetadata(
                provider="openrouter",
                model_id="google/gemma-4-26b-a4b-it:free",
                display_name="Gemma 4 26B A4B Free (OpenRouter)",
                capabilities={
                    AICapability.VISION,
                    AICapability.STRUCTURED_OUTPUT,
                    AICapability.TEXT_GENERATION,
                    AICapability.REASONING,
                },
                context_limits=ModelContextLimits(
                    max_context_tokens=262144,
                    max_output_tokens=8192,
                ),
                pricing=ModelPricing(
                    input_cost_per_1k_tokens=0.0,
                    output_cost_per_1k_tokens=0.0,
                    cost_per_image=0.0,
                    currency="USD",
                ),
            ),
            overwrite=True,
        )


def get_default_model_catalog() -> ModelCatalog:
    """Return a new ModelCatalog populated with default supported model metadata."""
    catalog = ModelCatalog()
    catalog.register_defaults()
    return catalog
