# WORKSTATION DESIGN SPECIFICATION
**Author**: Claude (Principal Quantitative Systems Architect & Design Critic)
**Project**: AdiTrader / QuantumValidator
**Date**: 2026-09-16

## 1. Product Identity
AdiTrader is a **Quantitative Research Workstation, Professional Market Terminal, and Deterministic Engineering System**. It is not a retail trading app, it is not a SaaS admin dashboard, and it is not a web portal. It is a high-performance, single-screen command center for rigorous, deterministic testing of quantitative strategies in Indian equity and derivatives markets.

## 2. Information Density & Layout Architecture
* **Single-Screen Multi-Pane Tiled Layout**: The application must occupy the full viewport width and height natively, operating without a master page scroll bar.
* **Persistent Context**: Essential financial context (Symbol, LTP, Market Phase, System Mode, Capital, Margin, P&L) must be permanently docked at the top. 
* **Zero Modal Abuse**: Core workflows (Scrip Master search, Option Chain ladders, Strategy Code Review) must open in dedicated dockable side panels or split panes, NEVER in a screen-darkening modal overlay. Modals are permitted exclusively for destructive warnings (e.g., "Confirm Wipe Database").
* **No Card-Soup, No Tab Silos**: Metrics must not be placed in floating bubble cards with 24px padding. Components must be delineated by strict 1px grid lines (tiled layout), taking inspiration from Bloomberg and DEXT.
* **High Density**: Utilize every pixel purposefully. Padding should be 4px or 8px max.

## 3. Exact Visual Grammar & Token Palette
* **Backgrounds & Surfaces**: Deep obsidian and charcoal scale.
  - Base Canvas: `#000000` to `#0B0E14`
  - Pane Surface: `#111622`
  - Elevated Input/Hover: `#1C2436`
* **Borders**: Crisp, 1px lines. Absolutely **no rounded bubble cards**. Corner radii restricted to max `2px` to `4px` for inputs and buttons only. Pane dividers are sharp `0px` radius lines.
  - Subtle Divider: `#1E2638`
  - Strong Border: `#28334A`
* **Typography**:
  - UI/Labels: `Inter` (or system-ui), tight line-height.
  - Financials/Tables/Greeks: `JetBrains Mono` strictly, with `tabular-nums`. All data columns must right-align.

## 4. Financial State Semantics
Crucial system states must be visually distinct and instantly recognizable without reading text.
* **REAL KOTAK MARKET DATA vs MOCK/REHEARSAL**: Live data utilizes vivid semantic tags (e.g., solid Cyan). Mock/Rehearsal mode must be permanently branded (e.g., Amber hash-stripes in the status bar or distinct "MOCK" badges).
* **REALIZED P&L vs UNREALIZED P&L**: Realized P&L is solid text (Green/Red). Unrealized P&L should have an italic or slightly muted treatment.
* **OBSERVED DATA vs CALCULATION vs AI vs INPUT**:
  - *Observed (Market)*: Standard bright white/cyan mono.
  - *Deterministic Calculation*: Crisp borders, mono text.
  - *AI Interpretation*: Distinct muted purple or deep indigo indicator. 
  - *User Input*: Elevated contrast backgrounds, amber focus rings.
* **VALID vs INCOMPLETE vs WARNING vs REJECTED**:
  - *Valid*: Green `#10B981`
  - *Incomplete*: Gray `#64748B`
  - *Warning*: Amber `#F59E0B`
  - *Rejected*: Red `#F43F5E`

## 5. AI Presentation
AI tools (strategy explainers, forecast trajectory) are **STRICTLY ADVISORY**. 
* **Zero Fake Magic**: No glowing buttons, no "sparkles", no typing animations.
* **Deterministic Veto**: AI output is subject to the validation engine. AI data is presented in muted secondary panes with clear cryptographic (SHA-256) hash seals to denote its snapshot state.

## 6. Complete Strategy Workflow
The layout must seamlessly accommodate this sequential pipeline without losing context:
`Strategy Definition -> AST Inspection -> AI Explanation -> 7-Pillar Validation -> Backtest/Forward-Simulate -> Review & Sensitivity Grids -> Research Dossier`.
Selecting a strategy in a left-side explorer pane immediately loads its context across all other visible tools in the main and right panes.

## 7. Coexistent Market & Options Workspace
* **Embedded Option Chain**: The Option Chain is a dual-sided (Calls Left, Puts Right, Strike Center) ladder rendered with strict tabular layout, integrating Black-Scholes Greeks (Delta, IV).
* **Scrip Master**: Instantaneous keyboard-driven search (Ctrl+K) populating a split-pane, NOT a blocking modal.
* **Pre-Replay Diagnostics**: Data envelopes and bounds checking must be visible adjacent to the simulation pane.

## 8. Terminal Workstation (TUI) Alignment
The Web GUI and the Textual TUI are siblings. The Web GUI must feel like a high-resolution, mouse-enabled extension of the Curses-based TUI. Keyboard shortcuts (F-keys, Ctrl+K, Tab, Esc) must be front-and-center in the GUI, mapping directly to TUI bindings.

## 9. Explicit Design Anti-Patterns (Prohibited Items)
* ❌ Floating Rounded Card Islands
* ❌ Modals blocking primary workflows (Option Chain, Strategy AST, Scrip Search)
* ❌ Tab-by-tab page silos with complete context destruction
* ❌ 16px/24px/32px padding and oversized whitespace margins
* ❌ Variable-width fonts for numbers/financial data
* ❌ Generic SaaS metric dashboard layouts
* ❌ "Ask AI" floating chat widgets
