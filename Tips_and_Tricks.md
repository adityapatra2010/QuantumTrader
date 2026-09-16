# AdiTrader / QuantumValidator — Operator's Guide: Kotak Neo Forward-Shadow Paper Testing (Tips & Tricks)

**Target Strategy**: NIFTY Dynamic CE Premium-Ladder (`tpl-nifty-ce-premium-ladder-v1`)  
**Target Platform**: Kotak Neo (Official SDK v3.0.6)  
**Execution Venue**: Strictly Air-Gapped Local Simulation (`core.PaperBroker`)  
**File Location**: `Tips_and_Tricks.md` (Project Root)

---

## 1. What This Subsystem Actually Does

The Kotak Neo forward-shadow execution subsystem allows you to run options trading strategies (specifically the **NIFTY CE Premium-Ladder**) against **live, real-time market data** streamed from your real Kotak Neo account, while ensuring that **zero real orders** are ever sent to Kotak Neo or the exchange.

All order entries, fills, trailing stops, statutory taxes, and position exits are executed strictly inside AdiTrader's local, in-memory **`PaperBroker`**. 

At the end of each session, the system computes an audit-grade balance sheet reconciliation and seals the entire trade ledger and event stream into a cryptographically verified **Run Dossier** with binary Merkle tree roots.

---

## 2. Complete Data & Execution Flow

