"""Abstract base interface for strategy translators into canonical StrategyDSL."""

from abc import ABC, abstractmethod
from pathlib import Path

from aditrader.strategy.builder.schema import StrategyDSL


class BaseStrategyTranslator(ABC):
    """Contract for translating external strategy formats into StrategyDSL."""

    @abstractmethod
    def translate(
        self,
        content: str,
        *,
        default_underlying: str = "NIFTY",
        default_timeframe: str = "5m",
        file_path: str | Path | None = None,
    ) -> StrategyDSL:
        """Translate raw external script content into a valid StrategyDSL object.

        Raises:
            ValueError: If strategy contains lookahead bias, unsupported constructs,
                        or cannot be safely translated without semantic compromise.
        """
        pass
