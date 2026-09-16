# AdiTrader GUI/TUI Transformation: Design & Architecture Specification

**Author**: Gemini (Product & Design Research Lead)  
**Reviewer**: Claude (Hostile Design Critic & Approval Authority)  
**Target User**: 54-year-old bank employee (financially literate, non-programmer, non-quant)  
**Architectural North Star**: The CLI is the canonical functional specification; GUI and TUI are unified operating surfaces powered by the exact same shared service layer.

---

## 1. Complete CLI Capability Inventory & Surface Mapping

AdiTrader provides **24 canonical operations** in its CLI. Every single operation maps directly into both the visual GUI and keyboard-first TUI:

| # | Capability | CLI Command | User Inputs & Flags | Output / Artifact | GUI Surface | TUI Surface |
|---|---|---|---|---|---|---|
| 1 | **System Diagnostics** | `aditrader doctor` | None | System, OS, SQLite, Kotak Neo SDK, data paths check report | **Settings / System Diagnostics** drawer with 1-click test | **Menu: System Diagnostics** (ASCII report) |
| 2 | **Environment Status** | `aditrader status` | None | Mode, DB, models, feed, PaperBroker balance, session token | **Top Navigation Status Pill** + Overview summary card | **Top Status Bar** & Status overview screen |
| 3 | **Initialize Database** | `aditrader init-db` | None | Creates SQLite ledger schema, stamps Alembic head | **Settings -> Ledger Database** "Initialize DB" button | **Settings -> Init DB** action |
| 4 | **Strategy Catalog** | `aditrader strategies` | `--detail <name>` | List of strategy templates, DNA profile, or AST printout | **Strategies Workspace** (Card/table catalog + Detail Drawer) | **Strategies Browser** (List with [Enter] to inspect) |
| 5 | **Scrip Master Search** | `aditrader search` | `query`, `--limit` | Matching instruments (token, exchange, lot size, strike, type) | **Global Search Dialog** (`Cmd/Ctrl+K`) + Data Scrip lookup | **Scrip Search Screen** with interactive filter |
| 6 | **Strategy Validation** | `aditrader validate` | `--strategy` / `--file`, `--policy`, `--csv`, `--bars` | 7-pillar verification matrix, gate scores, theoretical/empirical check | **Validation Studio** (Strategy selector, policy, data, matrix panel) | **Validation Wizard** (Step-by-step validator & matrix) |
| 7 | **Historical Backtest** | `aditrader backtest` | `--strategy` / `--file`, `--csv` / `--bars`, `--capital`, `--slippage-bps` | Trades, metrics, balance sheet reconciliation, sealed Run Dossier | **Simulation Studio -> Backtest Tab** (Config, live run, metrics, P&L) | **Run Backtest Flow** (Interactive form -> execution table) |
| 8 | **Web Dashboard Server** | `aditrader dashboard` | `--port`, `--host`, `--serve` / `--no-serve` | Starts local HTTP web workstation server | **The Web GUI itself** | **TUI Server Control** (Start/stop background server) |
| 9 | **Forward Paper Session** | `aditrader forward-test` | `--strategy`, `--instrument`, `--csv`, `--timeframe`, `--qty`, `--volume-mode`, `--capital`, `--slippage-bps`, `--mock`, `--ticks`, `--bars`, `--duration`, `--output`, `--strict-quality` | Live/mock paper session, tick aggregator, order fills, session dossier | **Simulation Studio -> Forward Paper Tab** (Streaming monitor, P&L, controls) | **Forward Session Runner** (Live tick dashboard & fill ledger) |
| 10 | **Feed Smoke Test** | `aditrader smoke-feed` | `--symbol`, `--ticks`, `--timeout`, `--mock` | Tick reception test, latency, LTP, bid/ask spread | **Data Workspace -> Feed Health Test** card with live tick counter | **Feed Smoke Test Screen** (ASCII tick stream) |
| 11 | **Dataset Inspection** | `aditrader inspect-data` | `file` / `--file`, `--symbol` | Ingestion check: columns, format, session bounds, gaps, replayability | **Data Workspace -> Dataset Table** + "Inspect Data" modal | **Dataset Inspector** (File picker -> diagnostic table) |
| 12 | **Strategy Code Audit** | `aditrader inspect-strategy` | `file` / `--file` | Pine Script v4/v5 / Python / DSL parser, lookahead check | **Strategies Workspace -> Strategy Auditor** modal (upload/paste) | **Audit Strategy File** (File path prompt -> report) |
| 13 | **Broker Authentication** | `aditrader kotak-auth` | `--mock` | Kotak Neo API auth check, token verification | **Settings -> Broker Connection** with "Test Connection" button | **Settings -> Test Auth** action |
| 14 | **Broker Discovery Suite** | `aditrader kotak-discover` | `--output-dir`, `--mock` | 5-stage progressive Kotak Neo retrieval & capability report | **Settings / Data -> Run Discovery Suite** with progress log | **Run Discovery Suite** screen |
| 15 | **Historical Data Download** | `aditrader kotak-history` | `symbol`, `--from-date`, `--to-date`, `--timeframe`, `--output`, `--mock` | Historical OHLCV bars fetched via Kotak Neo API, saved to disk | **Data Workspace -> Download Market Data** dialog | **Download Historical Data** wizard |
| 16 | **Option Chain Matrix** | `aditrader kotak-option-chain` | `--underlying`, `--expiry`, `--count`, `--output-dir`, `--mock` | Multi-strike option chain ladder with Greeks, IV, and Premium-Ladders | **Market Data -> Option Chain Ladder** view (CE/PE matrix) | **Option Chain Ladder** (ASCII two-sided matrix) |
| 17 | **Options Forward Shadow**| `aditrader forward-options` | `--strategy`, `--underlying`, `--expiry`, `--band`, `--capital`, `--slippage-bps`, `--duration`, `--output-dir`, `--snapshot-interval`, `--mock`, `--no-wait` | Live options paper session, band selection, trailing stops, Run Dossier | **Simulation Studio -> Options Forward Shadow** (Band, trailing stop) | **Options Forward Shadow** runner |
| 18 | **Run History** | `aditrader runs` | `--limit`, `--type` | History table of completed backtests & forward paper sessions | **Runs & Evidence Workspace** (Searchable, filterable runs table) | **Run History Browser** (Scrollable list with search) |
| 19 | **Run Dossier Inspection**| `aditrader inspect-run` | `run_id` | Full inspection: trade ledger, event stream, reconciliation, Merkle seals | **Run Dossier Inspection Modal** (Ledger, timeline, reconciliation, KAT) | **Inspect Run Screen** (Tabbed ASCII views) |
| 20 | **Strategy Explainer** | `aditrader explain-strategy` | `--strategy` / `--file`, `--model` | Educational strategy explanation: triggers, legs, hedge ratio, assumptions | **Strategies Workspace -> "Explain Strategy"** drawer / modal | **Strategy Explainer Screen** |
| 21 | **Strategy Suggestor** | `aditrader suggest-strategy` | `--regime`, `--symbol`, `--forecast`, `--validate`, `--out` | Suggests volatility-matched strategy adhering to 60/40 selling bias | **Strategies Workspace -> "Strategy Suggestor"** card / wizard | **Strategy Suggestor Flow** |
| 22 | **Strategy Reviewer** | `aditrader review-strategy` | `--strategy` / `--file`, `--policy`, `--csv`, `--bars` | Hostile adversarial review: unhedged gamma, ratio risk, curve-fitting | **Validation Studio -> "Adversarial Review"** critique panel | **Adversarial Review Screen** |
| 23 | **Price Forecast** | `aditrader forecast` | `--symbol`, `--timeframe`, `--horizon`, `--model`, `--csv`, `--bars` | Point-in-time probabilistic price trajectory cone [Low, Exp, High] | **Market Data / Overview -> Price Trajectory Forecast** card/chart | **Price Forecast Screen** (ASCII trajectory table) |
| 24 | **Research Dossier** | `aditrader research-dossier` | `--strategy` / `--file`, `--csv`, `--bars`, `--output` | Unified institutional dossier: AST rules, validation, KAT, sensitivity | **Runs / Validation -> "Compile Research Dossier"** modal | **Compile Dossier Action** |

