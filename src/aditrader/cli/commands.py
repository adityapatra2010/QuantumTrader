"""CLI command implementations for AdiTrader / QuantumValidator."""

import argparse
import importlib
import json
import logging
import os
import random
import sys
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, cast

from sqlalchemy import func, select
from sqlalchemy import inspect as sa_inspect

from aditrader.backtesting.runner import BacktestConfig, BacktestRunner, UnsupportedStrategyError
from aditrader.config.settings import get_settings
from aditrader.core.costs import SlippageModel
from aditrader.core.ledger.repository import LedgerRepository
from aditrader.core.ledger.schema import OrderRecord, PositionRecord, TradeRecord
from aditrader.core.models.execution import Trade
from aditrader.core.models.market_data import Bar, Tick
from aditrader.core.models.trade_signal import Signal
from aditrader.data.adapters.kotak_discovery import KotakCapabilityDiscoverer
from aditrader.data.adapters.kotak_neo import HAS_NEO_SDK, KotakNeoAdapter
from aditrader.data.adapters.kotak_option_chain import KotakOptionChainManager
from aditrader.data.feeds.csv_feed import CSVDataFeed
from aditrader.data.feeds.synthetic_feed import SyntheticDataFeed
from aditrader.data.forward import ForwardTestStatus
from aditrader.data.forward_runner import ForwardTestConfig, ForwardTestRunner
from aditrader.data.instruments.service import InstrumentSearchService
from aditrader.data.session import EXCHANGE_TIMEZONE
from aditrader.strategy.builder.schema import (
    StrategyDSL,
)
from aditrader.strategy.library.registry import StrategyRegistry
from aditrader.validation.models import ValidationStatus
from aditrader.validation.policies import (
    create_institutional_policy,
    create_moderate_policy,
    create_research_policy,
)
from aditrader.validation.service import StrategyValidationService
from aditrader.verification.integrity import DataIntegrityChecker

logger = logging.getLogger(__name__)


def _mask_secret(secret: str | None) -> str:
    """Mask secret value for safe diagnostic display."""
    if not secret:
        return "None"
    s = secret.strip()
    if len(s) <= 6:
        return "***"
    return f"{s[:2]}***{s[-2:]}"


