# Gemini Forensic Audit & Design Research Package for Claude

**Author**: Gemini (Product/Design Researcher & Implementation Lead)  
**Recipient & Sole Design Authority**: Claude (Principal Quantitative Systems Architect & Design Critic)  
**Date**: 2026-09-16  
**Subject**: Complete Workstation Design Reset for AdiTrader / QuantumValidator

---

## 1. Executive Summary & Purpose

The prior GUI/TUI transformation established 100% functional parity with the 25 canonical CLI operations, but the rendered Web Workstation remained fundamentally anchored to the old AdiTrader visual paradigm: a collection of disconnected tabs filled with rounded cards, large whitespace gaps, and modal popups.

This document presents the **Phase 1 Forensic Audit**, **Phase 2 Legacy Purge Identification**, **Phase 3 Reference Product Research**, and **Phase 4 Synthesis** to hand over to Claude as the sole design authority to create `WORKSTATION_DESIGN_SPECIFICATION.md`.

---

## 2. CLI Forensic Inspection (The Canonical Baseline)

AdiTrader's CLI defines 25 distinct subcommands. The GUI and TUI must remain 100% pure projections of these exact capabilities via `src/aditrader/system/operations.py`:

```text
                                 CANONICAL CLI CAPABILITIES
┌──────────────────────────────┬──────────────────────────────┬──────────────────────────────┐
│ SYSTEM & DATA INGESTION      │ STRATEGY & VALIDATION        │ EXECUTION & RESEARCH         │
├──────────────────────────────┼──────────────────────────────┼──────────────────────────────┤
│ 1. doctor (diagnostics)      │ 4. strategies (catalog/DNA)  │ 7. backtest (deterministic)  │
│ 2. status (system & capital) │ 6. validate (7-pillar matrix)│ 9. forward-test (paper)      │
│ 3. init-db (SQLite/Alembic)  │ 12. inspect-strategy (audit) │ 17. forward-options (shadow) │
│ 5. search (scrip master)     │ 20. explain-strategy (AST)   │ 18. runs (dossier history)   │
│ 10. smoke-feed (latency)     │ 21. suggest-strategy (regime)│ 19. inspect-run (tamper hash)│
│ 11. inspect-data (envelope)  │ 22. review-strategy (critic) │ 24. research-dossier (report)│
│ 13. kotak-auth (session)     │                              │ 8. dashboard (web server)    │
│ 14. kotak-discover (5-stage) │                              │ 25. tui (curses workstation) │
│ 15. kotak-history (OHLCV)    │                              │                              │
│ 16. kotak-option-chain (greeks)                             │                              │
│ 23. forecast (price trajectory)                             │                              │
└──────────────────────────────┴──────────────────────────────┴──────────────────────────────┘
```

### Core Execution & Security Contracts
* **ADR 002 (Air-Gap Invariant)**: Real broker order placement APIs (`place_order`, `modify_order`, `cancel_order`) do not exist. All executions route strictly to `PaperBroker`.
* **ADR 007 (Zero Dynamic Code Execution)**: Zero `eval()`, `exec()`, or runtime code generation. AST compiler state machines only.
* **ADR 010 (Net Portfolio Equity)**: `Total Equity = Cash Balance + sum(pos.qty * ltp)`. Symmetrical margin gates.
* **ADR 011 (Options Replay Air-Gap)**: Backtesting engine rejects options strategies with `UnsupportedStrategyError`. Multi-leg options support theoretical Black-Scholes Greeks and payoff corridors only.
* **ADR 012 (AI Advisory Isolation)**: AI outputs (forecasting, review, suggestor, explainer) are advisory estimates with SHA-256 provenance; validation engine retains absolute veto.

---

## 3. Forensic Breakdown of Existing GUI Weaknesses

### 3.1 What Failed in the Previous Design
The previous design attempted to polish the existing UI rather than reset it. Key structural failures:
1. **Card Proliferation ("Card Soup")**:
   - Every single metric, section, and tool was wrapped in an isolated rounded card (`.card`, `.section-card`, `.metric-card`).
   - The screen felt like a Bootstrap 4 admin dashboard or an early-2020s crypto dashboard with floating pill boxes.
