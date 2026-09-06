name: System Architecture
description: Core boundaries, directory structure, and decoupling rules for the trading OS.

# Goal
Enforce a modular, vendor-agnostic architecture where data providers, forecasting models, and UI layers interact through strict internal interfaces[cite: 1, 2].

# Directory Boundaries
- `data/`: Ingestion, broker adapters, and market data feeds[cite: 2]. SDKs must never leak beyond this boundary[cite: 1].
- `core/`: State management, bar aggregation, and the local paper broker[cite: 2]. Zero vendor SDK or network dependencies[cite: 1, 2].
- `options/`: Option chain discovery, Black-Scholes Greeks, and pure multi-leg payoff calculations[cite: 2].
- `ai/`: Decoupled machine learning subsystems containing `forecasting/`, `vision/`, `reviewer/`, and `teacher/`[cite: 1].
- `strategy_builder/`: Visual and programmatic strategy compilation and JSON tree evaluation[cite: 1].
- `validation/`: Statistical gatekeeping ("Institutional Mode")[cite: 1].
- `research/`: Strategy reports, sensitivity analysis, and experiment journals[cite: 1].
- `dashboard/`: Multi-page Plotly Dash presentation layer[cite: 2].
- `cli/`: Command-line interface entry points (`neopaper <noun> <verb>`)[cite: 2].

# Rules
- Core execution is strictly local paper-trading; real orders must never be routed to the exchange[cite: 2].
- The strategy engine and paper broker must treat live WebSocket streams and historical CSV replays identically[cite: 2].
- Swap implementations (e.g., swapping Gemini for an alternative LLM, or Kotak Neo for Dhan/Zerodha) by modifying adapter classes without touching domain logic[cite: 1].