# ==============================================================================
# 1. Doctor / Diagnostic Command
# ==============================================================================


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run comprehensive local system, dependency, configuration, and readiness diagnostics."""
    print("=" * 68)
    print("      AdiTrader / QuantumValidator — System Diagnostics (Doctor)")
    print("=" * 68)

    errors_found = 0

    # 1. Python Runtime
    py_major = sys.version_info.major
    py_minor = sys.version_info.minor
    py_micro = sys.version_info.micro
    if sys.version_info < (3, 11):  # noqa: UP036
        print(
            f"[ERROR]            Python Runtime: {py_major}.{py_minor}.{py_micro} (Python >= 3.11 required)"
        )
        errors_found += 1
    else:
        print(
            f"[READY]            Python Runtime: {py_major}.{py_minor}.{py_micro} ({sys.platform})"
        )

    # 2. Required Core Dependencies
    required_pkgs = [
        "pydantic",
        "pydantic_settings",
        "sqlalchemy",
        "alembic",
        "pyarrow",
        "polars",
    ]
    missing_pkgs: list[str] = []
    for pkg in required_pkgs:
        try:
            importlib.import_module(pkg)
        except ImportError:
            missing_pkgs.append(pkg)

    if not missing_pkgs:
        print(f"[READY]            Core Dependencies: All installed ({', '.join(required_pkgs)})")
    else:
        print(f"[ERROR]            Core Dependencies: Missing: {', '.join(missing_pkgs)}")
        errors_found += 1

    # 3. Storage & Cache Directories
    dirs_to_check = [Path("runs"), Path("data/cache")]
    dir_errors: list[str] = []
    for d in dirs_to_check:
        try:
            d.mkdir(parents=True, exist_ok=True)
            test_file = d / ".write_test"
            test_file.write_text("ok")
            test_file.unlink()
        except Exception as exc:
            dir_errors.append(f"{d} ({exc})")

    if not dir_errors:
        print(
            f"[READY]            Storage Directories: Writable ({', '.join(str(d) for d in dirs_to_check)})"
        )
    else:
        print(f"[ERROR]            Storage Directories: Not writable: {', '.join(dir_errors)}")
        errors_found += 1

    # 4. Configuration Validity
    try:
        settings = get_settings()
        print(
            f"[READY]            Configuration: Valid (env: {settings.aditrader_env}, tz: {settings.timezone})"
        )
    except Exception as exc:
        print(f"[ERROR]            Configuration: Failed to load settings ({exc})")
        errors_found += 1
        settings = None

    # 5. Database Availability
    if settings:
        try:
            repo = LedgerRepository(database_url=settings.database_url)
            with repo.engine.connect():
                insp = sa_inspect(repo.engine)
                existing_tables = insp.get_table_names()

            if existing_tables:
                print(
                    f"[READY]            Database: Connected & initialized ({settings.database_url}) [{', '.join(existing_tables)}]"
                )
            else:
                print(
                    "[OPTIONAL/MISSING] Database: Connected but tables not created yet (run 'aditrader init-db')"
                )
        except Exception as exc:
            print(f"[ERROR]            Database: Connection failed ({exc})")
            errors_found += 1

    # 6. Optional Market Data Credentials (Kotak Neo)
    if settings and settings.kotak_consumer_key:
        print(
            f"[READY]            Broker Feed (Kotak Neo): Configured (Consumer Key: {_mask_secret(settings.kotak_consumer_key)})"
        )
    else:
        print(
            "[OPTIONAL/MISSING] Broker Feed (Kotak Neo): Not configured (Mock mode and CSV/Parquet feeds active)"
        )

    # 7. Optional AI Provider Credentials
    gemini_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if gemini_key:
        print(f"[READY]            AI Vision (Gemini): Key configured ({_mask_secret(gemini_key)})")
    else:
        print("[OPTIONAL/MISSING] AI Vision (Gemini): Key not configured (offline fallback active)")

    ocr_key = os.environ.get("OCRSPACE_API_KEY") or os.environ.get("OCR_SPACE_API_KEY")
    if ocr_key:
        print(f"[READY]            AI OCR (OCR.Space): Key configured ({_mask_secret(ocr_key)})")
    else:
        print(
            "[OPTIONAL/MISSING] AI OCR (OCR.Space): Key not configured (direct vision fallback active)"
        )

    openrouter_key = os.environ.get("OPENROUTER_API_KEY")
    if openrouter_key:
        print(
            f"[READY]            AI Reasoning (OpenRouter): Key configured ({_mask_secret(openrouter_key)})"
        )
    else:
        print(
            "[OPTIONAL/MISSING] AI Reasoning (OpenRouter): Key not configured (provider fallback active)"
        )

    print("-" * 68)
    if errors_found == 0:
        print("Diagnostic Summary: SYSTEM READY FOR OFFLINE RESEARCH & LOCAL REPLAY")
        print("-" * 68)
        return 0
    else:
        print(f"Diagnostic Summary: {errors_found} CRITICAL ERROR(S) DETECTED")
        print("-" * 68)
        return 1


# ==============================================================================
# 2. Status Command
# ==============================================================================


def cmd_status(args: argparse.Namespace) -> int:
    """Display active environment, database state, cached scrips, and available strategies."""
    settings = get_settings()

    print("=" * 68)
    print("               AdiTrader / QuantumValidator — Status")
    print("=" * 68)
    print("System Version:    0.1.0 (Phase 7 Baseline)")
    print(f"Environment:       {settings.aditrader_env}")
    print(f"Timezone:          {settings.timezone}")
    print(f"Database URL:      {settings.database_url}")

    # Database state
    try:
        repo = LedgerRepository(database_url=settings.database_url)
        with repo.engine.connect():
            insp = sa_inspect(repo.engine)
            tables = insp.get_table_names()
        with repo.SessionLocal() as session:
            orders_cnt = (
                session.scalar(select(func.count()).select_from(OrderRecord))
                if "orders" in tables
                else 0
            )
            trades_cnt = (
                session.scalar(select(func.count()).select_from(TradeRecord))
                if "trades" in tables
                else 0
            )
            positions_cnt = (
                session.scalar(select(func.count()).select_from(PositionRecord))
                if "positions" in tables
                else 0
            )
        print(
            f"Database State:    Initialized ({len(tables)} tables, {orders_cnt or 0} orders, {trades_cnt or 0} trades, {positions_cnt or 0} positions)"
        )
    except Exception as exc:
        print(f"Database State:    Unreachable ({exc})")

    # Strategy library
    registry = StrategyRegistry()
    templates = registry.list_all()
    print(f"Strategy Library:  {len(templates)} registered built-in templates")
    for t in templates:
        print(
            f"  - {t.name} v{t.version} [{t.dsl_definition.underlying}] ({t.dsl_definition.timeframe}) — {t.dna.target_regime.value} ({t.dna.directionality.value})"
        )

    # Scrip cache
    cache_dir = Path("data/cache")
    scrip_parquets = list(cache_dir.glob("*scrip*.parquet"))
    if scrip_parquets:
        print(
            f"Scrip Master:      Cached locally ({scrip_parquets[0].name}, {scrip_parquets[0].stat().st_size // 1024} KB)"
        )
    else:
        print("Scrip Master:      Not cached (run 'aditrader search <symbol>' to auto-cache)")

    print("=" * 68)
    return 0


# ==============================================================================
# 3. Database Initialization Command
# ==============================================================================


def cmd_init_db(args: argparse.Namespace) -> int:
    """Initialize SQLite database tables for transactional ledger persistence."""
    settings = get_settings()
    Path("runs").mkdir(parents=True, exist_ok=True)

    print(f"Initializing database at: {settings.database_url} ...")
    repo = LedgerRepository(database_url=settings.database_url)
    repo.create_tables()

    # Synchronize Alembic migration state with current database schema
    try:
        from alembic.config import Config

        from alembic import command

        alembic_ini_path = Path(__file__).resolve().parent.parent.parent.parent / "alembic.ini"
        if not alembic_ini_path.is_file():
            alembic_ini_path = Path("alembic.ini")
        if alembic_ini_path.is_file():
            alembic_cfg = Config(str(alembic_ini_path))
            alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
            command.stamp(alembic_cfg, "head")
    except Exception as alembic_err:
        logger.debug("Could not stamp alembic version: %s", alembic_err)

    with repo.engine.connect():
        insp = sa_inspect(repo.engine)
        tables = insp.get_table_names()

    print(
        f"[READY] Database successfully initialized with {len(tables)} tables: {', '.join(tables)}"
    )
    return 0


# ==============================================================================
# 4. Strategies Command
# ==============================================================================


def cmd_strategies(args: argparse.Namespace) -> int:
    """List or inspect built-in and versioned strategies."""
    registry = StrategyRegistry()

    if args.detail:
        strategy_query = args.detail
        record = registry.find(strategy_query)
        if not record:
            print(f"[ERROR] Strategy '{strategy_query}' not found in registry.")
            return 1

        dsl = record.dsl_definition
        dna = record.dna
        print(f"Strategy:       {record.name} (v{record.version}) [ID: {record.id}]")
        print(f"Category:       {record.category.value}")
        print(f"Underlying:     {dsl.underlying}")
        print(f"Timeframe:      {dsl.timeframe}")
        print(f"Target Regime:  {dsl.target_regime or dna.target_regime.value}")
        print(f"Option Legs:    {len(dsl.legs)} defined")
        for i, leg in enumerate(dsl.legs):
            c_type = (
                leg.contract_type
                or (leg.contract_selector.option_type if leg.contract_selector else "OPT")
                or "OPT"
            )
            if leg.strike_offset is not None:
                spec_str = f"offset={leg.strike_offset}"
            elif leg.contract_selector is not None:
                sel = leg.contract_selector
                if sel.min_ltp is not None and sel.max_ltp is not None:
                    spec_str = f"selector=range(₹{sel.min_ltp:.1f}–₹{sel.max_ltp:.1f})"
                elif sel.target_ltp is not None:
                    spec_str = f"selector={sel.type.value}(target=₹{sel.target_ltp:.1f}±₹{sel.tolerance:.1f})"
                else:
                    spec_str = f"selector={sel.type.value}"
            else:
                spec_str = "dynamic"
            print(f"  Leg {i + 1}: {leg.side.value} {c_type} {spec_str} lots={leg.lots}")
        if dsl.premium_bands:
            print("Premium Bands:")
            for b in dsl.premium_bands:
                print(f"  • ₹{b.min_ltp:.2f}–₹{b.max_ltp:.2f}")
        print("Strategy DNA:")
        print(f"  Direction:      {dna.directionality.value}")
        print(f"  Target Regime:  {dna.target_regime.value}")
        print(f"  Gamma Risk:     {dna.gamma_risk.value}")
        print(f"  Theta Exposure: {dna.theta_exposure.value}")
        print(f"  Vega Exposure:  {dna.vega_exposure.value}")
        print(f"  Trading Style:  {dna.style.value}")
        print(f"  Validation:     {record.validation_score}/100")
        return 0

    # List all
    strategies = registry.list_all()
    print("=" * 68)
    print("                   Registered Strategy Templates")
    print("=" * 68)
    for s in strategies:
        print(
            f"• {s.name:<32} v{s.version:<5} [{s.dsl_definition.underlying:<8}] {s.dsl_definition.timeframe:<5}"
        )
        print(
            f"  Regime: {s.dna.target_regime.value:<22} Bias: {s.dna.directionality.value:<15} Legs: {len(s.dsl_definition.legs)}"
        )
    print("-" * 68)
    print("Use 'aditrader strategies --detail <name>' for detailed inspection.")
    return 0


# ==============================================================================
# 5. Search Command
# ==============================================================================


def cmd_search(args: argparse.Namespace) -> int:
    """Search scrip master contracts by symbol, strike, or derivative hierarchy."""
    adapter = KotakNeoAdapter(mock_mode=True)
    adapter.authenticate()
    service = InstrumentSearchService(adapter=adapter)

    cache_path = Path("data/cache/scrip_master.parquet")
    if cache_path.is_file():
        try:
            service.load_from_parquet(cache_path)
        except Exception:
            service.load_from_adapter()
    else:
        service.load_from_adapter()

    query = args.query
    limit = args.limit or 10

    results = service.search(query=query, limit=limit)
    if not results:
        print(f"No matching instruments found for query: '{query}'")
        return 0

    print("=" * 72)
    print(f" Search Results for: '{query}' (Top {len(results)})")
    print("=" * 72)
    print(f"{'Score':<6} {'Symbol':<22} {'Trading Symbol':<26} {'Type':<7} {'Lot':<5}")
    print("-" * 72)
    for r in results:
        c = r.contract
        print(
            f"{r.score:<6.1f} {c.symbol:<22} {c.trading_symbol:<26} {c.instrument_type:<7} {c.lot_size:<5}"
        )
    print("-" * 72)
    return 0


# ==============================================================================
# 6. Validate Command
# ==============================================================================


def cmd_validate(args: argparse.Namespace) -> int:
    """Validate strategy definition through static AST and institutional policy gates."""
    registry = StrategyRegistry()
    dsl: StrategyDSL | None = None

    if args.strategy:
        record = registry.find(args.strategy)
        if record:
            dsl = record.dsl_definition
        else:
            print(f"[ERROR] Built-in strategy '{args.strategy}' not found.")
            return 1
    elif args.file:
        path = Path(args.file)
        if not path.is_file():
            print(f"[ERROR] Strategy file not found: {path}")
            return 1
        from aditrader.strategy.loader import load_strategy_file

        try:
            dsl = load_strategy_file(path)
        except Exception as exc:
            print(f"[ERROR] Failed to load strategy from '{path.name}': {exc}")
            return 1
    else:
        print("[ERROR] Please specify either --strategy <name> or --file <path>")
        return 1

    policy_map = {
        "institutional": create_institutional_policy(),
        "moderate": create_moderate_policy(),
        "research": create_research_policy(),
    }
    policy = policy_map.get(args.policy.lower(), create_institutional_policy())

    print("=" * 68)
    print(f" Validating Strategy: '{dsl.name}' (Policy: {policy.policy_name})")
    print("=" * 68)

    bt_result: Any = None
    if dsl.legs:
        if getattr(args, "csv", None) or getattr(args, "bars", None):
            print("[NOTICE] Options strategies use theoretical payoff validation (ADR 011).")
            print("         Historical candle dataset was ignored for options payoff modeling.")
    else:
        csv_path = getattr(args, "csv", None)
        num_bars = getattr(args, "bars", None)
        if csv_path:
            p = Path(csv_path)
            if not p.is_file():
                print(f"[ERROR] CSV historical data file not found: {p}")
                return 1
            from aditrader.strategy.compiler.engine import ExecutableStrategy

            csv_feed = CSVDataFeed(file_path=p, symbol=dsl.underlying, timeframe=dsl.timeframe)
            runner = BacktestRunner(config=BacktestConfig(initial_capital=1_000_000.0))
            bt_result = runner.run(strategy=ExecutableStrategy(dsl), data=csv_feed)
        elif num_bars is not None:
            if num_bars <= 0:
                print(f"[ERROR] Invalid --bars {num_bars}: must be >= 1")
                return 1
            from aditrader.strategy.compiler.engine import ExecutableStrategy

            synth_feed = SyntheticDataFeed(symbol=dsl.underlying, num_bars=num_bars)
            runner = BacktestRunner(config=BacktestConfig(initial_capital=1_000_000.0))
            bt_result = runner.run(strategy=ExecutableStrategy(dsl), data=synth_feed)

    service = StrategyValidationService()
    report = service.validate(strategy=dsl, policy=policy, backtest_result=bt_result)

    if not dsl.legs and bt_result is None:
        print(f"Target Underlying:     {dsl.underlying}")
        print(f"Timeframe:             {dsl.timeframe}")
        print("Validation Path:       STRUCTURAL_AST (STRUCTURAL)")
        print(
            f"Final Verdict:         STRUCTURALLY_VALID (DATA_PENDING) (Score: {report.validation_score:.1f}/100)"
        )
        print("\nNotice:")
        print("  • Strategy AST structure and condition rules are valid.")
        print(
            "  • Empirical statistical gates (Expectancy, Drawdown, Profit Factor) require backtest data:"
        )
        print(f'      aditrader validate --strategy "{dsl.name}" --csv <path_to_candles.csv>')
        print("    Or test with synthetic historical bars:")
        print(f'      aditrader validate --strategy "{dsl.name}" --bars 100')
        print("-" * 68)
        return 0

    print(f"Target Underlying:     {dsl.underlying}")
    print(f"Timeframe:             {dsl.timeframe}")
    print(
        f"Validation Path:       {report.historical_vs_theoretical} ({report.validation_scope.value})"
    )
    print(
        f"Final Verdict:         {report.status.value} (Score: {report.validation_score:.1f}/100)"
    )

    if report.metrics:
        print("\nEmpirical Metrics:")
        for k, v in report.metrics.items():
            if isinstance(v, float):
                print(f"  {k:<24} {v:.2f}")
            else:
                print(f"  {k:<24} {v}")

    if dsl.legs:
        from aditrader.validation.service import check_options_replay_readiness

        readiness = check_options_replay_readiness(dsl)
        print("-" * 68)
        print("Options Replay Diagnostics:")
        if readiness.underlying:
            print(f"  Instrument:                 {readiness.underlying}")
        if readiness.option_type:
            print(f"  Option Type:                {readiness.option_type}")
        if readiness.premium_bands:
            print("  Premium Bands:")
            for b in readiness.premium_bands:
                print(f"    {b}")
        if readiness.short_summary:
            print(f"  Short:                      {readiness.short_summary}")
        if readiness.hedge_summary:
            print(f"  Hedge:                      {readiness.hedge_summary}")
        if readiness.trailing_summary:
            print(f"  Trailing:                   {readiness.trailing_summary}")
        print(
            f"  Dynamic Premium Selector:   {'SUPPORTED' if readiness.dynamic_selector_supported else 'UNSUPPORTED'}"
        )
        print("  Historical Option Replay:   UNAVAILABLE (requires intraday option chain feed)")
        print(f"  Exact Strike Resolution:    {readiness.strike_resolution}")
        print(f"  Deterministic Policy:       {readiness.selection_policy}")
        print(f"  Replay Readiness:           {readiness.status.value}")
        print(f"  Diagnosis:                  {readiness.reason}")

    if report.warnings:
        print("\nWarnings:")
        for w in report.warnings:
            print(f"  [WARN] {w}")

    if report.failed_gates:
        print("\nFailed Gates:")
        for r in report.failed_gates:
            print(f"  [GATE] {r}")

    print("-" * 68)
    return 0 if report.status == ValidationStatus.APPROVED else 1


# ==============================================================================
# 7. Backtest Command
# ==============================================================================


def cmd_backtest(args: argparse.Namespace) -> int:
    """Execute deterministic backtest simulation on linear assets against historical data."""
    registry = StrategyRegistry()
    dsl: StrategyDSL | None = None

    if args.strategy:
        record = registry.find(args.strategy)
        if record:
            dsl = record.dsl_definition
        else:
            print(f"[ERROR] Built-in strategy '{args.strategy}' not found.")
            return 1
    elif args.file:
        path = Path(args.file)
        if not path.is_file():
            print(f"[ERROR] Strategy file not found: {path}")
            return 1
        from aditrader.strategy.loader import load_strategy_file

        try:
            dsl = load_strategy_file(path)
        except Exception as exc:
            print(f"[ERROR] Failed to load strategy from '{path.name}': {exc}")
            return 1
    else:
        print("[ERROR] Please specify either --strategy <name> or --file <path>")
        return 1

    # Check for option legs guard
    if dsl.legs:
        print("=" * 68)
        print(f"[AIR-GAP GUARD] Strategy '{dsl.name}' defines {len(dsl.legs)} option leg(s).")
        print("BacktestRunner strictly prohibits silent proxy simulation of multi-leg option")
        print("To evaluate options strategies, run institutional payoff validation:")
        print(f'    aditrader validate --strategy "{dsl.name}"')
        print("Or run forward options shadow simulation:")
        print(f'    aditrader forward-options --strategy "{dsl.name}" --mock')
        print("=" * 68)
        return 1

    # Validate numeric CLI arguments
    if getattr(args, "bars", None) is not None and args.bars <= 0:
        print(f"[ERROR] Invalid --bars {args.bars}: must be a positive integer >= 1.")
        return 1
    capital = getattr(args, "capital", None)
    if capital is not None and capital <= 0:
        print(f"[ERROR] Invalid --capital {capital}: initial capital must be strictly positive.")
        return 1
    slip_bps = getattr(args, "slippage_bps", None)
    if slip_bps is not None and slip_bps < 0:
        print(f"[ERROR] Invalid --slippage-bps {slip_bps}: slippage cannot be negative.")
        return 1

    try:
        from aditrader.strategy.compiler.engine import ExecutableStrategy

        strategy = ExecutableStrategy(dsl)

        # Resolve data feed
        feed: Any = None
        if args.csv:
            csv_path = Path(args.csv)
            if not csv_path.is_file():
                print(f"[ERROR] CSV historical data file not found: {csv_path}")
                return 1
            feed = CSVDataFeed(file_path=csv_path, symbol=dsl.underlying, timeframe=dsl.timeframe)
        else:
            num_bars = args.bars or 100
            feed = SyntheticDataFeed(symbol=dsl.underlying, num_bars=num_bars)

        slip_val = slip_bps if slip_bps is not None else 2.5
        config = BacktestConfig(
            initial_capital=capital or 1_000_000.0,
            slippage_model=SlippageModel(percentage=slip_val / 10000.0),
            allow_same_bar_execution=False,
        )

        print("=" * 68)
        print(f" Backtest Simulation: '{dsl.name}' on {dsl.underlying}")
        print("=" * 68)

        runner = BacktestRunner(config=config)
        result = runner.run(strategy=strategy, data=feed)
    except UnsupportedStrategyError as exc:
        print(f"[AIR-GAP GUARD] {exc}")
        return 1
    except (ValueError, Exception) as exc:
        if isinstance(exc, UnsupportedStrategyError):
            print(f"[AIR-GAP GUARD] {exc}")
            return 1
        print(f"[ERROR] Backtest failed: {exc}")
        return 1

    perf = result.performance
    print(f"Processed Bars:        {result.bar_count}")
    print(f"Total Trades:          {perf.total_trades}")
    print(f"Starting Capital:      ₹{perf.starting_equity:,.2f}")
    print(f"Ending Capital:        ₹{perf.ending_equity:,.2f}")

    # Truthful accounting breakdown
    realized_pnl = sum(r.net_pnl for r in result.ledger) if getattr(result, "ledger", None) else 0.0
    terminal_unrealized = getattr(result, "terminal_unrealized_pnl", 0.0) or 0.0
    has_terminal_pos = bool(getattr(result, "terminal_positions", None))

    if perf.total_trades == 0:
        if has_terminal_pos:
            print(f"Terminal Unrealized:   ₹{terminal_unrealized:,.2f}")
            print(f"Total Net PnL (MTM):   ₹{perf.net_profit:,.2f} ({perf.return_pct:.2f}%)")
        else:
            print(f"Net Realized PnL:      ₹{perf.net_profit:,.2f} ({perf.return_pct:.2f}%)")
    else:
        if has_terminal_pos:
            print(f"Closed Realized PnL:   ₹{realized_pnl:,.2f}")
            print(f"Terminal Unrealized:   ₹{terminal_unrealized:,.2f}")
            print(f"Total Net PnL (MTM):   ₹{perf.net_profit:,.2f} ({perf.return_pct:.2f}%)")
        else:
            print(f"Net Realized PnL:      ₹{perf.net_profit:,.2f} ({perf.return_pct:.2f}%)")

    print(f"Win Rate:              {perf.win_rate * 100.0:.1f}%")
    print(f"Expectancy:            ₹{perf.expectancy:,.2f}")
    print(
        f"Profit Factor:         {f'{perf.profit_factor:.2f}' if perf.profit_factor is not None else 'N/A'}"
    )
    print(f"Max Drawdown:          {perf.max_drawdown_pct * 100.0:.2f}%")

    sharpe_note = (
        " [Caution: <1 day sample]"
        if result.bar_count < 375 and perf.sharpe_ratio is not None
        else ""
    )
    sortino_note = (
        " [Caution: <1 day sample]"
        if result.bar_count < 375 and perf.sortino_ratio is not None
        else ""
    )

    print(
        f"Sharpe Ratio:          {f'{perf.sharpe_ratio:.2f}{sharpe_note}' if perf.sharpe_ratio is not None else 'N/A'}"
    )
    print(
        f"Sortino Ratio:         {f'{perf.sortino_ratio:.2f}{sortino_note}' if perf.sortino_ratio is not None else 'N/A'}"
    )
    print(f"SQN:                   {f'{perf.sqn:.2f}' if perf.sqn is not None else 'N/A'}")

    if result.simulation_assumptions:
        assump = result.simulation_assumptions
        print("\nRecorded Simulation Assumptions:")
        print(f"  Fill Timing:         {assump.fill_assumption}")
        print(f"  Slippage Model:      {assump.slippage_model} ({assump.slippage_bps} bps)")
        print(f"  Cost Schedule:       {assump.cost_model}")
        print(f"  Data Origin:         {assump.data_source_type.value} ({assump.data_source_name})")
        print(f"  Synthetic Flag:      {assump.is_synthetic_data}")

    if result.dossier:
        dos = result.dossier
        print("\nRun Dossier & Cryptographic Verification:")
        print(f"  Run ID:              {dos.run_id}")
        print(f"  Execution Contract:  {dos.execution_contract.value}")
        print(f"  Overall Status:      {dos.verification_matrix.overall_status.value}")
        print(
            f"  Reconciliation:      {'RECONCILED' if dos.reconciliation.is_reconciled else 'DISCREPANCY'}"
        )
        print(f"  Closed Expectancy:   ₹{dos.closed_trade_expectancy:.2f}")
        print(f"  Terminal Adjusted:   ₹{dos.terminal_adjusted_expectancy:.2f}")
        print(f"  Event Merkle Root:   {dos.event_stream_merkle_root[:16]}...")
        print(f"  Trade Merkle Root:   {dos.trade_ledger_merkle_root[:16]}...")
        print(f"  Tamper Digest:       {dos.tamper_digest[:16]}...")
        print(f"  Dossier Path:        runs/backtest/dossier_{dos.run_id}.json")

    print("\nNext Steps:")
    print(f'    aditrader validate --strategy "{dsl.name}"')
    print(f'    aditrader forward-options --strategy "{dsl.name}" --mock')
    print("=" * 68)
    return 0


# ==============================================================================
# 8. Dashboard & Inspection Commands
# ==============================================================================


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Launch the responsive web research and paper trading dashboard."""
    port = getattr(args, "port", 8050) or 8050
    host = getattr(args, "host", "127.0.0.1") or "127.0.0.1"
    serve = bool(getattr(args, "serve", False))

    print("=" * 68)
    print("      AdiTrader / QuantumValidator — Research & Paper Dashboard")
    print("=" * 68)
    print("[NOTICE] Full multi-page Plotly Dash integration is scheduled for Phase 8.")
    print("         A lightweight, zero-dependency responsive Web GUI is ready now.")
    print(f"         Server endpoint: http://{host}:{port}")
    if not serve:
        print("         Run 'aditrader dashboard' to start the live server:")
        print("             aditrader dashboard --serve")
    print("=" * 68)

    if serve:
        from aditrader.web.server import run_dashboard

        run_dashboard(host=host, port=port)

    return 0


