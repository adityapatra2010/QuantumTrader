name: Data Pipeline
description: Market data ingestion, tick aggregation, caching, and normalization rules.

# Goal
Standardize and cache all live and historical market data feeds into a uniform data model, preventing strategies and UI modules from coupling to raw network APIs.

# Pipeline Architecture
External Data Sources (Kotak Neo WebSocket / Historical CSV)
|
v
Data Adapter Wrapper
|
v
Data Pipeline Normalization Engine
|
+-----------------+-----------------+
|                                   |
v                                   v
Tick Aggregator (1m/5m Bars)[cite: 2]   Option Chain Snapshot Engine[cite: 2]
|                                   |
+-----------------+-----------------+
|
v
Shared In-Memory Cache (Polars/Parquet)
|
+-----------------+-----------------+
|                                   |
v                                   v
Strategy Runner[cite: 2]             Plotly Dash UI[cite: 2]  
# Rules
- **Strict Isolation**: Strategies, the validation engine, and the UI must never call external SDK methods directly[cite: 1, 2]. All consumer components ingest data through the pipeline's normalized cache interface[cite: 1, 2].
- **Timezone Standardization**: Normalize every incoming tick, trade, and historical candle to `Asia/Kolkata` (IST) timestamps before caching[cite: 2].
- **Tick-to-Bar Aggregation**:
  - Live ticks must aggregate into standard OHLCV candles (Open, High, Low, Close, Volume, OI) at designated intervals (1m, 3m, 5m, 15m)[cite: 2].
  - Emit an immutable `Bar` event immediately upon candle close[cite: 2].

# Instrument Search & Derivatives Discovery (`data/instruments/`)
- **Normalized In-Memory Index (`InstrumentIndex`)**:
  - Ingests `ContractMetadata` from broker scrip masters or persistent Parquet cache files.
  - Multi-index architecture: Symbol map, Token map, Underlying contract sets, and hierarchical derivative structures.
- **Hierarchical Derivatives Resolution**:
  - Seamless navigation: `Underlying` -> `Derivative Type (FUT/OPT)` -> `Expiry Date` -> `Strike Price` -> `CE/PE`.
  - Helper methods: `resolve_derivative()`, `get_expiries()`, `get_strikes()`, `get_option_pair()`.
- **Deterministic Multi-Modal Scoring (`matcher.py`)**:
  - Scored ranking (0-100) combining exact token matches, exact symbols, symbol prefixes, structured derivative queries (e.g. "NIFTY 24000 CE", "RELIANCE FUT"), token containment, and fuzzy subsequence matching.
  - Strict institutional tie-breaking (scores descending, Equity before Derivatives on root queries, earliest expiry first, alphabetical symbol).
- **Persistent Caching (`InstrumentSearchService`)**:
  - Parquet serialization with zstd compression for instantaneous warm restarts without repeated scrip master downloads.
