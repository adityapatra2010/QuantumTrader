name: Coding Standards
description: Engineering conventions, typing standards, and execution constraints.

# Goal
Maintain high-reliability Python code tailored for low-latency live tick aggregation and offline backtesting on Fedora Linux[cite: 2].

# Rules
- Target Python 3.11+ using strict typing annotations (`typing.TypedDict`, `dataclasses`, `pydantic`).
- Conditions and evaluators must be pure functions that never mutate state[cite: 1].
- Actions may modify local ledger state through explicit, transactional methods[cite: 1, 2].
- File operations must persist data locally to SQLite or Parquet under a `runs/` directory[cite: 2].
- Never write hardcoded API keys, tokens, or TOTP secrets; load all credentials from environment variables or secure local configuration.
- Handle timestamps explicitly in Indian Standard Time (`Asia/Kolkata`)[cite: 2].