2. **Page-by-Page Tab Fragmentation & Context Loss**:
   - The UI forced the user to navigate across 7 separate tabs (`Overview`, `Strategies`, `Data`, `Validation`, `Simulation`, `Runs`, `Settings`).
   - *Example Failure*: A user looking at the Strategy Catalog in Tab 2 cannot see the Market Option Chain from Tab 3 or the Validation Status from Tab 4. Selecting a strategy required memorizing its name, switching to Validation, finding it again in a dropdown, clicking Validate, then switching to Simulation, finding it a third time, picking a dataset, and then switching to Runs to see results.
3. **Modal Popup Abuse**:
   - Global Scrip Search was trapped inside a modal dialog (`#scrip-search-modal`).
   - Option Chain was trapped inside a modal dialog (`#option-chain-modal`).
   - Feed Smoke Test was trapped inside a modal dialog (`#feed-smoke-modal`).
   - Strategy Script Auditor was trapped inside a modal dialog (`#strategy-audit-modal`).
   - *Result*: The user cannot cross-reference the Option Chain while configuring an options strategy! Modals blocked the entire interface, destroying workstation workflow continuity.
4. **Oversized Containers & Whitespace Soup**:
   - Empty padding (`padding: 24px 32px`, `margin-bottom: 24px`) pushed key information off the viewport.
   - At 1440x900, the user could only see 2-3 cards before having to scroll down a 3000px page.
5. **Weak Financial Density & Alignment**:
   - Financial numbers used variable-width font styling in several headers.
   - Lack of dense, columnar, multi-pane financial grid layouts.
6. **Weak System State Visibility**:
   - The air-gap guarantee was rendered as a static yellow/cyan warning bar at the top of every tab, consuming vertical space without providing actionable status.
   - Execution state (Paper vs Mock Rehearsal) was repeated on every card instead of living in a unified status ribbon.

---

## 4. The Legacy UI Purge List (What Must NOT Survive)

The following patterns, styles, and structural decisions are hereby condemned and must be completely purged from the new workstation:

1. ❌ **Floating Rounded Card Islands**: No more bubble cards floating in vast dark space with 16px margins and 8px border-radii.
2. ❌ **Tab-by-Tab Page Silos**: No more flipping between 7 full-page tabs where all context is wiped out.
3. ❌ **Modal Popup Dialogs for Primary Workflows**: The Option Chain, Scrip Search, Strategy AST, and Run Dossiers must live in persistent workspace panes or docked drawers, NOT viewport-blocking popups.
4. ❌ **Excessive Whitespace Padding**: Purge 24px/32px empty gutter padding. Transition to a 4px/8px high-density financial layout.
5. ❌ **Dropdown-Heavy Form Selectors**: Eliminate disconnected `<select>` elements that require re-selecting the strategy on 4 different pages.
6. ❌ **Generic SaaS Metric Grids**: Eliminate the giant "Big Number + Tiny Gray Label" KPI cards popularized by Stripe/Tailwind templates.
7. ❌ **Floating AI Assistant Card**: AI must not live in a generic "Ask AI" sidebar or standalone assistant widget. AI tools must be contextually embedded directly into Strategy Analysis, Validation Review, and Market Forecasting.
8. ❌ **Static Repetitive Warning Banners**: Remove static text boxes repeating ADR compliance text across every screen.

---

## 5. Design Research: The Four Reference Products

### 5.1 Bloomberg Terminal
* **Core Philosophy**: Absolute speed, extreme information density, zero latency, persistent context.
* **Key Principles**:
  * **Amber/Cyan/White on Deep Obsidian**: High-contrast, monochromatic discipline. Color is reserved exclusively for semantic state (Green=Up/Profit, Red=Down/Loss, Amber=Caution/Input, Cyan=Active System).
  * **Command Line & Ticker Ribbon**: Top command line (`<CMD> GO`) and persistent context ticker (Active Symbol, LTP, Change, Volume, High, Low) that never leaves the screen regardless of what function is active.
  * **Quadrant & Multi-Pane Tiling**: The screen is divided into 2 to 4 tiled panes with thin 1px dividers, displaying Depth, News/Events, Analytics, and Financial Statements simultaneously.
  * **Keyboard-First Navigation**: Function keys (`F1`-`F12`), mnemonics, and arrow-key cursor focus.
