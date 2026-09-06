name: AI Agent Orchestration
description: Multi-agent coordination, pipeline handoffs, and operational boundaries.

# Goal
Govern the responsibilities, execution handshakes, and operational authority across all specialized AI agents in the research and review pipeline[cite: 1].

# Agent Responsibilities & Boundaries

| Component | Responsibility | Authority Limit | Output Format |
|---|---|---|---|
| **Gemini Vision**[cite: 1] | Extract support, resistance, trends, and patterns from uploaded charts[cite: 1, 2]. | Pure observer; cannot construct or execute strategies[cite: 1]. | `VisionResult` with `ProvenanceRecord`[cite: 1] |
| **Forecast Model**[cite: 1, 2] | Predict price movements and confidence intervals from historical bars[cite: 1, 2]. | Probabilistic math only; cannot place signals or trades[cite: 1, 2]. | `ForecastResult` with `ProvenanceRecord`[cite: 2] |
| **Strategy Suggestor**[cite: 1] | Map market regimes to pre-built options templates using `BiasCfg`[cite: 1, 2]. | Proposes templates; cannot execute or bypass validation[cite: 1, 2]. | `SuggestionResult` with `ProvenanceRecord`[cite: 1] |
| **Validation Engine**[cite: 1] | Deterministic Institutional Mode gatekeeper (expectancy, drawdown, tail risk)[cite: 1]. | **Absolute veto power**; rejects unviable structures[cite: 1]. | `ValidationResult`[cite: 1] |
| **Strategy Reviewer**[cite: 1] | Critiques edge conditions, structural fragility, and risk profile[cite: 1]. | Qualitative review; cannot claim DETERMINISTIC (contract-enforced `AI_ADVISORY`)[cite: 1]. | `DossierSection` (`AI_ADVISORY` enforced via `AIMalformedOutputError`)[cite: 1] |
| **Teacher**[cite: 1] | Explains payoff curves, Greeks exposure, and historical context[cite: 1]. | Explanatory only; strictly prohibited from giving financial advice[cite: 1]. | `DossierSection` (`AI_ADVISORY`)[cite: 1] |

# Failure & Degraded Mode Handling (ADR 012)
- Engine `is_available() -> bool` methods must never raise network or runtime exceptions; they return `False` if credentials, API endpoints, or compute backends are unreachable or unconfigured[cite: 2].
- If an AI model or API provider is offline, unreachable, or times out during execution, raise explicit typed exceptions (`AIUnavailableError`, `AITimeoutError`, `AIConfigError`).
- Degraded mode operation: Omit or mark advisory sections as `[AI ADVISORY UNAVAILABLE]`; NEVER inject synthetic or fabricated predictions.
- Deterministic workflows (AST validation, backtesting, paper execution, payoff curves) remain fully operational without AI availability.

# Orchestration Pipeline

Gemini Vision (Chart Analysis)[cite: 1] + Forecast Model (Chronos/Kronos)[cite: 1, 2]
|
v
Strategy Suggestor (BiasCfg 60/40 Template Builder)[cite: 1]
|
v
Validation Engine (Deterministic Institutional Mode Veto)[cite: 1]
|
+-----------------------+-----------------------+
|                                               |
[Rejected]                                      [Approved][cite: 1]
|                                               |
v                                               v
Diagnostic Failure Dossier                      Research Dossier Generator
(Strategy Reviewer Analysis)                    (Combines Deterministic + AI Advisory)
                                                |
                                                v
                                                Human Researcher Approval
                                                |
                                                v
                                                Paper Broker Execution[cite: 1, 2]

