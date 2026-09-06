name: AI Agent Orchestration
description: Multi-agent coordination, pipeline handoffs, and operational boundaries.

# Goal
Govern the responsibilities, execution handshakes, and operational authority across all specialized AI agents in the research and review pipeline[cite: 1].

# Agent Responsibilities & Boundaries

| Agent | Responsibility | Authority Limit | Output Format |
|---|---|---|---|
| **Gemini Vision**[cite: 1] | Extract support, resistance, trends, and patterns from uploaded charts[cite: 1, 2]. | Pure observer; cannot construct or execute strategies[cite: 1]. | Structured JSON[cite: 1] |
| **Forecast Model**[cite: 1, 2] | Predict price movements and confidence intervals from historical bars[cite: 1, 2]. | Probabilistic math only; cannot place signals or trades[cite: 1, 2]. | `ForecastResult`[cite: 2] |
| **Strategy Suggestor**[cite: 1] | Map market regimes to pre-built options templates using 60/40 bias[cite: 1, 2]. | Proposes templates; cannot execute or bypass validation[cite: 1, 2]. | JSON Strategy Tree[cite: 1] |
| **Validation Engine**[cite: 1] | Institutional mode filter (expectancy, drawdown, sample size, tail risk)[cite: 1]. | **Absolute veto power**; rejects unviable structures[cite: 1]. | `ValidationResult`[cite: 1] |
| **Strategy Reviewer**[cite: 1] | Critiques edge conditions, structural fragility, and risk profile[cite: 1]. | Qualitative review; does not override validation filters[cite: 1]. | Research Dossier[cite: 1] |
| **Teacher**[cite: 1] | Explains payoff curves, Greeks exposure, and historical context[cite: 1]. | Explanatory only; strictly prohibited from giving financial advice[cite: 1]. | Markdown Text[cite: 1] |

# Orchestration Pipeline

Gemini Vision (Chart Analysis)[cite: 1] + Forecast Model (Kronos)[cite: 1, 2]
|
v
Strategy Suggestor (60/40 Template Builder)[cite: 1]
|
v
Validation Engine (Institutional Mode Veto)[cite: 1]
|
+-----------------------+-----------------------+
|                                               |
[Rejected]                                      [Approved][cite: 1]
|                                               |
v                  (In case of going forward)   v
Diagnostic Rejection Output----------------->Strategy Reviewer & Teacher[cite: 1]
|
v
Ready for Paper Execution[cite: 1, 2]
