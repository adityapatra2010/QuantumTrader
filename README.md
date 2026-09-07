# QuantumValidator / AdiTrader

**Institutional-Grade Paper-Trading & Quantitative Research Operating System for Indian Equity & Derivatives Markets**

---

## System Overview

QuantumValidator (AdiTrader) is a modular, mathematically rigorous quantitative research and paper-trading platform purpose-built for the National Stock Exchange of India (NSE) cash equities and F&O derivatives.

The platform guarantees institutional simulation integrity, strict anti-lookahead point-in-time historical replay, theoretical Black-Scholes Greek modeling for non-linear option structures, an AST-compiled declarative JSON strategy DSL, comprehensive pre-trade risk gates, multi-format NSE CSV ingestion with quality inspection, and a responsive web research workstation adhering to the institutional dark design system.

---

## Architectural & Security Invariants ("Never" Rules)

1. **Strict Air-Gapped Paper Execution (ADR 002)**: Real live broker order routing is physically impossible. Broker adapters (`data/adapters/`) are strictly read-only for market data ingestion and scrip discovery. All order state transitions, margin calculations, and fills occur strictly inside `core.PaperBroker`.
2. **Deterministic Anti-Lookahead Causality**: Historical bar and tick replays strictly enforce $exec\_ts \ge bar.timestamp$. Orders triggered by closed bar $T$ are executed at the prevailing market tick with verified causal timestamps.
3. **No Synthetic Quote Fabrication**: When replaying historical bar datasets or streaming depth-less quotes, the system records `bid=None` and `ask=None`. Missing market depth is never disguised with artificial bid/ask spreads.
4. **Options Simulation Air-Gap (ADR 011, ADR 013)**: Multi-leg options strategies cannot be simulated on linear spot bars without a dedicated option chain execution engine. Forward-testing multi-leg options strategies fails fast with `UnsupportedStrategyError`. Linear strategies are validated statistically via historical backtests; options strategies are evaluated theoretically via Black-Scholes Greeks, payoff curves, and margin/wing risk models.
5. **Declarative AST Compilation (ADR 001, ADR 007)**: Dynamic Python execution (`eval()`, `exec()`) is prohibited. All strategy logic is defined as versioned JSON AST trees with registered, statically compiled condition evaluators.
6. **Purely Advisory AI Isolation (ADR 005, ADR 012)**: All AI subsystems (Gemini Vision, OCR, OpenRouter) remain advisory with cryptographic input hash provenance (`SHA-256`) and cannot route orders or override validation verdicts.

---

## 60-Second Quickstart

```bash
# 1. Clone the repository and enter the directory
git clone https://github.com/adityaxd/aditrader.git
cd aditrader

# 2. Create and activate Python virtual environment (Python 3.11+)
python3 -m venv .venv
source .venv/bin/activate

# 3. Install package with development dependencies
pip install --upgrade pip
pip install -e ".[dev]"

# 4. Create local environment configuration from template
cp .env.example .env

# 5. Initialize the local SQLite transactional ledger
aditrader init-db

# 6. Verify environment health with Doctor
aditrader doctor
```

---

## Comprehensive Command Reference

The platform provides 11 verified CLI operations accessible via `aditrader`, `quantumvalidator`, or `python -m aditrader.cli`.

```
aditrader <command> [options]
```

### 1. System Diagnostics (`doctor`)
Run comprehensive checks across Python runtime, dependencies, storage directories, SQLite database connectivity, and optional broker credentials:
```bash
aditrader doctor
```

### 2. Operational Status (`status`)
Display active environment settings, database ledger records, strategy catalog count, scrip cache status, and active validation policies:
```bash
aditrader status
```

### 3. Initialize Database (`init-db`)
Initialize or upgrade the local SQLite transactional ledger tables (`orders`, `trades`, `positions`, `bars`, `account_balance`):
```bash
aditrader init-db
# or apply migrations via Alembic:
alembic upgrade head
```

### 4. Strategy Catalog (`strategies`)
List or inspect version-controlled built-in strategy templates and their multi-dimensional Strategy DNA:
```bash
# List all built-in strategy templates
aditrader strategies

# Inspect detailed metadata, AST structure, and Strategy DNA
aditrader strategies --detail iron_condor
aditrader strategies --detail test_ma_crossover
```

### 5. Scrip Search & Derivative Discovery (`search`)
Query the high-performance local in-memory scrip index by symbol, company name, strike, or derivative hierarchy:
```bash
# Search by index or underlying
aditrader search "NIFTY"

# Search specific option contract strike
aditrader search "NIFTY 24000 CE" --limit 5

# Search equity scrip
aditrader search "RELIANCE"
```

### 6. Quantitative Validation Gate (`validate`)
Validate linear or multi-leg option strategies through static AST rules and institutional risk floors (expectancy, drawdown, tail risk):
```bash
# Validate built-in option strategy under Institutional policy (strict default)
aditrader validate --strategy iron_condor

# Validate linear strategy under Moderate policy
aditrader validate --strategy test_ma_crossover --policy moderate

# Validate custom JSON strategy AST file
aditrader validate --file path/to/strategy.json --policy institutional
```

