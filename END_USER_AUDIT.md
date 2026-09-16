# AdiTrader End-User CLI Usability Audit

**Audit Date**: 2026-09-16  
**Auditor Persona**: New Quantitative Analyst / Systems Engineer evaluating AdiTrader via CLI without source-code knowledge  
**Execution Venue**: Strictly Local / Mock Rehearsal (Air-gapped)  
**Evaluated Binary**: `aditrader` (Python 3.14.3, Linux)  
**Target Document**: `END_USER_AUDIT.md` (Project Root)

---

## Executive Summary

AdiTrader demonstrates exceptionally high computational rigor, deterministic accounting, and uncompromising safety air-gaps when executing its mathematical core (`PaperBroker`, Black-Scholes modeling, and cryptographic Merkle tree sealing).

However, from the perspective of a **new end-user encountering the CLI for the first time**, the user experience contains significant friction, sharp edges, unhandled tracebacks, command discoverability gaps, and contradictory documentation. A user attempting to follow the official `README.md` immediately encounters broken file paths, phantom strategy names that fail when inspected, and commands that crash bash due to unquoted error suggestions.

Furthermore, once a forward-shadow or backtest session concludes, the CLI offers **zero native commands to inspect the resulting Run Dossier**, leaving the user staring at an unparsed JSON path on disk without any terminal summary of trades, P&L, or capital changes.

---

## Overall Usability Problems

1. **The "Dossier Dead-End"**: The CLI excels at generating cryptographically sealed Run Dossiers (`runs/forward/forward_dossier_*.json` and `runs/backtest/dossier_run_bt_*.json`), but provides **no CLI command to inspect, list, summarize, or verify them**. The only tool provided is the Web GUI (`dashboard --serve`).
2. **Contradictory Strategy Ecosystem**: `README.md` instructs users to inspect and backtest `test_ma_crossover`. But running `aditrader strategies --detail test_ma_crossover` fails with an error stating the strategy does not exist, even while `aditrader backtest --strategy test_ma_crossover` accepts it.
3. **CLI Error Traps Leading to Bash Syntax Errors**: When a user attempts to backtest an option strategy, the CLI correctly halts per ADR 011, but its suggested remediation command (`aditrader validate --strategy NIFTY CE Premium Ladder`) omits quotation marks, causing bash to fail with `unrecognized arguments: CE Premium Ladder`.
4. **Unhandled Tracebacks on Everyday User Input Mistakes**: Negative values for `--bars` or `--capital` cause raw Python `ValueError` and Pydantic `ValidationError` tracebacks rather than clean, friendly CLI diagnostic messages.
5. **Silent Mock Fallback Inconsistency**: While `forward-options` strictly fails closed when credentials are missing, `forward-test` and `kotak-auth` silently fall back to mock rehearsal mode without warning or prompt, creating false confidence regarding live connectivity.
6. **False Claims in Mock Artifacts**: When `forward-options` runs in `--mock` mode, the generated JSON dossier explicitly records `"details": "Real Kotak Neo live data stream verified."` in its data integrity pillar, misrepresenting mock rehearsal data as real broker feeds.

---

## Critical Blockers

### CRIT-01: CLI Error Suggests Unquoted Command That Crashes Bash
* **Severity**: Critical (User cannot copy-paste suggested fix)
* **Exact Command Used**:
  ```bash
  aditrader backtest --strategy "NIFTY CE Premium Ladder"
  ```
* **What a Normal User Expected**: Either a simulated backtest or a clear suggestion on how to validate the strategy.
* **What Actually Happened**:
  The command halted with:
  ```text
  [AIR-GAP GUARD] Strategy 'NIFTY CE Premium Ladder' defines 2 option leg(s).
  BacktestRunner strictly prohibits silent proxy simulation of multi-leg option
  strategies on spot/futures candles (ADR 011).
  To evaluate options strategies, run institutional payoff validation:
      aditrader validate --strategy NIFTY CE Premium Ladder
  ```
  When the user copies and executes that exact suggested command:
  ```bash
  aditrader validate --strategy NIFTY CE Premium Ladder
  ```
  The CLI immediately errors out with code 2:
  ```text
  aditrader: error: unrecognized arguments: CE Premium Ladder
  ```
* **Why It Is Confusing/Broken**: The CLI's own error output teaches the user an invalid command syntax that breaks argument parsing.
* **Concrete Recommendation**: Wrap multi-word strategy names in double quotes in all CLI help and error messages, or suggest the canonical template slug `tpl-nifty-ce-premium-ladder-v1`.

