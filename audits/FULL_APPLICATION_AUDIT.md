# AdiTrader — Full Application Audit

## Audit Metadata

* **Audit Date**: 2026-09-16
* **Auditor**: Independent Quantitative Systems & Usability Auditor
* **Audit Methodology**: Clean-Room, Black-Box CLI & End-User Exploration followed by White-Box Architecture & Source Verification
* **Target Execution Venue**: Isolated Scratch Clone (Air-Gapped, Read-Only, 100% Mock Rehearsal)
* **Operating System**: Linux fedora 6.19.10-300.fc44.x86_64
* **Python Runtime**: Python 3.14.3
* **Primary Source of Truth**: GitHub Remote Published Repository

---

## Executive Summary

AdiTrader (QuantumValidator) presents a dual reality:

1. **Computational Core (High Integrity)**: When evaluated at the mathematical and accounting level (`core.PaperBroker`, Black-Scholes Greeks, dynamic premium ladder contract resolution, statutory tax calculators, and balance sheet reconciliation), the platform is extraordinarily rigorous. All 37 deterministic Known-Answer Tests (KAT) pass with paisa-level precision ($\pm ₹0.00$), and the physical air-gap preventing live broker execution is absolute.
2. **User Experience & Surface Integration (Fragile & Contradictory)**: When evaluated as an end-user product, the platform contains severe ergonomic traps, broken documentation paths, phantom strategies, unhandled Python/Pydantic tracebacks on common input errors, and out-of-the-box test failures.
   - On a fresh GitHub clone, **the test suite fails out of the box** (7 failures, 2 errors) due to an uncommitted directory (`src/aditrader/ui/assets`) and a hardcoded desktop path (`/home/aditya/Desktop/myst.pine`).
   - The CLI's own error suggestion instructs users to run an unquoted command that crashes bash.
   - The CLI provides **no command to inspect or summarize completed run dossiers**, leaving users at a dead-end.
   - When running `aditrader forward-options --mock`, the generated cryptographic dossier claims `"Real Kotak Neo live data stream verified."`, creating false audit evidence.
   - The AI subsystem (`src/aditrader/ai/`) is completely disconnected from all trading, backtesting, and validation workflows.

---

## Repository / Commit Audited

* **Repository URL**: `https://github.com/adityapatra2010/QuantumTrader.git`
* **Audited Branch**: `main` (Default branch)
* **Audited Commit SHA**: `ce321aa6336b1e1b68f7306fe22e4bdf0f67f01b`
* **Commit Message**: `feat(forward): implement Kotak Neo option chain integration and air-gapped forward-options runner`
* **Audit Clone Path**: `/home/aditya/.gemini/antigravity-cli/brain/0b8efa9c-af30-4a11-93b0-c222e6b239a2/scratch/QuantumTrader_Audit`
* **Working Tree State**: Clean (`nothing to commit, working tree clean`)

---

## Application Capability Inventory