* **What NOT to Copy**: Do not copy Bloomberg's proprietary yellow keys, nostalgic 1980s typography, or archaic three-letter function codes (`DES <GO>`). Extract its **persistent context ribbon, 1px tiled layout, and uncompromising density**.

### 5.2 Dhan / DEXT (T3)
* **Core Philosophy**: Professional Indian derivatives workstation (NSE/NFO), customizable blank canvas, speed-optimized execution.
* **Key Principles**:
  * **Context Synchronization**: Linked widgets. Selecting `NIFTY 24000 CE` in the Watchlist/Search instantly synchronizes the Option Chain, Greeks ladder, Price Ladder (DOM), and Positions.
  * **Compact Two-Sided Option Chain**: In-line Calls (Left) and Puts (Right) with strike ladder in the center column. Spot price highlighted as a horizontal line between In-The-Money (ITM) and Out-Of-The-Money (OTM) contracts.
  * **Dense Docked Panels**: Dark charcoal `#1E222D` with crisp `#2A2E39` borders. Minimal 4px borders, zero floating cards.
  * **Docked Status Ribbon**: Bottom bar showing latency (ms), broker connectivity, NSE market session status, and unread system alerts.
* **What NOT to Copy**: Do not copy Dhan's proprietary trading icons, live broker order ticket layouts, or gamified broker branding. Extract its **two-sided option chain geometry, linked-context synchronization, and compact Indian market session indicators**.

### 5.3 Zerodha Streak
* **Core Philosophy**: Systematic strategy construction, automated algorithmic validation, and scanner clarity without programming.
* **Key Principles**:
  * **Strategy-First Pipeline**: Linear progression:
    $$\text{Strategy Specification} \longrightarrow \text{Condition Engine} \longrightarrow \text{Backtest Replay} \longrightarrow \text{Performance Matrix} \longrightarrow \text{Deploy Paper}$$
  * **Plain-Language Condition Blocks**: Complex AST nodes expressed as clean visual rule statements (e.g., `Close crosses above EMA(20) on 5m`).
  * **Transaction Ledger & Drawdown Decomposition**: Clear tabular presentation of trade fills, entry/exit reasons, holding duration, and individual trade P&L alongside the equity curve.
  * **Parameter Sensitivity**: Clean grid showing how varying stop-loss or profit targets impacts expectancy.
* **What NOT to Copy**: Do not copy Streak's retail SaaS website layout or cloud subscription flow. Extract its **step-by-step strategy validation pipeline and clear decomposition of entry/exit triggers**.

### 5.4 TradeStrom
* **Core Philosophy**: Compact market regime identification, rapid volatility scanning, and actionable market context for option scalpers and swing traders.
* **Key Principles**:
  * **Instant Regime Pulse**: Immediate classification of the market into actionable states (High IV vs Low IV, Trending vs Rangebound, Mean-Reverting).
  * **Compact Volatility & Greeks Overview**: Key levels (PCR, Max Pain, ATM IV, ATM Straddle price) displayed in a dense horizontal summary strip rather than scattered across pages.
  * **Focus on Immediate Opportunities**: Filtering out illiquid or irrelevant strikes to emphasize high-probability dynamic premium bands.
* **What NOT to Copy**: Do not copy affiliate marketing banners, trading course teasers, or external P&L screenshots. Extract its **compact market regime header and instant options summary metrics (PCR, ATM IV, ATM Straddle)**.

---

## 6. Synthesis: The New AdiTrader Workstation Architecture

To turn AdiTrader into a true institutional quantitative workstation, we propose uniting these principles into a **Single-Screen Multi-Pane Tiled Workstation** with a persistent contextual layout:

