"""Primary CLI entrypoint and command router for AdiTrader / QuantumValidator."""

import argparse
import sys
from collections.abc import Sequence

from aditrader.cli.commands import (
    cmd_backtest,
    cmd_dashboard,
    cmd_doctor,
    cmd_explain_strategy,
    cmd_forecast,
    cmd_forward_options,
    cmd_forward_test,
    cmd_init_db,
    cmd_inspect_data,
    cmd_inspect_run,
    cmd_inspect_strategy,
    cmd_kotak_auth,
    cmd_kotak_discover,
    cmd_kotak_history,
    cmd_kotak_option_chain,
    cmd_research_dossier,
    cmd_review_strategy,
    cmd_runs,
    cmd_search,
    cmd_smoke_feed,
    cmd_status,
    cmd_strategies,
    cmd_suggest_strategy,
    cmd_tui,
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
    p_val.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Path to CSV historical candle dataset for empirical statistical validation",
    )
    p_val.add_argument(
        "--bars",
        type=int,
        default=None,
        help="Number of synthetic historical bars to simulate for empirical validation",
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
        default=True,
        help="Start the live responsive HTTP research dashboard server (default: True)",
    )
    p_dash.add_argument(
        "--no-serve",
        dest="serve",
        action="store_false",
        help="Display dashboard server information without launching the server",
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
    p_inspect.add_argument(
        "file", nargs="?", type=str, default=None, help="Path to CSV file to inspect"
    )
    p_inspect.add_argument(
        "--file",
        type=str,
        dest="file_opt",
        default=None,
        help="Path to CSV file to inspect (flag alternative)",
    )
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
    p_insp_strat.add_argument(
        "file",
        nargs="?",
        type=str,
        default=None,
        help="Path to strategy file to inspect",
    )
    p_insp_strat.add_argument(
        "--file",
        type=str,
        dest="file_opt",
        default=None,
        help="Path to strategy file to inspect (flag alternative)",
    )
    p_insp_strat.set_defaults(handler=cmd_inspect_strategy)

    # 13. kotak-auth
    p_kotak_auth = subparsers.add_parser(
        "kotak-auth",
        help="Run Kotak Neo API authentication smoke test and data session capability check",
    )
    p_kotak_auth.add_argument(
        "--mock",
        action="store_true",
        default=False,
        help="Force offline simulated mock authentication check",
    )
    p_kotak_auth.set_defaults(handler=cmd_kotak_auth)

    # 14. kotak-discover
    p_kotak_disc = subparsers.add_parser(
        "kotak-discover",
        help="Execute 5-stage progressive Kotak Neo retrieval and 10-year options suitability discovery",
    )
    p_kotak_disc.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory to persist raw API response captures and capability report",
    )
    p_kotak_disc.add_argument(
        "--mock",
        action="store_true",
        default=False,
        help="Run discovery suite using offline simulated mock adapter",
    )
    p_kotak_disc.set_defaults(handler=cmd_kotak_discover)

    # 15. kotak-history
    p_kotak_hist = subparsers.add_parser(
        "kotak-history",
        help="Fetch historical OHLCV candle data via Kotak Neo, capture raw JSON, and audit integrity",
    )
    p_kotak_hist.add_argument(
        "symbol",
        nargs="?",
        type=str,
        default=None,
        help="Instrument symbol (e.g., 'NIFTY', 'BANKNIFTY', or contract symbol)",
    )
    p_kotak_hist.add_argument(
        "--symbol",
        type=str,
        dest="symbol_arg",
        default=None,
        help="Instrument symbol (flag option)",
    )
    p_kotak_hist.add_argument(
        "--from-date",
        type=str,
        default=None,
        help="Start date in YYYY-MM-DD format (default: 30 days prior)",
    )
    p_kotak_hist.add_argument(
        "--to-date",
        type=str,
        default=None,
        help="End date in YYYY-MM-DD format (default: today)",
    )
    p_kotak_hist.add_argument(
        "--timeframe",
        type=str,
        default="5m",
        choices=["1m", "3m", "5m", "10m", "15m", "30m", "60m", "1d", "1w"],
        help="Historical candle interval (default: 5m)",
    )
    p_kotak_hist.add_argument(
        "--output",
        type=str,
        default=None,
        help="File path to write normalized JSON dataset",
    )
    p_kotak_hist.add_argument(
        "--mock",
        action="store_true",
        default=False,
        help="Force offline simulated mock data retrieval",
    )
    p_kotak_hist.set_defaults(handler=cmd_kotak_history)

    # 16. kotak-option-chain
    p_kotak_chain = subparsers.add_parser(
        "kotak-option-chain",
        help="Fetch and verify live Kotak Neo option chain, quotes, WebSocket, and Premium-Ladder selection",
    )
    p_kotak_chain.add_argument(
        "--underlying",
        type=str,
        default="NIFTY",
        help="Root underlying symbol (default: NIFTY)",
    )
    p_kotak_chain.add_argument(
        "--expiry",
        type=str,
        default=None,
        help="Expiration date in YYYY-MM-DD format (default: nearest active)",
    )
    p_kotak_chain.add_argument(
        "--count",
        type=int,
        default=100,
        help="Number of strikes to fetch around ATM (default: 100)",
    )
    p_kotak_chain.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory to save raw snapshot JSON (default: runs/kotak_raw)",
    )
    p_kotak_chain.add_argument(
        "--mock",
        action="store_true",
        default=False,
        help="Force offline simulated mock data retrieval",
    )
    p_kotak_chain.set_defaults(handler=cmd_kotak_option_chain)

    # 17. forward-options
    p_fwd_opt = subparsers.add_parser(
        "forward-options",
        help="Run live air-gapped paper-trading forward shadow session for option strategies",
    )
    p_fwd_opt.add_argument(
        "--strategy",
        "-s",
        type=str,
        default="tpl-nifty-ce-premium-ladder-v1",
        help="Strategy ID or YAML file path (default: tpl-nifty-ce-premium-ladder-v1)",
    )
    p_fwd_opt.add_argument(
        "--underlying",
        "-u",
        type=str,
        default="NIFTY",
        help="Root underlying index symbol (default: NIFTY)",
    )
    p_fwd_opt.add_argument(
        "--expiry",
        type=str,
        default=None,
        help="Target expiration date in YYYY-MM-DD format (default: nearest active Thursday)",
    )
    p_fwd_opt.add_argument(
        "--band",
        type=int,
        default=0,
        help="Active premium band index (default: 0 = Band 1: 50.0-59.5)",
    )
    p_fwd_opt.add_argument(
        "--capital",
        type=float,
        default=1_000_000.0,
        help="Initial simulated paper capital in INR (default: 1,000,000.0)",
    )
    p_fwd_opt.add_argument(
        "--slippage-bps",
        type=float,
        default=5.0,
        help="Execution slippage in basis points (default: 5.0)",
    )
    p_fwd_opt.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Maximum session run duration in seconds (default: full session until 15:30 IST)",
    )
    p_fwd_opt.add_argument(
        "--output-dir",
        type=str,
        default="runs/forward",
        help="Directory to save forward session Run Dossiers (default: runs/forward)",
    )
    p_fwd_opt.add_argument(
        "--raw-capture-dir",
        type=str,
        default="runs/kotak_raw",
        help="Directory to save raw option-chain snapshots (default: runs/kotak_raw)",
    )
    p_fwd_opt.add_argument(
        "--snapshot-interval",
        type=float,
        default=300.0,
        help="Periodic raw option chain capture interval in seconds (default: 300.0)",
    )
    p_fwd_opt.add_argument(
        "--mock",
        action="store_true",
        default=False,
        help="Force offline simulated mock feed for local rehearsal or unit testing",
    )
    p_fwd_opt.add_argument(
        "--no-wait",
        action="store_true",
        default=False,
        help="Do not wait for 09:15 IST market open if started before session hours",
    )
    p_fwd_opt.set_defaults(handler=cmd_forward_options)

    # 18. runs
    p_runs = subparsers.add_parser(
        "runs",
        help="List completed historical backtest and forward paper-trading run dossiers",
    )
    p_runs.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum number of runs to display (default: 20)",
    )
    p_runs.add_argument(
        "--type",
        type=str,
        choices=["all", "backtest", "forward"],
        default="all",
        help="Filter by execution run type (default: all)",
    )
    p_runs.set_defaults(handler=cmd_runs)

    # 19. inspect-run
    p_insp_run = subparsers.add_parser(
        "inspect-run",
        help="Inspect sealed Run Dossier details, trade ledger, and verification matrix",
    )
    p_insp_run.add_argument(
        "run_id",
        type=str,
        help="Run identifier or file path to dossier JSON",
    )
    p_insp_run.set_defaults(handler=cmd_inspect_run)

    # 20. explain-strategy
    p_expl = subparsers.add_parser(
        "explain-strategy",
        help="Generate grounded educational explanation of strategy logic, rules, and geometry",
    )
    expl_group = p_expl.add_mutually_exclusive_group(required=True)
    expl_group.add_argument("--strategy", type=str, help="Name of built-in strategy template")
    expl_group.add_argument("--file", type=str, help="Path to strategy AST JSON definition")
    p_expl.add_argument(
        "--model",
        type=str,
        default="strategy-explainer-v1",
        help="Explainer engine model identifier (default: strategy-explainer-v1)",
    )
    p_expl.set_defaults(handler=cmd_explain_strategy)

    # 21. suggest-strategy
    p_sugg = subparsers.add_parser(
        "suggest-strategy",
        help="Suggest strategy templates conditioned on market regime and 60/40 selling bias",
    )
    p_sugg.add_argument(
        "--regime",
        type=str,
        default="NORMAL_VOLATILITY",
        help="Identified market regime context (e.g. 'NORMAL_VOLATILITY', 'HIGH_VOLATILITY', 'BULLISH')",
    )
    p_sugg.add_argument(
        "--symbol",
        type=str,
        default="NIFTY",
        help="Root underlying instrument symbol (default: NIFTY)",
    )
    p_sugg.add_argument(
        "--forecast",
        type=str,
        default=None,
        choices=["bullish", "bearish", "neutral"],
        help="Optional directional forecast bias",
    )
    p_sugg.add_argument(
        "--validate",
        action="store_true",
        default=False,
        help="Immediately validate suggestion against institutional gates",
    )
    p_sugg.add_argument(
        "--out",
        type=str,
        default=None,
        help="Optional path to save generated StrategyDSL JSON",
    )
    p_sugg.set_defaults(handler=cmd_suggest_strategy)

    # 22. review-strategy
    p_rev = subparsers.add_parser(
        "review-strategy",
        help="Generate hostile adversarial review evaluating structural integrity and risk exposures",
    )
    rev_group = p_rev.add_mutually_exclusive_group(required=True)
    rev_group.add_argument("--strategy", type=str, help="Name of built-in strategy template")
    rev_group.add_argument("--file", type=str, help="Path to strategy AST JSON definition")
    p_rev.add_argument(
        "--policy",
        type=str,
        default="institutional",
        choices=["institutional", "moderate", "research"],
        help="Validation policy threshold profile (default: institutional)",
    )
    p_rev.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Path to CSV historical candle dataset for empirical review",
    )
    p_rev.add_argument(
        "--bars",
        type=int,
        default=None,
        help="Number of synthetic historical bars to simulate",
    )
    p_rev.set_defaults(handler=cmd_review_strategy)

    # 23. forecast
    p_fc = subparsers.add_parser(
        "forecast",
        help="Generate point-in-time probabilistic market price trajectory forecast",
    )
    p_fc.add_argument(
        "--symbol",
        type=str,
        default="NIFTY",
        help="Symbol or index to forecast (default: NIFTY)",
    )
    p_fc.add_argument(
        "--timeframe",
        type=str,
        default="5m",
        choices=["1m", "3m", "5m", "15m", "1d"],
        help="Bar timeframe interval (default: 5m)",
    )
    p_fc.add_argument(
        "--horizon",
        type=int,
        default=5,
        help="Number of future bars to forecast (default: 5)",
    )
    p_fc.add_argument(
        "--model",
        type=str,
        default="heuristic-drift-v1",
        help="Forecasting foundation model or heuristic identifier (default: heuristic-drift-v1)",
    )
    p_fc.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Path to CSV historical candle dataset",
    )
    p_fc.add_argument(
        "--bars",
        type=int,
        default=60,
        help="Number of synthetic historical bars if CSV not supplied (default: 60)",
    )
    p_fc.set_defaults(handler=cmd_forecast)

    # 24. research-dossier
    p_dos = subparsers.add_parser(
        "research-dossier",
        help="Compile complete multi-section institutional Research Dossier with ADR 012 provenance",
    )
    dos_group = p_dos.add_mutually_exclusive_group(required=True)
    dos_group.add_argument("--strategy", type=str, help="Name of built-in strategy template")
    dos_group.add_argument("--file", type=str, help="Path to strategy AST JSON definition")
    p_dos.add_argument(
        "--csv",
        type=str,
        default=None,
        help="Path to CSV historical candle dataset for empirical backtest section",
    )
    p_dos.add_argument(
        "--bars",
        type=int,
        default=None,
        help="Number of synthetic historical bars to simulate",
    )
    p_dos.add_argument(
        "--output",
        type=str,
        default=None,
        help="File path to save Markdown Research Dossier",
    )
    p_dos.set_defaults(handler=cmd_research_dossier)

    # 25. tui
    p_tui = subparsers.add_parser(
        "tui",
        help="Launch interactive terminal workstation (curses-based GUI/TUI)",
    )
    p_tui.set_defaults(handler=cmd_tui)

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
