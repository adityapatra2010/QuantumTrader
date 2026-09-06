"""Abstract base classes and provider-agnostic interfaces for AI subsystems.

Per ADR 005 and ADR 012:
- All external AI providers are abstracted behind pure interfaces.
- Core engines interact only with standardized ForecastResult, VisionResult, and SuggestionResult.
- Zero direct coupling to specific foundation model packages (Kronos, Chronos, Gemini).
- Zero live execution or order routing capabilities.
"""

from abc import ABC, abstractmethod
from typing import final

from aditrader.ai.errors import AIMalformedOutputError
from aditrader.ai.models import (
    BiasCfg,
    DossierSection,
    DossierSectionSourceType,
    ForecastResult,
    OCRResult,
    SuggestionResult,
    VisionResult,
)
from aditrader.core.models.market_data import Bar
from aditrader.strategy.builder.schema import StrategyDSL
from aditrader.validation.models import ValidationResult


class ForecastEngine(ABC):
    """Abstract interface for probabilistic time-series forecasting models."""

    @abstractmethod
    def forecast(self, history: list[Bar], horizon_bars: int = 5) -> ForecastResult:
        """Generate probabilistic price trajectory from closed historical bars.

        Args:
            history: Chronologically sorted list of closed historical OHLCV bars.
            horizon_bars: Number of steps into the future to forecast.

        Returns:
            ForecastResult with strict point-in-time cutoff and bounds validation.

        Raises:
            AIUnavailableError: If model or backend resources are offline.
            AITimeoutError: If computation exceeds deadline.
            AIMalformedOutputError: If model predictions violate envelope or sanity bounds.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if model weights, dependencies, and compute backend are operational.

        Must never raise network or runtime exceptions; returns False if backend is
        unreachable or unconfigured.
        """
        ...


class VisionEngine(ABC):
    """Abstract interface for multimodal chart screenshot analysis."""

    @abstractmethod
    def analyze(
        self,
        image_bytes: bytes,
        spot_price: float | None = None,
        ocr_result: OCRResult | None = None,
    ) -> VisionResult:
        """Extract observable support/resistance and patterns from chart imagery.

        Args:
            image_bytes: Raw bytes of uploaded chart image.
            spot_price: Optional prevailing spot price for coordinate envelope validation.
            ocr_result: Optional OCR-extracted text and bounding regions from a prior OCR stage.

        Returns:
            VisionResult containing detected structures, reasoning, and image hash.

        Raises:
            AIUnavailableError: If vision service or API credentials are offline.
            AITimeoutError: If processing exceeds deadline.
            AIMalformedOutputError: If output JSON is corrupted or invalid.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if vision service and API credentials are functional.

        Must never raise network or runtime exceptions; returns False if backend is
        unreachable or unconfigured.
        """
        ...


class OCREngine(ABC):
    """Abstract interface for optical character recognition engines."""

    @abstractmethod
    def extract_text(self, image_bytes: bytes) -> OCRResult:
        """Extract text and bounding regions from image bytes.

        Args:
            image_bytes: Raw bytes of uploaded chart or document image.

        Returns:
            OCRResult with extracted text, regions, and ProvenanceRecord.

        Raises:
            AIUnavailableError: If OCR service is offline or unconfigured.
            AITimeoutError: If OCR processing times out.
            AICredentialError: If API key is missing or invalid.
            AIMalformedOutputError: If output format is invalid or corrupted.
            AIProviderError: If OCR provider reports rate limit or server error.
        """
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Return True if OCR service and credentials are operational.

        Must never raise network or runtime exceptions; returns False if backend is
        unreachable or unconfigured.
        """
        ...


class StrategySuggestor(ABC):
    """Abstract interface for proposing declarative strategy structures matching market regime."""

    @abstractmethod
    def suggest(
        self,
        regime: str,
        bias: BiasCfg,
        forecast: ForecastResult | None = None,
        vision: VisionResult | None = None,
    ) -> SuggestionResult:
        """Generate a declarative strategy proposal matching regime and bias.

        Args:
            regime: Identified market regime name (e.g., 'Low IV Sideways', 'Trend Following').
            bias: Machine-readable selling vs. buying bias configuration.
            forecast: Optional probabilistic forecast artifact.
            vision: Optional multimodal chart extraction artifact.

        Returns:
            SuggestionResult containing declarative StrategyDSL and provenance.
        """
        ...


class StrategyReviewer(ABC):
    """Abstract interface for qualitative structural review of strategy dossiers."""

    @final
    def review(
        self,
        strategy: StrategyDSL,
        validation_result: ValidationResult,
    ) -> DossierSection:
        """Produce an advisory qualitative critique of strategy mechanics and failure modes.

        Enforces ADR 012 contract: The generated section MUST have
        source_type == DossierSectionSourceType.AI_ADVISORY and contain a valid ProvenanceRecord.

        Args:
            strategy: Declarative StrategyDSL evaluated.
            validation_result: Authoritative deterministic validation output.

        Returns:
            DossierSection strictly tagged with source_type=AI_ADVISORY and full model provenance.

        Raises:
            AIMalformedOutputError: If review output attempts to masquerade as DETERMINISTIC
                or any non-AI_ADVISORY source type, or if provenance is missing.
        """
        section = self._generate_review(strategy, validation_result)
        if section.source_type != DossierSectionSourceType.AI_ADVISORY:
            raise AIMalformedOutputError(
                f"StrategyReviewer output must have source_type={DossierSectionSourceType.AI_ADVISORY.value}, "
                f"got '{section.source_type.value}'"
            )
        if section.provenance is None:
            raise AIMalformedOutputError(
                "StrategyReviewer output must include a valid ProvenanceRecord"
            )
        return section

    @abstractmethod
    def _generate_review(
        self,
        strategy: StrategyDSL,
        validation_result: ValidationResult,
    ) -> DossierSection:
        """Internal provider hook to generate the qualitative review section.

        Subclasses must implement this method to produce the review content.
        The wrapper `review()` method enforces ADR 012 source_type invariants.
        """
        ...