```text
┌────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ TOP GLOBAL COMMAND & CONTEXT RIBBON (40px)                                                                             │
│ [AdiTrader v1.0] [Active Symbol: NIFTY 50 · ₹24,013.25 (+0.45%)] [Mode: Strict PaperBroker (ADR 002)] [Kotak: REHEARSAL]│
│ [Portfolio: Cash ₹2.50L | Margin ₹6.00L | Equity ₹10.00L | Realized ₹0.00 | Unrealized -₹210.00] [Search: Ctrl+K]      │
├───────────────────┬────────────────────────────────────────────────────────────────────┬───────────────────────────────┤
│ LEFT PANEL (260px)│ CENTER WORKSPACE (FLEX 1 - MULTI-PANE TILED)                       │ RIGHT PANEL (320px)           │
│ WORKSPACE EXPLORER│                                                                    │ CONTEXTUAL INSPECTOR          │
│                   │ ┌────────────────────────────────────────────────────────────────┐ │                               │
│ • Strategies (6)  │ │ WORKSPACE VIEWPORT (Tiled Panes or Focused Full-Height)        │ │ • Strategy DNA & AST Rules    │
│   - NIFTY CE Band │ │                                                                │ │ • 7-Pillar Verification     │
│   - Iron Condor   │ │ [Pane A: Market & Option Chain Ladder (Calls | Strike | Puts)] │ │   Scorecard (Pass/Fail)     │
│   - Bull Spread   │ │                                                                │ │ • Adversarial Reviewer      │
│ • Datasets (2)    │ │ [Pane B: Historical Replay / Forward Shadow Rehearsal]         │ │ • Forecast Trajectory Cone  │
│   - nifty_sample  │ │                                                                │ │ • Merkle Root & Tamper Hash │
│   - reliance_deriv│ │ [Pane C: Itemized Trade Ledger & Event Stream]                 │ │ • Balance Sheet Equation    │
│ • Run History (10)│ │                                                                │ │   Equity = Cash + PnL - Fees│
│ • System Tools    │ └────────────────────────────────────────────────────────────────┘ │                               │
├───────────────────┴────────────────────────────────────────────────────────────────────┴───────────────────────────────┤
│ BOTTOM DOCKED ACTION & STATUS BAR (32px)                                                                               │
│ [F1/1] Strategy Workspace | [F2/2] Option Chain | [F3/3] Validation | [F4/4] Backtest | [F5/5] Rehearsal | [F6/6] Runs    │
│ [Status: Engine Deterministic · SQLite WAL Connected · Session Active] [Lat: 1.2ms] [NSE: 09:15-15:30 IST] [?] Hotkeys│
└────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘
```

### Key Architectural Shifts:
1. **Persistent Portfolio & Market Header**: The active symbol, spot price, session status, and exact capital breakdown (`Cash`, `Blocked Margin`, `Realized PnL`, `Unrealized PnL`, `Ending Equity`) are permanently visible at the top.
2. **Left Workspace Navigator**: Instantly select strategies, datasets, past runs, or system tools without losing center-pane context.
3. **Center Tiled Workspace**: Houses the core analytical surfaces (Strategy Pipeline, Two-Sided Option Chain with Black-Scholes Greeks, Replay Runner, Trade Ledger).
4. **Right Contextual Inspector**: Displays progressive disclosure of whatever is active in the center pane (Strategy AST rules, 7-Pillar Verification Matrix, Adversarial Review critique, Merkle Root seals, or Reproducibility comparison).
5. **Zero Modals for Primary Workflows**: The option chain and scrip master are integrated into the main workstation panes, allowing simultaneous cross-referencing.
6. **Bottom Docked Action Bar**: Clear hotkey bindings (`1-6`, `Tab`, `Ctrl+K`, `[v]` Validate, `[b]` Backtest, `[m]` Mode, `[?]` Help).

---

## 7. Submission to Claude

Gemini now formally submits this research and forensic audit to Claude.  
**Claude is the sole design authority** and will now author `WORKSTATION_DESIGN_SPECIFICATION.md` to define the exact visual grammar, tokens, component layouts, and financial semantics.
