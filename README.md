# QuantumValidator / AdiTrader

**Institutional-Grade Paper-Trading & Quantitative Research Platform for Indian Equity & Derivatives Markets**

---

## System Overview

QuantumValidator (AdiTrader) is a decoupled, mathematically rigorous quantitative research and simulation operating system designed for National Stock Exchange of India (NSE) cash equities and F&O derivatives.

The platform guarantees institutional simulation integrity, strict anti-lookahead historical backtesting, theoretical payoff modeling for non-linear option structures, an AST-compiled declarative strategy DSL, and comprehensive pre-trade risk controls.

---

## Architectural & Security Invariants

1. **Strict Air-Gapped Paper Execution (ADR 002)**: Broker adapters (`data/adapters/`) are strictly read-only for market data ingestion and scrip master discovery. Order routing methods are permanently barred; all order state transitions and fills occur inside `core.PaperBroker`.
2. **Deterministic Anti-Lookahead Backtesting**: Historical bar replays enforce zero lookahead bias. Signals generated at Bar $T$ close are executed at Bar $T+1$ open with realistic friction and volume participation limits.
3. **Options Simulation Air-Gap (ADR 011)**: Multi-leg option strategies cannot be proxied onto underlying spot candles. Linear assets are validated statistically via historical backtests; multi-leg options are validated theoretically via Black-Scholes Greeks, payoff curves, and margin/wing risk models.
4. **Declarative AST Compilation (ADR 001, ADR 007)**: Strategies are compiled from version-controlled JSON AST trees into stateless state machines. Dynamic code evaluation (`eval()`, `exec()`) is prohibited.
5. **Advisory AI Isolation (ADR 005, ADR 012)**: All AI subsystems (Gemini Vision, OCR, OpenRouter) remain purely advisory with complete provenance tracking and cannot place trades or alter validation verdicts.

---

## Run QuantumValidator Locally

Follow this step-by-step workflow to install, verify, and run QuantumValidator from a fresh clone.

### 1. Prerequisites & Environment Activation

QuantumValidator requires **Python 3.11+** on Linux (or macOS/WSL2).

```bash
# Clone repository
git clone https://github.com/adityaxd/aditrader.git
cd aditrader

# Create virtual environment with Python 3.11+
python3 -m venv .venv

# Activate virtual environment
source .venv/bin/activate

# Upgrade pip and install package with development dependencies
pip install --upgrade pip
pip install -e ".[dev]"
```

### 2. Configure Environment Variables

Create your local `.env` file from the provided safe template:

```bash
cp .env.example .env
```

* **Offline Development**: The default values in `.env` are preconfigured for local offline simulation with SQLite (`runs/aditrader.db`), local Parquet caching (`data/cache/`), and synthetic/mock market data feeds. No external credentials are required to start or backtest.
* **Optional Live Feeds**: To connect to live Kotak Neo market data streams, populate `KOTAK_CONSUMER_KEY`, `KOTAK_CONSUMER_SECRET`, `KOTAK_MOBILE_NUMBER`, and `KOTAK_PASSWORD`.
* **Optional AI Providers**: To enable vision or OCR advisory parsing, add `GEMINI_API_KEY`, `OCRSPACE_API_KEY`, or `OPENROUTER_API_KEY`.
* **Security Rule**: Never commit `.env` or credential tokens into source control.

### 3. Initialize the Local Database

Initialize the local transactional SQLite ledger tables:

```bash
aditrader init-db
```
*Or apply database migrations via Alembic:*
```bash
alembic upgrade head
```

This creates the local database file at `runs/aditrader.db` with WAL mode enabled (ADR 008) and schemas for `orders`, `positions`, `trades`, and `account_balance`.

### 4. Verify System Readiness (Doctor)

Run the built-in diagnostic tool to verify runtime dependencies, database connectivity, directory permissions, and configuration:

```bash
aditrader doctor
# or: quantumvalidator doctor
```

A healthy installation will output:
```
====================================================================
      AdiTrader / QuantumValidator — System Diagnostics (Doctor)
====================================================================
[READY]            Python Runtime: 3.11.x (linux)
[READY]            Core Dependencies: All installed (pydantic, sqlalchemy, alembic, pyarrow, polars)
[READY]            Storage Directories: Writable (runs, data/cache)
[READY]            Configuration: Valid (env: development, tz: Asia/Kolkata)
[READY]            Database: Connected & initialized (sqlite:///runs/aditrader.db)
[OPTIONAL/MISSING] Broker Feed (Kotak Neo): Not configured (Mock mode active)
[OPTIONAL/MISSING] AI Vision (Gemini): Key not configured (offline fallback active)
--------------------------------------------------------------------
Diagnostic Summary: SYSTEM READY FOR OFFLINE RESEARCH & LOCAL REPLAY
--------------------------------------------------------------------
```

---

## Command Reference

The platform provides canonical CLI commands accessible via `aditrader`, `quantumvalidator`, or `python -m aditrader.cli`.

### Check System Status
```bash
aditrader status
```
Displays system version, environment, database connection and record counts, strategy catalog size, scrip cache status, and active validation policies.

### List & Inspect Strategy Templates
```bash
# List all built-in version-controlled strategies
aditrader strategies

# Inspect detailed metadata, legs, and Strategy DNA for a specific template
aditrader strategies --detail iron_condor
```

### Validate a Strategy
Validate multi-leg options or linear strategies against institutional risk gates (unhedged tail risk, slope boundary conditions, expectancy floors):

