name: Testing Standards
description: Comprehensive testing requirements for quantitative correctness, deterministic simulation, broker behavior, market-data integrity, state machines, persistence, security boundaries, and regression prevention.

# Goal

Ensure QuantumValidator produces correct, reproducible, causally valid, and auditable results before any live-data paper-forward testing.

All mission-critical behavior must be testable offline and deterministically.

# Core Principles

* Prefer deterministic fixtures over real network calls.
* Never weaken a safety invariant merely to make a test pass.
* Tests must verify behavior and invariants, not implementation details alone.
* Every previously discovered bug must have a regression test.
* Unsupported behavior must be tested as an explicit rejection/failure.
* Test boundaries between subsystems, not only individual functions.
* Avoid tests that pass because mocks are unrealistically permissive.
* Use fake clocks / deterministic timestamps where time affects behavior.
* Preserve existing tests unless behavior is intentionally and correctly changed.

# Quantitative Correctness

* `options/greeks.py`: Validate Black-Scholes delta, gamma, theta, and vega against established offline reference values.
* `options/payoff.py`: Verify payoff curves, breakevens, max loss, and max profit for calls, puts, vertical spreads, and supported multi-leg structures.
* Validate numerical edge cases:

  * zero/near-zero time to expiry
  * extreme volatility
  * deep ITM / OTM
  * invalid inputs
  * finite outputs
* `validation/`: Explicitly test rejection of:

  * negative expectancy
  * excessive drawdown
  * insufficient sample size
  * failed OOS criteria
  * invalid walk-forward windows
  * look-ahead violations
  * malformed strategies

# Strategy Engine

Test:

* DSL parsing
* schema/version validation
* compilation
* operator semantics
* deterministic repeated evaluation
* state transitions
* entry/exit behavior
* duplicate signal prevention
* position lifecycle
* strategy reset/session boundaries
* expiry/session handling

For stateful strategies, test adversarial paths rather than only happy paths.

# Point-in-Time / Anti-Lookahead Testing

Explicitly test temporal causality.

Examples:

* strategy cannot access future ticks
* signal timestamp <= order timestamp <= fill timestamp
* a bar cannot generate a trade using information after its close
* replay ordering is deterministic
* out-of-order ticks are handled explicitly
* partial bars cannot trigger closed-bar strategies
* shutdown cannot manufacture a signal

Any temporal invariant should have a regression test.

# Market-Data Testing

Test canonical Tick/Bar normalization.

Cover:

* valid ticks
* missing optional fields
* malformed ticks
* negative prices
* crossed markets
* invalid OHLC envelopes
* duplicate ticks
* out-of-order ticks
* stale ticks
* timestamp normalization
* timezone normalization
* session boundaries
* volume semantics
* cumulative-volume resets

Verify that unavailable fields remain unavailable rather than being synthetically invented.

# CSV Replay Testing

NSE CSV replay must be deterministic.

Test:

* file detection
* supported column variants
* date/time parsing
* timezone handling
* malformed rows
* missing required columns
* numeric conversion
* duplicate rows
* ordering
* session boundaries
* replay speed controls if implemented
* replay produces identical results across repeated runs

Verify:
`same input + same config → same tick sequence → same trades → same final result`

Test that replay mode can never silently become live mode.

# PaperBroker

Test:

* BUY market fills
* SELL market fills
* quote-aware fills
* spread handling
* slippage
* limit-order invariants
* partial fills if supported
* position accounting
* realized/unrealized PnL
* fees
* taxes
* instrument-aware costs
* margin requirements
* short-side margin
* closing vs opening orders
* reversals
* insufficient capital
* broker rejection behavior

Critical invariants:

BUY LIMIT:
`fill_price <= limit_price`

SELL LIMIT:
`fill_price >= limit_price`

No paper order may ever reach a live broker API.

# Options Safety Boundary

Explicitly test that unsupported multi-leg derivative strategies:

* are rejected before execution
* cannot create underlying spot proxy trades
* cannot create fake quantity=1 fallback orders
* cannot bypass the strategy validation layer
* do not modify broker/ledger state

This must be a fail-closed regression suite.

# Forward Runner

Integration-test:

`market data → aggregation → strategy → risk → PaperBroker → recorder`

Test:

* startup
* readiness
* live/simulated status transitions
* zero-tick timeout
* disconnect
* reconnect
* invalid feed data
* strategy exception
* broker rejection
* persistence failure
* clean shutdown
* repeated stop()
* STOPPING lifecycle semantics
* partial-bar shutdown
* duplicate-bar prevention

Verify background-thread/event-loop failures are surfaced rather than silently swallowed.

# Live Feed Adapter

Real network tests must be opt-in.

Default CI:

* mock SDK/network boundary
* deterministic transport
* no real credentials
* no real network dependency

Test:

* missing SDK
* authentication failure
* authentication success
* connection failure
* subscription failure
* readiness timeout
* first valid tick establishes readiness
* disconnect
* reconnect
* malformed vendor message
* clean close

Authentication must never imply feed readiness.

# Persistence

Test:

* SQLite inserts/queries
* transactions
* rollback behavior
* UTC normalization
* chronological ordering
* duplicate prevention
* corrupt input handling
* atomic JSON writes
* interrupted write behavior where testable
* recovery from temporary files

# Concurrency

Test thread/event-loop interactions where the subsystem is concurrent.

Cover:

* simultaneous stop() calls
* tick arrival during shutdown
* disconnect during processing
* callback re-entry
* lock contention
* no deadlock
* no duplicate processing

Prefer deterministic concurrency tests over sleep-based timing tests.

# Property / Invariant Testing

Where practical, use property-based testing for:

* numerical calculations
* price/quantity conservation
* timestamp ordering
* limit-price constraints
* PnL accounting
* position transitions
* CSV replay determinism

Examples:

`cash + unrealized_pnl = net_equity`

`BUY limit fill <= limit`

`SELL limit fill >= limit`

`fill_timestamp >= signal_timestamp`

# Failure Injection

Do not only test successful execution.

Inject:

* malformed data
* missing configuration
* missing dependency
* network failure
* timeout
* stale feed
* broker rejection
* disk error
* corrupted persistence
* strategy exception
* invalid strategy definition

The expected behavior should be explicit and fail-closed.

# Security Regression Testing

Test that:

* credentials are not logged
* secrets are not written into strategy output
* live-order APIs remain unreachable from PaperBroker
* unsupported operations fail closed
* path/file handling cannot escape intended directories where applicable
* untrusted strategy input cannot execute arbitrary Python
* user strategy definitions cannot call `eval`/`exec`
* GUI/API boundaries validate untrusted input

# Regression Discipline

Every fixed bug must gain a regression test.

Do not remove a regression test because the current implementation no longer reproduces the bug.

When an existing behavior intentionally changes:

1. update the test
2. document the semantic change
3. verify neighboring invariants still hold

# Test Quality Review

After the suite passes, inspect tests themselves for:

* mocks hiding real bugs
* assertions that are too weak
* tests checking only "no exception"
* hardcoded values that accidentally encode implementation details
* missing negative cases
* missing boundary cases
* tests that depend on system wall-clock time
* tests that depend on machine/network state

A passing suite is not sufficient evidence if the assertions do not prove the intended invariant.

# Verification

Run:

* targeted tests first
* then complete pytest suite
* strict mypy
* Ruff check
* Ruff format check

Report:

* test count
* skipped tests and reasons
* coverage of newly changed behavior
* any intentionally untested external integration
* any remaining known limitations