```
[ Kotak Neo REST API ]               [ Kotak Neo SFeed WebSocket ]
  • expiries()                         • Live streaming ticks
  • option_chain(count=100)            • Real-time LTP & volume
         │                                       │
         ▼                                       ▼
┌─────────────────────────────────────────────────────────────────┐
│              KotakOptionForwardRunner (Strategy Layer)          │
│  1. Discovers contracts (Band 1 CE: ₹50–₹59.50 + Hedge: ~₹5.00) │
│  2. Evaluates entry conditions                                  │
│  3. Attaches contract-bound PremiumTrailingStop to short leg    │
│  4. Evaluates incoming ticks & ratchets stop down               │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                     Internal Paper Orders Only
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                   core.PaperBroker (Air-Gap)                    │
│  • Simulates fills crossing the bid/ask spread                  │
│  • Applies basis-point slippage model                           │
│  • Enforces official NSE lot sizes (NIFTY: 25 shares/lot)       │
│  • Computes statutory taxes: STT, Exchange, SEBI, GST, Stamp   │
└────────────────────────────────┬────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Post-Session Verification                    │
│  1. ReconciliationChecker: Audits balance sheet (±₹0.00 delta)  │
│  2. Binary SHA-256 Merkle tree over events and trades           │
│  3. Tamper-proof Run Dossier saved to `runs/forward/`           │
│  4. Raw 202-contract option chains saved to `runs/kotak_raw/`   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. What Is Real vs. What Is Simulated

| Component | Real (From Kotak Neo) | Simulated (In AdiTrader) |
|---|:---:|:---:|
| **Underlying Spot Price (NIFTY 50)** | **YES** | NO |
| **Available Option Expiries** | **YES** | NO |
| **100-Strike Option Chain** | **YES** | NO |
| **Live Option Quotes (LTP, Bid, Ask, OI, Vol)** | **YES** | NO |
| **Live Tick Stream (WebSocket SFeed)** | **YES** | NO |
| **Order Placement / Modification / Cancel** | **NO** | **YES** (Internal `PaperBroker`) |
| **Trade Fills & Execution Pricing** | **NO** | **YES** (Crossing live Bid/Ask + Slippage) |
| **Margin Requirement & Cash Balance** | **NO** | **YES** (Local Net Equity Ledger) |
| **Broker Account Balance** | **NO** | **YES** (Simulated Starting ₹1,000,000.00) |
| **Broker Order Book & Positions** | **NO** | **YES** (Isolated SQLite/In-Memory State) |

---

## 4. What This System Does NOT Do

> [!CAUTION]
> **CRITICAL ARCHITECTURAL AIR-GAP (ADR 002)**  
> This system does **NOT** place, modify, or cancel real live orders on your Kotak Neo trading account.

1. **No Live Order Routing**: The methods `place_order()`, `modify_order()`, and `cancel_order()` in [`KotakNeoAdapter`](file:///home/aditya/Documents/coding/AdiTrader/src/aditrader/data/adapters/kotak_neo.py) and [`AbstractBrokerAdapter`](file:///home/aditya/Documents/coding/AdiTrader/src/aditrader/data/adapters/base.py) are physically blocked with unconditional `NotImplementedError` security vetoes.
2. **No Real Funds at Risk**: The starting capital (default ₹1,000,000.00) is entirely virtual. Fills occur in memory inside [`PaperBroker`](file:///home/aditya/Documents/coding/AdiTrader/src/aditrader/core/broker.py).
3. **No Synthetic Price Fabrication (ADR 011)**: While execution is simulated, market quotes are **never** invented using Black-Scholes formulas. If a contract has no live quote, the system refuses to guess prices and fails closed.

---

## 5. Timeline of a Trading Session

### Phase 1: Pre-Market (Before 09:15:00 IST)
- If you start the runner before 09:15:00 IST (e.g. at 09:05 IST):
  - The runner authenticates with Kotak Neo and verifies credentials.
  - It detects `now_ist < 09:15:00` and enters a countdown wait state:
    ```
    Pre-market state detected (09:05:00 IST). Waiting 600.0 seconds until 09:15:00 IST open...
    ```
  - It safely sleeps in 1-second intervals until 09:15:00 IST.
  - *(To bypass this waiting period during testing or after hours, pass `--no-wait`).*

### Phase 2: Session Open & Contract Selection (09:15:00 IST)
At exactly 09:15:00 IST, the runner coordinates session startup:
1. **Expiry Discovery**: Calls `chain_manager.fetch_expiries("NIFTY")`. Selects the nearest active expiry (e.g. `2026-09-24`) or the date specified in `--expiry`.
2. **Option Chain Pull**: Calls Kotak Neo REST endpoint `option_chain(count=100)` to fetch 50 strikes above and 50 strikes below ATM.
3. **Raw Capture #1 (DISCOVERY)**: Saves the complete 100-strike option chain JSON to `runs/kotak_raw/` with a SHA-256 digest.
4. **Data Quality Audit**: Verifies that the chain has non-zero quotes, valid strikes, and consistent timestamps. If corrupted, it fails closed immediately.
5. **Contract Selection**:
   - **Short Leg**: Scans Call (CE) options for a strike whose LTP falls inside **Band 1** (₹50.00–₹59.50). If multiple strikes qualify, it picks the strike closest to ₹54.75.
   - **Hedge Leg**: Independently scans all CE options for a cheap ratio hedge priced near **₹5.00** (allowed range: ₹3.00–₹7.00). If multiple qualify, it picks the one closest to ₹5.00, tie-breaking by higher strike (further OTM).
6. **Token Registration**: Registers the numeric exchange tokens of both contracts (e.g. `71472`) with `KotakNeoAdapter` so WebSocket packets map to canonical symbols.

### Phase 3: Paper Position Entry
1. **Lot Sizing**:
   - Short Leg: 1 lot = **25 shares** (`OrderSide.SELL`).
   - Hedge Leg: 4 lots = **100 shares** (`OrderSide.BUY`).
2. **Execution Simulation**:
   - Short Leg: Submits market SELL order. Fills at best **`bid`** quote (e.g. ₹54.80) or `ltp * (1 - slippage)`.
   - Hedge Leg: Submits market BUY order. Fills at best **`ask`** quote (e.g. ₹5.20) or `ltp * (1 + slippage)`.
3. **Trailing Stop Initialization**:
   - Attaches a `PremiumTrailingStop` to the **short leg only** (`initial_gap=5.0`, `trail_step=5.0`, `ratchet=True`).
   - The hedge leg has **zero** trailing stop attached (it remains open until group exit).
4. **Raw Capture #2 (POSITION_OPENED)**: Saves full option chain and trade snapshot to `runs/kotak_raw/`.

### Phase 4: Intraday Ingestion & Monitoring (09:15 to 15:15 IST)
1. **Tick Streaming**: Kotak Neo `SFeedWebSocket` streams live market ticks for the short CE, hedge CE, and NIFTY spot into an internal queue.
2. **Trailing Ratchet State Machine**:
   - Every tick on the short CE updates the trailing stop.
   - If the premium drops favorably, the stop ratchets down.
3. **Quote Freshness Monitor**:
   - If no ticks arrive for >120 seconds, the runner logs a warning and marks `DATA_FEED_DEGRADED`.
   - When ticks resume, it emits `FEED_RECOVERED`.
4. **Periodic Raw Captures**: Every 300 seconds (5 minutes), the runner saves the current chain state to `runs/kotak_raw/`.

### Phase 5: Group Exit & Square-Off
An exit is triggered under any of the following conditions:
1. **Trailing Stop Hit**: The short CE premium spikes up to or above the ratcheted stop price.
2. **15:15 IST Intraday Square-Off**: The session reaches 15:15:00 IST. Both legs are squared off automatically.
3. **Session Close (15:30 IST)**: Market closes at 15:30:00 IST.
4. **Duration Reached**: If `--duration <sec>` was provided and time expires.
5. **User Interrupt (Ctrl+C)**: Handled cleanly; forces immediate paper square-off before shutdown.

When an exit triggers:
- **Simultaneous Close**: Both the short CE (buy to close) and hedge CE (sell to close) are filled in `PaperBroker` crossing the bid/ask spread.
- **Active Group Reset**: `self._active_group` is cleared, preventing stale ticks from routing to closed trades.
- **Raw Capture #3 (POSITION_CLOSED)**: Saves exit prices, P&L, and full chain state to `runs/kotak_raw/`.

### Phase 6: Post-Session Audit & Sealing
1. **Reconciliation Audit**: Checks that $\text{Starting Capital} + \text{Realized P\&L} - \text{Charges} == \text{Ending Equity} \pm ₹0.01$.
2. **Cryptographic Merkle Sealing**: Calculates binary SHA-256 Merkle roots over all discrete execution events and executed trades.
3. **Sealed Run Dossier**: Persists the complete run dossier to `runs/forward/forward_dossier_<run_id>.json`.

---

## 6. How the Trailing Ratchet Works (Numerical Example)

The short leg sells a call option. When you are short an option, **lower prices are profitable**, while higher prices represent a loss.

| Step | Short CE Market Price | Favorable Drop From Entry | Ratchet Steps ($\lfloor \Delta / 5.0 \rfloor$) | Ratcheted Stop Loss (SL) | Status / Action |
|:---:|:---:|:---:|:---:|:---:|---|
| **Entry** | **₹50.00** | ₹0.00 | 0 | **₹55.00** | Initial SL set at $\text{Entry} + \text{Gap}$ ($50 + 5$) |
| 1 | ₹48.00 | ₹2.00 | 0 | ₹55.00 | Favorable drop < step (5.0); SL stays at 55.00 |
| 2 | **₹40.00** | **₹10.00** | **2** | **₹45.00** | **RATCHET DOWN**: SL drops from 55.00 to 45.00 |
| 3 | ₹43.00 | ₹7.00 | — | ₹45.00 | Adverse bounce; ratchet **NEVER** loosens |
| 4 | **₹30.00** | **₹20.00** | **4** | **₹35.00** | **RATCHET DOWN**: SL drops from 45.00 to 35.00 |
| 5 | ₹32.00 | ₹18.00 | — | ₹35.00 | Stop remains locked at 35.00 |
| 6 | **₹35.00** | — | — | **TRIGGERED** | **STOP HIT**: Tick price reaches SL (35.00 >= 35.00). Coordinated exit of both legs triggered immediately! |

---

## 7. Exact CLI Commands (From Current Code)

### 1. Real Kotak Neo Forward-Shadow Session (Standard 09:15 Run)
```bash
aditrader forward-options --strategy tpl-nifty-ce-premium-ladder-v1
```
- Waits for 09:15 IST automatically.
- Connects to your real Kotak Neo account for market data.
- Executes 100% paper fills inside local `PaperBroker`.
- Squares off automatically at 15:15 IST.
- Saves sealed Run Dossier to `runs/forward/`.

### 2. Offline Mock Rehearsal (Run Anytime, 24/7)
```bash
aditrader forward-options --mock --duration 10.0 --no-wait
```
- Bypasses Kotak API authentication (no credentials required).
- Generates a synthetic 100-strike option chain with realistic LTP and moneyness.
- Injects mock ticks to verify trailing ratchet and group exit.
- Runs for 10 seconds and seals a complete Run Dossier.

### 3. Run Specific Premium Band or Expiry
```bash
# Trade Band 2 (₹60.00–₹69.50) instead of Band 1:
aditrader forward-options --band 1

