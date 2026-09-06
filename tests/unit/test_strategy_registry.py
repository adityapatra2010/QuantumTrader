"""Unit tests verifying Strategy Registry version immutability and lookup behavior."""

from datetime import UTC, datetime

import pytest

from aditrader.strategy.library.models import (
    Directionality,
    MarketRegime,
    StrategyCategory,
    StrategyRecord,
)
from aditrader.strategy.library.registry import (
    StrategyNotFoundError,
    StrategyRegistry,
    StrategyVersionExistsError,
)
from aditrader.strategy.library.templates import (
    build_template_record,
    create_nifty_iron_condor_dsl,
)


def test_registry_loads_builtins_by_default() -> None:
    """Verify registry automatically indexes built-in templates."""
    registry = StrategyRegistry(load_builtins=True)
    all_strategies = registry.list_all()

    assert len(all_strategies) >= 3
    # Check iron condor presence
    ic = registry.get_by_name("Nifty Weekly Iron Condor")
    assert ic.name == "Nifty Weekly Iron Condor"
    assert ic.version == "1.0.0"


def test_version_immutability_enforced() -> None:
    """Verify attempting to overwrite an existing version raises StrategyVersionExistsError."""
    registry = StrategyRegistry(load_builtins=False)

    dsl = create_nifty_iron_condor_dsl()
    record_v1 = build_template_record(dsl, template_id="strat-1", version="1.0.0")
    registry.register(record_v1)

    # Attempting to re-register the same name and version must fail
    record_v1_duplicate = build_template_record(dsl, template_id="strat-1-copy", version="1.0.0")
    with pytest.raises(StrategyVersionExistsError) as exc_info:
        registry.register(record_v1_duplicate)
    assert "already exists and is immutable" in str(exc_info.value)

    # Registering a new version with the same name must succeed
    record_v2 = StrategyRecord(
        id="strat-1",
        name=record_v1.name,
        version="1.1.0",
        category=StrategyCategory.USER,
        creator="User",
        created_at=datetime(2026, 9, 7, 10, 0, tzinfo=UTC),
        validation_score=95.0,
        dna=record_v1.dna,
        dsl_definition=record_v1.dsl_definition,
    )
    registry.register(record_v2)

    # Lookup should retrieve the latest version (1.1.0) when unspecified
    latest = registry.get_by_name(record_v1.name)
    assert latest.version == "1.1.0"

    # Specific version lookup works
    v1_lookup = registry.get_by_name(record_v1.name, version="1.0.0")
    assert v1_lookup.version == "1.0.0"


def test_registry_not_found_errors() -> None:
    """Verify StrategyNotFoundError raised on non-existent strategies or versions."""
    registry = StrategyRegistry(load_builtins=False)

    with pytest.raises(StrategyNotFoundError):
        registry.get("non-existent-id")

    with pytest.raises(StrategyNotFoundError):
        registry.get_by_name("Non Existent Name")


def test_registry_query_filtering() -> None:
    """Verify registry querying by category, directionality, and regime."""
    registry = StrategyRegistry(load_builtins=True)

    delta_neutral = registry.query(directionality=Directionality.DELTA_NEUTRAL)
    assert len(delta_neutral) >= 2  # Iron Condor, Long Straddle

    trending = registry.query(target_regime=MarketRegime.TREND_FOLLOWING)
    assert len(trending) >= 1  # Bull Call Spread