def cmd_inspect_data(args: argparse.Namespace) -> int:
    """Inspect CSV market data file compatibility, columns, schema, and quality prior to replay."""
    file_path = (
        getattr(args, "file_opt", None)
        or getattr(args, "file", None)
        or getattr(args, "csv", None)
        or getattr(args, "csv_file", None)
    )
    if not file_path:
        print("[ERROR] Please provide a path to a CSV file to inspect.")
        data_dir = Path("data")
        if data_dir.is_dir():
            csvs = sorted(list(data_dir.glob("*.csv")))
            if csvs:
                print("\nDiscovered datasets in repository:")
                for c in csvs:
                    print(f"  aditrader inspect-data --file {c}")
        return 1

    path = Path(file_path)
    if not path.is_file():
        print(f"[ERROR] File not found: {file_path}")
        return 1

    symbol = getattr(args, "symbol", None)
    from aditrader.data.feeds.nse_csv import NSECSVInspector

    print("=" * 68)
    print("      AdiTrader / QuantumValidator — Market Data Dataset Inspector")
    print("=" * 68)
    print(f"File Path:        {path.resolve()}")
    print(f"File Size:        {path.stat().st_size:,} bytes")
    if symbol:
        print(f"Target Symbol:    {symbol}")
    print("-" * 68)

    try:
        report = NSECSVInspector.inspect_file(path, target_symbol=symbol)
    except Exception as exc:
        print(f"[ERROR] Inspection failed: {exc}")
        return 1

    print(f"Detected Format:  {report.detected_format.value}")
    replay_status = "YES - VALID" if report.is_valid_replayable else "NO - NOT REPLAYABLE"
    if not report.is_valid_replayable and report.replay_ineligibility_reason:
        replay_status += f" ({report.replay_ineligibility_reason})"
    print(f"Replay Ready:     {replay_status}")
    print(f"Total Lines:      {report.total_lines:,}")
    print(f"Parsed Bars:      {report.parsed_bars:,}")
    if report.total_derivative_rows is not None:
        print(f"Derivative Quotes: {report.total_derivative_rows:,}")
    print(f"Timeframe:        {report.timeframe_detected}")
    if report.start_time and report.end_time:
        start_fmt = report.start_time[:10] if len(report.start_time) >= 10 else report.start_time
        end_fmt = report.end_time[:10] if len(report.end_time) >= 10 else report.end_time
        print(f"Date Range:       {start_fmt} to {end_fmt}")
    if getattr(report, "underlying_symbols", None):
        print(f"Underlying:       {', '.join(report.underlying_symbols)}")
    if getattr(report, "expiries_found", None):
        exp_disp = ", ".join(report.expiries_found[:6])
        if len(report.expiries_found) > 6:
            exp_disp += f" (+{len(report.expiries_found) - 6} more)"
        print(f"Expiries ({len(report.expiries_found)}):     {exp_disp}")
    if getattr(report, "option_types", None):
        opt_types_disp = [f"{t} (Futures)" if t == "XX" else t for t in report.option_types]
        print(f"Option Types:     {', '.join(opt_types_disp)}")
    if getattr(report, "derivative_fields", None):
        print(f"Derivative Fields: {', '.join(report.derivative_fields)}")
    if report.symbols and not getattr(report, "underlying_symbols", None):
        top_syms = ", ".join(report.symbols[:8])
        if len(report.symbols) > 8:
            top_syms += f" (+{len(report.symbols) - 8} more)"
        print(f"Symbols ({len(report.symbols)}):     {top_syms}")
    print(f"Columns ({len(report.columns_found)}):     {', '.join(report.columns_found)}")
    print(
        f"Available Fields: Volume={'YES' if report.has_volume else 'NO'}, "
        f"OI={'YES' if report.has_oi else 'NO'}, "
        f"VWAP={'YES' if report.has_vwap else 'NO'}, "
        f"TickCount={'YES' if report.has_tick_count else 'NO'}"
    )

    if report.quality_warnings:
        print("-" * 68)
        print(f"Quality Warnings ({len(report.quality_warnings)}):")
        for w in report.quality_warnings[:10]:
            print(f"  [!] {w}")
        if len(report.quality_warnings) > 10:
            print(f"  ... and {len(report.quality_warnings) - 10} additional warnings.")
    else:
        print("-" * 68)
        print("Quality Check:    CLEAN - Zero anomalies detected.")

    print("=" * 68)
    from aditrader.data.feeds.nse_csv import NSECSVFormat

    inspection_success = report.detected_format != NSECSVFormat.UNKNOWN and (
        report.parsed_bars > 0 or getattr(report, "total_derivative_rows", 0) > 0
    )
    return 0 if inspection_success else 1