```bash
# Institutional Policy (Strict)
aditrader validate --strategy iron_condor

# Moderate Policy (Standard paper-trading thresholds)
aditrader validate --strategy bull_call_spread --policy moderate

# Validate from a custom JSON AST definition file
aditrader validate --file path/to/strategy.json
```

### Run a Deterministic Backtest
Execute historical backtests on linear assets (Equities / Futures) with realistic slippage, volume participation limits, and recorded simulation assumptions:

```bash
# Run backtest with 100 synthetic market bars
aditrader backtest --strategy test_ma_crossover --bars 100

# Run backtest against a historical CSV file
aditrader backtest --strategy test_ma_crossover --csv tests/fixtures/nifty_sample.csv --capital 1000000 --slippage-bps 2.5
```

### Search Instruments & Derivatives
Search the high-performance scrip index by symbol, trading symbol, strike, or derivative type:

```bash
aditrader search "NIFTY 24000 CE"
aditrader search "RELIANCE" --limit 5
```

### Forward Paper-Testing (Air-Gapped Rehearsal & Live Replay)
Execute forward-testing sessions connecting streaming market data directly through the pre-trade risk engine and strictly air-gapped `PaperBroker` with quote-aware fill execution:

```bash
# Run linear MA crossover on NIFTY for 50 ticks in mock rehearsal mode:
aditrader forward-test --strategy test_ma_crossover --ticks 50

# Run forward-testing session bounded by closed bars:
aditrader forward-test --strategy test_ma_crossover --bars 5 --timeframe 1s

# Run forward test with custom paper capital and save audit dossier:
aditrader forward-test --strategy test_ma_crossover --capital 2000000 --duration 10 --output runs/my_forward_session.json

# Run with strict market data quality checks (aborts immediately on crossed quotes or bad data):
aditrader forward-test --strategy test_ma_crossover --ticks 100 --strict-quality
```

---

## Getting Started Q&A

| Question | Answer |
| :--- | :--- |
| **How do I install dependencies?** | `pip install -e ".[dev]"` inside an active virtual environment. |
| **How do I activate the environment?** | `source .venv/bin/activate` |
| **How do I configure environment variables?** | `cp .env.example .env` and edit optional keys as needed. Safe defaults work offline out-of-the-box. |
| **How do I initialize the database?** | `aditrader init-db` (or `alembic upgrade head`). |
| **How do I verify installation?** | Run `aditrader doctor`. Ensure all core checks report `[READY]`. |
| **How do I start the application?** | Use `aditrader status`, `aditrader strategies`, `aditrader backtest`, `aditrader validate`, or `aditrader forward-test`. |
| **How do I start the research UI?** | **Not yet active**: The Plotly Dash UI is scheduled for **Phase 8**. Running `aditrader dashboard` prints an architectural roadmap notice. |
| **How do I start paper forward-testing?** | Run `aditrader forward-test --strategy <name>` with optional `--ticks`, `--bars`, or `--duration` limits. Uses strictly air-gapped `PaperBroker` and quote-aware fill simulation. |
| **Where are logs & results stored?** | SQLite database at `runs/aditrader.db`; session dossiers at `runs/forward/`; Parquet market caches at `data/cache/`. |
| **How do I stop the application?** | CLI commands execute deterministically and exit cleanly with standard return codes. For active sessions, send `SIGINT` (`Ctrl+C`) for graceful conclusion. |

---

## Verification & Quality Assurance

All commits must pass the institutional verification suite:

```bash
# 1. Run complete unit and integration test suite
pytest

# 2. Enforce strict static type checking across all files
mypy src tests

# 3. Verify code style and linting
ruff check src tests

# 4. Verify formatting
ruff format --check src tests
```

---

## Project Status & Roadmap

* **Phase 0–5.6**: Core Domain, Ledger Persistence, Order State Machine, Greeks Engine, AST Compiler, Strategy DNA, Backtest Engine, Risk Engine, Simulation Integrity — **COMPLETE & VERIFIED ✅**
* **Phase 6**: Tri-Path Strategy Validation Engine & Institutional Policy Framework — **COMPLETE & SEALED ✅**
* **Instrument Search Subsystem**: In-Memory Multi-Index, Token/Symbol Scoring, Scrip Master Parquet Caching — **COMPLETE & SEALED ✅**
* **Market Data Fidelity & Replay Parity**: Canonical Models, Kotak Neo Quote Parser, Aggregator Volume Modes & Quality Guards, Data Quality Engine, Simulation Assumptions & Forward Test Auditing — **COMPLETE & VERIFIED ✅**
* **Developer Experience & Local Startup Workflow**: Unified CLI Router (`doctor`, `status`, `init-db`, `strategies`, `search`, `validate`, `backtest`, `forward-test`), Setup Documentation — **COMPLETE & VERIFIED ✅**
* **Forward-Testing Runner**: Application Orchestrator, Quote-Aware Paper Fills, Pre-Trade Risk Gates, Session Lifecycle, Dossier & Ledger Persistence, CLI `aditrader forward-test` — **COMPLETE & VERIFIED ✅**
* **Phase 7**: AI Subsystems & Advisory Pipeline (Time-series Forecasting, Gemini Vision Pattern Parser, Strategy Suggestor, Quantitative Research Dossier) — **NEXT MILESTONE ⏳**
* **Phase 8**: Interactive Plotly Dash Research Workspace & Terminal UI — **SCHEDULED ⏳**
* **Phase 7A/7B**: Provider Registry, Model Catalog, Gemini Vision & OCR Runtime — **IN PROGRESS / CONTROLLED FOUNDATION**
* **Phase 8**: Plotly Dash Multi-Page Dashboard & Interactive Research Workspace — **PLANNED**