---

### CRIT-02: `validate` Cannot Accept Historical Datasets via CLI
* **Severity**: Critical (Linear strategy validation via CLI is permanently blocked)
* **Exact Command Used**:
  ```bash
  aditrader validate --strategy "Nifty Intraday Trend"
  ```
* **What a Normal User Expected**: The command validates the strategy definition.
* **What Actually Happened**:
  ```text
  Final Verdict:         NOT_RECOMMENDED (Score: 100.0/100)
  Warnings:
    [WARN] BacktestResult missing. Historical statistical gates were not evaluated.
  Failed Gates:
    [GATE] MISSING_BACKTEST_RESULT
  ```
  The command exited with code 1.
* **Why It Is Confusing/Broken**:
  The user checks `aditrader validate --help`:
  ```text
  usage: aditrader validate [-h] (--strategy STRATEGY | --file FILE)
                            [--policy {institutional,moderate,research}]
  ```
  There is **no `--csv` or `--data` flag** in `aditrader validate`. Therefore, a user can *never* successfully validate a linear strategy through the CLI because there is no mechanism to provide the backtest data required by the historical statistical gate.
* **Concrete Recommendation**: Add `--csv` and `--bars` flags to `aditrader validate` so users can provide a dataset for linear historical gate evaluation, or automatically evaluate syntax-only validation with a distinct verdict like `SYNTAX_VALID (HISTORICAL_EVALUATION_PENDING)`.

---

## Major Problems

### MAJ-01: `forward-options` Omits Performance Summary on Completion
* **Severity**: Major (User has no idea what happened during session)
* **Exact Command Used**:
  ```bash
  aditrader forward-options --mock --duration 5.0 --no-wait
  ```
* **What a Normal User Expected**: A summary table showing ticks processed, paper orders executed, entry/exit prices, gross/net P&L, and ending equity (similar to `forward-test`).
* **What Actually Happened**:
  ```text
  ============================================================================
    KOTAK NEO REAL FORWARD-SHADOW PAPER EXECUTION (OPTIONS)
  ============================================================================
  Mode:             MOCK / REHEARSAL
  Strategy:         tpl-nifty-ce-premium-ladder-v1
  Underlying:       NIFTY
  Capital:          ₹1,000,000.00
  Slippage:         5.0 bps
  Order Routing:    AIR-GAPPED (All fills execute in local PaperBroker)
  Live Orders:      DISABLED BY ARCHITECTURE (ADR 002)
  ----------------------------------------------------------------------------
  ----------------------------------------------------------------------------
  [SUCCESS] Forward shadow session concluded cleanly.
  Sealed Dossier:   runs/forward/forward_dossier_fwd_opt_0e9a2969.json
  ============================================================================
  ```
* **Why It Is Confusing/Broken**: The session executed 2 orders, filled ₹161.47 in net P&L, executed 2 stop loss ratchets, and squared off at session close, but printed **zero** of this information to stdout. The user cannot tell if any trading occurred without opening the raw JSON file.
* **Concrete Recommendation**: Print an end-of-session summary block matching `forward-test` displaying: Trades executed, Short/Hedge fill prices, Ratchet count, Gross P&L, Statutory fees, Net P&L, and Ending balance.

---

### MAJ-02: Dossier Falsely Claims "Real Kotak Neo Live Stream Verified" in Mock Mode
* **Severity**: Major (Audit truthfulness violation)
* **Exact Command Used**:
  ```bash
  aditrader forward-options --mock --duration 5.0 --no-wait
  ```
* **Observed Artifact Content** (`runs/forward/forward_dossier_fwd_opt_0e9a2969.json` line 40):
  ```json
  "data_integrity": {
    "pillar_name": "Data Integrity Audit",
    "pillar_type": "DATA_INTEGRITY",
    "status": "PASS",
    "score": 100.0,
    "details": "Real Kotak Neo live data stream verified.",
    "diagnostics": [],
    "evaluated_at": "2026-09-16T10:49:04.232503+05:30"
  }
  ```
* **Why It Is Confusing/Broken**: In a mock rehearsal run with zero Kotak credentials, the cryptographic Run Dossier records that real Kotak Neo data was verified.
* **Concrete Recommendation**: Check `config.mock_mode` when constructing the `data_integrity` pillar; in mock mode, report `"Simulated mock option chain and synthetic tick stream verified."`.

---