### 7. Deterministic Backtesting (`backtest`)
Execute point-in-time historical backtests on linear assets with statutory exchange taxes, slippage modeling, and volume participation limits:
```bash
# Backtest using synthetic market bars
aditrader backtest --strategy test_ma_crossover --bars 100

# Backtest using historical CSV dataset
aditrader backtest --strategy test_ma_crossover --csv tests/fixtures/nifty_sample.csv --capital 1000000 --slippage-bps 2.5
```

### 8. Dataset Discovery & Quality Inspection (`inspect-data`)
Inspect CSV market data files before replay. Automatically detects format variants (NSE Intraday, CM Bhavcopy, FO Bhavcopy, Index History), verifies price envelopes, date ranges, and reports anomalies:
```bash
# Inspect any local CSV dataset
aditrader inspect-data data/nifty_sample.csv

# Inspect and filter for a specific scrip symbol
aditrader inspect-data data/cm_bhavcopy.csv --symbol RELIANCE
```

### 9. Forward Paper-Testing Runner (`forward-test`)
Execute an air-gapped paper trading session connecting streaming or replayed market data through the pre-trade risk engine and strictly isolated `PaperBroker`:
```bash
# 1. Run in simulated rehearsal mode for 50 ticks
aditrader forward-test --strategy test_ma_crossover --ticks 50 --mock

# 2. Replay real historical CSV dataset for deterministic forward testing
aditrader forward-test --strategy test_ma_crossover --csv data/nifty_sample.csv

# 3. Run timed session with custom paper capital and write JSON audit dossier
aditrader forward-test --strategy test_ma_crossover --capital 2000000 --duration 15 --output runs/my_forward_session.json

# 4. Run with strict market data quality checks (fails fast on crossed or bad ticks)
aditrader forward-test --strategy test_ma_crossover --ticks 100 --strict-quality
```

### 10. Market-Data Feed Smoke Test (`smoke-feed`)
Verify live or mock WebSocket connectivity, TOTP authentication, scrip subscriptions, and tick normalization without placing orders (strictly read-only):
```bash
# Smoke test in mock rehearsal mode
aditrader smoke-feed --symbol NIFTY --ticks 5 --mock

# Smoke test against live Kotak Neo SFeed WebSocket (requires credentials in .env)
aditrader smoke-feed --symbol NIFTY --ticks 10 --timeout 20.0
```

### 11. Responsive Web GUI Dashboard (`dashboard`)
Launch the browser-first, responsive research workstation adhering to `DESIGN_LANGUAGE.md` (dark theme `#0E1117`, surface `#161B22`, border `#30363D`, Inter/JetBrains Mono fonts):
```bash
# Display dashboard configuration and roadmap status
aditrader dashboard

# Launch the live responsive HTTP dashboard server
aditrader dashboard --serve --port 8050
```
Open `http://127.0.0.1:8050` in your web browser (desktop, tablet, or smartphone).

---

## Responsive Web GUI Architecture

The dashboard server is built with zero unnecessary heavy web dependencies (using Python standard library `ThreadingHTTPServer`) and provides an institutional single-page research interface:

* **Real-Time State Badges**: Distinct visual indicators for `LIVE_CONNECTED`, `SIMULATED_REHEARSAL`, `CSV_REPLAY`, `LIVE_CONNECTING`, `LIVE_FAILED`, `UNSUPPORTED`, and `STALE_DATA`.
* **Portfolio & Ledger Analytics**: Real-time view of Total Capital, Available Cash, Realized P&L, Unrealized P&L, Margin Utilization %, open paper positions, and recent paper fills with itemized statutory charges (STT, exchange turnover, stamp duty).
* **Strategy Catalog & AST Explorer**: Interactive inspection of built-in templates, Strategy DNA vectors (Theta bias, delta profile, target regime), and declarative AST JSON definitions.
* **Run History & Dossier Viewer**: Access recorded forward-testing sessions and audit dossiers saved under `runs/forward/`.
* **Integrated Dataset Inspector**: Test any local CSV file path interactively with real-time feedback on schema classification, column recognition, and price envelope sanity.
* **Mobile-Responsive & Accessible**: Touch targets $\ge 44$px, responsive CSS grid (single column on mobile $<768$px; multi-column on desktop $\ge 768$px), and horizontal scrolling on dense financial tables.
* **Strict Security Air-Gap**: 100% read-only interface; zero order placement endpoints exist; sensitive project credentials and system paths are guarded against path traversal.

---

## NSE CSV Engine & Supported Formats

The high-fidelity `NSECSVParser` and `NSECSVInspector` natively recognize and normalize:

| Dataset Format | Expected Headers / Columns | Special Capabilities |
| :--- | :--- | :--- |
| **NSE Intraday (1m / 5m / 15m)** | `Date`, `Time` (or `timestamp`), `Open`, `High`, `Low`, `Close`, `Volume`, `OI` | Auto-combines separate date & time columns; infers bar interval; preserves trade counts. |
| **NSE Capital Market Bhavcopy** | `SYMBOL`, `SERIES`, `OPEN`, `HIGH`, `LOW`, `CLOSE`, `TOTTRDQTY`, `TOTTRDVAL`, `TIMESTAMP`, `TOTALTRADES` | Parses `dd-MMM-yyyy` dates; filters series (e.g. `EQ`); derives authentic volume-weighted VWAP. |
| **NSE F&O Derivatives Bhavcopy** | `INSTRUMENT`, `SYMBOL`, `EXPIRY_DT`, `STRIKE_PR`, `OPTION_TYP`, `OPEN`, `HIGH`, `LOW`, `CLOSE`, `CONTRACTS`, `OPEN_INT` | Resolves composite contract symbols; normalizes contract counts and open interest. |
| **NSE Historical Index CSV** | `Date`, `Open`, `High`, `Low`, `Close`, `Shares Traded`, `Turnover (Rs. Cr)` | Cleans comma-formatted numbers (`"21,500.50"`); parses turnover and volume safely. |
| **Generic OHLCV CSV** | `timestamp`, `open`, `high`, `low`, `close`, `volume` | Standard CSV candle replay with strict Asia/Kolkata timezone localization. |

---

## Developer Getting Started FAQ

| Question | Answer |
| :--- | :--- |
| **How do I install dependencies?** | `pip install -e ".[dev]"` inside an activated virtual environment (`.venv`). |
| **How do I activate the environment?** | `source .venv/bin/activate` (Linux/macOS) or `.venv\Scripts\activate` (Windows). |
| **How do I configure environment variables?** | `cp .env.example .env`. Safe default values work completely offline out-of-the-box. |
| **How do I initialize the database?** | Run `aditrader init-db` (creates SQLite WAL database at `runs/aditrader.db`). |
| **How do I verify installation?** | Run `aditrader doctor`. Ensure core runtime checks report `[READY]`. |
| **How do I inspect a CSV file before replay?** | Run `aditrader inspect-data path/to/market_data.csv`. |
| **How do I start paper forward-testing?** | Run `aditrader forward-test --strategy test_ma_crossover` with optional `--csv <path>`, `--ticks <N>`, or `--duration <sec>`. |
| **How do I launch the research UI?** | Run `aditrader dashboard --serve --port 8050` and open `http://127.0.0.1:8050` in a browser. |
| **Where are logs & simulation results saved?** | SQLite database at `runs/aditrader.db`; session dossiers at `runs/forward/`; scrip master Parquet caches at `data/cache/`. |
| **How do I stop active sessions?** | Send `SIGINT` (`Ctrl+C`) to cleanly flush in-progress bars, record final session metrics, and close database connections. |

---

## Quality Verification

All contributions must strictly satisfy the 4-stage quality gate before merging:

```bash
# 1. Run all unit and integration tests (368+ passing tests)
./.venv/bin/pytest tests/unit/

# 2. Strict static type analysis across all source files (0 errors)
./.venv/bin/mypy --strict src tests

# 3. Code formatting and linting
./.venv/bin/ruff check src tests

# 4. Format consistency check
./.venv/bin/ruff format --check src tests
```

---

## Milestone Progress

* **Phase 0–5.6**: Core Domain, Ledger Persistence, Greeks Engine, AST Compiler, Strategy DNA, Risk Engine — **COMPLETE & VERIFIED ✅**
* **Phase 6**: Tri-Path Strategy Validation Engine & Institutional Policy Framework — **COMPLETE & SEALED ✅**
* **Instrument Search Subsystem**: In-Memory Scrip Master Multi-Index & Scoring — **COMPLETE & SEALED ✅**
* **Forward-Testing Rehearsal & Audit Remediation**: Quote Truthfulness, Limit Clamping, Symmetrical Margins, Dynamic Tax Resolution — **COMPLETE & VERIFIED ✅**
* **Kotak Neo Live Market-Data Feed**: Official `kotakneoapi>=3.0.0` SFeed WebSocket Streaming, Explicit Readiness Handshake — **COMPLETE & VERIFIED ✅**
* **NSE CSV Ingestion & Dataset Discovery**: Intraday split Date/Time, CM/FO Bhavcopy, Index Historical, Static Dataset Inspector — **COMPLETE & VERIFIED ✅**
* **Responsive Web GUI Foundation**: Zero-Dependency Threading HTTP Server, Responsive Dark Technical UI (`DESIGN_LANGUAGE.md`), REST APIs — **COMPLETE & VERIFIED ✅**
* **Phase 7**: AI Subsystems & Advisory Pipeline (Time-series Forecasting, Gemini Vision Pattern Parser, Strategy Suggestor, Quantitative Research Dossier) — **NEXT MILESTONE ⏳**
* **Phase 8**: Plotly Dash Multi-Page Dashboard & Interactive Options Workstation — **PLANNED ⏳**
