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
