"""AI Provider Adapters for external foundation model backends."""

from aditrader.ai.providers.google import GoogleAIProvider
from aditrader.ai.providers.ocrspace import OCRSpaceProvider
from aditrader.ai.providers.openrouter import OpenRouterProvider

__all__ = ["GoogleAIProvider", "OCRSpaceProvider", "OpenRouterProvider"]