---

## 2. Target User Profile & Usability Constraints

### Primary Persona: "Ramesh Sharma", 54, Senior Bank Branch Manager
- **Financial Background**: 28 years in banking. Thoroughly understands credit vs debit, realized vs unrealized profit, balance sheets, interest rate dynamics, margin safety, and statutory taxes (STT, GST, stamp duty). Trades index options personal account (Iron Condors, credit spreads).
- **Technical Literacy**: Uses core banking software (Finacle), MS Excel, brokerage apps. Does **not** know Python, Git, Docker, command-line arguments, JSON AST, or compiler concepts.
- **Cognitive Needs**:
  - Clear, readable typography (minimum 13px, high-contrast text, tabular lining numbers).
  - Clear cause-and-effect ("What does this button do? What will happen next?").
  - Absolute transparency on paper simulation vs live execution: Never wants to wonder if real money is at risk.
  - Zero developer jargon in primary views (no "AST", "Pydantic", "ADR 002 violation", "Serialization error").
  - Immediate access to evidence ("Show me the trade ledger", "Show me the fee breakdown", "Show me why this failed").

---

## 3. Existing UI Audit (KEEP / IMPROVE / REWORK / REMOVE)

| Screen / Component | Current State | Verdict | Target Architectural Evolution |
|---|---|---|---|
| **Global Header** | Small text, technical ADR banner, emoji pills | **REWORK** | Replace with an institutional status bar: Product title (`AdiTrader`), calm Mode Pill (`Paper Simulation Only · Air-Gapped`), Active Session indicator, Connectivity health, and unified navigation tabs. |
| **Overview Tab** | 6 fragmented cards, AI Assistant card, empty space | **IMPROVE** | Reorganize into: (1) System Health & Capital Summary, (2) Recent Activity & Audit Trail, (3) Quick Workflows ("Validate Strategy", "Run Backtest", "Inspect Data"), (4) Market Forecast & Regime pulse. |
| **Strategies Tab** | Cards list + NIFTY CE dynamic ladder feature | **IMPROVE** | Keep rich template catalog. Add: (1) Plain-English summary first, (2) Clear distinction between Options Multi-Leg vs Equity Linear, (3) Direct action bar on each card: `View Details`, `Explain Mechanics`, `Validate`, `Run Simulation`, (4) Strategy code auditor for uploading Pine/JSON files. |
| **Data Tab** | Dataset table, diagnostics modal | **IMPROVE** | Add: (1) Broker Scrip Master Search (`Cmd+K` or search bar), (2) Feed Health Smoke Test card with live tick latency, (3) Download Historical Data wizard (`kotak-history`). Turn raw diagnostics into clean financial checklist. |
| **Validation Tab** | Dropdown, policy selector, 7-pillar matrix | **IMPROVE** | Transform into a 3-step decision studio: Step 1 (Select Strategy), Step 2 (Select Policy & Verification Mode: Theoretical Payoff or Empirical Dataset), Step 3 (Evaluation Scorecard with 7-pillar breakdown and Adversarial Review critique). |
| **Simulation Tab** | Conflated linear backtest & forward shadow session | **REWORK** | Clearly divide into two sub-workspaces: **(A) Historical Backtest** (deterministic linear replay with equity curve and fee ledger) and **(B) Forward Paper Rehearsal** (real-time/mock tick stream, option chain band tracker, trailing stop monitor). Unmistakable `MOCK REHEARSAL` vs `REAL FEED` banners. |
| **Runs Tab** | Table of past runs, dossier inspection modal | **IMPROVE** | Rename clearly to **Runs & Evidence**. Enhance table with column sorting, status filtering, and a comprehensive Run Inspector drawer: Performance Scorecard, Closed Trade Ledger, Event Timeline, Balance Sheet Reconciliation, and Merkle Tamper Seals. |
| **Settings Tab** | API credentials, session token | **IMPROVE** | Add: System Diagnostics (`aditrader doctor`), Database Initialization (`aditrader init-db`), Kotak Neo Discovery Suite (`aditrader kotak-discover`), and Broker Connection Test. |
| **Floating/Pasted AI Widgets** | Generic assistant card | **REWORK** | Embed AI capabilities contextually into the screens where they belong (Explainer in Strategies, Suggestor in Strategy Builder, Reviewer in Validation, Forecast in Market Data, Dossier in Runs). |
| **Internal Developer Jargon** | "AST serialization", "ADR 002 physically air-gapped", "Pydantic validator" | **REMOVE** | Purge internal compliance jargon from primary user workflows. Translate into clean financial vernacular ("Hedged Spread", "Maximum Risk", "Paper Simulation", "Rule Syntax"). |