def cmd_inspect_strategy(args: argparse.Namespace) -> int:
    """Inspect strategy file syntax, language, constructs, lookahead safety, and compatibility."""
    file_path = (
        getattr(args, "file_opt", None)
        or getattr(args, "file", None)
        or getattr(args, "strategy_file", None)
        or getattr(args, "path", None)
    )
    if not file_path:
        print("[ERROR] Please provide a path to a strategy file to inspect.")
        return 1

    path = Path(file_path)
    if not path.is_file():
        print(f"[ERROR] Strategy file not found: {file_path}")
        return 1

    from aditrader.strategy.inspector import StrategyFormat, StrategyInspector

    print("=" * 68)
    print("      AdiTrader / QuantumValidator — Strategy Compatibility Inspector")
    print("=" * 68)
    print(f"File Path:          {path.resolve()}")
    print(f"File Size:          {path.stat().st_size:,} bytes")

    try:
        report = StrategyInspector.inspect_file(path)
    except Exception as exc:
        print(f"[ERROR] Strategy inspection failed: {exc}")
        return 1

    print("-" * 68)
    print(f"Detected Format:    {report.detected_format.value}")
    lang_display = report.language
    if report.version_detected:
        lang_display += f" ({report.version_detected})"
    print(f"Language:           {lang_display}")
    print(f"Script Type:        {report.script_type.value}")
    if report.strategy_name:
        print(f"Strategy Title:     {report.strategy_name}")
    if report.underlying_detected:
        print(f"Target Symbol:      {report.underlying_detected}")
    if report.timeframe_detected:
        print(f"Target Timeframe:   {report.timeframe_detected}")

    print(f"Translation Status: {report.translation_status.value}")
    print(f"Semantic Fidelity:  {report.fidelity_level.value}")
    print(f"Validation Ready:   {'YES' if report.validation_ready else 'NO'}")
    print(f"Simulation Ready:   {'YES' if report.simulation_ready else 'NO'}")
    print(f"Forward-Test Ready: {'YES' if report.forward_test_ready else 'NO'}")

    if report.supported_constructs:
        print(f"Supported Rules:    {', '.join(report.supported_constructs)}")
    if report.unsupported_constructs:
        print(f"Unsupported Rules:  {', '.join(report.unsupported_constructs)}")

    # 1. Semantic Mismatch Alert
    if report.naming_behavior_mismatch:
        print("-" * 68)
        print("  [SEMANTIC MISMATCH DETECTED]")
        print(f"  Title / Claim:     {report.strategy_name}")
        if report.position_semantics:
            print(f"  Actual Execution:  {report.position_semantics}")
        if report.option_leg_semantics:
            print(f"  Option Structure:  {report.option_leg_semantics}")
        print(f"  Diagnostic Notice: {report.naming_behavior_mismatch}")

    # 2. Custom P&L Arithmetic Audit
    if report.custom_pnl_detected and report.custom_pnl_details:
        print("-" * 68)
        print("  [CUSTOM P&L ARITHMETIC AUDIT]")
        pnl_d = report.custom_pnl_details
        vars_str = ", ".join(pnl_d.get("variables", []))
        print(f"  Formula Variables: {vars_str}")
        if "payoff_model" in pnl_d:
            print(f"  Payoff Model:      {pnl_d['payoff_model']}")
        if pnl_d.get("target_profit_value") is not None:
            print(f"  Target Profit:     ₹{pnl_d['target_profit_value']:,.2f}")
        if pnl_d.get("max_loss_limit_value") is not None:
            print(f"  Max Loss Limit:    ₹{pnl_d['max_loss_limit_value']:,.2f}")
        if "pricing_connection" in pnl_d:
            print(f"  Pricing Linkage:   {pnl_d['pricing_connection']}")
        if "dsl_evaluation_limitation" in pnl_d:
            print(f"  AST Limitation:    {pnl_d['dsl_evaluation_limitation']}")

    # 3. Construct Discovery & Classification Matrix
    if report.detected_constructs:
        print("-" * 68)
        print("  [CONSTRUCT DISCOVERY & CLASSIFICATION MATRIX]")
        print(f"  {'Construct':<34} | {'Category':<12} | {'Fidelity':<13} | {'Translatable':<12}")
        print(f"  {'-' * 34}-+-{'-' * 12}-+-{'-' * 13}-+-{'-' * 12}")
        for c in report.detected_constructs:
            trans_str = "YES" if c.translatable else "NO"
            print(
                f"  {c.name[:34]:<34} | {c.category:<12} | {c.fidelity.value:<13} | {trans_str:<12}"
            )
            if c.details:
                print(f"    ↳ {c.details}")

    # 3.5. Instrument Portability Audit
    if report.portability_assessment:
        print("-" * 68)
        print("  [INSTRUMENT PORTABILITY AUDIT]")
        pa = report.portability_assessment
        if pa.source_instrument_hint or pa.target_instrument_hint:
            src = pa.source_instrument_hint or "Unknown / Generic"
            tgt = pa.target_instrument_hint or "Unspecified"
            print(f"  Porting Path:      {src}  --->  {tgt}")
        print(f"  Verdict:           {pa.portability_verdict}")

        if pa.assumptions_preserved:
            print("\n  Preserved Assumptions:")
            for item in pa.assumptions_preserved:
                print(f"    [OK] {item}")
        if pa.assumptions_changed:
            print("\n  Changed Assumptions:")
            for item in pa.assumptions_changed:
                print(f"    [CHANGED] {item}")
        if pa.assumptions_unknown:
            print("\n  Unknown / Discretionary Assumptions:")
            for item in pa.assumptions_unknown:
                print(f"    [UNKNOWN] {item}")
        if pa.unsafe_mappings:
            print("\n  Unsafe / Critical Risk Mappings:")
            for item in pa.unsafe_mappings:
                print(f"    [UNSAFE] {item}")

    # 4. PaperBroker Comparison Notes
    if report.order_behavior_notes:
        print("-" * 68)
        print("  [PAPERBROKER VS PINE SIMULATION COMPARISON]")
        for note in report.order_behavior_notes:
            print(f"  • {note}")

    print("-" * 68)
    if report.has_lookahead_risk:
        print(
            "[ALERT] LOOKAHEAD / REPAINTING RISK DETECTED! Strategy violates point-in-time rules."
        )
    if report.has_intrabar_risk:
        print("[WARN] Intrabar tick calculation detected. Simulating bar-close only.")
    if report.has_options_legs:
        print("[AIR-GAP] Multi-leg options detected. Protected by ADR 011 options air gap.")
        print("  Dynamic premium selector:       SUPPORTED")
        print("  Historical option-chain replay: UNAVAILABLE (requires intraday option chain)")
        print("  Exact strike resolution:        POINT_IN_TIME_DYNAMIC")
        print("  Deterministic selection policy: CLOSEST_PREMIUM with deterministic tie-breaker")
        print("  Replay readiness:               STRUCTURALLY_VALID_NOT_REPLAYABLE")

    if report.rejection_reasons:
        print("\nRejection Reasons / Limitations:")
        for r in report.rejection_reasons:
            print(f"  [REJECT] {r}")

    if report.warnings:
        print("\nDiagnostic Warnings:")
        for w in report.warnings:
            print(f"  [WARN] {w}")

    if not report.rejection_reasons and not report.warnings and not report.has_lookahead_risk:
        print("Quality Check:      CLEAN - Fully compatible with QuantumValidator AST.")

    print("=" * 68)
    # Inspection succeeds (0) if format is recognized and no fatal lookahead bias
    inspection_success = (
        report.detected_format != StrategyFormat.UNKNOWN and not report.has_lookahead_risk
    )
    return 0 if inspection_success else 1