| Subsystem / Component | Implemented Status | Verification Status | Notes |
|---|---|---|---|
| **CLI Dispatcher** (`aditrader`) | FULL | PASS WITH CONCERN | 17 subcommands; flat unorganized namespace; no grouping |
| **CLI Doctor** (`aditrader doctor`) | FULL | PASS | Verifies runtime, deps, SQLite DB, masked secrets |
| **CLI Status** (`aditrader status`) | FULL | PASS WITH CONCERN | Displays DB counts and strategies; references non-existent command |
| **CLI Init DB** (`aditrader init-db`) | FULL | PASS WITH CONCERN | Initializes SQLite; breaks subsequent `alembic upgrade head` |
| **CLI Strategies** (`aditrader strategies`) | FULL | PASS WITH CONCERN | Lists 5 templates; omits `test_ma_crossover` documented in README |
| **CLI Search** (`aditrader search`) | FULL | PASS | Rapid scrip discovery with score, type, lot size |
| **CLI Validate** (`aditrader validate`) | PARTIAL | BROKEN | Permanent dead-end for linear strategies; missing `--csv` flag |
| **CLI Backtest** (`aditrader backtest`) | FULL | PASS WITH CONCERN | Deterministic execution; raw tracebacks on negative numbers |
| **CLI Dashboard** (`aditrader dashboard`) | FULL | PASS WITH CONCERN | Requires redundant `--serve` flag to actually start |
| **CLI Forward-Test** (`aditrader forward-test`) | FULL | PASS WITH CONCERN | Silently falls back to mock mode without warning |
| **CLI Smoke-Feed** (`aditrader smoke-feed`) | FULL | PASS | Clear streaming output with LTP, Bid/Ask, Vol, OI |
| **CLI Inspect-Data** (`aditrader inspect-data`) | FULL | PASS | Auto-detects 5 NSE CSV formats; verifies envelopes |
| **CLI Inspect-Strategy** (`aditrader inspect-strategy`) | FULL | PASS | Multi-language construct classification and lookahead check |
| **CLI Kotak-Auth** (`aditrader kotak-auth`) | FULL | PASS WITH CONCERN | Reports "PASS (MOCK MODE)" when credentials absent |
| **CLI Kotak-Discover** (`aditrader kotak-discover`) | FULL | PASS | 5-stage historical discovery proving expired options amnesia |
| **CLI Kotak-History** (`aditrader kotak-history`) | FULL | PASS | Pulls OHLCV and runs integrity audit |
| **CLI Kotak-Option-Chain** (`aditrader kotak-option-chain`) | FULL | PASS | 202-contract snapshot, cross-check, selection verification |
| **CLI Forward-Options** (`aditrader forward-options`) | FULL | PASS WITH CONCERN | Fails closed on live credentials; prints no end-of-session summary |
| **Configuration** (`settings.py`) | FULL | PASS | Pydantic BaseSettings loading from `.env` |
| **Data: CSV Feed** (`csv_feed.py`, `nse_csv.py`) | FULL | PASS | Point-in-time streaming, strict envelope validation |
| **Data: Cache** (`cache.py`) | FULL | PASS | Parquet storage for scrip master and historical bars |
| **Data: Kotak Neo Adapter** (`kotak_neo.py`) | FULL | PASS | TOTP+MPIN auth, REST client, SFeed WebSocket |
| **Strategy: AST Compiler** (`compiler/engine.py`) | FULL | PASS | AST evaluation without eval/exec; registered operators |
| **Strategy: Translators** (`translators/pine.py`) | FULL | PASS | Translates Pine Script AST into declarative JSON |
| **Strategy: Library Registry** (`library/registry.py`) | FULL | PASS | 5 registered templates; Strategy DNA indexing |
| **Backtesting Engine** (`runner.py`) | FULL | PASS WITH CONCERN | Deterministic, anti-lookahead; Sharpe blown up on short samples |
| **Options Engine** (`options/payoff.py`, `greeks.py`) | FULL | PASS | Black-Scholes Greeks, payoff curves, wing margin |
| **PaperBroker** (`core/broker.py`) | FULL | PASS | Symmetrical margin gate, cash accounting, bid/ask fills |
| **Cost Calculator** (`core/costs.py`) | FULL | PASS | Official post-Oct 2024 NSE/SEBI statutory tax schedules |
| **Reconciliation Engine** (`verification/reconciliation.py`) | FULL | PASS | Invariant: Ending Equity = Starting Capital + Net Profit |
| **Provenance Engine** (`verification/trace.py`) | FULL | PASS | Step-by-step formula and input decomposition |
| **Cryptographic Sealing** (`backtesting/models.py`) | FULL | PASS | SHA-256 binary Merkle trees over event and trade streams |
| **AI Runtime** (`ai/`) | DEAD / UNUSED | PARTIAL | Modules exist, unit-tested, but zero calls in trading pipeline |
| **AI Forecasting** (`ai/forecasting/`) | UNIMPLEMENTED | UNIMPLEMENTED | 0-byte stub file |
| **AI Reviewer** (`ai/reviewer/`) | UNIMPLEMENTED | UNIMPLEMENTED | 0-byte stub file |
| **AI Suggestor** (`ai/suggestor/`) | UNIMPLEMENTED | UNIMPLEMENTED | 0-byte stub file |
| **AI Teacher** (`ai/teacher/`) | UNIMPLEMENTED | UNIMPLEMENTED | 0-byte stub file |
| **Database Persistence** (`aditrader.db`) | FULL | PASS WITH CONCERN | SQLite WAL; mismatch with Alembic baseline |
| **Web Dashboard** (`web/static/index.html`) | FULL | PASS | 7 responsive tabs, Plotly-free lightweight JS |

---

## End-User Journey

### Walkthrough of a New User's Experience

1. **Installation & Clone**: User clones `https://github.com/adityapatra2010/QuantumTrader.git`.
2. **First Run (`aditrader doctor`)**: User runs `doctor`. All checks pass with green status.
3. **Getting Started (`README.md`)**: User opens `README.md` and tries Section 4:
   ```bash
   aditrader strategies --detail test_ma_crossover
   ```
   **Crash**: CLI outputs `[ERROR] Strategy 'test_ma_crossover' not found in registry.`
4. **Trying Backtest from Docs**: User tries Section 7:
   ```bash
   aditrader backtest --strategy test_ma_crossover --csv tests/fixtures/nifty_sample.csv
   ```
   **Crash**: CLI outputs `[ERROR] CSV historical data file not found: tests/fixtures/nifty_sample.csv`.
5. **Trying Option Strategy Backtest**: User tries:
   ```bash
   aditrader backtest --strategy "NIFTY CE Premium Ladder"
   ```
   CLI rejects backtest and suggests:
   ```text
   aditrader validate --strategy NIFTY CE Premium Ladder
   ```
   User copies and pastes this command.
   **Crash**: `aditrader: error: unrecognized arguments: CE Premium Ladder`.