# Specify an explicit expiry date (YYYY-MM-DD):
aditrader forward-options --expiry 2026-09-24

# Set initial paper capital and slippage:
aditrader forward-options --capital 2000000 --slippage-bps 2.5
```

### 4. Check System & Credential Health (`doctor`)
```bash
aditrader doctor
```
- Checks Python runtime (>= 3.11).
- Checks core library dependencies.
- Tests directory writeability (`runs/`, `data/cache/`).
- Verifies database connectivity.
- Checks if Kotak Neo consumer key is configured in `.env`.

### 5. Check System State & Registered Templates (`status`)
```bash
aditrader status
```
- Displays current environment, timezone, and database URL.
- Reports database table counts (`orders`, `trades`, `positions`).
- Lists all registered institutional strategy templates.

### 6. Inspect Completed Runs via Web Dashboard
```bash
aditrader dashboard --serve --port 8050
```
- Opens interactive web dashboard at `http://127.0.0.1:8050`.
- Navigate to the **Runs** tab to view:
  - Itemized Trade Ledger with fee attribution.
  - Chronological Event Timeline.
  - Balance Sheet Invariant Verification Audit.
  - One-click bit-for-bit Recalculation Audit.
  - Cryptographic Merkle tree roots and raw JSON export.

---

## 8. Where Files & Outputs Are Saved

