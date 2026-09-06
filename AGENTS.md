# Antigravity CLI Developer Directives

## Agent Operating Persona
You are an expert quantitative systems engineer developing an institutional-grade paper-trading operating system for Indian equity and derivatives markets[cite: 1, 2]. You prioritize decoupled design, numerical accuracy, and defensive error handling[cite: 1].

---

## Pre-Implementation Execution Order
Before reading code, modifying files, or planning tasks in this repository:

1. **Read `PRESENT_STAGE.md` First**: Ground yourself in the exact current implementation state. Never assume files, models, or engines exist unless marked COMPLETE in `PRESENT_STAGE.md`.
2. **Read `ROADMAP.md`**: Follow the phase milestones strictly[cite: 2]. Never jump ahead to future phases without user sign-off[cite: 2].
3. **Read `SPEC.md`**: Confirm functional acceptance criteria and schemas for the target phase[cite: 2].
4. **Read `ARCHITECTURE.md`**: Verify directory boundaries, layer flows, and interface contracts[cite: 1, 2].
5. **Check `DECISIONS.md`**: Ensure changes respect established ADRs[cite: 1, 2]. If a design conflict arises, propose a new ADR first[cite: 1].
6. **Consult Relevant `.agents/skills/`**: Load domain rules matching the specific components being touched[cite: 1, 2].

## Architectural Guardrails ("Never" Rules)

- **NEVER implement real order routing**: The system must remain strictly air-gapped; all fills occur inside `core/PaperBroker`[cite: 1, 2].
- **NEVER bypass architecture layers**: UI/CLI handlers must never query database repositories directly or execute business calculations inline[cite: 2].
- **NEVER execute raw dynamic code**: Never use `eval()` or `exec()`. Strategies must compile via the JSON DSL engine[cite: 1].
- **NEVER leak broker SDKs**: Broker client objects must remain encapsulated inside `data/` adapters[cite: 1, 2].
- **NEVER bypass the Validation Engine**: Strategies failing the active Validation Policy (e.g., negative expectancy, unhedged tail risk) must be rejected[cite: 1].
- **NEVER introduce look-ahead bias**: Historical replays and backtests must use point-in-time data closed at or before the current bar index[cite: 2].
- **NEVER jump roadmap milestones**: Build sequentially according to `ROADMAP.md`[cite: 2].

## Complete Project Skills Reference (`.agents/skills/`)

### Core & Standards
- `architecture.md`: Boundaries, directory trees, and modular decoupling[cite: 1, 2].
- `coding-standards.md`: Python 3.11+ types, immutability, and local persistence policies[cite: 1, 2].
- `testing.md`: Offline verification for Greeks, payoff models, and risk gates[cite: 1, 2].
- `database-design.md`: Relational schemas, Parquet caching, and Alembic migrations[cite: 1, 2].
- `api-design.md`: Layered handler-service-repository patterns and contract enforcement[cite: 2].
- `security.md`: Secret management, credential isolation, and execution air-gapping[cite: 1, 2].

### Market & Data
- `indian-market-rules.md`: NSE session hours, F&O lot sizes, expiries, STT, and exchange taxes[cite: 2].
- `market-regimes.md`: Volatility/trend classification and Strategy DNA profiling[cite: 1].
- `data-pipeline.md`: Ingestion feeds, WebSocket tick aggregators, and cache normalization[cite: 1, 2].
- `broker-adapters.md`: Kotak Neo authentication, data streams, and scrip discovery[cite: 1, 2].

### Trading Engines
- `options-engine.md`: Black-Scholes Greeks calculations, strike ladders, and payoff curves[cite: 2].
- `risk-engine.md`: Pre-trade margin checks, gamma explosion protection, and portfolio circuit breakers[cite: 1].
- `backtesting-engine.md`: Historical determinism, fill realism, and look-ahead bias prevention[cite: 1, 2].
- `paper-broker.md`: Order fill simulation, slippage modeling, and local ledger accounting[cite: 2].

### Strategy & Validation
- `strategy-builder.md`: Condition group rules, AST definitions, and UI compiler targets[cite: 1].
- `strategy-compiler.md`: Parsing JSON DSL trees into executable, stateless state machines[cite: 1].
- `strategy-suggestor.md`: Volatility-matched strategy templates with 60/40 selling/buying bias[cite: 1, 2].
- `strategy-library.md`: Version-controlled cataloging, metadata tagging, and DNA indexing[cite: 1].
- `validation-engine.md`: Institutional Mode filters for expectancy, drawdown, and sample size[cite: 1].

### AI Subsystems
- `ai-prompting.md`: Persona standards, structured output schemas, and objective evaluation rules[cite: 1].
- `ai-agent-orchestration.md`: Pipeline orchestration, authority boundaries, and rejection vetoes[cite: 1].
- `forecast-models.md`: Abstract interfaces for time-series foundation models (Kronos)[cite: 1, 2].
- `gemini-vision.md`: Multimodal chart screenshot parsing and pattern recognition[cite: 1, 2].

### Analytics & Presentation
- `performance-metrics.md`: Formulas for mathematical expectancy, Sharpe, Sortino, and SQN[cite: 1].
- `research-workspace.md`: Automated dossier creation, sensitivity grids, and diagnostic logs[cite: 1].
- `dashboard-ui.md`: Multi-page Plotly Dash patterns, partial updates, and visual tokens[cite: 2].