6. **Trying Linear Strategy Validation**: User tries:
   ```bash
   aditrader validate --strategy "Nifty Intraday Trend"
   ```
   **Crash**: Command exits with error code 1: `Failed Gates: [GATE] MISSING_BACKTEST_RESULT`. The user inspects `aditrader validate --help` and discovers there is no way to pass data.
7. **Running Forward-Options Mock**: User runs:
   ```bash
   aditrader forward-options --mock --duration 5.0 --no-wait
   ```
   Output displays:
   ```text
   [SUCCESS] Forward shadow session concluded cleanly.
   Sealed Dossier: runs/forward/forward_dossier_fwd_opt_10408968.json
   ```
   No summary of trades, P&L, fees, or capital is printed. User has no idea whether money was made or lost.
8. **Inspecting Results**: User searches `aditrader --help` for a command to inspect the run dossier. No such command exists. User is forced to manually inspect raw JSON files.
9. **Inspecting Mock Dossier**: User opens the JSON file and reads line 40:
   `"details": "Real Kotak Neo live data stream verified."`
   The user realizes the mock rehearsal run produced a dossier falsely claiming real broker data.

---

## CLI Audit

### Summary of Commands and Behaviors

1. **`aditrader doctor`**: PASS. Clean output, correctly masks secrets, reports runtime and database status.
2. **`aditrader status`**: PASS WITH CONCERN. Displays database table counts and registered strategy templates. However, references non-existent command: `(run search or adapter scrip master download)`.
3. **`aditrader init-db`**: PASS WITH CONCERN. Creates 4 tables via `metadata.create_all()`. Does not stamp Alembic version, breaking `alembic upgrade head`.
4. **`aditrader strategies`**: PASS WITH CONCERN. Lists 5 registered templates. Accepts `--detail <name_or_id>`. Rejects `test_ma_crossover` which is the primary example in documentation.
5. **`aditrader search`**: PASS. Accurate search with score and lot size.
6. **`aditrader validate`**: BROKEN for linear strategies. Lacks `--csv` or `--bars` arguments; always fails linear strategies with `MISSING_BACKTEST_RESULT`.
7. **`aditrader backtest`**: PASS WITH CONCERN. Correctly executes deterministic simulation, enforces ADR 011 air-gap, applies statutory taxes. Dumps raw tracebacks on negative `--bars` or negative `--capital`. Mislabels net profit as "Net Realized PnL" when open positions exist.
8. **`aditrader dashboard`**: PASS WITH CONCERN. Running without `--serve` does nothing except tell the user to run with `--serve`.
9. **`aditrader forward-test`**: PASS WITH CONCERN. Executes linear forward session in PaperBroker. Silently falls back to mock mode when Kotak credentials are absent.
10. **`aditrader smoke-feed`**: PASS. Verified tick streaming, bid/ask quotes, volume, and open interest.
11. **`aditrader inspect-data`**: PASS. Excellent format detection (`NSE_INTRADAY`, `NSE_DERIVATIVE_QUOTE`, `NSE_CM_BHAVCOPY`, `NSE_FO_BHAVCOPY`, `NSE_INDEX_HISTORY`).
12. **`aditrader inspect-strategy`**: PASS. Comprehensive script inspection, lookahead bias detection, and construct fidelity matrix.
13. **`aditrader kotak-auth`**: PASS WITH CONCERN. Reports `PASS (MOCK MODE)` when credentials are absent, giving ambiguous feedback.
14. **`aditrader kotak-discover`**: PASS. Thorough 5-stage retrieval capability check proving expired option amnesia on broker API.
15. **`aditrader kotak-history`**: PASS. Fetches historical candles and audits envelope integrity.
16. **`aditrader kotak-option-chain`**: PASS. Fetches and parses 202-contract option chain with cross-checks.
17. **`aditrader forward-options`**: PASS WITH CONCERN. Executes dynamic premium ladder, ratio hedge, and trailing stop ratchet. Fails closed on missing credentials in real mode. Fails to print performance summary on completion.

---

## Configuration Audit

* **Source File**: `src/aditrader/config/settings.py`
* **Configuration Model**: Pydantic `BaseSettings` reading from environment variables and `.env`.
* **Configured Variables**:
  - `ADITRADER_ENV` (default: `"development"`)
  - `LOG_LEVEL` (default: `"INFO"`)
  - `TIMEZONE` (default: `"Asia/Kolkata"`)
  - `DATABASE_URL` (default: `"sqlite:///runs/aditrader.db"`)
  - `REDIS_URL` (default: `None`)
  - `KOTAK_CONSUMER_KEY`, `KOTAK_CONSUMER_SECRET`, `KOTAK_MOBILE_NUMBER`, `KOTAK_PASSWORD`, `KOTAK_UCC`, `KOTAK_MPIN`, `KOTAK_TOTP_SECRET`
  - `GEMINI_API_KEY`
  - `INITIAL_CAPITAL` (default: `1_000_000.0`)
  - `MAX_MARGIN_UTILIZATION` (default: `0.85`)
  - `INTRADAY_MAX_DRAWDOWN` (default: `0.05`)