---

## 4. AdiTrader Design System & Language

### 4.1 Aesthetic Foundation
A quantitative workstation must feel **calm, precise, restrained, and trustworthy**. No crypto-casino gamification, no generic SaaS marketing templates, no harsh pitch-black backgrounds.

### 4.2 Core Color Tokens (6 Primary Hex Values + Semantics)
- `--bg-canvas`: `#0c0e12` (Deep Obsidian Charcoal, softer than `#000` to prevent eye strain during long market sessions)
- `--bg-surface`: `#141820` (Elevated dark slate container background)
- `--bg-elevated`: `#1c222e` (Active card / hover / modal surface)
- `--border-subtle`: `#252d3d` (Crisp 1px borders providing structure without visual noise)
- `--text-primary`: `#f1f5f9` (Clean, crisp off-white for high legibility)
- `--text-secondary`: `#94a3b8` (Muted slate for labels, timestamps, and secondary metadata)
- `--accent-primary`: `#3b82f6` (Precision Institutional Blue for interactive controls and focus rings)

### 4.3 Semantic Financial Colors
- `--color-profit`: `#10b981` (Balanced emerald green for positive returns and passing gates)
- `--color-loss`: `#ef4444` (Clear crimson red for losses, drawdowns, and safety vetoes)
- `--color-warning`: `#f59e0b` (Warm amber for warnings, partial hedges, and data gaps)
- `--color-options`: `#8b5cf6` (Royal violet for option legs, Greeks, and volatility structures)
- `--color-paper`: `#0ea5e9` (Cyan / Sky Blue for paper-trading mode and rehearsal badges)

