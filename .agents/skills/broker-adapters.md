name: Broker Adapters
description: Rules for market data feeds, contract discovery, and authentication.

# Goal
Isolate vendor-specific SDKs (e.g., Kotak Neo) within a resilient, read-only data ingestion layer[cite: 1, 2].

# Responsibilities
- Authentication handling (TOTP, MPIN, session management)[cite: 2].
- Streaming live tick data via WebSockets (e.g., SFeed) and aggregating ticks into `Bar` structures[cite: 2].
- Fetching historical OHLCV data for replay fixtures[cite: 2].
- Scrip master downloads and option contract discovery (strikes, expiries, CE/PE tokens)[cite: 2].

# Boundaries & Safety
- Read-only data operations only; order execution methods must not be implemented or exposed[cite: 1, 2].
- Wrap all vendor SDK calls; do not pass vendor objects into the strategy engine or paper broker[cite: 1, 2].
- Gracefully handle market closures outside NSE market hours (09:15–15:30 IST) without spinning or failing[cite: 2].
- Automatically log API responses and retry network connection drops[cite: 1].