### MAJ-03: Raw Python Tracebacks on Simple Parameter Mistakes
* **Severity**: Major (Poor production polish)
* **Exact Commands Used**:
  1. Negative bars:
     ```bash
     aditrader backtest --strategy test_ma_crossover --bars -10
     ```
     Result:
     ```text
     ValueError: Backtest data is empty. At least one bar is required.
     ```
  2. Negative capital:
     ```bash
     aditrader backtest --strategy test_ma_crossover --capital -5000
     ```
     Result:
     ```text
     pydantic_core._pydantic_core.ValidationError: 1 validation error for BacktestConfig
     initial_capital
       Input should be greater than 0 [type=greater_than, input_value=-5000.0, input_type=float]
     ```
  3. Negative capital in `forward-options`:
     ```bash
     aditrader forward-options --mock --capital -100 --duration 2.0 --no-wait
     ```
     Result:
     ```text
     pydantic_core._pydantic_core.ValidationError: 1 validation error for ForwardOptionsSessionConfig
     initial_capital
       Input should be greater than 0 [type=greater_than, input_value=-100.0, input_type=float]
     ```
* **Why It Is Confusing/Broken**: Standard CLI applications validate input parameters and catch Pydantic validation errors, formatting them as clean `[ERROR] Invalid capital: must be greater than 0.` messages instead of dumping 20-line callstacks.
* **Concrete Recommendation**: Wrap CLI config instantiations in `try...except (ValidationError, ValueError) as exc:` and print clean user-facing error messages with usage hints.

---

### MAJ-04: Contradiction in Strategy Registry vs Backtest/Validation Acceptance
* **Severity**: Major (User cannot discover strategies that the system actually runs)
* **Exact Commands Used**:
  ```bash
  aditrader strategies
  aditrader strategies --detail test_ma_crossover
  aditrader backtest --strategy test_ma_crossover --bars 100
  ```
* **What Actually Happened**:
  1. `aditrader strategies` lists only 5 strategies:
     - `Nifty Weekly Iron Condor`
     - `Nifty Long Straddle`
     - `Nifty Bull Call Spread`
     - `NIFTY CE Premium Ladder`
     - `Nifty Intraday Trend`
  2. `aditrader strategies --detail test_ma_crossover` fails with `[ERROR] Strategy 'test_ma_crossover' not found in registry.`
  3. But `aditrader backtest --strategy test_ma_crossover` runs successfully!
* **Why It Is Confusing/Broken**: `test_ma_crossover` is the primary strategy referenced across the entire `README.md`. A new user trying to inspect it is told it does not exist, yet can backtest it.
* **Concrete Recommendation**: Formally register `test_ma_crossover` in the template registry or update documentation to use registered names like `nifty_intraday_trend`.

---

## Minor Problems

### MIN-01: Alarming "REAL" Header Banner in `--mock` Mode
* **Severity**: Minor (Confusing psychological framing)
* **Exact Command Used**:
  ```bash
  aditrader forward-options --mock --duration 5.0 --no-wait
  ```
* **Output Banner**:
  ```text
  ============================================================================
    KOTAK NEO REAL FORWARD-SHADOW PAPER EXECUTION (OPTIONS)
  ============================================================================
  Mode:             MOCK / REHEARSAL
  ```
* **Why It Is Confusing**: Even though the line below specifies `Mode: MOCK / REHEARSAL`, the banner title starts with `REAL...`. Users double-check whether they accidentally triggered real broker orders.
* **Recommendation**: Change title to `KOTAK NEO FORWARD-SHADOW PAPER EXECUTION (OPTIONS) [MOCK REHEARSAL]` when `--mock` is active.

---

### MIN-02: `aditrader dashboard` Requires Redundant `--serve` Flag
* **Severity**: Minor (Unnecessary keystroke friction)
* **Exact Command Used**:
  ```bash
  aditrader dashboard
  ```
* **Output**:
  ```text
  [NOTICE] Full multi-page Plotly Dash integration is scheduled for Phase 8.
           A lightweight, zero-dependency responsive Web GUI is ready now.
           Server endpoint: http://127.0.0.1:8050
           Run with '--serve' to start the live server:
               aditrader dashboard --serve
  ```
* **Why It Is Confusing**: When a user types `aditrader dashboard`, they want to start the dashboard. Having a command named `dashboard` that does nothing except tell the user to type `aditrader dashboard --serve` is redundant friction.
* **Recommendation**: Make serving the dashboard the default behavior when `aditrader dashboard` is invoked without arguments.

---

