"""AI Subsystems & Advisory Pipeline.

This package provides abstract interfaces and data contracts for probabilistic
forecasting, multimodal chart vision, and strategy suggestion.

Per ADR 005 and ADR 012:
- All AI components are strictly advisory.
- Deterministic validation and risk engines hold absolute authority.
- No live broker routing or direct order execution.
"""

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
    AICredentialResolver,
    DictCredentialResolver,
    EnvCredentialResolver,
)
from aditrader.ai.errors import (
    AIConfigError,
    AICredentialError,
    AIError,
    AILookaheadError,
    AILowConfidenceError,
    AIMalformedOutputError,
    AIModelNotFoundError,
    AIProviderError,
    AIProviderNotFoundError,
    AITimeoutError,
    AIUnavailableError,
    AIUnsupportedCapabilityError,
)
from aditrader.ai.models import (
    AISourceType,
    BiasCfg,
    DossierSection,
    DossierSectionSourceType,
    ForecastResult,
    PatternObservation,
    ProvenanceRecord,
    ResearchDossier,
    SuggestionResult,
    VisionResult,
)
from aditrader.ai.registry import (
    AIProvider,
    AIProviderRegistry,
    BaseAIProvider,
)
from aditrader.ai.service import (
    AIServiceResolver,
    SubsystemName,
)

__all__ = [
    "AIBudgetConfig",
    "AICapability",
    "AIConfigError",
    "AICredentialError",
    "AICredentialResolver",
    "AIError",
    "AILookaheadError",
    "AILowConfidenceError",
    "AIMalformedOutputError",
    "AIModelNotFoundError",
    "AIProvider",
    "AIProviderError",
    "AIProviderNotFoundError",
    "AIProviderRegistry",
    "AIServiceConfig",
    "AIServiceResolver",
    "AISourceType",
    "AISubsystemsConfig",
    "AITimeoutError",
    "AIUnavailableError",
    "AIUnsupportedCapabilityError",
    "BaseAIProvider",
    "BiasCfg",
    "DictCredentialResolver",
    "DossierSection",
    "DossierSectionSourceType",
    "EnvCredentialResolver",
    "ForecastEngine",
    "ForecastResult",
    "ModelCatalog",
    "ModelContextLimits",
    "ModelMetadata",
    "ModelPricing",
    "ModelUsageLimit",
    "PatternObservation",
    "ProvenanceRecord",
    "ResearchDossier",
    "StrategyReviewer",
    "StrategySuggestor",
    "SubsystemModelConfig",
    "SubsystemName",
    "SuggestionResult",
    "VisionEngine",
    "VisionResult",
]
