"""Global pytest configuration and shared fixtures for AdiTrader."""

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def project_root() -> Path:
    """Return the repository root directory."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def src_root(project_root: Path) -> Path:
    """Return the src root directory."""
    return project_root / "src" / "aditrader"