* **Findings**:
  - Secret masking is cleanly implemented across CLI commands.
  - `KOTAK_PASSWORD` is an unnecessary legacy field when `KOTAK_UCC` is set.
  - Configuration fallback behavior is inconsistent: `forward-options` strictly requires credentials in real mode, while `forward-test` and `kotak-auth` silently fall back to mock mode.

---

## Data Layer Audit

* **Ingestion Engines**:
  - `CSVDataFeed` (`csv_feed.py`): Supports CSV replay, timestamp parsing, and session filtering.
  - `NSECSVInspector` (`nse_csv.py`): Robust regex-based detection across 5 NSE CSV formats.
* **Scrip Master Cache**:
  - `cache.py` manages local parquet caches in `data/cache/`.
  - Offline fallback to mock scrip index when broker scrip master is unpopulated.
* **Option Chain Handling**:
  - `KotakOptionChainAdapter` successfully normalizes 100 strikes around ATM into structured `OptionChain` with CE/PE contract pairs, Greeks, and L2 bid/ask depth.
  - Correctly captures raw API snapshots in `runs/kotak_raw/`.

---

## Strategy System Audit

* **Strategy Registry**:
  - 5 registered templates in `src/aditrader/strategy/library/registry.py`:
    1. `tpl-iron-condor-v1` ("Nifty Weekly Iron Condor")
    2. `tpl-long-straddle-v1` ("Nifty Long Straddle")
    3. `tpl-bull-call-spread-v1` ("Nifty Bull Call Spread")
    4. `tpl-nifty-ce-premium-ladder-v1` ("NIFTY CE Premium Ladder")
    5. `tpl-intraday-trend-v1` ("Nifty Intraday Trend")
* **Deficiencies**:
  - `test_ma_crossover` is hardcoded as an ad-hoc fallback in `commands.py` (`_get_sample_ma_crossover()`) and `forward_runner.py`, but is **not** registered in `StrategyRegistry`.
  - Strategy validation via CLI is impossible for linear strategies due to the missing `--csv` argument.

---

## Backtesting Audit

* **Execution Contract**: Enforces strict point-in-time anti-lookahead causality ($exec\_ts \ge bar.timestamp$).
* **Execution Models**: Default `NEXT_BAR_OPEN` fills at next bar open with slippage; `SAME_BAR_CLOSE` optional.
* **Options Prohibition (ADR 011)**: Strictly halts with an air-gap guard if `dsl.legs` are defined, preventing fake historical proxy simulation.
* **Mathematical Anomaly**: Annualized Sharpe and Sortino ratios are computed over very short samples (e.g. 50 or 100 1-minute bars) using annualization factor $\sqrt{94,500} \approx 307.4$, resulting in misleading metrics like Sharpe = 22.40 or -64.98 with 0 or 1 trade.

---

## Forward Execution Audit

* **Two Disconnected Forward Runners**:
  1. `ForwardRunner` (`aditrader forward-test`): Supports linear strategies, emits detailed terminal summary table, but silently falls back to mock mode without credentials.
  2. `ForwardOptionsRunner` (`aditrader forward-options`): Supports multi-leg options, dynamic contract resolution, and trailing stop ratchets. Fails closed on missing credentials, but emits zero terminal summary of trades, P&L, or capital on completion.
* **Session Lifecycle**:
  - Pre-market wait until 09:15 IST (bypassable via `--no-wait`).
  - Contract discovery at 09:15 IST (Band 1 CE + ₹5.00 CE hedge).
  - Trailing ratchet on short CE ticks.
  - Automatic square-off at 15:15 IST or timeout.

---

## PaperBroker Audit

* **Source File**: `src/aditrader/core/broker.py`
* **Architectural Boundaries**:
  - Real order routing is physically blocked: `place_order()`, `modify_order()`, and `cancel_order()` on broker adapters raise unconditional `NotImplementedError` security vetoes.
  - All orders are executed inside `core.PaperBroker`.
* **Margin & Accounting Logic**:
  - Symmetrical solvency gates for Long, Short, and Position Reversals.
  - Net Capital = Cash Balance + $\sum (\text{pos.qty} \times \text{LTP})$.
  - Realistic fill pricing crossing the bid/ask spread (Buy at Ask, Sell at Bid).
  - Exchange limit order invariant: Limit orders never fill worse than the limit price.

---

## Accounting & Reconciliation Audit

