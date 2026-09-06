"""Version-controlled strategy registry with DNA indexing and immutability guarantees."""

import threading

from aditrader.strategy.library.models import (
    Directionality,
    MarketRegime,
    StrategyCategory,
    StrategyRecord,
)
from aditrader.strategy.library.templates import get_builtin_templates


class StrategyRegistryError(Exception):
    """Base exception for strategy registry errors."""


class StrategyVersionExistsError(StrategyRegistryError):
    """Raised when attempting to overwrite an existing strategy version."""


class StrategyNotFoundError(StrategyRegistryError):
    """Raised when a requested strategy or version is not present in the registry."""


class StrategyRegistry:
    """Thread-safe, version-controlled catalog of trading strategies."""

    def __init__(self, load_builtins: bool = True) -> None:
        self._lock = threading.RLock()
        # id -> {version -> StrategyRecord}
        self._by_id: dict[str, dict[str, StrategyRecord]] = {}
        # name -> {version -> StrategyRecord}
        self._by_name: dict[str, dict[str, StrategyRecord]] = {}

        if load_builtins:
            for template in get_builtin_templates().values():
                self.register(template)

    def register(self, record: StrategyRecord) -> None:
        """Register a versioned strategy record into the catalog.

        Args:
            record: Immutable StrategyRecord instance.

        Raises:
            StrategyVersionExistsError: If a strategy with the same (name, version)
                or (id, version) is already registered.
        """
        with self._lock:
            if record.id in self._by_id and record.version in self._by_id[record.id]:
                raise StrategyVersionExistsError(
                    f"Strategy ID '{record.id}' version '{record.version}' already exists and is immutable."
                )

            if record.name in self._by_name and record.version in self._by_name[record.name]:
                raise StrategyVersionExistsError(
                    f"Strategy name '{record.name}' version '{record.version}' already exists and is immutable."
                )

            if record.id not in self._by_id:
                self._by_id[record.id] = {}
            self._by_id[record.id][record.version] = record

            if record.name not in self._by_name:
                self._by_name[record.name] = {}
            self._by_name[record.name][record.version] = record

    def get(self, strategy_id: str, version: str | None = None) -> StrategyRecord:
        """Retrieve strategy by ID and optional version.

        If version is None, the most recently registered version is returned.
        """
        with self._lock:
            versions = self._by_id.get(strategy_id)
            if not versions:
                raise StrategyNotFoundError(f"Strategy ID '{strategy_id}' not found in registry.")

            if version is not None:
                if version not in versions:
                    raise StrategyNotFoundError(
                        f"Version '{version}' not found for strategy ID '{strategy_id}'."
                    )
                return versions[version]

            # Return latest registered version
            return list(versions.values())[-1]

    def get_by_name(self, name: str, version: str | None = None) -> StrategyRecord:
        """Retrieve strategy by name and optional version.

        If version is None, the most recently registered version is returned.
        """
        with self._lock:
            versions = self._by_name.get(name)
            if not versions:
                raise StrategyNotFoundError(f"Strategy named '{name}' not found in registry.")

            if version is not None:
                if version not in versions:
                    raise StrategyNotFoundError(
                        f"Version '{version}' not found for strategy named '{name}'."
                    )
                return versions[version]

            return list(versions.values())[-1]

    def list_all(self) -> list[StrategyRecord]:
        """Return all registered strategy records across all versions."""
        with self._lock:
            records: list[StrategyRecord] = []
            for version_map in self._by_id.values():
                records.extend(version_map.values())
            return records

    def query(
        self,
        category: StrategyCategory | None = None,
        directionality: Directionality | None = None,
        target_regime: MarketRegime | None = None,
    ) -> list[StrategyRecord]:
        """Query strategy records filtered by category and DNA vector attributes."""
        with self._lock:
            matches: list[StrategyRecord] = []
            for record in self.list_all():
                if category is not None and record.category != category:
                    continue
                if directionality is not None and record.dna.directionality != directionality:
                    continue
                if target_regime is not None and record.dna.target_regime != target_regime:
                    continue
                matches.append(record)
            return matches
