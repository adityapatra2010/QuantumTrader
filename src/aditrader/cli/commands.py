"""CLI command implementations for AdiTrader / QuantumValidator."""

import argparse
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy import inspect as sa_inspect

from aditrader.backtesting.runner import BacktestConfig, BacktestRunner, UnsupportedStrategyError
from aditrader.config.settings import get_settings
from aditrader.core.costs import SlippageModel
from aditrader.core.ledger.repository import LedgerRepository
from aditrader.core.ledger.schema import OrderRecord, PositionRecord, TradeRecord
from aditrader.core.models.execution import Trade
from aditrader.core.models.market_data import Bar
from aditrader.core.models.trade_signal import Signal
from aditrader.data.adapters.kotak_neo import KotakNeoAdapter
from aditrader.data.feeds.csv_feed import CSVDataFeed
from aditrader.data.feeds.synthetic_feed import SyntheticDataFeed
from aditrader.data.forward import ForwardTestStatus
from aditrader.data.forward_runner import ForwardTestConfig, ForwardTestRunner
from aditrader.data.instruments.service import InstrumentSearchService
from aditrader.strategy.builder.schema import (
    ASTOperator,
    ConditionCategory,
    ConditionGroup,
    ConditionNode,
    StrategyDSL,
)
from aditrader.strategy.library.models import StrategyRecord
from aditrader.strategy.library.registry import StrategyRegistry
from aditrader.validation.models import ValidationStatus
from aditrader.validation.policies import (
    create_institutional_policy,
    create_moderate_policy,
    create_research_policy,
)
from aditrader.validation.service import StrategyValidationService


def _mask_secret(secret: str | None) -> str:
    """Mask secret value for safe diagnostic display."""
    if not secret:
        return "None"
    s = secret.strip()
    if len(s) <= 6:
        return "***"
    return f"{s[:2]}***{s[-2:]}"


def _find_strategy(registry: StrategyRegistry, query: str) -> StrategyRecord | None:
    """Find a registered strategy record by ID, exact name, or fuzzy match."""
    # 1. Direct ID match
    try:
        return registry.get(query)
    except Exception:
        pass

    # 2. Direct name match
    try:
        return registry.get_by_name(query)
    except Exception:
        pass

    # 3. Normalized / case-insensitive search
    q = query.lower().replace("-", " ").replace("_", " ").strip()
    for record in registry.list_all():
        name_clean = record.name.lower().replace("-", " ").replace("_", " ").strip()
        id_clean = record.id.lower().replace("-", " ").replace("_", " ").strip()
        if q in (name_clean, id_clean) or q in name_clean:
            return record

    return None