* **Independent Verification**:
  - Cash P&L: Buy 25 @ ₹24,013.87, Sell 25 @ ₹24,013.87 = Net P&L ₹0.00 - ₹50.49 fees = -₹50.49. Verified.
  - Forward-Options Rehearsal:
    - Leg 1: Sell 25 CE @ ₹57.42, Buy 25 CE @ ₹46.02 = Gross P&L +₹285.00, Fees ₹50.20 = Net +₹234.80.
    - Leg 2: Buy 100 CE @ ₹5.29, Sell 100 CE @ ₹5.04 = Gross P&L -₹25.00, Fees ₹48.33 = Net -₹73.33.
    - Total Net Profit: ₹234.80 - ₹73.33 = +₹161.47.
    - Starting Capital: ₹1,000,000.00.
    - Ending Equity: ₹1,000,161.47.
    - Balance Sheet Discrepancy: $\pm ₹0.00$.
* **Statutory Taxes**:
  - STT, Exchange charges, SEBI turnover fees, Stamp duty, and 18% GST match official post-October 2024 Indian exchange schedules.

---

## Provenance / Dossier / Cryptographic Audit

* **Merkle Tree Verification**:
  - Binary SHA-256 Merkle trees calculated over discrete execution events and executed trades.
  - Verified bit-for-bit in Known-Answer Tests.
* **Tamper Digest**:
  - Canonical JSON serialization hashed with SHA-256. Verified tamper-resistant.
* **Audit Failure (P0)**:
  - In `ForwardOptionsRunner` (`forward_options_runner.py`), when running in `--mock` mode, the generated dossier records:
    `"details": "Real Kotak Neo live data stream verified."`
    in the `data_integrity` pillar. This is a material falsehood in an audit artifact.

---

## AI Runtime Audit

* **Files Inspected**: `src/aditrader/ai/`
* **Status**: **DEAD / UNCONNECTED SUBSYSTEM**.
* **Findings**:
  - `GoogleGeminiProvider`, `OpenRouterProvider`, and `OCRSpaceProvider` are implemented and unit-tested in isolation.
  - The packages `ai/forecasting/`, `ai/reviewer/`, `ai/suggestor/`, and `ai/teacher/` are completely empty 0-byte stub files.
  - The entire AI subsystem is never called by any strategy compiler, backtest runner, forward runner, or CLI command.
  - The dashboard "Test Connection" button for Gemini in `web/services.py:273` only checks if the API key is longer than 10 characters; it never makes a live API call to Gemini.

---

## Persistence / Database Audit

* **Database**: Local SQLite with Write-Ahead Logging (WAL) at `runs/aditrader.db`.
* **Tables**: `account_balances`, `orders`, `positions`, `trades`.
* **Alembic Inconsistency**:
  - Running `aditrader init-db` creates tables using SQLAlchemy `create_all()`.
  - Running `alembic upgrade head` afterwards fails with:
    `sqlite3.OperationalError: table orders already exists`.
  - `init-db` fails to stamp the Alembic head revision in `alembic_version`.

---

## Dashboard / Web Audit

* **Source Files**: `src/aditrader/web/static/index.html`, `src/aditrader/web/server.py`, `src/aditrader/web/services.py`.
* **Features**:
  - Zero-dependency Single Page Application adhering to institutional dark theme (`#0E1117`).
  - 7 tabs: Overview, Strategies, Data, Validation, Simulation, Runs, Settings.
  - Interactive balance sheet audit modal, recalculation comparison, and Merkle tree root inspection.
* **Bug in Dossier Lookup**:
  - `web/services.py:1223` searches for `session_{run_id}.json` instead of `forward_dossier_{run_id}.json`, breaking equity curve rendering for forward-options runs.

---

## Documentation Audit

* **Contradictions & Errors**:
  1. `README.md` Line 89: `aditrader strategies --detail test_ma_crossover` fails with `[ERROR] Strategy not found in registry.`
  2. `README.md` Line 127: `aditrader backtest --strategy test_ma_crossover --csv tests/fixtures/nifty_sample.csv` fails with `[ERROR] CSV historical data file not found`. Actual path is `data/nifty_sample.csv`.
  3. `README.md` Line 141: `aditrader inspect-data --file data/cm_bhavcopy.csv` references a file that does not exist in the repository.
  4. `forward-test --help`: States that multi-leg option strategies are strictly air-gapped pending Phase 8, failing to mention `forward-options`.

---

## Test Suite Audit

* **Clean-Room Test Execution**:
  - Command: `pytest -q --tb=short`
  - Result: **7 FAILED, 2 ERRORS, 555 PASSED, 8 SKIPPED** (out of 572 tests).
* **Root Causes of Test Failures**:
  1. **Hardcoded User Desktop Path**: `tests/unit/test_pine_compatibility_hardening.py` line 29:
     ```python
     MYST_PINE_PATH = Path("/home/aditya/Desktop/myst.pine")
     ```
     Causes 8 test failures on any machine or clean clone where `/home/aditya/Desktop/myst.pine` does not exist.
  2. **Uncommitted Package Directory**: `tests/unit/test_baseline.py` line 67 asserts that `src/aditrader/ui/assets` exists. Because git does not track empty directories without a `.gitkeep`, this test fails on a clean clone.

