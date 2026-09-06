name: Security & Isolation
description: Credential handling, broker isolation, sandboxing, and operational guardrails.

# Goal
Prevent accidental live execution, secret leakage, and unconstrained code execution within AI-driven workflows[cite: 1, 2].

# Secret Management
- **Zero Hardcoded Credentials**: API tokens, consumer keys, TOTP secrets, and user MPINs must be read exclusively from environment variables (`.env` ignored in `.gitignore`).
- **Token Containment**: Broker session tokens (e.g., Kotak Neo JWTs) must remain inside the `data/` adapter layer and never be returned to UI components or API responses[cite: 1, 2].

# Operational Guardrails
- **Paper Trading Air-Gap**: The `core/PaperBroker` code path must contain zero references or imports to vendor order-placement endpoints[cite: 1, 2]. Live exchange submission methods must not exist anywhere in the codebase[cite: 1, 2].
- **Sandboxed DSL Execution**: The visual strategy builder and AI suggestion modules compile to declarative JSON AST trees[cite: 1]. Arbitrary Python execution via `eval()` or `exec()` is strictly forbidden[cite: 1].
- **Audit Logging**: Record all parameter overrides, validation failures, and mock session initiations with microsecond timestamps in a local security event log.