### MIN-03: Inconsistent Default Slippage Across Commands
* **Severity**: Minor (Inconsistent simulation defaults)
* **Observation**:
  - `aditrader backtest`: `--slippage-bps` defaults to **2.5 bps**
  - `aditrader forward-test`: `--slippage-bps` defaults to **2.5 bps**
  - `aditrader forward-options`: `--slippage-bps` defaults to **5.0 bps**
* **Recommendation**: Document the rationale (e.g. options bid-ask spread vs equity index spot) in the CLI help text for `forward-options`.

---

### MIN-04: Non-Existent Command Referenced in `status`
* **Severity**: Minor (Dead-end instruction)
* **Observed CLI Output** in `aditrader status`:
  ```text
  Scrip Master:      Not cached (run search or adapter scrip master download)
  ```
* **Why It Is Confusing**: `"adapter scrip master download"` is internal developer jargon; there is no such CLI command.
* **Recommendation**: Change to: `Scrip Master: Not cached (run 'aditrader search <query>' to trigger auto-download)`.

---

## Confusing / Inconsistent UX

### UX-01: Silent Fallback in `forward-test` vs Hard Fail-Closed in `forward-options`
* When running `forward-options` without credentials:
  ```text
  [FAIL CLOSED] Authentication error: REAL_KOTAK_AUTHENTICATION_FAILED: Incomplete Kotak Neo credentials for live authentication. Silent mock fallback is strictly prohibited. Run with --mock for simulated rehearsal.
  ```
* When running `forward-test` without credentials:
  The command proceeds silently in mock mode:
  ```text
  Market Feed Mode: SIMULATED_REHEARSAL (Mock Adapter)
  ```
* **User impact**: Users get contradictory safety signals across commands within the same platform.

---

### UX-02: Backtest with 0 Trades Shows Positive P&L and Sharpe 22.40
* In `aditrader backtest --strategy "Nifty Intraday Trend"` (synthetic 100 bars):
  ```text
  Processed Bars:        100
  Total Trades:          0
  Starting Capital:      ₹1,000,000.00
  Ending Capital:        ₹1,000,216.60
  Net Realized PnL:      ₹216.60 (0.00%)
  Win Rate:              0.0%
  Expectancy:            ₹0.00
  Profit Factor:         0.00
  Max Drawdown:          0.02%
  Sharpe Ratio:          22.40
  Sortino Ratio:         35.04
  Overall Status:        FAIL
  ```
* **User confusion**:
  1. If `Total Trades: 0`, how did capital increase from ₹1,000,000 to ₹1,000,216.60? (An open terminal position was marked to market, but it is labeled `Net Realized PnL: ₹216.60`).
  2. How can a strategy with 0 closed trades have a Sharpe Ratio of 22.40?
  3. Why is `Overall Status: FAIL`? (Because institutional policy requires minimum trade counts, but this is never explained to the user).

---

## Error Message Problems

| Command Attempted | Observed Error | Expected Behavior | Problem Type |
|---|---|---|---|
| `aditrader strategies --detail "NonExistent"` | `[ERROR] Strategy 'NonExistent' not found in registry.` | Suggest closest matching strategies or available list. | Missing suggestions |
| `aditrader backtest --strategy "NIFTY CE Premium Ladder"` | `...run institutional payoff validation: aditrader validate --strategy NIFTY CE Premium Ladder` | Suggest quoted strategy name `aditrader validate --strategy "NIFTY CE Premium Ladder"` | Causes syntax error |
| `aditrader backtest --strategy test_ma_crossover --bars -10` | `ValueError: Backtest data is empty. At least one bar is required.` | `[ERROR] Invalid --bars: must be a positive integer.` | Raw unhandled traceback |
| `aditrader backtest --strategy test_ma_crossover --capital -5000` | `pydantic_core._pydantic_core.ValidationError: 1 validation error...` | `[ERROR] Invalid --capital: must be greater than 0.` | Raw Pydantic traceback |
| `aditrader inspect-strategy "NIFTY CE Premium Ladder"` | `[ERROR] Strategy file not found: NIFTY CE Premium Ladder` | Clarify that `inspect-strategy` requires a file path, whereas `strategies --detail` inspects built-ins. | Confusing command overlap |

---

## Documentation Problems

### DOC-01: Broken File Paths in `README.md`
1. `README.md` Line 127:
   ```bash
   aditrader backtest --strategy test_ma_crossover --csv tests/fixtures/nifty_sample.csv
   ```
   **Observed CLI Error**: `[ERROR] CSV historical data file not found: tests/fixtures/nifty_sample.csv`  
   *Actual location in repo*: `data/nifty_sample.csv`