---

## Security / Air-Gap Audit

* **Verification of Air-Gap**:
  - `KotakNeoAdapter.place_order()`: Inherits from `AbstractBrokerAdapter.place_order()`, raising `NotImplementedError` with a security veto.
  - `KotakNeoAdapter.modify_order()`: Raises `NotImplementedError`.
  - `KotakNeoAdapter.cancel_order()`: Raises `NotImplementedError`.
  - All forward orders are instantiated and filled exclusively in `core.PaperBroker`.
  - Real broker order routing is **physically impossible** by construction.
* **Credentials & Secret Handling**:
  - CLI commands and logs cleanly mask sensitive keys (`_mask_secret()`).

---

## Quantitative Correctness Audit

* **P&L Arithmetic**: Exact to ₹0.01.
* **Lot Sizing**: Verified against current NSE circulars (NIFTY: 25, BANKNIFTY: 15, FINNIFTY: 25, MIDCPNIFTY: 50).
* **Option Payoff Modeling**: Put-Call parity, Bull Call Spread, Iron Condor, and Long Straddle payoffs match analytical benchmarks within $10^{-4}$.
* **Labeling Defect**: Terminal P&L on open positions is labeled "Net Realized PnL" in backtest CLI output.
* **Annualization Defect**: Intraday Sharpe ratios annualized over sub-day samples generate unrealistic values (>20.0).

---

## Edge-Case Audit

| Test Case | Command | Result | Evaluation |
|---|---|---|---|
| Negative `--bars` | `backtest --bars -10` | Raw `ValueError` traceback | BROKEN |
| Negative `--capital` | `backtest --capital -5000` | Raw Pydantic `ValidationError` traceback | BROKEN |
| Negative capital in forward | `forward-options --capital -100` | Raw Pydantic `ValidationError` traceback | BROKEN |
| Invalid strategy name | `backtest --strategy invalid` | Clean `[ERROR]` message | PASS |
| Non-existent CSV file | `inspect-data missing.csv` | Clean `[ERROR]` message | PASS |
| Unquoted multi-word strategy | `validate --strategy NIFTY CE...` | Bash syntax error (unrecognized args) | BROKEN |
| Real forward without creds | `forward-options` (no `--mock`) | Fails closed with clean explanation | PASS |
| Forward-test without creds | `forward-test` (no `--mock`) | Silently executes in mock mode | PASS WITH CONCERN |

---

## Contradictions & Stale Documentation

1. **`test_ma_crossover` in README vs Registry**: README claims it is in the registry; registry only contains 5 templates.
2. **`tests/fixtures/nifty_sample.csv` in README vs Filesystem**: Path in README does not exist; actual file is `data/nifty_sample.csv`.
3. **`forward-test --help` vs `forward-options`**: `forward-test` claims option forward execution is impossible; `forward-options` implements it.
4. **`init-db` vs `alembic upgrade head`**: Both documented in README; running both causes database collision.

---

## Unimplemented / Partially Implemented Features

1. **AI Subsystems** (`ai/forecasting/`, `ai/reviewer/`, `ai/suggestor/`, `ai/teacher/`): Empty 0-byte files; planned but absent.
2. **AI Trading Pipeline Integration**: `ai/` library exists but is completely disconnected from execution.
3. **Linear Strategy CLI Validation**: `aditrader validate` lacks `--csv` input, making linear validation impossible via CLI.
4. **CLI Dossier Inspection**: No CLI command exists to inspect or summarize Run Dossiers.
5. **Multi-Page Plotly Dash**: Documented in roadmap; replaced by lightweight single-page Web GUI.

---

## P0 Findings

### P0-1: Mock Forward Dossiers Claim "Real Kotak Neo Live Stream Verified"
* **Location**: `src/aditrader/data/forward_options_runner.py:970`
* **Evidence**: Line 40 of `forward_dossier_*.json` records `"details": "Real Kotak Neo live data stream verified."` even when `--mock` was executed with zero broker credentials.
* **Impact**: Falsifies audit provenance; misrepresents simulated data as verified real-market data.

### P0-2: Test Suite Fails on Clean GitHub Clone
* **Location**: `tests/unit/test_pine_compatibility_hardening.py:29`, `tests/unit/test_baseline.py:67`
* **Evidence**: `pytest` exits with 7 failures and 2 errors out of the box because of `/home/aditya/Desktop/myst.pine` and missing `src/aditrader/ui/assets`.
* **Impact**: External developers, CI pipelines, and auditors cannot run tests cleanly without manual intervention.

---

## P1 Findings

### P1-1: CLI Suggested Remediation Command Crashes Bash
* **Location**: `src/aditrader/cli/commands.py:616`
* **Evidence**: `aditrader backtest --strategy "NIFTY CE Premium Ladder"` suggests running `aditrader validate --strategy NIFTY CE Premium Ladder` without quotes, which causes `aditrader: error: unrecognized arguments: CE Premium Ladder`.
* **Impact**: Users copying the system's recommended fix encounter an immediate command-line syntax crash.