| Item | Directory / File Path | Description |
|---|---|---|
| **Sealed Run Dossiers** | `runs/forward/forward_dossier_<run_id>.json` | Complete cryptographic session report with Merkle roots, ledger, events, and balance sheet audit |
| **Raw Option Chain Snapshots** | `runs/kotak_raw/raw_option_chain_NIFTY_<expiry>_<trigger>_<ts>.json` | Full 202-contract option chains captured at DISCOVERY, ENTRY, EXIT, and every 5 minutes |
| **Transactional Database** | `runs/aditrader.db` | Local SQLite database recording orders, trades, and position history |
| **Scrip Master Cache** | `data/cache/*.parquet` | Cached broker scrip master for fast offline instrument search |

---

## 9. Understanding the Balance Sheet Audit in the Dossier

At the conclusion of each session, AdiTrader executes an institutional balance sheet audit:

$$\text{Ending Equity} = \text{Starting Capital} + \text{Realized P\&L} + \text{Unrealized P\&L} - \text{Total Charges}$$

Inside the sealed dossier (`runs/forward/*.json`), look at the `"reconciliation"` block:
```json
"reconciliation": {
  "is_reconciled": true,
  "starting_capital": 1000000.0,
  "ending_equity": 1000161.47,
  "total_realized_pnl": 260.0,
  "total_unrealized_pnl": 0.0,
  "total_charges": 98.53,
  "equity_discrepancy": 0.0,
  "details": "Balance sheet perfectly reconciled: Expected ₹1000161.47 == Observed ₹1000161.47 (realized: ₹260.00, unrealized: ₹0.00, charges: ₹98.53, equity_delta: ₹0.00)"
}
```
- **`is_reconciled: true`**: Confirms all cash, position values, and statutory taxes balance to the exact paisa (₹0.00 discrepancy).
- **`total_charges`**: Combines STT (0.1% on options sell turnover), NSE turnover charges, SEBI charges, Stamp Duty, and 18% GST.

---

## 10. Operator Checklists

### Before Starting a Live Session (Pre-Market)
1. [ ] **Verify `.env` Credentials**: Ensure all required Kotak Neo parameters are populated in `/home/aditya/Documents/coding/AdiTrader/.env`:
   ```bash
   KOTAK_CONSUMER_KEY="your_app_consumer_key"
   KOTAK_CONSUMER_SECRET="your_app_consumer_secret"
   KOTAK_MOBILE_NUMBER="your_mobile_number"
   KOTAK_UCC="your_ucc_id"
   KOTAK_PASSWORD="your_password"
   KOTAK_MPIN="your_mpin"
   KOTAK_TOTP_SECRET="your_totp_secret_base32"
   ```
2. [ ] **Run Doctor Check**:
   ```bash
   aditrader doctor
   ```
   Confirm that Core Dependencies, Storage Directories, and Broker Feed report `[READY]`.
3. [ ] **Run Quick Mock Sanity Rehearsal**:
   ```bash
   aditrader forward-options --mock --duration 5.0 --no-wait
   ```
   Verify that mock execution completes and outputs a sealed dossier with `is_reconciled: True`.
