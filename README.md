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

# Validate custom JSON, YAML, or Pine Script strategy file
aditrader validate --file path/to/strategy.json --policy institutional
aditrader validate --file path/to/strategy.yaml --policy institutional
aditrader validate --file path/to/strategy.pine --policy institutional
```

### 7. Deterministic Backtesting (`backtest`)
Execute point-in-time historical backtests on linear assets with statutory exchange taxes, slippage modeling, and volume participation limits:
```bash
# Backtest using synthetic market bars
aditrader backtest --strategy test_ma_crossover --bars 100

# Backtest using historical CSV dataset
aditrader backtest --strategy test_ma_crossover --csv tests/fixtures/nifty_sample.csv --capital 1000000 --slippage-bps 2.5

# Backtest using custom multi-format strategy file (YAML or translated Pine Script)
aditrader backtest --file path/to/strategy.yaml --csv tests/fixtures/nifty_sample.csv
aditrader backtest --file path/to/strategy.pine --bars 100
```

### 8. Dataset Discovery & Quality Inspection (`inspect-data`)
Inspect CSV market data files before replay. Automatically detects format variants (NSE Intraday, CM Bhavcopy, FO Bhavcopy, Index History, Derivative Quotes), verifies price envelopes, date ranges, and reports anomalies:
```bash
# Inspect any local CSV dataset (positional argument)
aditrader inspect-data data/nifty_sample.csv

# Inspect and filter for a specific scrip symbol via explicit flag
aditrader inspect-data --file data/cm_bhavcopy.csv --symbol RELIANCE

# Audit real-world NSE derivative quote archive datasets
aditrader inspect-data --file ~/Downloads/Quote-Derivative-RELIANCE-07-03-2026-07-09-2026.csv
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

### 12. Strategy Compatibility & Safety Inspector (`inspect-strategy`)
Inspect any strategy script or file without executing it. Automatically classifies format (JSON AST, YAML AST, TradingView Pine Script v4-v6, EasyLanguage, AmiBroker AFL, thinkScript, MetaTrader MQL4/MQL5, NinjaScript, LEAN, Backtrader, vectorbt, Freqtrade), checks lookahead bias (`barmerge.lookahead_on`), identifies multi-leg options air-gaps, and assesses translation fidelity:
```bash
# Inspect native JSON or YAML AST strategy (positional argument)
aditrader inspect-strategy strategy.yaml

# Inspect TradingView Pine Script with full construct fidelity matrix
aditrader inspect-strategy strategy.pine

# Inspect with explicit --file flag
aditrader inspect-strategy --file ~/Desktop/mcx.pine

# Inspect external Python or MetaTrader scripts safely (read-only AST parsing, zero execution)
aditrader inspect-strategy backtrader_model.py
```

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

## Market-Data Compatibility Matrix: Parseable vs Replayable

QuantumValidator maintains a strict, honest distinction between files that are statically **Parseable** (for inspection, discovery, metadata extraction, and quality verification) versus files that are **Replayable** (capable of driving the linear deterministic backtest or paper-trading runner loops). Missing market depth is never disguised with artificial quotes:

| Dataset Schema Format | Key Expected Headers | Parseable | Replayable | Replay Eligibility & Air-Gap Policy |
| :--- | :--- | :---: | :---: | :--- |
| **NSE Intraday (1m / 5m / 15m)** | `Date`, `Time` (or `timestamp`), `Open`, `High`, `Low`, `Close`, `Volume`, `OI` | **YES** | **YES** | **Replay Ready**: Sequential chronological candle stream for linear equity/futures strategies. Inactive bars preserve zero false alerts. |
| **NSE Capital Market Bhavcopy** | `SYMBOL`, `SERIES`, `OPEN`, `HIGH`, `LOW`, `CLOSE`, `TOTTRDQTY`, `TOTTRDVAL`, `TIMESTAMP` | **YES** | **YES** (Daily) | **Replayable for Daily Swing**: 1d single-bar snapshot per scrip. Authentic volume-weighted VWAP derived from `TOTTRDVAL / TOTTRDQTY`. |
| **NSE Historical Index CSV** | `Date`, `Open`, `High`, `Low`, `Close`, `Shares Traded`, `Turnover (Rs. Cr)` | **YES** | **YES** (Daily) | **Replay Ready**: Daily historical index benchmark series (e.g. NIFTY 50, NIFTY BANK). Cleans comma-formatted numbers safely. |
| **Generic OHLCV CSV** | `timestamp`, `open`, `high`, `low`, `close`, `volume` | **YES** | **YES** | **Replay Ready**: Standard linear spot/futures replay with strict `Asia/Kolkata` timezone localization. |
| **NSE F&O Bhavcopy** | `INSTRUMENT`, `SYMBOL`, `EXPIRY_DT`, `STRIKE_PR`, `OPTION_TYP`, `OPEN`, `HIGH`, `LOW`, `CLOSE`, `CONTRACTS`, `OPEN_INT` | **YES** | **NO** | **Air-Gapped (ADR 011)**: Contains multi-expiry, multi-strike derivatives snapshot rows. Bar runner refuses linear replay to prevent unhedged proxy fills. |
| **NSE Derivative Quotes (Daily F&O)** | `Instrument`, `Underlying`, `Expiry Date`, `Option Type`, `Strike Price`, `Open`, `High`, `Low`, `Close`, `Last`, `Settlement Price`, `Volume`, `Value`, `OI`, `Change in OI` | **YES** | **NO** | **Air-Gapped (ADR 011)**: Official exchange download archive format (e.g. `Quote-Derivative-RELIANCE-*.csv`). High-fidelity parser extracts 27,000+ contracts, 9+ expiries, settlement prices, and open interest. Preserved for Phase 8 option surface calibration. |

---

## Strategy Normalization & Compatibility Engine

QuantumValidator enforces a **Single Normalized Intermediate Representation (IR)**: the declarative `StrategyDSL` AST (`schema_version: "1.0"`). External strategies normalize into `StrategyDSL` rather than executing arbitrary imperative code:

| Strategy Format / Ecosystem | Detection Token | Translation Status | Semantic Fidelity | Normalization & Safety Policy |
| :--- | :--- | :--- | :--- | :--- |
| **Declarative JSON AST** | `JSON_DSL` | `SUPPORTED` | `EXACT` | Native institutional representation; validated against Pydantic schema v1.0. Zero dynamic code. |
| **Declarative YAML AST** | `YAML_DSL` | `SUPPORTED` | `EXACT` | Human-authored declarative AST parsed strictly via `yaml.safe_load`. Pure schema compilation. |
| **TradingView Pine Script (v4–v6)** | `PINE_SCRIPT` | `TRANSLATABLE` / `INSPECT_ONLY` | `EQUIVALENT` / `APPROXIMATED` | Deterministic indicator and logic subset translated. Procedural loops, mutable `var :=` state, and custom P&L fail closed (ADR 007). Lookahead bias triggers fatal rejection. |
| **TradeStation EasyLanguage** | `EASYLANGUAGE` | `INSPECT_ONLY` | `UNSUPPORTED` | Static AST token detection of inputs, vars, and order directives. Direct execution barred by ADR 007. |
| **AmiBroker AFL** | `AMIBROKER_AFL` | `INSPECT_ONLY` | `UNSUPPORTED` | Static token detection of `_SECTION_BEGIN`, `Buy`, `Sell`, and array operations. |
| **ThinkOrSwim thinkScript** | `THINKSCRIPT` | `INSPECT_ONLY` | `UNSUPPORTED` | Static token detection of `AddOrder`, study declarations, and lower plots. |
| **MetaTrader MQL4 / MQL5** | `METATRADER_MQL4/5` | `INSPECT_ONLY` | `UNSUPPORTED` | Static classification of `#property`, `OnInit`, `OnTick`, `OrderSend`. Direct execution barred. |
| **NinjaTrader NinjaScript (C#)** | `NINJATRADER` | `INSPECT_ONLY` | `UNSUPPORTED` | Static C# AST detection of `OnBarUpdate` and `Strategy` inheritance. |
| **QuantConnect LEAN** | `QUANTCONNECT_LEAN` | `INSPECT_ONLY` | `UNSUPPORTED` | Static detection of `QCAlgorithm`, `Initialize`, and resolution handlers. |
| **Python Frameworks (Backtrader, vectorbt, Freqtrade)** | `PYTHON_*` | `INSPECT_ONLY` | `UNSUPPORTED` | Read-only `ast.parse` inspection of classes and methods. **Raw code execution is strictly prohibited (ADR 007).** |

---

## Pine Script Construct Fidelity & Translation Matrix

When inspecting TradingView Pine Script (`@version=4`, `@version=5`, or `@version=6`), constructs are classified with explicit fidelity levels:

| Construct Category | Pine Script Syntax | Fidelity Level | Translatable? | QuantumValidator Behavior & Mapping |
| :--- | :--- | :---: | :---: | :--- |
| **Directives** | `//@version=5`, `strategy("Title", overlay=true)` | `EXACT` | YES | Configures strategy container name, overlay mode, and version. |
| **Directives** | `initial_capital = 100000`, `default_qty_value = 1` | `EXACT` | YES | Maps to backtest capital and default order size. |
| **Technical Indicators** | `ta.sma`, `ta.ema`, `ta.rsi`, `ta.atr`, `ta.macd`, `ta.supertrend` | `EXACT` | YES | Direct mapping to statically compiled, vectorized indicator classes. |
| **Timing Triggers** | `hour == 10 and minute == 0` | `EXACT` | YES | Maps directly to `ConditionCategory.TIME` (`time_of_day == "10:00"`). |
| **Order Directives** | `strategy.entry("Long", strategy.long)` | `EQUIVALENT` | YES | Maps to underlying long order signal in linear paper broker. |
| **Order Directives** | `strategy.entry("Short", strategy.short)` | `EQUIVALENT` | YES | Maps to underlying short order signal in linear paper broker. |
| **Order Exits** | `strategy.close("Long")` | `EQUIVALENT` | YES | Closes matching active position in paper ledger. |
| **Bracket Exits** | `strategy.exit("TP_SL", limit=..., stop=...)` | `EQUIVALENT` | YES | Bracket exit with take-profit limit and stop-loss protective orders. |
| **Emergency Exits** | `strategy.close_all()` | `EQUIVALENT` | YES | Unconditional position liquidation (e.g. EOD square-off or time stop). |
| **Crossovers** | `ta.crossover(a, b)`, `ta.crossunder(a, b)` | `EQUIVALENT` | YES | Maps to `ASTOperator.CROSSES_ABOVE` and `CROSSES_BELOW`. |
| **User Inputs** | `input.int(...)`, `input.float(...)`, `input.bool(...)` | `APPROXIMATED` | YES | Static configuration inputs; mapped as strategy parameter dictionary. |
| **Session Filters** | `input.session("0915-1530")` | `APPROXIMATED` | YES | Restricts strategy evaluation to exchange operating session hours. |
| **Multi-Condition** | `cond1 and cond2 or cond3` | `EQUIVALENT` | YES | Compiles to nested `ConditionGroup` nodes with `AND`/`OR` operators. |
| **Persistent State** | `var int count = 0`, `count := count + 1` | `UNSUPPORTED` | **NO (Blocker)** | Mutable procedural state across bars is barred by ADR 007 from declarative AST. |
| **Procedural Loops** | `for i = 0 to 10`, `while cond` | `UNSUPPORTED` | **NO (Blocker)** | Iterative loops barred by ADR 007; strategies must use vectorized indicators. |
| **Multi-Timeframe** | `request.security(syminfo.tickerid, "D", close)` | `UNSUPPORTED` | **NO (Blocker)** | Multi-timeframe requests require synchronized multi-resolution feed replay. |
| **Lookahead Bias** | `barmerge.lookahead_on` | `UNSUPPORTED` | **NO (FATAL)** | Repainting / future leakage strictly prohibited; inspection and validation reject immediately. |
| **Synthetic P&L** | `currentPL = 1000 - priceDiff * 2` | `UNSUPPORTED` | **NO (Blocker)** | Custom algebraic P&L cannot override PaperBroker mark-to-market accounting. |
| **Visual Elements** | `plot`, `plotshape`, `fill`, `hline`, `bgcolor` | `VISUAL_ONLY` | NO | Chart rendering elements on TradingView; safely ignored during simulation. |
| **Canvas Drawings** | `box.new`, `line.new`, `label.new`, `table.new` | `VISUAL_ONLY` | NO | Interactive chart drawings; safely ignored during simulation. |
| **Alerts** | `alertcondition(...)` | `VISUAL_ONLY` | NO | Webhook triggers; safely ignored during offline paper execution. |

---

## Real-World Adversarial Case Studies

### Case Study 1: `myst.pine` — Synthetic Options Simulation vs Real Option Legs (ADR 011)

An adversarial TradingView strategy titled `"4-Leg Weekly Iron Fly & Broken Wing Straddle Simulation"` was analyzed:
* **The Claim**: The strategy's title and comments claimed to trade an institutional 4-leg Iron Fly option structure with broken wing asymmetry.
* **The Reality**: Deep inspection revealed the script only submitted single underlying spot orders (`strategy.entry("Long", strategy.long)`) and calculated option payoffs via synthetic algebraic formulas in script variables (`priceDiff = math.abs(close - atmStrike)`, `currentPL = 1000 - priceDiff * 2`). No real option contracts, strike ladders, expiries, or Black-Scholes Greeks were involved.
* **QuantumValidator Resolution**:
  1. `aditrader inspect-strategy` successfully inspected the script (exit code 0), classifying all constructs without executing code.
  2. Flagged a prominent **`[SEMANTIC MISMATCH DETECTED]`** warning and a **`[CUSTOM P&L ARITHMETIC AUDIT]`** breakdown, proving that zero option legs were actually traded.
  3. Correctly reported `has_options_legs: false`, preserving the **Options Simulation Air-Gap (ADR 011)** by refusing to pretend a linear spot order was a multi-leg derivative.
  4. `aditrader validate` failed closed (exit code 1) with precise blocker diagnostic notices pointing the developer to `inspect-strategy`.

### Case Study 2: `mcx.pine` — MCX Gold vs International XAUUSD Portability Audit

A production strategy titled `"4H Range Sweep v2 - MCX Gold (India)"` was subjected to an adversarial cross-market portability audit:
* **The Context**: A 4H liquidity range sweep strategy originally designed for international Forex/CFD markets (XAUUSD) was ported by an author to the Indian Multi Commodity Exchange (MCX) without adjusting contract sizing, market hours, or statutory taxes.
* **QuantumValidator Resolution**:
  `aditrader inspect-strategy --file ~/Desktop/mcx.pine` automatically performed an in-depth **`[INSTRUMENT PORTABILITY AUDIT]`**:
  1. **Critical Capital Inadequacy**: Script configured `initial_capital = 100,000` (₹1 Lakh) and `default_qty = 1` contract. On MCX Gold, standard contract lot size is **1 kg** (~₹80 Lakhs notional value), requiring minimum SEBI/MCX SPAN + ELM margin of **₹8,00,000–₹10,00,000**. The account had only ~12% of required margin; all orders would immediately fail pre-trade risk gates. (In XAUUSD CFD trading, $100k demo capital with 1:500 leverage allows trading 1 lot with just $500 margin).
  2. **Session Timing Mismatch**: Script hardcoded `sessionWindow = "0915-2330 IST"` (NSE equity hours). However, **MCX commodity trading opens at 09:00 AM IST**, causing the strategy to blindly clip off the first 15 minutes of MCX opening price discovery and gap sweeps.
  3. **Commission Underestimation Risk**: Script assumed a flat `commission_value = 50` cash per contract. In India, statutory commodity taxes (CTT 0.01% on sell = ₹800/lot, Stamp Duty 0.002%, MCX turnover charges, SEBI fees, 18% GST) exceed **₹1,100–₹1,500 per lot** on an ₹80 Lakh contract (24x higher than assumed), heavily distorting backtest profit factor.
  4. **Contract Expiry & Settlement**: XAUUSD is a perpetual cash-settled CFD; MCX Gold Futures are bi-monthly contracts with **compulsory physical delivery** and delivery tender margin escalations.
  5. **Verdict**: Rated **`UNSAFE - CRITICAL CAPITAL & REGULATORY MISMATCH`**, protecting quant researchers from catastrophic real-world deployment failures while confirming valid mathematical sweep logic was preserved.

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