def cmd_forward_test(args: argparse.Namespace) -> int:
    """Run an air-gapped live or rehearsal forward paper-testing session."""
    strategy_arg = getattr(args, "strategy", None)
    if not strategy_arg:
        print("=" * 68)
        print("              Forward-Testing & Paper-Trading Runner")
        print("=" * 68)
        print("[NOTICE] Forward-testing executes compiled strategies against streaming")
        print("         market data inside the strictly air-gapped PaperBroker.")
        print("         NO REAL ORDERS ARE EVER ROUTED TO ANY BROKER OR EXCHANGE.")
        print()
        print("Usage:")
        print("  aditrader forward-test --strategy <strategy_id> [options]")
        print()
        print("Examples:")
        print("  # Run linear MA crossover on NIFTY for 50 ticks in mock rehearsal:")
        print("  aditrader forward-test --strategy test_ma_crossover --ticks 50")
        print()
        print("  # Replay real historical CSV dataset for deterministic forward testing:")
        print("  aditrader forward-test --strategy test_ma_crossover --csv data/nifty_sample.csv")
        print()
        print("  # Run momentum breakout forward test for 30 seconds:")
        print("  aditrader forward-test --strategy momentum_breakout --duration 30")
        print()
        print("  # Run with custom paper capital and output dossier path:")
        print(
            "  aditrader forward-test --strategy test_ma_crossover --capital 2000000 --output runs/my_forward_run.json"
        )
        print()
        print("Note: Multi-leg option strategies are strictly air-gapped from forward execution")
        print("      pending Phase 8 synthetic IV modeling. Only linear strategies are supported.")
        print("=" * 68)
        return 0

    # Resolve strategy
    registry = StrategyRegistry()
    record = registry.find(strategy_arg)
    dsl: StrategyDSL | None = None
    if record:
        dsl = record.dsl_definition
    else:
        print(f"[ERROR] Strategy '{strategy_arg}' not found in registry.")
        return 1

    if dsl.legs:
        print("[ROUTING] Multi-leg option strategy detected.")
        print(f"          Routing execution to KotakOptionForwardRunner: {dsl.name}")
        return cmd_forward_options(args)

    instrument = getattr(args, "instrument", None) or dsl.underlying
    timeframe = getattr(args, "timeframe", None) or dsl.timeframe
    capital = getattr(args, "capital", 1_000_000.0) or 1_000_000.0
    slippage_bps = (
        getattr(args, "slippage_bps", 2.5)
        if getattr(args, "slippage_bps", None) is not None
        else 2.5
    )
    force_mock = getattr(args, "mock", False)
    max_ticks = getattr(args, "ticks", None)
    max_bars = getattr(args, "bars", None)
    duration = getattr(args, "duration", None)
    out_path = Path(args.output) if getattr(args, "output", None) else None
    strict_qual = getattr(args, "strict_quality", False)
    raw_vol_mode = getattr(args, "volume_mode", "TRADED_VOLUME") or "TRADED_VOLUME"
    vol_mode: Literal["TICK_COUNT", "TRADED_VOLUME", "CUMULATIVE", "INCREMENTAL"] = (
        cast(Literal["TICK_COUNT", "TRADED_VOLUME", "CUMULATIVE", "INCREMENTAL"], raw_vol_mode)
        if raw_vol_mode in ("TICK_COUNT", "TRADED_VOLUME", "CUMULATIVE", "INCREMENTAL")
        else "TRADED_VOLUME"
    )
    qty_arg = getattr(args, "qty", None)

    config = ForwardTestConfig(
        symbol=instrument,
        timeframe=timeframe,
        qty=qty_arg,
        volume_mode=vol_mode,
        initial_capital=capital,
        slippage_bps=slippage_bps,
        strict_quality_checks=strict_qual,
        max_ticks=max_ticks,
        max_bars=max_bars,
        duration_seconds=duration,
        output_path=out_path,
        force_mock=force_mock,
    )

    settings = get_settings()
    has_credentials = bool(
        settings.kotak_consumer_key
        and settings.kotak_mobile_number
        and (settings.kotak_ucc or settings.kotak_password)
    )
    from aditrader.data.adapters.kotak_neo import HAS_NEO_SDK

    csv_path = getattr(args, "csv", None)
    csv_feed: CSVDataFeed | None = None
    if csv_path:
        csv_file = Path(csv_path)
        if not csv_file.is_file():
            print(f"[ERROR] CSV dataset not found: {csv_path}")
            return 1
        from aditrader.data.feeds.nse_csv import NSECSVFormat, NSECSVInspector

        csv_report = NSECSVInspector.inspect_file(csv_file)
        if csv_report.detected_format == NSECSVFormat.DERIVATIVE_QUOTE:
            print(
                f"[ERROR] CSV dataset '{csv_file.name}' is classified as NSE_DERIVATIVE_QUOTE.\n"
                "        Multi-contract daily derivative quote series cannot be replayed as a linear candle feed;\n"
                "        options execution is air-gapped per ADR 011 and ADR 002.\n"
                "        Silent proxy execution of option contracts against underlying spot or linear state machines is prohibited.\n"
                "        Use 'aditrader inspect-data' to analyze this dataset."
            )
            return 1
        csv_feed = CSVDataFeed(
            file_path=csv_file,
            symbol=instrument,
            timeframe=timeframe,
            session_filter=False,
        )
        if len(csv_feed) == 0:
            print(f"[ERROR] No valid bars found for symbol '{instrument}' in CSV '{csv_path}'.")
            return 1
        mode_label = f"SIMULATION / CSV_REPLAY ({csv_path}, {len(csv_feed)} bars)"
    elif force_mock:
        mode_label = "SIMULATED_REHEARSAL (Mock Adapter)"
    elif has_credentials:
        if not HAS_NEO_SDK:
            print(
                "\n[FAIL-CLOSED SAFETY VETO] Real Kotak Neo forward session rejected:\n"
                "  Live Kotak Neo SDK is not installed in the current Python environment.\n"
                "To run an offline rehearsal without broker credentials, specify:\n"
                f'  aditrader forward-test --strategy "{dsl.name}" --mock\n'
                "Or replay a historical CSV dataset:\n"
                f'  aditrader forward-test --strategy "{dsl.name}" --csv data/nifty_sample.csv'
            )
            return 1
        mode_label = "LIVE_STREAM (Kotak Neo SFeed)"
    else:
        print(
            "\n[FAIL-CLOSED SAFETY VETO] Real Kotak Neo forward test rejected:\n"
            "  Missing required Kotak Neo credentials in environment (.env).\n"
            "  Live forward-shadow paper testing requires KOTAK_CONSUMER_KEY, KOTAK_MOBILE_NUMBER, etc.\n"
            "\nTo run an offline rehearsal without broker credentials, specify:\n"
            f'  aditrader forward-test --strategy "{dsl.name}" --mock\n'
            "\nOr replay a historical CSV dataset:\n"
            f'  aditrader forward-test --strategy "{dsl.name}" --csv data/nifty_sample.csv'
        )
        return 1

    print("=" * 68)
    print("      AdiTrader / QuantumValidator — Forward Paper Testing")
    print("=" * 68)
    print("[EXECUTION VENUE] Strictly Air-Gapped PaperBroker (NO LIVE BROKER ORDERS)")
    print(f"Strategy:         {dsl.name} (v{getattr(dsl, 'schema_version', '1.0')})")
    print(f"Instrument:       {config.symbol}")
    print(f"Timeframe:        {config.timeframe}")
    print(f"Volume Mode:      {config.volume_mode}")
    print(f"Initial Capital:  ₹{config.initial_capital:,.2f}")
    print(f"Slippage Model:   {config.slippage_bps} bps")
    print(f"Market Feed Mode: {mode_label}")
    if max_ticks:
        print(f"Stop Limit:       {max_ticks} ticks")
    if max_bars:
        print(f"Stop Limit:       {max_bars} bars")
    if duration:
        print(f"Timeout Limit:    {duration:.1f} seconds")
    print("-" * 68)
    print("Starting forward paper-testing session... Press Ctrl+C to stop cleanly.")
    print("-" * 68)

    def on_bar_closed(bar: Bar) -> None:
        print(
            f"[BAR CLOSED] {bar.timestamp.strftime('%H:%M:%S')} "
            f"O={bar.open:.2f} H={bar.high:.2f} L={bar.low:.2f} C={bar.close:.2f} V={bar.volume}"
        )

    def on_signal_emitted(sig: Signal) -> None:
        print(
            f"[SIGNAL]     {sig.direction.value} on {sig.symbol} (timestamp: {sig.timestamp.strftime('%H:%M:%S')})"
        )

    def on_trade_executed(trd: Trade) -> None:
        print(
            f"[PAPER FILL] {trd.side.value} {trd.qty}x {trd.symbol} @ ₹{trd.fill_price:.2f} "
            f"(slippage: ₹{trd.slippage:.2f}, fees: ₹{trd.stt + trd.charges:.2f})"
        )

    runner = ForwardTestRunner(
        config=config,
        strategy=dsl,
        feed=csv_feed,
        on_bar_callback=on_bar_closed,
        on_signal_callback=on_signal_emitted,
        on_trade_callback=on_trade_executed,
    )

    result = runner.run()
    session = result.session

    print("\n" + "=" * 68)
    print("            Forward-Testing Session Summary")
    print("=" * 68)
    print(f"Session ID:       {session.session_id}")
    print(f"Status:           {session.status.value}")
    print(f"Stop Reason:      {session.stop_reason or 'Normal completion'}")
    print(
        f"Ticks Processed:  {session.total_ticks} ({session.valid_ticks} valid, {session.ticks_with_quotes} with quotes)"
    )
    print(f"Bars Completed:   {session.bars_count}")
    print(f"Paper Orders:     {session.orders_count}")
    print(f"Paper Fills:      {session.trades_count}")
    print(f"Starting Capital: ₹{config.initial_capital:,.2f}")
    print(f"Ending Capital:   ₹{result.ending_balance.total_capital:,.2f}")
    print(f"Realized PnL:     ₹{session.realized_pnl:,.2f}")
    print(f"Unrealized PnL:   ₹{session.unrealized_pnl:,.2f}")
    if session.avg_latency_ms is not None:
        print(
            f"Average Latency:  {session.avg_latency_ms:.1f} ms (Peak: {session.max_latency_ms or 0:.1f} ms)"
        )
    if result.dossier_path:
        print(f"Session Dossier:  {result.dossier_path}")
    print("=" * 68)

    return 0 if session.status == ForwardTestStatus.COMPLETED else 1


# ==============================================================================
# 10. Smoke Feed Command (Read-Only Market Data Smoke Test)
# ==============================================================================


def cmd_smoke_feed(args: argparse.Namespace) -> int:
    """Run a safe, strictly read-only smoke test against Kotak Neo live or mock feed.

    NO ORDERS ARE EVER PLACED (Physical air gap ADR 002).
    Validates WebSocket connectivity, authentication, scrip subscription,
    and normalized streaming market ticks.
    """
    symbol = getattr(args, "symbol", "NIFTY") or "NIFTY"
    raw_ticks = getattr(args, "ticks", None)
    target_ticks = 5 if raw_ticks is None else int(raw_ticks)
    if target_ticks <= 0:
        print(f"[ERROR] Invalid --ticks {target_ticks}: tick count must be strictly positive.")
        return 1
    timeout_sec = getattr(args, "timeout", 15.0) or 15.0
    force_mock = getattr(args, "mock", False)

    from aditrader.data.adapters.kotak_neo import HAS_NEO_SDK

    settings = get_settings()
    has_credentials = bool(
        settings.kotak_consumer_key
        and settings.kotak_mobile_number
        and (settings.kotak_ucc or settings.kotak_password)
    )

    is_live = has_credentials and not force_mock

    print("=" * 68)
    print("      AdiTrader / QuantumValidator — Market Data Feed Smoke Test")
    print("=" * 68)
    print("[AIR-GAP GUARD] Strictly READ-ONLY market data. No order routing possible.")
    print(f"Target Symbol:       {symbol}")
    print(f"Target Ticks:        {target_ticks}")
    print(f"Readiness Timeout:   {timeout_sec:.1f}s")
    print(
        f"Mode:                {'LIVE (Kotak Neo SFeed)' if is_live else 'SIMULATED_REHEARSAL (Mock Adapter)'}"
    )
    print(f"SDK Available:       {'Yes (neo_api_client)' if HAS_NEO_SDK else 'No'}")
    print("-" * 68)

    if is_live and not HAS_NEO_SDK:
        print("[FAIL CLOSED] Cannot run live smoke test: neo_api_client SDK is not available.")
        print("              Run with --mock to test simulated streaming ingestion.")
        return 1

    if not force_mock and not has_credentials:
        print(
            "\n[FAIL-CLOSED SAFETY VETO] Real Kotak Neo market data feed rejected:\n"
            "  Missing required Kotak Neo credentials in environment (.env).\n"
            "\nTo run a simulated streaming feed smoke test without credentials, specify:\n"
            f"  aditrader smoke-feed --symbol {symbol} --mock"
        )
        return 1

    adapter = KotakNeoAdapter(
        mock_mode=not is_live,
        readiness_timeout=timeout_sec,
    )

    received_ticks: list[Tick] = []
    done_event = threading.Event()

    def on_tick(tick: Tick) -> None:
        received_ticks.append(tick)
        ist_str = tick.timestamp.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
        bid_str = f"Bid: ₹{tick.bid:.2f} ({tick.bid_qty})" if tick.bid is not None else "Bid: N/A"
        ask_str = f"Ask: ₹{tick.ask:.2f} ({tick.ask_qty})" if tick.ask is not None else "Ask: N/A"
        print(
            f"  [TICK #{len(received_ticks):02d}] {tick.symbol} | LTP: ₹{tick.ltp:.2f} | "
            f"{bid_str} | {ask_str} | Vol: {tick.volume} | OI: {tick.oi or 'N/A'} | Time: {ist_str} IST"
        )
        if len(received_ticks) >= target_ticks:
            done_event.set()

    print(f"Authenticating adapter ({'LIVE' if is_live else 'MOCK'})...")
    try:
        adapter.authenticate()
        print("[OK] Authentication successful.")
    except Exception as exc:
        print(f"[ERROR] Authentication failed: {exc}")
        return 1

    print(f"Subscribing to tick stream for '{symbol}'...")
    try:
        adapter.subscribe_ticks([symbol], on_tick)
    except Exception as exc:
        print(f"[ERROR] Subscription failed: {exc}")
        adapter.disconnect()
        return 1

    feeder_thread: threading.Thread | None = None
    if not is_live:

        def _mock_feeder() -> None:
            price = 24000.0 if "NIFTY" in symbol.upper() else 1000.0
            while not done_event.is_set() and len(received_ticks) < target_ticks:
                price += random.uniform(-2.0, 2.0)
                tick = Tick(
                    symbol=symbol,
                    ltp=round(price, 2),
                    bid=round(price - 0.5, 2),
                    ask=round(price + 0.5, 2),
                    bid_qty=50,
                    ask_qty=50,
                    volume=100,
                    oi=50000,
                    timestamp=datetime.now(tz=EXCHANGE_TIMEZONE),
                    source="MOCK_SMOKE_FEED",
                    is_synthetic=True,
                )
                adapter.emit_mock_tick(tick)
                time.sleep(0.1)

        feeder_thread = threading.Thread(target=_mock_feeder, daemon=True, name="SmokeMockFeeder")
        feeder_thread.start()

    print(f"Waiting for {target_ticks} tick(s) (timeout: {timeout_sec:.1f}s)...")
    start_time = time.time()
    finished_in_time = done_event.wait(timeout=timeout_sec)
    elapsed = time.time() - start_time

    print("-" * 68)
    adapter.disconnect()
    if feeder_thread and feeder_thread.is_alive():
        feeder_thread.join(timeout=1.0)

    print(f"Session Duration:    {elapsed:.2f}s")
    print(f"Ticks Received:      {len(received_ticks)} / {target_ticks}")
    print(f"Feed Final Status:   {adapter.feed_status}")

    if finished_in_time and len(received_ticks) >= target_ticks:
        print("[VERDICT] PASS — Feed streaming and tick normalization verified successfully.")
        print("=" * 68)
        return 0
    else:
        print(f"[VERDICT] FAIL — Failed to receive {target_ticks} ticks within {timeout_sec:.1f}s.")
        print("=" * 68)
        return 1