### P1-2: `aditrader validate` Permanently Blocks Linear Strategies via CLI
* **Location**: `src/aditrader/cli/__init__.py:127-142`, `src/aditrader/cli/commands.py:465-575`
* **Evidence**: Linear strategies fail institutional validation with `MISSING_BACKTEST_RESULT`, but `aditrader validate` has no `--csv` or `--data` flag to provide historical data.
* **Impact**: CLI users cannot validate linear strategies.

### P1-3: `forward-options` Emits No Terminal Summary of Executed Trades or P&L
* **Location**: `src/aditrader/cli/commands.py:1785-1815`
* **Evidence**: On session conclusion, `forward-options` prints only `[SUCCESS] Forward shadow session concluded cleanly` and the JSON path, omitting trades, fill prices, fees, and net profit.
* **Impact**: Users cannot determine session performance without parsing raw JSON.

### P1-4: Raw Tracebacks on Standard Input Mistakes
* **Location**: `src/aditrader/cli/commands.py:638, 1769`
* **Evidence**: Passing negative numbers to `--bars` or `--capital` causes unhandled Python `ValueError` and Pydantic `ValidationError` tracebacks.
* **Impact**: Unprofessional error handling exposing internal callstacks.

---

## P2 Findings

### P2-1: `README.md` Documents Non-Existent File Paths and Unregistered Strategies
* **Location**: `README.md:89, 127, 141`
* **Evidence**: References `test_ma_crossover` in `strategies --detail` (not registered) and `tests/fixtures/nifty_sample.csv` (does not exist).
* **Impact**: First-time users following the quickstart encounter immediate errors.

### P2-2: Silent Mock Fallback Inconsistency Between Forward Runners
* **Location**: `src/aditrader/cli/commands.py:1128, 1760`
* **Evidence**: `forward-options` strictly fails closed without credentials, while `forward-test` silently runs mock mode without warning.
* **Impact**: Confusing and contradictory safety signals across commands.

### P2-3: Database Table Collision Between `init-db` and `alembic`
* **Location**: `src/aditrader/cli/commands.py:257-268`
* **Evidence**: `init-db` creates tables without stamping Alembic head; running `alembic upgrade head` crashes with `table orders already exists`.
* **Impact**: Breaks standard migration workflows.

### P2-4: Backtest CLI Mislabels Unrealized Terminal P&L as "Net Realized PnL"
* **Location**: `src/aditrader/cli/commands.py:671`
* **Evidence**: Backtest on 100 bars with 0 closed trades prints `Total Trades: 0` and `Net Realized PnL: ₹216.60`.
* **Impact**: Inaccurate accounting terminology in user output.

---

## P3 Findings

### P3-1: Alarming "REAL" Header Banner in `--mock` Mode
* **Location**: `src/aditrader/cli/commands.py:1740`
* **Evidence**: Banner reads `KOTAK NEO REAL FORWARD-SHADOW PAPER EXECUTION` even when `--mock` is active.
* **Impact**: Causes user hesitation and concern over real order placement.

### P3-2: Redundant `--serve` Flag for `aditrader dashboard`
* **Location**: `src/aditrader/cli/commands.py:706`
* **Evidence**: Running `aditrader dashboard` prints a notice telling the user to pass `--serve`.
* **Impact**: Unnecessary keystrokes for the primary GUI command.

### P3-3: Web Services Dossier Path Discrepancy
* **Location**: `src/aditrader/web/services.py:1223`
* **Evidence**: Hardcodes `session_{run_id}.json` instead of checking `forward_dossier_{run_id}.json`, preventing equity curve rendering for forward-options runs.
* **Impact**: Minor data omission in web dashboard modal.

---

## Things That Are Actually Working Well

1. **Architectural Air-Gap (ADR 002)**: Broker adapters have real order routing physically blocked with unconditional `NotImplementedError` security vetoes.
2. **Deterministic Known-Answer Test Suite**: 37 mathematical test vectors verifying Cash/Short P&L, lot sizes, Black-Scholes Greeks, and statutory taxes with exact paisa precision.
3. **NSE Statutory Charge Schedules**: Accurate post-October 2024 tax schedules including STT, turnover charges, SEBI fees, stamp duty, and 18% GST.
4. **Option Chain Normalization & Strike Ladders**: `KotakOptionChainManager` accurately parses 100 strikes around ATM with full L2 depth.
5. **Dynamic Premium-Ladder Selection**: Deterministic selection of Band 1 short CE and ratio hedge CE near ₹5.00 with clean tie-breaking.
6. **Trailing Stop Ratchet**: Pure state machine correctly ratchets stop down as short option premium falls favorably, and never loosens.
7. **Dataset Inspection Engine**: `aditrader inspect-data` reliably classifies 5 NSE CSV formats and audits price envelope integrity.
8. **Cryptographic Merkle Trees**: Binary SHA-256 Merkle trees over discrete execution events and trades provide robust tamper-evident sealing.
9. **Doctor Diagnostic Tooling**: `aditrader doctor` delivers immediate, transparent feedback on dependencies, storage, and database state.
10. **Zero-Dependency Web Workstation**: Lightweight, responsive dark-themed dashboard operating without external CDN dependencies.

