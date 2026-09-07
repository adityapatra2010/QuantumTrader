"""Primary CLI entrypoint and command router for AdiTrader / QuantumValidator."""

import argparse
import sys
from collections.abc import Sequence

from aditrader.cli.commands import (
    cmd_backtest,
    cmd_dashboard,
    cmd_doctor,
    cmd_forward_test,
    cmd_init_db,
    cmd_inspect_data,
    cmd_inspect_strategy,
    cmd_search,
    cmd_smoke_feed,
    cmd_status,
    cmd_strategies,
    cmd_validate,
)


def build_parser() -> argparse.ArgumentParser:
    """Construct command-line interface parser and subcommands."""
    parser = argparse.ArgumentParser(
        prog="aditrader",
        description="AdiTrader / QuantumValidator — Institutional Quantitative Trading & Research OS",
    )
    subparsers = parser.add_subparsers(dest="subcommand", help="Available operations")

    # 1. doctor
    p_doctor = subparsers.add_parser(
        "doctor",
        help="Run comprehensive local system, dependency, and configuration diagnostics",
    )
    p_doctor.set_defaults(handler=cmd_doctor)

    # 2. status
    p_status = subparsers.add_parser(
        "status",
        help="Display active environment mode, database connectivity, and subsystem status",
    )
    p_status.set_defaults(handler=cmd_status)

    # 3. init-db
    p_init_db = subparsers.add_parser(
        "init-db",
        help="Initialize SQLite database tables for transactional ledger persistence",
    )
    p_init_db.set_defaults(handler=cmd_init_db)

    # 4. strategies
    p_strat = subparsers.add_parser(
        "strategies",
        help="List or inspect version-controlled built-in strategy templates",
    )
    p_strat.add_argument(
        "--detail",
        type=str,
        default=None,
        help="Name of specific strategy to inspect in detail",
    )
    p_strat.set_defaults(handler=cmd_strategies)

    # 5. search
    p_search = subparsers.add_parser(
        "search",
        help="Search broker scrip master instruments by symbol, strike, or derivative hierarchy",
    )
    p_search.add_argument("query", type=str, help="Search query (e.g. 'NIFTY', '24000 CE')")
    p_search.add_argument(
        "--limit", type=int, default=10, help="Maximum results to return (default: 10)"
    )
    p_search.set_defaults(handler=cmd_search)

    # 6. validate
    p_val = subparsers.add_parser(
        "validate",
        help="Validate strategy definition through static AST and institutional policy gates",
    )
    val_group = p_val.add_mutually_exclusive_group(required=True)
    val_group.add_argument("--strategy", type=str, help="Name of built-in strategy template")
    val_group.add_argument("--file", type=str, help="Path to strategy AST JSON definition")
    p_val.add_argument(
        "--policy",
        type=str,
        default="institutional",
        choices=["institutional", "moderate", "research"],
        help="Validation policy threshold profile (default: institutional)",
    )
    p_val.set_defaults(handler=cmd_validate)

    # 7. backtest
    p_bt = subparsers.add_parser(
        "backtest",
        help="Execute deterministic backtest simulation on linear assets against historical data",
    )
    bt_group = p_bt.add_mutually_exclusive_group(required=True)
    bt_group.add_argument("--strategy", type=str, help="Name of built-in strategy template")
    bt_group.add_argument("--file", type=str, help="Path to strategy AST JSON definition")
    p_bt.add_argument(
        "--bars",
        type=int,
        default=100,
        help="Number of synthetic historical bars to simulate (default: 100)",
    )
    p_bt.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Path to CSV historical candle dataset",
    )
    p_bt.add_argument(
        "--capital",
        type=float,
        default=1_000_000.0,
        help="Starting cash capital in INR (default: 1,000,000.0)",
    )
    p_bt.add_argument(
        "--slippage-bps",
        type=float,
        default=2.5,
        help="Execution slippage in basis points (default: 2.5)",
    )
    p_bt.set_defaults(handler=cmd_backtest)

    # 8. dashboard
    p_dash = subparsers.add_parser(
        "dashboard",
        help="Launch responsive research and paper-trading dashboard web interface",
    )
    p_dash.add_argument(
        "--port",
        type=int,
        default=8050,
        help="HTTP server port (default: 8050)",
    )
    p_dash.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="HTTP server host address (default: 127.0.0.1)",
    )
    p_dash.add_argument(
        "--serve",
        action="store_true",
        default=False,
        help="Start the live responsive HTTP research dashboard server",
    )
    p_dash.set_defaults(handler=cmd_dashboard)

    # 9. forward-test
    p_fwd = subparsers.add_parser(
        "forward-test",
        help="Run live air-gapped paper-trading forward session",
    )
    p_fwd.add_argument(
        "--strategy",
        "-s",
        type=str,
        default=None,
        help="Strategy name or ID to execute (e.g., 'test_ma_crossover', 'momentum_breakout')",
    )
    p_fwd.add_argument(
        "--instrument",
        "-i",
        type=str,
        default=None,
        help="Instrument trading symbol (defaults to strategy underlying symbol)",
    )
    p_fwd.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Path to CSV historical or intraday dataset for deterministic paper replay",
    )
    p_fwd.add_argument(
        "--timeframe",
        type=str,
        default=None,
        help="Bar aggregation timeframe override (e.g., '1m', '5m')",
    )
    p_fwd.add_argument(
        "--qty",
        type=int,
        default=None,
        help="Order execution quantity override (defaults to lot size for derivatives, 1 for equity)",
    )
    p_fwd.add_argument(
        "--volume-mode",
        type=str,
        choices=["TRADED_VOLUME", "TICK_COUNT", "CUMULATIVE", "INCREMENTAL"],
        default="TRADED_VOLUME",
        help="Volume aggregation semantics (default: TRADED_VOLUME)",
    )
    p_fwd.add_argument(
        "--capital",
        type=float,
        default=1_000_000.0,
        help="Starting paper trading capital in INR (default: 1,000,000.0)",
    )
    p_fwd.add_argument(
        "--slippage-bps",
        type=float,
        default=2.5,
        help="Execution slippage in basis points (default: 2.5)",
    )
    p_fwd.add_argument(
        "--mock",
        action="store_true",
        default=False,
        help="Force simulated mock broker feed even if live credentials are configured",
    )
    p_fwd.add_argument(
        "--ticks",
        type=int,
        default=None,
        help="Stop session automatically after processing N ticks",
    )
    p_fwd.add_argument(
        "--bars",
        type=int,
        default=None,
        help="Stop session automatically after completing N closed bars",
    )
    p_fwd.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Stop session automatically after N seconds",
    )
    p_fwd.add_argument(
        "--output",
        type=str,
        default=None,
        help="Custom file path to persist JSON session dossier",
    )
    p_fwd.add_argument(
        "--strict-quality",
        action="store_true",
        default=False,
        help="Halt session immediately on any market data quality anomaly",
    )
    p_fwd.set_defaults(handler=cmd_forward_test)

    # 10. smoke-feed
    p_smoke = subparsers.add_parser(
        "smoke-feed",
        help="Run safe read-only market data smoke test against Kotak Neo live or mock feed",
    )
    p_smoke.add_argument(
        "--symbol",
        type=str,
        default="NIFTY",
        help="Symbol or index to subscribe to (e.g. 'NIFTY', 'BANKNIFTY', 'RELIANCE')",
    )
    p_smoke.add_argument(
        "--ticks",
        type=int,
        default=5,
        help="Number of streaming ticks to receive before concluding (default: 5)",
    )
    p_smoke.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Readiness and collection timeout in seconds (default: 15.0)",
    )
    p_smoke.add_argument(
        "--mock",
        action="store_true",
        default=False,
        help="Force simulated mock broker feed even if credentials exist",
    )
    p_smoke.set_defaults(handler=cmd_smoke_feed)

    # 11. inspect-data
    p_inspect = subparsers.add_parser(
        "inspect-data",
        help="Inspect CSV market data file compatibility, columns, schema, and quality prior to replay",
    )
    p_inspect.add_argument("file", type=str, help="Path to CSV file to inspect")
    p_inspect.add_argument(
        "--symbol",
        type=str,
        default=None,
        help="Filter/target symbol to evaluate (optional)",
    )
    p_inspect.set_defaults(handler=cmd_inspect_data)

    # 12. inspect-strategy
    p_insp_strat = subparsers.add_parser(
        "inspect-strategy",
        help="Inspect strategy file syntax, language, constructs, lookahead safety, and compatibility",
    )
    p_insp_strat.add_argument("file", type=str, help="Path to strategy file to inspect")
    p_insp_strat.set_defaults(handler=cmd_inspect_strategy)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Primary entrypoint for CLI command execution."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not hasattr(args, "handler"):
        parser.print_help()
        return 0

    return int(args.handler(args))


if __name__ == "__main__":
    sys.exit(main())