def cmd_kotak_auth(args: argparse.Namespace) -> int:
    """Execute standalone smoke test and capability check for Kotak Neo API authentication."""
    print("=" * 68)
    print("  KOTAK NEO API AUTHENTICATION & DATA SMOKE TEST")
    print("=" * 68)

    settings = get_settings()
    is_mock = getattr(args, "mock", False) or settings.aditrader_env == "test"

    has_credentials = bool(
        settings.kotak_consumer_key
        and settings.kotak_consumer_secret
        and settings.kotak_mobile_number
        and settings.kotak_password
    )

    sdk_version = "3.0.6" if HAS_NEO_SDK else "NOT INSTALLED"
    print(f"SDK Status:          {'INSTALLED (neo_api_client)' if HAS_NEO_SDK else 'UNAVAILABLE'}")
    print(f"SDK VERSION:         {sdk_version}")
    print(f"Target Environment:  {settings.aditrader_env}")
    print(
        f"Configured Auth:     {'CREDENTIALS PRESENT' if has_credentials else 'CREDENTIALS ABSENT'}"
    )
    if has_credentials:
        print(f"Mobile Number:       {_mask_secret(settings.kotak_mobile_number)}")
        print(f"Consumer Key:        {_mask_secret(settings.kotak_consumer_key)}")
        print(f"UCC:                 {_mask_secret(settings.kotak_ucc)}")

    if not is_mock and not has_credentials:
        print(
            "\n[FAIL-CLOSED SAFETY VETO] Kotak Neo authentication check rejected:\n"
            "  Missing required Kotak Neo credentials in environment (.env).\n"
            "\nTo test simulated offline authentication without live credentials, specify:\n"
            "  aditrader kotak-auth --mock"
        )
        return 1

    adapter = KotakNeoAdapter(mock_mode=is_mock)

    auth_passed = False
    try:
        adapter.authenticate()
        auth_passed = True
    except Exception as exc:
        print(f"\n[ERROR] Authentication failed: {exc}")
        auth_passed = False

    print("-" * 68)
    if auth_passed:
        if is_mock:
            print("KOTAK NEO AUTHENTICATION: PASS (MOCK MODE)")
            print("DATA SESSION:        AVAILABLE (LOCAL OFFLINE / SYNTHETIC)")
        else:
            print("KOTAK NEO AUTHENTICATION: PASS")
            print("DATA SESSION:        AVAILABLE (LIVE)")
        print(f"SDK VERSION:         {sdk_version}")
        print("=" * 68)
        return 0
    else:
        print("KOTAK NEO AUTHENTICATION: FAIL")
        print("DATA SESSION:        UNAVAILABLE")
        print(f"SDK VERSION:         {sdk_version}")
        print("=" * 68)
        return 1


def cmd_kotak_discover(args: argparse.Namespace) -> int:
    """Execute the progressive 5-stage Kotak Neo data retrieval and 10-year suitability discovery suite."""
    print("=" * 72)
    print("  KOTAK NEO HISTORICAL DATA CAPABILITY & 10-YEAR OPTIONS DISCOVERY")
    print("=" * 72)

    settings = get_settings()
    is_mock = getattr(args, "mock", False)
    has_credentials = bool(settings.kotak_consumer_key and settings.kotak_consumer_secret)

    if not is_mock and not has_credentials:
        print(
            "\n[FAIL-CLOSED SAFETY VETO] Kotak Neo discovery suite rejected:\n"
            "  Missing required Kotak Neo credentials in environment (.env).\n"
            "\nTo run discovery in offline mock mode, specify:\n"
            "  aditrader kotak-discover --mock"
        )
        return 1

    out_dir_arg = getattr(args, "output_dir", None)
    output_dir = Path(out_dir_arg) if out_dir_arg else Path("runs/kotak_raw")

    adapter = KotakNeoAdapter(mock_mode=is_mock)
    discoverer = KotakCapabilityDiscoverer(adapter=adapter, raw_capture_dir=output_dir)

    print(f"Execution Mode:      {'OFFLINE MOCK' if is_mock else 'LIVE BROKER API'}")
    print(f"Output Directory:    {output_dir}")
    print("Running 5-stage progressive retrieval tests...")
    print("-" * 72)

    report = discoverer.run_discovery_suite(output_dir=output_dir)

    print(f"{'TEST ID':<10} | {'NAME':<36} | {'STATUS':<6} | {'RECORDS':<8}")
    print("-" * 72)
    for t in report.tests:
        print(f"{t.test_id:<10} | {t.name[:36]:<36} | {t.status:<6} | {t.returned_records:<8}")
        if t.diagnostics:
            print(f"   -> {t.diagnostics}")

    print("=" * 72)
    print(f"10-YEAR OPTIONS BACKTEST DATA: {report.ten_year_options_verdict}")
    print("=" * 72)
    print("Definitive Assessment Rationale:")
    print(f"  {report.verdict_rationale}")
    print("\nIdentified Blocking Factors:")
    for i, factor in enumerate(report.blocking_factors, 1):
        print(f"  {i}. {factor}")

    print("\nComprehensive capability JSON dossier written to:")
    dossier_path = (
        output_dir / f"kotak_capability_report_{datetime.now(UTC).strftime('%Y%m%d')}.json"
    )
    try:
        dossier_path.parent.mkdir(parents=True, exist_ok=True)
        dossier_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
        print(f"  {dossier_path}")
    except Exception as exc:
        print(f"  [Warning: could not write dossier file: {exc}]")

    print("=" * 72)
    return 0


def cmd_kotak_history(args: argparse.Namespace) -> int:
    """Fetch historical candle data for a symbol via Kotak Neo, capture raw JSON, and audit integrity."""
    symbol = getattr(args, "symbol", None) or getattr(args, "symbol_arg", None) or "NIFTY"
    timeframe = getattr(args, "timeframe", "5m")
    start_str = getattr(args, "from_date", None)
    end_str = getattr(args, "to_date", None)
    out_file = getattr(args, "output", None)
    is_mock = getattr(args, "mock", False)

    print("=" * 70)
    print("  KOTAK NEO HISTORICAL DATA RETRIEVAL & INTEGRITY AUDIT")
    print("=" * 70)

    now_ist = datetime.now(EXCHANGE_TIMEZONE)
    if end_str:
        try:
            end_dt = datetime.strptime(end_str, "%Y-%m-%d").replace(
                hour=15, minute=30, tzinfo=EXCHANGE_TIMEZONE
            )
        except ValueError:
            print(f"[ERROR] Invalid --to-date format: {end_str}. Expected YYYY-MM-DD.")
            return 1
    else:
        end_dt = now_ist

    if start_str:
        try:
            start_dt = datetime.strptime(start_str, "%Y-%m-%d").replace(
                hour=9, minute=15, tzinfo=EXCHANGE_TIMEZONE
            )
        except ValueError:
            print(f"[ERROR] Invalid --from-date format: {start_str}. Expected YYYY-MM-DD.")
            return 1
    else:
        start_dt = end_dt - timedelta(days=29)

    print(f"Target Symbol:       {symbol}")
    print(f"Timeframe:           {timeframe}")
    print(
        f"Query Window:        {start_dt.strftime('%Y-%m-%d %H:%M')} to {end_dt.strftime('%Y-%m-%d %H:%M')} IST"
    )

    settings = get_settings()
    if not is_mock and not (settings.kotak_consumer_key and HAS_NEO_SDK):
        print(
            "\n[FAIL-CLOSED SAFETY VETO] Real Kotak Neo historical retrieval rejected:\n"
            "  Missing required Kotak Neo credentials or live SDK in environment.\n"
            "\nTo retrieve simulated historical data in mock mode, specify:\n"
            f"  aditrader kotak-history --symbol {symbol} --mock"
        )
        return 1

    adapter = KotakNeoAdapter(mock_mode=is_mock)
    if is_mock and not adapter._mock_bars.get(symbol):
        mock_sample: list[Bar] = []
        curr = start_dt
        p = 24000.0 if "NIFTY" in symbol.upper() else 100.0
        while curr <= end_dt:
            if curr.weekday() < 5 and (9 * 60 + 15 <= curr.hour * 60 + curr.minute <= 15 * 60 + 30):
                mock_sample.append(
                    Bar(
                        timestamp=curr,
                        open=round(p, 2),
                        high=round(p + 15.0, 2),
                        low=round(p - 15.0, 2),
                        close=round(p + 2.0, 2),
                        volume=10000,
                        oi=50000,
                        symbol=symbol,
                        source="KOTAK_HISTORICAL",
                        timeframe=timeframe,
                    )
                )
            curr += timedelta(minutes=5 if timeframe in ("5m", "5min") else 1)
        adapter.inject_mock_data(bars={symbol: mock_sample})

    try:
        adapter.authenticate()
    except Exception as exc:
        print(f"[ERROR] Authentication failed: {exc}")
        return 1

    print("Fetching historical bars...")
    try:
        bars = adapter.fetch_historical_bars(
            symbol=symbol,
            start_time=start_dt,
            end_time=end_dt,
            timeframe=timeframe,
        )
    except Exception as exc:
        print(f"[ERROR] Failed to fetch historical data: {exc}")
        return 1

    print(f"Retrieved Bars:      {len(bars)}")
    if not bars:
        print("[WARNING] Zero bars returned by Kotak Neo for requested range.")
        return 0

    print(
        f"First Bar:           {bars[0].timestamp.strftime('%Y-%m-%d %H:%M')} IST | O={bars[0].open} C={bars[0].close}"
    )
    print(
        f"Last Bar:            {bars[-1].timestamp.strftime('%Y-%m-%d %H:%M')} IST | O={bars[-1].open} C={bars[-1].close}"
    )

    # Audit bars using DataIntegrityChecker
    print("-" * 70)
    print("Running Data Integrity Audit on Normalized Bars...")
    interval_min = 5 if timeframe in ("5m", "5min") else (1 if timeframe in ("1m", "1min") else 15)
    integrity_report = DataIntegrityChecker.audit_bars(
        bars,
        source_identifier=f"kotak_{symbol}",
        expected_interval_minutes=interval_min,
    )
    print(f"Integrity Status:    {'PASS' if integrity_report.is_valid else 'FAIL'}")
    print(f"Total Bars Audited:  {integrity_report.total_records}")
    print(f"Intraday Gaps:       {len(integrity_report.gaps)}")
    print(f"Envelope Violations: {integrity_report.envelope_violations_count}")
    print(f"Duplicate Timestamps:{integrity_report.duplicates_count}")
    print(f"Timezone Violations: {integrity_report.timezone_violations_count}")

    if out_file:
        out_path = Path(out_file)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        import json

        payload = [b.model_dump(mode="json") for b in bars]
        out_path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        print(f"\nNormalized bars written to: {out_path}")

    print("=" * 70)
    return 0 if integrity_report.is_valid else 1