2. `README.md` Line 141:
   ```bash
   aditrader inspect-data --file data/cm_bhavcopy.csv --symbol RELIANCE
   ```
   **Observed CLI Error**: `[ERROR] File not found: data/cm_bhavcopy.csv`  
   *File does not exist in repo.*

---

### DOC-02: Phantom Strategy in `README.md`
* `README.md` Line 89:
  ```bash
  aditrader strategies --detail test_ma_crossover
  ```
  **Observed CLI Error**: `[ERROR] Strategy 'test_ma_crossover' not found in registry.`

---

### DOC-03: Obsolete Air-Gap Claims in `forward-test --help`
* When running `aditrader forward-test --help`, the usage example notes:
  ```text
  Note: Multi-leg option strategies are strictly air-gapped from forward execution
        pending Phase 8 synthetic IV modeling. Only linear strategies are supported.
  ```
  This directly contradicts the presence of `forward-options`, which executes multi-leg option strategies (`tpl-nifty-ce-premium-ladder-v1`) against live/mock chains today.

---

## Command Discoverability Problems

1. **Flat 17-Command Namespace**: `aditrader --help` lists 17 commands alphabetically/arbitrarily with no visual grouping between:
   - **Diagnostics**: `doctor`, `status`
   - **Research & Strategy**: `strategies`, `validate`, `inspect-strategy`
   - **Data & Scrip**: `search`, `inspect-data`, `kotak-discover`, `kotak-history`, `kotak-option-chain`, `smoke-feed`
   - **Execution Venues**: `backtest`, `forward-test`, `forward-options`
   - **Presentation**: `dashboard`
   - **Maintenance**: `init-db`, `kotak-auth`
2. **Missing Dataset Listing**: There is no `aditrader datasets` or `aditrader list-data` command. A user has to inspect local files by guessing paths or browsing the filesystem.
3. **Missing Dossier Inspection**: There is no `aditrader dossiers` or `aditrader inspect-run <run_id>` command.

---

## Workflow Problems

1. **The Validation Dead-End**: A user discovers a strategy (`aditrader strategies`), inspects it (`strategies --detail`), validates it (`validate --strategy`), and gets `NOT_RECOMMENDED (Score: 100.0/100, MISSING_BACKTEST_RESULT)` with no CLI flag to provide data.
2. **The Forward Execution Fork**: A user wanting to paper-trade must guess whether to use `forward-test` or `forward-options`. If they use `forward-test` with an options strategy, they get an error. If they use `forward-options` with a linear strategy, it ignores the argument and defaults to NIFTY CE Premium Ladder.
3. **The Results Black Hole**: Once a session completes, the user is given a path to a JSON file (`runs/forward/forward_dossier_fwd_opt_*.json`). There is no CLI viewer or terminal summary command to render the ledger, P&L, or verification matrix.

---

## Things That Worked Well

1. **`aditrader doctor`**: Clear, beautifully formatted system diagnostics checking runtime, dependencies, database tables, and optional credentials.
2. **`aditrader smoke-feed --mock`**: Flawless mock tick streaming with LTP, Bid/Ask spread, Volume, and OI updates in real time.
3. **`aditrader inspect-data` on Derivative Quotes**: Excellent format auto-detection (`NSE_DERIVATIVE_QUOTE`), column breakdown, and clear plain-English explanation of why multi-expiry derivative files cannot be replayed as single-instrument linear spot bars.
4. **Deterministic P&L Accounting**: When inspecting the raw JSON dossier generated by `forward-options`, all 11 execution events, trade fills, fees (STT, exchange, SEBI, GST, stamp duty), and balance sheet reconciliations match with exact paisa precision ($\pm ₹0.00$ delta).
5. **Defensive Fail-Closed Gate**: Running `aditrader forward-options` without credentials and without `--mock` fails closed immediately with an informative message preventing silent mock execution.

---

## Complete User Journey Tested

```text
1. aditrader --help
   ↓
2. aditrader doctor
   ↓
3. aditrader status
   ↓
4. aditrader strategies
   ↓
5. aditrader strategies --detail "NIFTY CE Premium Ladder"
   ↓
6. aditrader validate --strategy "NIFTY CE Premium Ladder"
   ↓
7. aditrader smoke-feed --symbol NIFTY --ticks 3 --mock
   ↓
8. aditrader forward-options --mock --duration 5.0 --no-wait
   ↓
9. aditrader inspect-data data/nifty_sample.csv
   ↓
10. aditrader backtest --strategy test_ma_crossover --csv data/nifty_sample.csv
   ↓
11. aditrader dashboard --serve (inspected offline via curl)
```