### 4.4 Typography System
- **UI & Controls**: `-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif`
  - Base body: `14px / 1.5` line-height for comfortable reading by a 54-year-old operator.
  - Section headers: `16px / 1.4` font-weight 600.
  - Page titles: `20px / 1.3` font-weight 600.
  - Avoid all-caps labels; use standard sentence case with subtle letter spacing (`0.01em`).
- **Financial Numbers, Tables & Code**: `"JetBrains Mono", "SF Mono", Menlo, Consolas, monospace`
  - Strict tabular lining numerals (`font-variant-numeric: tabular-nums`).
  - Right-aligned monetary figures with explicit `₹` prefix and 2 decimals (`+₹2,540.50`).
  - Percentages formatted with explicit sign and 2 decimals (`+1.45%`, `-0.82%`).

### 4.5 Financial State Semantics (Multi-Sensory Differentiation)
Never rely on color alone:
1. **Market Data Mode**:
   - `🟢 LIVE MARKET DATA (Kotak Neo)`: Emerald border + solid dot + explicit provider tag.
   - `🔵 MOCK REHEARSAL DATA`: Cyan border + dashed icon + explicit "Simulated" tag.
2. **Execution State**:
   - `🛡️ PAPER EXECUTION ONLY`: Permanent header indicator stating "Air-gapped local PaperBroker. Real live broker routing is disabled."
3. **Accounting Presentation**:
   - `Realized P&L`: Labeled "Closed Trades Net Profit (After Fees & STT)".
   - `Unrealized P&L`: Labeled "Open Position Floating P&L (Mark-to-Market)".
   - `Ending Equity`: Labeled "Total Portfolio Equity = Cash + Position Value".
4. **Validation Status**:
   - `✅ VERIFIED / APPROVED`: Solid green badge with checkmark and policy name.
   - `⚠️ DATA REQUIRED (Incomplete)`: Amber badge with explanatory text: "Structural rules passed; historical backtest needed for empirical rating."
   - `🛑 REJECTED / VETO`: Red badge with exact failing gate and reason.