---

## Technical Debt

1. **Decoupled AI Subsystem**: `src/aditrader/ai/` is an orphan subsystem not integrated into any trading or validation flow.
2. **Duplicate Forward Runner Infrastructures**: `ForwardRunner` (linear) and `ForwardOptionsRunner` (options) duplicate event logging, dossier persistence, and configuration models.
3. **Ad-Hoc Strategy Fallback**: Hardcoding `_get_sample_ma_crossover()` across 4 files instead of registering it in `StrategyRegistry`.
4. **Annualization Calculation on Short Samples**: Sharpe and Sortino formulas lack sample duration checks, blowing up metrics on minute-level bars.

---

## Missing Tests

1. **Clean Clone Isolation Tests**: Tests verifying that all test fixtures reside strictly within the repository (no external Desktop paths).
2. **Linear Validation CLI Tests**: Tests verifying `aditrader validate` behavior with historical dataset parameters.
3. **CLI Argument Error Handling Tests**: Tests verifying that negative numbers and invalid arguments produce formatted `[ERROR]` messages rather than raw tracebacks.
4. **Mock Dossier Truthfulness Assertions**: Tests asserting that dossiers generated in mock mode explicitly state mock provenance in the `data_integrity` pillar.
5. **Alembic Migration Roundtrip Tests**: Tests asserting that `init-db` and `alembic upgrade head` can be executed sequentially without table existence errors.

---

## Product / UX Debt

1. **No CLI Dossier Inspector**: Lack of `aditrader inspect-run` or `aditrader runs` command to view completed run results from the terminal.
2. **Missing Dataset Discovery**: No command to list available CSV datasets in `data/`.
3. **Uninformative Forward-Options Completion**: Lack of an ASCII performance summary table when a forward options session completes.
4. **Confusing Validation Verdicts**: Linear strategies without datasets receiving `NOT_RECOMMENDED (Score: 100.0/100)` rather than a clear `INCOMPLETE_DATA` status.

---

## Recommended Fix Order

1. **Phase 1: Integrity & Test Hygiene (Immediate)**
   - Fix `tests/unit/test_pine_compatibility_hardening.py` to use an in-repo fixture instead of `/home/aditya/Desktop/myst.pine`.
   - Add a `.gitkeep` to `src/aditrader/ui/assets` so clean clones pass all baseline tests.
   - Fix `ForwardOptionsRunner` to record `"Simulated mock option chain verified"` in mock dossiers.
2. **Phase 2: CLI Usability & Bug Remediation**
   - Wrap strategy names in double quotes in `cmd_backtest` remediation suggestions.
   - Add end-of-session summary table to `cmd_forward_options`.
   - Wrap CLI argument parsing in try/except blocks to format `ValidationError` and `ValueError` into clean user error messages.
   - Add `--csv` flag to `cmd_validate` to allow linear strategy validation via CLI.
   - Fix `README.md` file paths (`data/nifty_sample.csv`) and register `test_ma_crossover` in `StrategyRegistry`.
3. **Phase 3: Subsystem Consolidation**
   - Synchronize `init-db` with Alembic by stamping `head`.
   - Add `aditrader inspect-run <run_id>` to view completed dossiers via CLI.
   - Update `web/services.py:1223` to recognize `forward_dossier_{run_id}.json`.

---

## What Should NOT Be Changed

1. **Air-Gap Architecture (ADR 002)**: Do NOT alter or remove the `NotImplementedError` guards on broker adapter order routing methods.
2. **PaperBroker Accounting Invariants**: Do NOT alter the symmetrical solvency gate or the net equity formula ($\text{Cash} + \sum \text{pos.qty} \times \text{LTP}$).
3. **Statutory Tax Schedules**: Do NOT modify the tax rates in `CostCalculator`; they are accurate according to current NSE/SEBI rules.
4. **Deterministic KAT Vectors**: Do NOT weaken the 37 Known-Answer Test assertions or their 1-paisa tolerance.
5. **AST Condition Engine**: Do NOT introduce `eval()` or `exec()` for dynamic strategy evaluation; keep declarative AST parsing.

---

## Final Assessment

AdiTrader possesses a rock-solid, institutional-grade calculation and risk core, but is currently hindered by integration rough edges, broken documentation paths, and test suite hygiene issues on fresh clones. Addressing the P0 and P1 findings will transform it into a cohesive, user-operable, and publication-ready quantitative operating system.
