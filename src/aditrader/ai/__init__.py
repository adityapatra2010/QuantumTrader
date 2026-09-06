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
from aditrader.ai.errors import (
    AIConfigError,
    AIError,
    AILookaheadError,
    AILowConfidenceError,
    AIMalformedOutputError,
    AIProviderError,
    AITimeoutError,
    AIUnavailableError,
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

__all__ = [
    "AIConfigError",
    "AIError",
    "AILookaheadError",
    "AILowConfidenceError",
    "AIMalformedOutputError",
    "AIProviderError",
    "AISourceType",
    "AITimeoutError",
    "AIUnavailableError",
    "BiasCfg",
    "DossierSection",
    "DossierSectionSourceType",
    "ForecastEngine",
    "ForecastResult",
    "PatternObservation",
    "ProvenanceRecord",
    "ResearchDossier",
    "StrategyReviewer",
    "StrategySuggestor",
    "SuggestionResult",
    "VisionEngine",
    "VisionResult",
]