---

## Exact Reproduction Steps

To reproduce every error and UX friction point observed during this audit:

```bash
# 1. Reproduce bash syntax error from unquoted error suggestion:
./.venv/bin/aditrader backtest --strategy "NIFTY CE Premium Ladder"
# Copy and execute suggested command:
./.venv/bin/aditrader validate --strategy NIFTY CE Premium Ladder

# 2. Reproduce linear strategy validation dead-end:
./.venv/bin/aditrader validate --strategy "Nifty Intraday Trend"

# 3. Reproduce broken README strategy:
./.venv/bin/aditrader strategies --detail test_ma_crossover

# 4. Reproduce broken README file paths:
./.venv/bin/aditrader backtest --strategy test_ma_crossover --csv tests/fixtures/nifty_sample.csv

# 5. Reproduce raw tracebacks on parameter errors:
./.venv/bin/aditrader backtest --strategy test_ma_crossover --bars -10
./.venv/bin/aditrader backtest --strategy test_ma_crossover --capital -5000
./.venv/bin/aditrader forward-options --mock --capital -100 --duration 2.0 --no-wait

# 6. Reproduce false live stream claim in mock dossier:
./.venv/bin/aditrader forward-options --mock --duration 3.0 --no-wait
cat runs/forward/forward_dossier_*.json | grep -A 5 "data_integrity"
```

---

## Recommended Fixes

1. **Enforce Double Quotes in Remediations**: In `cmd_backtest`, wrap strategy suggestions in quotes: `aditrader validate --strategy "{strategy.name}"`.
2. **Add Terminal Summary to `forward-options`**: When `ForwardOptionsRunner` concludes, print an ASCII summary table showing orders placed, fills, short/hedge fill prices, ratchets, gross P&L, statutory fees, and net profit.
3. **Synchronize `README.md` Examples**: Fix paths in `README.md` from `tests/fixtures/nifty_sample.csv` to `data/nifty_sample.csv`, and replace references to `test_ma_crossover` with registered templates like `nifty_intraday_trend`.
4. **Catch and Format Input Validation Errors**: Wrap CLI configuration building in try-catch blocks that intercept Pydantic `ValidationError` and `ValueError`, emitting formatted `[ERROR]` messages.
5. **Truthful Mock Reporting in Run Dossiers**: In `ForwardOptionsRunner`, check `config.mock_mode` and write `"Simulated mock option chain verified"` instead of `"Real Kotak Neo live data stream verified."`.
6. **Add `aditrader inspect-run <path_or_id>` Command**: Expose an offline CLI command to view and verify completed Run Dossiers without requiring the web dashboard.
7. **Consolidate Forward Testing**: Unify `forward-test` and `forward-options` or cross-reference them clearly in their respective `--help` outputs.

---

## Priority Order

| Priority | Item ID | Action | Target File(s) |
|---|---|---|---|
| **P0** | CRIT-01 | Fix unquoted strategy name in backtest air-gap guard suggestion | `src/aditrader/cli/commands.py` |
| **P0** | MAJ-02 | Fix false claim of "Real Kotak Neo live data stream" in mock dossier | `src/aditrader/data/forward_options_runner.py` |
| **P1** | DOC-01 | Fix broken CSV file paths and phantom strategies in `README.md` | `README.md` |
| **P1** | MAJ-01 | Add comprehensive session summary output to `forward-options` CLI | `src/aditrader/cli/commands.py` |
| **P1** | MAJ-03 | Catch Pydantic/ValueError in CLI handlers to eliminate raw tracebacks | `src/aditrader/cli/commands.py` |
| **P2** | CRIT-02 | Add `--csv` flag to `aditrader validate` for linear historical evaluation | `src/aditrader/cli/commands.py`, `src/aditrader/cli/__init__.py` |
| **P2** | UX-01 | Align silent fallback behavior between `forward-test` and `forward-options` | `src/aditrader/cli/commands.py` |
| **P2** | MIN-01 | Remove "REAL" prefix from header banner when `--mock` is passed | `src/aditrader/cli/commands.py` |
| **P3** | MIN-02 | Make `aditrader dashboard` default to `--serve` | `src/aditrader/cli/__init__.py`, `commands.py` |
| **P3** | New Feat | Add `aditrader inspect-run` / `aditrader runs` command for offline dossier inspection | `src/aditrader/cli/commands.py` |