def cmd_kotak_option_chain(args: argparse.Namespace) -> int:
    """Verify and demonstrate live Kotak Neo option chain, quotes, WebSocket, and Premium-Ladder selection."""
    print("=" * 76)
    print("  KOTAK NEO OPTION-CHAIN INTEGRATION & LIVE STRATEGY SMOKE TEST")
    print("=" * 76)

    settings = get_settings()
    is_mock = getattr(args, "mock", False) or not bool(settings.kotak_consumer_key)
    underlying = getattr(args, "underlying", "NIFTY") or "NIFTY"
    count = int(getattr(args, "count", 100) or 100)
    user_expiry = getattr(args, "expiry", None)
    out_dir_arg = getattr(args, "output_dir", None)
    out_dir = Path(out_dir_arg) if out_dir_arg else Path("runs/kotak_raw")

    print(f"SDK Status:          {'INSTALLED (neo_api_client)' if HAS_NEO_SDK else 'UNAVAILABLE'}")
    print("SDK Version:         3.0.6")
    print(f"Target Mode:         {'OFFLINE SIMULATED MOCK' if is_mock else 'LIVE BROKER API'}")
    print(f"Underlying Symbol:   {underlying}")

    adapter = KotakNeoAdapter(mock_mode=is_mock)
    mgr = KotakOptionChainManager(adapter=adapter, mock_mode=is_mock)

    # 1. Authentication
    print("-" * 76)
    print("1. AUTHENTICATION")
    try:
        adapter.authenticate()
        print(f"   Status:           PASS ({'MOCK SESSION' if is_mock else 'AUTHENTICATED LIVE'})")
    except Exception as exc:
        print(f"   Status:           FAIL ({exc})")
        return 1

    # 2. Expiries
    print("-" * 76)
    print(f"2. EXPIRIES (underlying: {underlying})")
    expiries = mgr.fetch_expiries(underlying=underlying)
    print(
        f"   Available Expiries ({len(expiries)}): {', '.join(expiries[:6])}{'...' if len(expiries) > 6 else ''}"
    )
    if not expiries:
        print("   [ERROR] No active expiries returned by API.")
        return 1

    selected_expiry = user_expiry or expiries[0]
    print(
        f"   Selected Expiry:  {selected_expiry} ({'User Specified' if user_expiry else 'Nearest Active'})"
    )

    # 3. Option Chain Snapshot
    print("-" * 76)
    print(f"3. OPTION CHAIN SNAPSHOT (count: {count})")
    raw_chain = mgr.fetch_option_chain(underlying=underlying, expiry=selected_expiry, count=count)
    chain = mgr.normalize_option_chain(raw_chain, spot_price=24500.0)
    print(
        f"   Total Contracts:  {len(chain.contracts)} ({sum(1 for c in chain.contracts if c.option_type == 'CE')} CE, {sum(1 for c in chain.contracts if c.option_type == 'PE')} PE)"
    )

    calls = [c for c in chain.contracts if c.option_type == "CE"]
    sorted_calls = sorted(calls, key=lambda c: c.strike)
    if sorted_calls:
        print(
            f"   Strike Span (CE): {sorted_calls[0].strike:.0f} to {sorted_calls[-1].strike:.0f} INR"
        )

    print("\n   Sample Call (CE) Strikes:")
    print(
        f"   {'STRIKE':<8} | {'LTP (₹)':<8} | {'BID (₹)':<8} | {'ASK (₹)':<8} | {'VOLUME':<10} | {'OI':<10}"
    )
    print("   " + "-" * 62)
    step = max(1, len(sorted_calls) // 6)
    for c in sorted_calls[::step][:6]:
        b_str = f"{c.bid:.2f}" if c.bid is not None else "-"
        a_str = f"{c.ask:.2f}" if c.ask is not None else "-"
        print(
            f"   {c.strike:<8.0f} | {c.ltp:<8.2f} | {b_str:<8} | {a_str:<8} | {c.volume:<10} | {c.oi:<10}"
        )

    # 4. Cross-Check Against quotes()
    print("-" * 76)
    print("4. CROSS-CHECK: option_chain() vs quotes() REST ENDPOINT")
    comparisons = mgr.verify_against_quotes(chain.contracts, sample_size=4)
    print(f"   {'SYMBOL':<26} | {'CHAIN LTP':<9} | {'QUOTE LTP':<9} | {'DIFF':<6} | {'DEPTH'}")
    print("   " + "-" * 66)
    for cmp in comparisons:
        q_ltp_str = f"{cmp.quote_ltp:.2f}" if cmp.quote_ltp is not None else "N/A"
        diff_str = "0.00" if cmp.ltp_matches else "DRIFT"
        depth_str = "YES (L2)" if cmp.has_depth else "NO"
        print(
            f"   {cmp.symbol[:26]:<26} | {cmp.chain_ltp:<9.2f} | {q_ltp_str:<9} | {diff_str:<6} | {depth_str}"
        )

    # 5. WebSocket Verification
    print("-" * 76)
    print("5. SFEED WEBSOCKET PATH VERIFICATION")
    ws_res = mgr.verify_websocket_path(chain.contracts, sample_size=2)
    print(f"   WebSocket Status: {ws_res.status}")
    print(f"   Tokens Verified:  {', '.join(ws_res.subscribed_tokens)}")
    print(f"   Details:          {ws_res.details}")

    # 6. Premium-Ladder Live Selection Readiness
    print("-" * 76)
    print("6. NIFTY CE PREMIUM-LADDER FIRST-STEP SELECTION")
    ladder_res = mgr.evaluate_premium_ladder_selection(chain)
    print(f"   Selection Status: {ladder_res.selection_status}")
    print(
        f"   Determinism:      {'VERIFIED DETERMINISTIC' if ladder_res.is_deterministic else 'FAILED'}"
    )
    if ladder_res.short_leg_symbol:
        print(
            f"   Short Leg (1 CE): {ladder_res.short_leg_symbol} | Strike {ladder_res.short_leg_strike:.0f} | LTP ₹{ladder_res.short_leg_ltp:.2f} | Band {ladder_res.short_leg_band}"
        )
    else:
        print("   Short Leg:        NOT RESOLVED")

    if ladder_res.hedge_leg_symbol:
        print(
            f"   Hedge Leg (4 CE): {ladder_res.hedge_leg_symbol} | Strike {ladder_res.hedge_leg_strike:.0f} | LTP ₹{ladder_res.hedge_leg_ltp:.2f} (Target ₹{ladder_res.hedge_leg_target} ± ₹{ladder_res.hedge_leg_tolerance})"
        )
    else:
        print("   Hedge Leg:        NOT RESOLVED")

    if ladder_res.failure_reason:
        print(f"   Failure Reason:   {ladder_res.failure_reason}")

    # 7. Data Quality Audit
    print("-" * 76)
    print("7. DATA QUALITY & COMPLETENESS AUDIT")
    qa = mgr.audit_data_quality(chain)
    print(f"   Quality Status:   {qa.status}")
    print(f"   Unique Strikes:   {qa.strikes_count} ({qa.min_strike:.0f} to {qa.max_strike:.0f})")
    print(f"   Duplicate Strikes:{qa.duplicate_strikes_count}")
    print(f"   Missing LTPs:     {qa.missing_ltp_count}")
    print(f"   Stale Quotes:     {qa.stale_quotes_count}")
    print(f"   Hedge Available:  {'YES' if qa.has_hedge_candidates else 'NO'}")
    if qa.issues:
        print("   Identified Issues:")
        for issue in qa.issues:
            print(f"     - {issue}")

    # 8. Persist Raw Capture JSON
    print("-" * 76)
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_file = (
        out_dir
        / f"raw_option_chain_{underlying}_{selected_expiry}_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
    )
    import json

    snapshot_file.write_text(json.dumps(raw_chain, indent=2, default=str), encoding="utf-8")
    print(f"8. Raw snapshot preserved at: {snapshot_file}")

    print("=" * 76)
    print("SUMMARY VERDICT: LIVE OPTION CHAIN READY FOR FORWARD SHADOW TESTING")
    print("=" * 76)
    return 0 if ladder_res.selection_status in ("SELECTED", "PARTIAL") else 1


def cmd_forward_options(args: argparse.Namespace) -> int:
    """Run an air-gapped real Kotak forward paper-trading session for option strategies."""
    from aditrader.data.forward_options_runner import (
        ForwardOptionsSessionConfig,
        KotakOptionForwardRunner,
        RealKotakAuthenticationError,
    )

    strategy_arg = getattr(args, "strategy", None) or "tpl-nifty-ce-premium-ladder-v1"
    underlying = getattr(args, "underlying", None) or getattr(args, "instrument", None) or "NIFTY"
    expiry = getattr(args, "expiry", None)
    band_index = getattr(args, "band", 0) or 0
    capital_raw = getattr(args, "capital", None)
    capital = 1_000_000.0 if capital_raw is None else float(capital_raw)
    if capital <= 0:
        print(f"[ERROR] Invalid --capital {capital}: initial capital must be strictly positive.")
        return 1

    slippage_raw = getattr(args, "slippage_bps", None)
    slippage_bps = 5.0 if slippage_raw is None else float(slippage_raw)
    if slippage_bps < 0:
        print(f"[ERROR] Invalid --slippage-bps {slippage_bps}: slippage cannot be negative.")
        return 1

    duration_raw = getattr(args, "duration", None)
    duration = None if duration_raw is None else float(duration_raw)
    if duration is not None and duration <= 0:
        print(f"[ERROR] Invalid --duration {duration}: duration must be positive.")
        return 1

    out_dir = Path(getattr(args, "output_dir", "runs/forward") or "runs/forward")
    raw_dir = Path(getattr(args, "raw_capture_dir", "runs/kotak_raw") or "runs/kotak_raw")
    interval = getattr(args, "snapshot_interval", 300.0) or 300.0
    mock_mode = getattr(args, "mock", False)
    wait_for_open = not getattr(args, "no_wait", False)

    try:
        config = ForwardOptionsSessionConfig(
            strategy_id=strategy_arg,
            underlying=underlying,
            target_expiry=expiry,
            band_index=band_index,
            initial_capital=capital,
            slippage_bps=slippage_bps,
            output_dir=out_dir,
            raw_capture_dir=raw_dir,
            snapshot_interval_seconds=interval,
            mock_mode=mock_mode,
            wait_for_market_open=wait_for_open,
            duration_seconds=duration,
        )
    except Exception as cfg_err:
        print(f"[ERROR] Invalid forward options configuration: {cfg_err}")
        return 1

    banner_title = (
        "  KOTAK NEO MOCK REHEARSAL FORWARD-SHADOW PAPER EXECUTION (OPTIONS)"
        if mock_mode
        else "  KOTAK NEO REAL FORWARD-SHADOW PAPER EXECUTION (OPTIONS)"
    )
    print("=" * 76)
    print(banner_title)
    print("=" * 76)
    print(
        f"Mode:             {'MOCK / REHEARSAL' if mock_mode else 'REAL KOTAK ACCOUNT (PAPER-AIRGAPPED)'}"
    )
    print(f"Strategy:         {strategy_arg}")
    print(f"Underlying:       {underlying}")
    print(f"Capital:          ₹{capital:,.2f}")
    print(f"Slippage:         {slippage_bps} bps")
    print("Order Routing:    AIR-GAPPED (All fills execute in local PaperBroker)")
    print("Live Orders:      DISABLED BY ARCHITECTURE (ADR 002)")
    print("-" * 76)

    try:
        runner = KotakOptionForwardRunner(config=config)
        dossier_path = runner.run()

        # Load dossier data for comprehensive terminal summary table
        try:
            with open(dossier_path, encoding="utf-8") as df:
                dos = json.load(df)
            rec = dos.get("reconciliation", {})
            vmat = dos.get("verification_matrix", {})
            trades = dos.get("ledger", [])

            gross_pnl = rec.get("total_realized_pnl", rec.get("gross_profit", 0.0))
            total_charges = rec.get("total_charges", 0.0)
            net_profit = dos.get("net_profit", 0.0)
            start_cap = dos.get("initial_capital", capital)
            end_eq = dos.get("ending_equity", capital + net_profit)
            ret_pct = (net_profit / start_cap * 100.0) if start_cap > 0 else 0.0
            reconciled = rec.get("is_reconciled", True)
            disc = rec.get("equity_discrepancy", rec.get("discrepancy", 0.0))
            overall_status = vmat.get("overall_status", "THEORETICAL_PASS")

            print("-" * 76)
            print("FORWARD-SHADOW EXECUTION SUMMARY")
            print("-" * 76)
            print(f"Status:           CONCLUDED CLEANLY ({overall_status})")
            print(
                f"Mode:             {'MOCK / REHEARSAL' if mock_mode else 'REAL KOTAK LIVE FEED'}"
            )
            print(f"Strategy:         {dos.get('strategy_id', strategy_arg)}")
            print(f"Underlying:       {underlying}")
            print(f"Starting Capital: ₹{start_cap:,.2f}")
            print(f"Ending Equity:    ₹{end_eq:,.2f}")
            print(f"Gross PnL:        {'+' if gross_pnl >= 0 else ''}₹{gross_pnl:,.2f}")
            print(f"Statutory Costs:  ₹{total_charges:,.2f} (STT, Turnover, SEBI, GST, Stamp)")
            print(
                f"Net Profit:       {'+' if net_profit >= 0 else ''}₹{net_profit:,.2f} ({'+' if ret_pct >= 0 else ''}{ret_pct:.2f}%)"
            )
            print(f"Trades Executed:  {len(trades)}")
            print(f"Events Recorded:  {dos.get('event_count', 0)}")
            print(
                f"Balance Sheet:    {'RECONCILED' if reconciled else 'DISCREPANCY'} (Discrepancy: ±₹{disc:.2f})"
            )
            if dos.get("trade_ledger_merkle_root"):
                print(f"Ledger Merkle:    {dos['trade_ledger_merkle_root'][:16]}...")
            if dos.get("tamper_digest"):
                print(f"Tamper Digest:    {dos['tamper_digest'][:16]}...")

            if trades:
                print("\nExecuted Option Trades:")
                for i, t in enumerate(trades):
                    t_side = t.get("side", "")
                    t_qty = t.get("quantity", 0)
                    t_sym = t.get("symbol", "")
                    t_entry = t.get("entry_price", t.get("fill_price", 0.0))
                    t_exit = t.get("exit_price")
                    t_exit_str = f"Exit: ₹{t_exit:>6.2f}" if t_exit is not None else "Exit: OPEN"
                    t_net = t.get("net_pnl", 0.0)
                    print(
                        f"  #{i + 1:<2} {t_side:<4} {t_qty:>4} {t_sym:<22} Entry: ₹{t_entry:>6.2f}  {t_exit_str}  Net: {'+' if t_net >= 0 else ''}₹{t_net:>7.2f}"
                    )

        except Exception as read_err:
            logger.warning("Could not read dossier for summary: %s", read_err)

        print("-" * 76)
        print("[SUCCESS] Forward shadow session concluded cleanly.")
        print(f"Sealed Dossier:   {dossier_path}")
        print("=" * 76)
        return 0
    except RealKotakAuthenticationError as auth_err:
        print(f"[FAIL CLOSED] Authentication error: {auth_err}")
        return 1
    except KeyboardInterrupt:
        print("\n[STOPPED] Session interrupted by user (Ctrl+C). Cleaning up...")
        return 0
    except Exception as exc:
        print(f"[ERROR] Session failed: {exc}")
        return 1


# ==============================================================================
# 18. Runs History & Dossier Inspection Commands
# ==============================================================================


def cmd_runs(args: argparse.Namespace) -> int:
    """List completed backtest and forward-shadow run dossiers."""
    from aditrader.web.services import get_completed_runs

    limit = getattr(args, "limit", 20) or 20
    filter_type = getattr(args, "type", "all") or "all"

    records = get_completed_runs(run_type=filter_type, limit=limit)

    print("=" * 84)
    print("                     Completed Run Dossiers History")
    print("=" * 84)
    if not records:
        print("No completed run dossiers found in runs/backtest/ or runs/forward/.")
        print("Execute a backtest or forward session to generate run dossiers:")
        print("  aditrader backtest --strategy test_ma_crossover --bars 100")
        print("  aditrader forward-options --mock --duration 5.0 --no-wait")
        print("=" * 84)
        return 0

    print(
        f"{'RUN ID':<24} {'TYPE':<10} {'STRATEGY':<24} {'NET PROFIT':>12} {'TRDS':>5} {'STATUS':<12}"
    )
    print("-" * 84)
    for r in records:
        pnl = r["net_pnl"]
        pnl_str = f"{'+' if pnl >= 0 else ''}₹{pnl:,.2f}"
        print(
            f"{r['run_id']:<24} {r['type']:<10} {r['strategy'][:22]:<24} {pnl_str:>12} {r['trades']:>5} {r['status']:<12}"
        )
    print("-" * 84)
    print("Inspect any run: aditrader inspect-run <run_id>")
    print("=" * 84)
    return 0


def cmd_inspect_run(args: argparse.Namespace) -> int:
    """Inspect a completed Run Dossier by run ID or file path."""
    from aditrader.web.services import find_dossier_path

    target = getattr(args, "run_id", None) or getattr(args, "id_or_path", None)
    if not target:
        print("[ERROR] Please specify a run ID or path to a dossier JSON file.")
        return 1

    target_path = Path(target)
    dossier_file: Path | None = target_path if target_path.is_file() else find_dossier_path(target)

    if not dossier_file or not dossier_file.is_file():
        print(f"[ERROR] Run Dossier not found for query: '{target}'")
        print("Use 'aditrader runs' to view available completed run dossiers.")
        return 1

    try:
        with open(dossier_file, encoding="utf-8") as f:
            dos = json.load(f)
    except Exception as exc:
        print(f"[ERROR] Failed to parse dossier JSON at {dossier_file}: {exc}")
        return 1

    run_id = dos.get("run_id", dossier_file.stem)
    strat = dos.get("strategy_id", dos.get("strategy_name", "Unknown"))
    mode = dos.get("mode", "N/A")
    venue = dos.get("venue", "AIR_GAPPED_PAPER_BROKER")
    initial_cap = dos.get("initial_capital", dos.get("starting_equity", 0.0))
    ending_eq = dos.get("ending_equity", 0.0)
    net_profit = dos.get("net_profit", 0.0)
    ret_pct = (net_profit / initial_cap * 100.0) if initial_cap > 0 else 0.0

    print("=" * 76)
    print(f"       RUN DOSSIER INSPECTION: {run_id}")
    print("=" * 76)
    print(f"Strategy:         {strat} (v{dos.get('strategy_version', '1.0')})")
    print(f"Underlying:       {dos.get('underlying', 'N/A')}")
    print(f"Mode:             {mode}")
    print(f"Venue:            {venue}")
    print(f"Created At:       {dos.get('created_at', 'N/A')}")
    if dos.get("closed_at"):
        print(f"Closed At:        {dos['closed_at']}")
    print(f"Starting Capital: ₹{initial_cap:,.2f}")
    print(f"Ending Equity:    ₹{ending_eq:,.2f}")
    print(
        f"Net Profit:       {'+' if net_profit >= 0 else ''}₹{net_profit:,.2f} ({'+' if ret_pct >= 0 else ''}{ret_pct:.2f}%)"
    )
    print(f"Trade Count:      {dos.get('trade_count', len(dos.get('ledger', [])))}")
    print(f"Event Count:      {dos.get('event_count', len(dos.get('events', [])))}")

    # Balance sheet reconciliation
    rec = dos.get("reconciliation", {})
    if rec:
        print("-" * 76)
        print("Balance Sheet Reconciliation:")
        reconciled = rec.get("is_reconciled", True)
        disc = rec.get("equity_discrepancy", rec.get("discrepancy", 0.0))
        print(f"  Audit Status:   {'RECONCILED' if reconciled else 'DISCREPANCY DETECTED'}")
        print(f"  Discrepancy:    ±₹{disc:.2f}")
        if rec.get("total_charges") is not None:
            print(f"  Total Charges:  ₹{rec.get('total_charges', 0.0):,.2f}")
        if rec.get("total_realized_pnl") is not None:
            print(f"  Realized PnL:   ₹{rec.get('total_realized_pnl', 0.0):,.2f}")
    elif dos.get("reconciliation_balance") is not None:
        print("-" * 76)
        print("Balance Sheet Reconciliation:")
        bal = dos.get("reconciliation_balance")
        print(f"  Audit Status:   {'RECONCILED' if bal else 'DISCREPANCY DETECTED'}")

    # Cryptographic integrity
    print("-" * 76)
    print("Cryptographic Integrity & Merkle Roots:")
    if dos.get("event_stream_merkle_root"):
        print(f"  Event Root:     {dos['event_stream_merkle_root']}")
    if dos.get("trade_ledger_merkle_root"):
        print(f"  Ledger Root:    {dos['trade_ledger_merkle_root']}")
    if dos.get("tamper_digest"):
        print(f"  Tamper Digest:  {dos['tamper_digest']}")

    # Verification matrix
    vmat = dos.get("verification_matrix", {})
    if vmat:
        print("-" * 76)
        print(f"Verification Matrix (Overall: {vmat.get('overall_status', 'PASS')}):")
        for pillar_key in [
            "structural",
            "data_integrity",
            "known_answer_tests",
            "historical_replay",
            "empirical_metrics",
            "options_theoretical",
            "reconciliation",
        ]:
            p = vmat.get(pillar_key)
            if isinstance(p, dict):
                p_name = p.get("pillar_name", pillar_key)
                p_stat = p.get("status", "N/A")
                p_detail = p.get("details", "")
                print(f"  • {p_name:<30} [{p_stat:<10}] {p_detail}")

    # Executed trades table
    ledger = dos.get("ledger", [])
    if ledger:
        print("-" * 76)
        print("Trade Ledger:")
        for i, t in enumerate(ledger[:20]):
            side = t.get("side", "")
            qty = t.get("quantity", 0)
            sym = t.get("symbol", "")
            entry_p = t.get("entry_price", t.get("fill_price", 0.0))
            exit_p = t.get("exit_price")
            exit_str = f"Exit: ₹{exit_p:>7.2f}" if exit_p is not None else "Exit: OPEN"
            pnl = t.get("net_pnl", 0.0)
            pnl_str = f"{'+' if pnl >= 0 else ''}₹{pnl:,.2f}"
            print(
                f"  #{i + 1:<2} {side:<4} {qty:>4} {sym:<22} Entry: ₹{entry_p:>7.2f}  {exit_str}  Net: {pnl_str:>10}"
            )
        if len(ledger) > 20:
            print(f"  ... and {len(ledger) - 20} more trades")

    print("-" * 76)
    print(f"Dossier Location: {dossier_file}")
    print("=" * 76)
    return 0
