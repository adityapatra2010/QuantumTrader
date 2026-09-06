name: Strategy Compiler
description: Compiles visual Strategy Builder configurations and JSON DSL trees into executable state machines.

# Goal
Provide an isolated compiler that converts declarative JSON definitions into validated, executable `Strategy` objects without generating unconstrained Python source code.

# Compilation Pipeline
Visual UI Builder / AI Suggestor
|
v
JSON Domain Specific Language (DSL)
|
v
Compiler AST Parser
|
+------+------+
|             |
[Valid]       [Invalid] ---> Rejection & Diagnostic Syntax Errors / Continue Anyway with Warning.
|
v
Executable Strategy State Machine  
# Architectural Boundaries
- **UI Decoupling**: The strategy compiler must never import Dash components, HTML elements, or UI state.
- **Strict AST Validation**:
  - Validate every condition against registered operator types (`GREATER_THAN`, `CROSSES_ABOVE`, `WITHIN_RANGE`, `MATCHES_REGIME`).
  - Ensure all option legs have valid strike offsets relative to ATM, explicit sides (`BUY`/`SELL`), and supported contract types (`CE`/`PE`).
- **Runtime Determinism**: Compiled strategy state machines must implement `on_bar(history: list[Bar]) -> Signal` and remain completely stateless between independent evaluation ticks.
