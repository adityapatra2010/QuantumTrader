name: API Design
description: Layered backend boundary rules, endpoint decoupling, and contract enforcement.

# Goal
Enforce a strict 4-layer backend architecture to decouple business logic from presentation clients (Dash UI, CLI, or future frontends)[cite: 1, 2].

# Layered Flow Pattern

Client Request (Plotly Dash / CLI / REST Client)[cite: 2]
|
v
[Handler / Router]: Request validation, serialization, auth checks
|
v
[Service Layer]: Domain orchestration (Strategy, Risk, Validation)[cite: 1]
|
v
[Repository Layer]: Abstracted data queries and state persistence
|
v
[Database / Cache]: SQLite / Parquet / In-Memory Store[cite: 2]


# Architectural Rules
- **Zero Domain Logic in Handlers**: API routes and Dash callbacks must never evaluate Greeks, compute payoffs, or execute paper trades inline[cite: 2]. They must delegate entirely to domain services[cite: 2].
- **Strict Pydantic Contracts**: All incoming requests and outgoing payloads must conform to validated Pydantic models. Raw dictionaries must not cross service boundaries.
- **Stateless Services**: Service methods must accept explicit context parameters rather than maintaining shared runtime state across calls[cite: 1].
