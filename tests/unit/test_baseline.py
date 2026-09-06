"""Phase 0 Baseline Tests verifying tooling, environment, directory layout, and persistence."""

import sys
from pathlib import Path

from sqlalchemy import create_engine, text

from aditrader.config.settings import get_settings


def test_python_runtime_version() -> None:
    """Verify runtime Python meets institutional standard (>= 3.11)."""
    assert sys.version_info >= (3, 11), f"Python version {sys.version} is below 3.11"


def test_package_import() -> None:
    """Verify core aditrader package is discoverable and importable."""
    import aditrader

    assert aditrader is not None


def test_settings_defaults() -> None:
    """Verify default system settings comply with specification."""
    settings = get_settings()
    assert settings.timezone == "Asia/Kolkata"
    assert settings.initial_capital == 1_000_000.0
    assert settings.max_margin_utilization == 0.85
    assert settings.intraday_max_drawdown == 0.05
    assert "aditrader.db" in settings.database_url


def test_architecture_directory_skeleton(project_root: Path) -> None:
    """Verify all 4 architectural layer directories exist strictly adhering to ARCHITECTURE.md."""
    src = project_root / "src" / "aditrader"
    required_packages = [
        src / "config",
        src / "data",
        src / "data" / "adapters",
        src / "data" / "feeds",
        src / "core",
        src / "core" / "ledger",
        src / "core" / "models",
        src / "core" / "risk",
        src / "options",
        src / "strategy",
        src / "strategy" / "builder",
        src / "strategy" / "compiler",
        src / "strategy" / "library",
        src / "backtesting",
        src / "validation",
        src / "validation" / "ast",
        src / "validation" / "institutional",
        src / "ai",
        src / "ai" / "forecasting",
        src / "ai" / "vision",
        src / "ai" / "reviewer",
        src / "ai" / "teacher",
        src / "ai" / "suggestor",
        src / "research",
        src / "ui",
        src / "ui" / "assets",
        src / "ui" / "pages",
        src / "cli",
    ]
    for pkg in required_packages:
        assert pkg.is_dir(), f"Required package directory missing: {pkg}"


def test_alembic_baseline_migration_exists(project_root: Path) -> None:
    """Verify Alembic configuration and baseline migration file are present."""
    alembic_ini = project_root / "alembic.ini"
    baseline_rev = project_root / "alembic" / "versions" / "0001_baseline.py"
    assert alembic_ini.is_file(), "alembic.ini missing"
    assert baseline_rev.is_file(), "0001_baseline.py missing"


def test_database_connectivity_sqlite_wal(tmp_path: Path) -> None:
    """Verify local SQLite connectivity and Write-Ahead Logging (WAL) configuration (ADR 008)."""
    db_file = tmp_path / "test_wal.db"
    engine = create_engine(f"sqlite:///{db_file}")
    with engine.connect() as conn:
        conn.execute(text("PRAGMA journal_mode=WAL;"))
        result = conn.execute(text("PRAGMA journal_mode;")).scalar()
        assert str(result).upper() == "WAL", f"Expected WAL journal mode, got {result}"