def _get_sample_ma_crossover() -> StrategyDSL:
    """Deterministic linear MA crossover strategy for local backtesting."""
    return StrategyDSL(
        schema_version="1.0",
        name="test_ma_crossover",
        underlying="NIFTY",
        timeframe="1m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="close",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=24000.0,
                )
            ],
        ),
        exit_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="close",
                    operator=ASTOperator.LESS_THAN,
                    threshold=23950.0,
                )
            ],
        ),
    )


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
        print("Scrip Master:      Not cached (run search or adapter scrip master download)")

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
        record = _find_strategy(registry, strategy_query)
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
            print(
                f"  Leg {i + 1}: {leg.side.value} {leg.contract_type} offset={leg.strike_offset} lots={leg.lots}"
            )
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
        record = _find_strategy(registry, args.strategy)
        if record:
            dsl = record.dsl_definition
        elif args.strategy.lower() in ("test_ma_crossover", "ma_crossover"):
            dsl = _get_sample_ma_crossover()
        else:
            print(f"[ERROR] Built-in strategy '{args.strategy}' not found.")
            return 1
    elif args.file:
        path = Path(args.file)
        if not path.is_file():
            print(f"[ERROR] Strategy file not found: {path}")
            return 1
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            dsl = StrategyDSL.model_validate(data)
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

    service = StrategyValidationService()
    report = service.validate(strategy=dsl, policy=policy)

    print(f"Target Underlying:     {dsl.underlying}")
    print(f"Timeframe:             {dsl.timeframe}")
    print(
        f"Validation Path:       {report.historical_vs_theoretical} ({report.validation_scope.value})"
    )
    print(
        f"Final Verdict:         {report.status.value} (Score: {report.validation_score:.1f}/100)"
    )

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
        record = _find_strategy(registry, args.strategy)
        if record:
            dsl = record.dsl_definition
        elif args.strategy.lower() in ("test_ma_crossover", "ma_crossover"):
            dsl = _get_sample_ma_crossover()
        else:
            print(f"[ERROR] Built-in strategy '{args.strategy}' not found.")
            return 1
    elif args.file:
        path = Path(args.file)
        if not path.is_file():
            print(f"[ERROR] Strategy file not found: {path}")
            return 1
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
            dsl = StrategyDSL.model_validate(data)
    else:
        print("[ERROR] Please specify either --strategy <name> or --file <path>")
        return 1

    # Check for option legs guard
    if dsl.legs:
        print("=" * 68)
        print(f"[AIR-GAP GUARD] Strategy '{dsl.name}' defines {len(dsl.legs)} option leg(s).")
        print("BacktestRunner strictly prohibits silent proxy simulation of multi-leg option")
        print("strategies on spot/futures candles (ADR 011).")
        print("To evaluate options strategies, run institutional payoff validation:")
        print(f"    aditrader validate --strategy {dsl.name}")
        print("=" * 68)
        return 1

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

    slip_bps = args.slippage_bps if args.slippage_bps is not None else 2.5
    config = BacktestConfig(
        initial_capital=args.capital or 1_000_000.0,
        slippage_model=SlippageModel(percentage=slip_bps / 10000.0),
        allow_same_bar_execution=False,
    )

    print("=" * 68)
    print(f" Backtest Simulation: '{dsl.name}' on {dsl.underlying}")
    print("=" * 68)

    runner = BacktestRunner(config=config)
    try:
        result = runner.run(strategy=strategy, data=feed)
    except UnsupportedStrategyError as exc:
        print(f"[AIR-GAP GUARD] {exc}")
        return 1

    perf = result.performance
    print(f"Processed Bars:        {result.bar_count}")
    print(f"Total Trades:          {perf.total_trades}")
    print(f"Starting Capital:      ₹{perf.starting_equity:,.2f}")
    print(f"Ending Capital:        ₹{perf.ending_equity:,.2f}")
    print(f"Net Realized PnL:      ₹{perf.net_profit:,.2f} ({perf.return_pct:.2f}%)")
    print(f"Win Rate:              {perf.win_rate * 100.0:.1f}%")
    print(f"Expectancy:            ₹{perf.expectancy:,.2f}")
    print(
        f"Profit Factor:         {f'{perf.profit_factor:.2f}' if perf.profit_factor is not None else 'N/A'}"
    )
    print(f"Max Drawdown:          {perf.max_drawdown_pct * 100.0:.2f}%")
    print(
        f"Sharpe Ratio:          {f'{perf.sharpe_ratio:.2f}' if perf.sharpe_ratio is not None else 'N/A'}"
    )
    print(
        f"Sortino Ratio:         {f'{perf.sortino_ratio:.2f}' if perf.sortino_ratio is not None else 'N/A'}"
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

    print("=" * 68)
    return 0


# ==============================================================================
# 8. Dashboard & Forward-Test Notices (Roadmap Boundaries)
# ==============================================================================


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Inform user that dashboard UI is scheduled for Phase 8."""
    print("=" * 68)
    print("                Plotly Dash Research Workspace")
    print("=" * 68)
    print("[NOTICE] The interactive Plotly Dash UI is scheduled for Phase 8")
    print("         (Dashboard & Interactive Research Workspace) per ROADMAP.md.")
    print("         Web servers and frontend handlers are not active in Phase 7.")
    print("         Please use available CLI research commands:")
    print("             aditrader doctor")
    print("             aditrader status")
    print("             aditrader strategies")
    print("             aditrader validate --strategy <name>")
    print("             aditrader backtest --strategy <name>")
    print("             aditrader search <query>")
    print("=" * 68)
    return 0


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
        print("  # Run Iron Condor options forward test for 30 seconds:")
        print("  aditrader forward-test --strategy iron_condor --duration 30")
        print()
        print("  # Run with custom paper capital and output dossier path:")
        print(
            "  aditrader forward-test --strategy test_ma_crossover --capital 2000000 --output runs/my_forward_run.json"
        )
        print("=" * 68)
        return 0

    # Resolve strategy
    registry = StrategyRegistry()
    record = _find_strategy(registry, strategy_arg)
    dsl: StrategyDSL | None = None
    if record:
        dsl = record.dsl_definition
    elif strategy_arg.lower() in ("test_ma_crossover", "ma_crossover"):
        dsl = _get_sample_ma_crossover()
    else:
        print(f"[ERROR] Strategy '{strategy_arg}' not found in registry.")
        return 1

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

    config = ForwardTestConfig(
        symbol=instrument,
        timeframe=timeframe,
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
        and settings.kotak_consumer_secret
        and settings.kotak_mobile_number
        and settings.kotak_password
    )
    mode_label = (
        "Kotak Neo Live WebSocket"
        if (has_credentials and not force_mock)
        else "Simulated Rehearsal (Mock Adapter)"
    )

    print("=" * 68)
    print("      AdiTrader / QuantumValidator — Forward Paper Testing")
    print("=" * 68)
    print("[EXECUTION VENUE] Strictly Air-Gapped PaperBroker (NO LIVE BROKER ORDERS)")
    print(f"Strategy:         {dsl.name} (v{getattr(dsl, 'schema_version', '1.0')})")
    print(f"Instrument:       {config.symbol}")
    print(f"Timeframe:        {config.timeframe}")
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