4. [ ] **Launch Live Session by 09:10 IST**:
   ```bash
   aditrader forward-options --strategy tpl-nifty-ce-premium-ladder-v1
   ```
   Let the runner sit in the pre-market countdown until 09:15:00 IST.

### After the Session (Post-Market)
1. [ ] **Verify Clean Session Conclusion**: Ensure the terminal displays:
   ```
   [SUCCESS] Forward shadow session concluded cleanly.
   Sealed Dossier: runs/forward/forward_dossier_fwd_opt_xxxx.json
   ```
2. [ ] **Check Dossier Reconciliation**: Open the dossier JSON or launch the dashboard:
   ```bash
   aditrader dashboard --serve --port 8050
   ```
   In the **Runs** tab, verify `Balance Sheet Reconciled: True` with `equity_delta: ₹0.00`.
3. [ ] **Inspect Raw Captures**: Check `ls -la runs/kotak_raw/` to ensure at least 3–4 raw option-chain snapshots were saved with valid SHA-256 hashes.

---

## 11. Common Warnings, Errors & Troubleshooting

| Error / Warning | What It Means | How to Fix |
|---|---|---|
| `REAL_KOTAK_AUTHENTICATION_FAILED: Incomplete Kotak Neo credentials` | One or more required fields (`consumer_key`, `mobile_number`, `ucc/password`) are missing from `.env`. | Add the credentials to `.env`. For testing without credentials, pass `--mock`. |
| `Kotak Neo live authentication failed: Invalid TOTP` | The TOTP code generated from `KOTAK_TOTP_SECRET` was rejected, or `KOTAK_TOTP_SECRET` is missing/out of sync. | Verify system clock synchronization and check that your Base32 TOTP secret is correct. |
| `DATA_FEED_DEGRADED: no ticks received for 120.0s` | The WebSocket connection is active, but Kotak Neo has stopped sending tick packets for over 2 minutes. | Normal during illiquid pre-market or exchange holidays. If during market hours, check internet connectivity. The system will auto-recover when ticks resume. |
| `Option chain data quality check FAILED` | The option chain returned by Kotak Neo contained crossed quotes, negative LTPs, or zero strikes. | The runner fails closed per institutional policy. Check if the underlying or expiry is trading. |
| `NoEligibleOptionContractError: Contract selection failed` | No strike in the 100-strike chain fell within the configured premium band (₹50–₹59.50) or no hedge was found near ₹5. | Run with `--band <index>` to select a different band (e.g. `--band 1` for ₹60–₹69.50), or check if market IV shifted significantly. |

---

## 12. Known Caveats / Things To Verify

1. **TOTP Secret and MPIN are Required for Automated Login**:
   - The official Kotak Neo SDK v3.0.6 requires both a valid 6-digit TOTP and a 6-digit MPIN.
   - You **must** define `KOTAK_TOTP_SECRET` and `KOTAK_MPIN` in `.env` for unattended headless execution. Without `KOTAK_TOTP_SECRET`, the login flow cannot generate TOTP codes automatically.
2. **`forward-test` vs. `forward-options` Flag Divergence**:
   - `aditrader forward-test` auto-routes options strategies to `forward-options`, **but** `forward-test` does not have `--band`, `--expiry`, `--no-wait`, or `--snapshot-interval` in its argument parser.
   - If you need any of these flags, **always run `aditrader forward-options` directly**.
3. **`aditrader dashboard` Requires `--serve`**:
   - Running `aditrader dashboard` without `--serve` will only display endpoint information and immediately exit. To start the actual web server, you must provide `--serve` (e.g. `aditrader dashboard --serve`).
4. **Thursday Expiry Day Handling**:
   - If `--expiry` is omitted, the code selects `expiries[0]`, which is the earliest active expiry date.
   - On Thursday mornings, `expiries[0]` is today's expiry. If you intend to trade the *next* week's contract on expiry day to avoid same-day 0-DTE gamma decay, explicitly pass `--expiry YYYY-MM-DD`.
5. **Terminal Logging**:
   - Detailed execution events and ticks are emitted via Python's standard `logging` module under `aditrader.data.forward_options_runner`.
   - If you want full debug output in the terminal, set `LOG_LEVEL=DEBUG` in `.env`.