5. **Evidence Provenance**:
   - `[DETERMINISTIC]`: Solid border + "Formula Calculation".
   - `[AI_ADVISORY]`: Subtle violet border + "AI Research Estimate (Non-Authoritative)".

---

## 5. Shared Service Layer Architecture

The GUI and TUI do not implement any independent calculations or business logic. Both invoke the exact same canonical service layer:

```text
                     SHARED DOMAIN & APPLICATION LAYER
       (BacktestRunner, ForwardRunner, StrategyRegistry, ValidationService,
        PaperBroker, NSECSVInspector, InstrumentSearch, AIServiceBridge)
                                     │
                 ┌───────────────────┴───────────────────┐
                 │                                       │
         REST API BRIDGE                         PYTHON TUI ENGINE
       (web/services.py)                         (cli/tui/engine.py)
                 │                                       │
          WEB DASHBOARD                             TERMINAL TUI
     (Single-Page GUI in HTML5)                 (Curses / Keyboard Nav)
```

1. **Strategy Discovery**: Both call `StrategyRegistry.list_all()`.
2. **Validation**: Both call `StrategyValidationService.validate()`.
3. **Backtesting**: Both call `BacktestRunner.run()`.
4. **Forward Paper Rehearsal**: Both call `ActiveRunManager.start_forward_run()`.
5. **Dossier & Run Inspection**: Both call `ValidationServiceBridge.inspect_run()`.
6. **Data Inspection**: Both call `NSECSVInspector.inspect()`.
7. **Instrument Search**: Both call `InstrumentSearchService.search()`.
8. **AI Research**: Both call `AIServiceBridge.*` methods.

---

## 6. TUI (Terminal User Interface) Architecture

The TUI is implemented as a clean, zero-dependency, keyboard-first terminal workstation using Python's built-in `curses` library (with graceful ANSI fallback).

### Key Features:
- **Header**: Shows `AdiTrader Workstation`, mode (`Paper Simulation`), active session, and current screen.
- **Top Navigation Bar**: Numbered keys or Left/Right arrows:
  `[1] Overview | [2] Strategies | [3] Data | [4] Validation | [5] Simulation | [6] Runs | [7] Settings`
- **Main Viewport**: Scrollable panels, high-contrast ASCII tables with tabular-aligned figures, and interactive forms with field validation.
- **Hotkeys**:
  - `↑ / ↓` or `k / j`: Move selection in tables and lists.
  - `Enter`: Select, inspect, or submit.
  - `Tab / Shift+Tab`: Cycle between inputs/panels.
  - `/` or `s`: Instant search / filter.
  - `Esc` or `b`: Back / Close modal.
  - `q`: Exit TUI safely.
  - `?`: Contextual hotkey help bar at bottom.

---

## 7. Claude Design Approval Gate (Mandatory Questions)

Before any code implementation, Claude must evaluate the following 11 dimensions:

1. **Product Derivation**: Does the design derive strictly from the actual 24 CLI capabilities without inventing new trading functionality?
2. **Usability Elevation**: Does it make the CLI capabilities substantially easier to operate?
3. **Target User Fit**: Can a 54-year-old bank manager operate it independently without a developer beside them?
4. **Information Hierarchy**: Are P&L, risk, strategy state, and validation clearly primary, while hashes and timestamps remain subordinate?
5. **Information Density**: Does it achieve high information density with low cognitive decoding cost?
6. **Financial Credibility**: Does it look and feel like serious financial software?
7. **Anti-Trope Restraint**: Does it avoid generic AI-dashboard aesthetics (all-caps labels, card-kit soup, marketing hero numbers)?
8. **State Communication**: Are market modes (Real vs Mock), execution (Paper only), accounting (Realized vs Unrealized), and AI advisory states unmistakable?
9. **Visual Simplicity**: Is anything visually overcomplicated or redundant?
10. **Scalability**: Does this design cleanly accommodate all 24 CLI operations?
11. **Implementation Readiness**: Is the visual and component architecture coherent enough to implement globally?
