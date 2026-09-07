"""Embedded responsive HTML, CSS, and JS single-page interface for AdiTrader Web Dashboard.

Strictly follows DESIGN_LANGUAGE.md:
- Technical dark theme (#0E1117 background, #161B22 surface, #30363D border).
- Color semantics (#2EA043 green, #DA3633 red, #58A6FF blue, #D29922 amber).
- Typography (JetBrains Mono / monospace for numbers/tables; Inter / sans-serif for UI).
- Touch-target accessibility (>= 44px) and responsive mobile viewport.
- Strictly read-only research workstation (ADR 002 physical air-gap).
"""

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=5.0, user-scalable=yes">
  <title>AdiTrader / QuantumValidator — Quantitative Research & Paper Workstation</title>
  <style>
    :root {
      --bg: #0E1117;
      --surface: #161B22;
      --surface-hover: #21262D;
      --border: #30363D;
      --border-bright: #484F58;
      --text: #C9D1D9;
      --text-muted: #8B949E;
      --text-bright: #F0F6FC;
      --green: #2EA043;
      --green-bg: rgba(46, 160, 67, 0.15);
      --red: #DA3633;
      --red-bg: rgba(218, 54, 51, 0.15);
      --blue: #58A6FF;
      --blue-bg: rgba(88, 166, 255, 0.15);
      --amber: #D29922;
      --amber-bg: rgba(210, 153, 34, 0.15);
      --font-sans: system-ui, -apple-system, 'Inter', 'Segoe UI', Roboto, sans-serif;
      --font-mono: ui-monospace, 'JetBrains Mono', 'Fira Code', 'Courier New', monospace;
    }

    * { box-sizing: border-box; margin: 0; padding: 0; }

    body {
      background-color: var(--bg);
      color: var(--text);
      font-family: var(--font-sans);
      line-height: 1.5;
      -webkit-font-smoothing: antialiased;
      padding-bottom: 40px;
    }

    /* Top Navigation / App Header */
    header {
      background-color: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 12px 20px;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      position: sticky;
      top: 0;
      z-index: 100;
    }

    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .brand-title {
      font-size: 1.1rem;
      font-weight: 700;
      color: var(--text-bright);
      letter-spacing: -0.02em;
    }

    .brand-subtitle {
      font-size: 0.75rem;
      color: var(--text-muted);
      font-family: var(--font-mono);
      background: var(--surface-hover);
      padding: 2px 6px;
      border-radius: 4px;
      border: 1px solid var(--border);
    }

    .status-strip {
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      font-family: var(--font-mono);
      font-size: 0.75rem;
      font-weight: 600;
      padding: 4px 10px;
      border-radius: 9999px;
      border: 1px solid transparent;
      min-height: 28px;
    }

    .badge-live {
      background: var(--green-bg);
      color: var(--green);
      border-color: var(--green);
    }

    .badge-sim {
      background: var(--amber-bg);
      color: var(--amber);
      border-color: var(--amber);
    }

    .badge-paper {
      background: var(--blue-bg);
      color: var(--blue);
      border-color: var(--blue);
    }

    .badge-alert {
      background: var(--red-bg);
      color: var(--red);
      border-color: var(--red);
    }

    .pulse-dot {
      width: 8px;
      height: 8px;
      border-radius: 50%;
      background-color: currentColor;
      animation: pulse 2s infinite ease-in-out;
    }

    @keyframes pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.4; transform: scale(0.8); }
    }

    /* Navigation Tabs */
    nav {
      display: flex;
      background: var(--surface);
      border-bottom: 1px solid var(--border);
      padding: 0 20px;
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }

    .tab-btn {
      background: none;
      border: none;
      color: var(--text-muted);
      font-family: var(--font-sans);
      font-size: 0.88rem;
      font-weight: 500;
      padding: 12px 16px;
      cursor: pointer;
      border-bottom: 2px solid transparent;
      white-space: nowrap;
      min-height: 44px;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: color 0.15s, border-color 0.15s;
    }

    .tab-btn:hover {
      color: var(--text-bright);
    }

    .tab-btn.active {
      color: var(--blue);
      border-bottom-color: var(--blue);
      font-weight: 600;
    }

    /* Main Container */
    main {
      max-width: 1400px;
      margin: 0 auto;
      padding: 20px;
    }

    .tab-pane {
      display: none;
    }

    .tab-pane.active {
      display: block;
    }

    /* Responsive Grid Layouts */
    .metric-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 24px;
    }

    .card {
      background-color: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 16px;
      box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
    }

    .card-title {
      font-size: 0.78rem;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 6px;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .metric-val {
      font-family: var(--font-mono);
      font-size: 1.5rem;
      font-weight: 700;
      color: var(--text-bright);
    }

    .metric-val.positive { color: var(--green); }
    .metric-val.negative { color: var(--red); }
    .metric-val.neutral { color: var(--blue); }

    .metric-sub {
      font-size: 0.75rem;
      color: var(--text-muted);
      margin-top: 4px;
      font-family: var(--font-mono);
    }

    /* Section Cards */
    .section-card {
      background-color: var(--surface);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 20px;
      margin-bottom: 20px;
    }

    .section-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
      padding-bottom: 10px;
      border-bottom: 1px solid var(--border);
    }

    .section-heading {
      font-size: 1.05rem;
      font-weight: 600;
      color: var(--text-bright);
    }

    /* Tables */
    .table-container {
      width: 100%;
      overflow-x: auto;
      -webkit-overflow-scrolling: touch;
    }

    table {
      width: 100%;
      border-collapse: collapse;
      text-align: left;
      font-size: 0.85rem;
    }

    th {
      background-color: var(--surface-hover);
      color: var(--text-muted);
      font-weight: 600;
      text-transform: uppercase;
      font-size: 0.72rem;
      letter-spacing: 0.04em;
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }

    td {
      padding: 10px 12px;
      border-bottom: 1px solid var(--border);
      color: var(--text);
      white-space: nowrap;
    }

    tr:last-child td {
      border-bottom: none;
    }

    tr:hover td {
      background-color: rgba(255, 255, 255, 0.02);
    }

    .mono {
      font-family: var(--font-mono);
    }

    /* Buttons & Inputs */
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
      padding: 8px 16px;
      border-radius: 6px;
      font-size: 0.85rem;
      font-weight: 600;
      font-family: var(--font-sans);
      cursor: pointer;
      min-height: 44px;
      min-width: 44px;
      border: 1px solid transparent;
      transition: all 0.15s;
    }

    .btn-primary {
      background-color: var(--blue);
      color: #0E1117;
      border-color: var(--blue);
    }

    .btn-primary:hover {
      background-color: #79B8FF;
    }

    .btn-outline {
      background-color: transparent;
      color: var(--text);
      border-color: var(--border);
    }

    .btn-outline:hover {
      background-color: var(--surface-hover);
      border-color: var(--border-bright);
    }

    .input-group {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-bottom: 16px;
    }

    input[type="text"] {
      flex: 1;
      min-width: 250px;
      min-height: 44px;
      background-color: var(--bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      color: var(--text-bright);
      padding: 8px 14px;
      font-family: var(--font-mono);
      font-size: 0.85rem;
    }

    input[type="text"]:focus {
      outline: none;
      border-color: var(--blue);
    }

    /* Preformatted Code & AST Viewer */
    pre.code-block {
      background-color: var(--bg);
      border: 1px solid var(--border);
      border-radius: 6px;
      padding: 12px;
      font-family: var(--font-mono);
      font-size: 0.8rem;
      overflow-x: auto;
      color: var(--text);
      max-height: 380px;
      white-space: pre-wrap;
      word-break: break-all;
    }

    /* Notice Banner */
    .air-gap-banner {
      background: rgba(88, 166, 255, 0.08);
      border: 1px solid rgba(88, 166, 255, 0.25);
      border-radius: 6px;
      padding: 10px 14px;
      font-size: 0.8rem;
      margin-bottom: 20px;
      display: flex;
      align-items: center;
      gap: 10px;
      color: var(--text-bright);
    }

    .air-gap-banner strong {
      color: var(--blue);
    }

    /* Modal dialog */
    .modal-backdrop {
      display: none;
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(0, 0, 0, 0.7);
      backdrop-filter: blur(2px);
      z-index: 1000;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }

    .modal-backdrop.active {
      display: flex;
    }

    .modal {
      background: var(--surface);
      border: 1px solid var(--border-bright);
      border-radius: 8px;
      max-width: 750px;
      width: 100%;
      max-height: 85vh;
      overflow-y: auto;
      padding: 20px;
    }

    .modal-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 16px;
    }

    .modal-close {
      background: none;
      border: none;
      color: var(--text-muted);
      font-size: 1.5rem;
      cursor: pointer;
      padding: 4px 8px;
      min-width: 44px;
      min-height: 44px;
    }

    /* Mobile Adaptations */
    @media (max-width: 768px) {
      header {
        padding: 10px 14px;
      }
      main {
        padding: 12px;
      }
      .metric-grid {
        grid-template-columns: 1fr;
      }
      .section-card {
        padding: 14px;
      }
      .tab-btn {
        padding: 10px 12px;
        font-size: 0.82rem;
      }
    }
  </style>
</head>
<body>

  <!-- Top Header -->
  <header>
    <div class="brand">
      <div class="brand-title">AdiTrader</div>
      <div class="brand-subtitle">QuantumValidator v1.0</div>
    </div>
    <div class="status-strip" id="status-badges">
      <span class="badge badge-paper"><span class="pulse-dot"></span> PAPER BROKER</span>
      <span class="badge badge-sim" id="feed-badge">CHECKING FEED...</span>
      <span class="badge badge-live" id="db-badge">SQLITE DB</span>
    </div>
  </header>

  <!-- Navigation Bar -->
  <nav>
    <button class="tab-btn active" onclick="switchTab('portfolio')">📊 Portfolio & Status</button>
    <button class="tab-btn" onclick="switchTab('strategies')">📜 Strategy Catalog</button>
    <button class="tab-btn" onclick="switchTab('runs')">📁 Run History & Research</button>
    <button class="tab-btn" onclick="switchTab('inspect')">🔍 Dataset Inspector</button>
  </nav>

  <!-- Main Workstation -->
  <main>

    <!-- Air Gap Safety Notice -->
    <div class="air-gap-banner">
      <span style="font-size: 1.2rem;">🛡️</span>
      <div>
        <strong>ADR 002 Air-Gapped Simulation Active:</strong>
        All orders route strictly into local PaperBroker. Real live broker execution is physically disabled.
      </div>
    </div>

    <!-- 1. Portfolio & Status Tab -->
    <div id="tab-portfolio" class="tab-pane active">
      <div class="metric-grid">
        <div class="card">
          <div class="card-title">Total Capital</div>
          <div class="metric-val mono" id="m-capital">₹1,000,000.00</div>
          <div class="metric-sub" id="m-available">Avail: ₹1,000,000.00</div>
        </div>
        <div class="card">
          <div class="card-title">Realized P&L</div>
          <div class="metric-val mono" id="m-realized">₹0.00</div>
          <div class="metric-sub" id="m-trades-count">0 paper trades</div>
        </div>
        <div class="card">
          <div class="card-title">Unrealized P&L</div>
          <div class="metric-val mono" id="m-unrealized">₹0.00</div>
          <div class="metric-sub" id="m-positions-count">0 open positions</div>
        </div>
        <div class="card">
          <div class="card-title">Margin Utilization</div>
          <div class="metric-val mono neutral" id="m-margin-pct">0.0%</div>
          <div class="metric-sub" id="m-blocked">Blocked: ₹0.00</div>
        </div>
      </div>

      <!-- Active Positions Card -->
      <div class="section-card">
        <div class="section-header">
          <div class="section-heading">Active Paper Positions</div>
          <button class="btn btn-outline" onclick="loadStatus()">↻ Refresh</button>
        </div>
        <div class="table-container">
          <table id="positions-table">
            <thead>
              <tr>
                <th>Symbol</th>
                <th>Quantity</th>
                <th>Avg Price</th>
                <th>Current Price</th>
                <th>Unrealized P&L</th>
                <th>Side</th>
              </tr>
            </thead>
            <tbody id="positions-body">
              <tr><td colspan="6" style="text-align: center; color: var(--text-muted);">No open paper positions</td></tr>
            </tbody>
          </table>
        </div>
      </div>

      <!-- Recent Paper Trades Card -->
      <div class="section-card">
        <div class="section-header">
          <div class="section-heading">Recent Paper Fills</div>
        </div>
        <div class="table-container">
          <table id="trades-table">
            <thead>
              <tr>
                <th>Time (IST)</th>
                <th>Trade ID</th>
                <th>Symbol</th>
                <th>Side</th>
                <th>Quantity</th>
                <th>Fill Price</th>
                <th>Slippage</th>
                <th>Charges & STT</th>
              </tr>
            </thead>
            <tbody id="trades-body">
              <tr><td colspan="8" style="text-align: center; color: var(--text-muted);">No paper fills recorded yet</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- 2. Strategy Catalog Tab -->
    <div id="tab-strategies" class="tab-pane">
      <div class="section-card">
        <div class="section-header">
          <div class="section-heading">Version-Controlled Built-in Strategies</div>
          <div style="font-size: 0.8rem; color: var(--text-muted);">Institutional AST Rules</div>
        </div>
        <div class="table-container">
          <table id="strategies-table">
            <thead>
              <tr>
                <th>Name / ID</th>
                <th>Underlying</th>
                <th>Timeframe</th>
                <th>Strategy DNA</th>
                <th>Institutional Policy</th>
                <th>Action</th>
              </tr>
            </thead>
            <tbody id="strategies-body">
              <tr><td colspan="6" style="text-align: center;">Loading strategy library...</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- 3. Run History Tab -->
    <div id="tab-runs" class="tab-pane">
      <div class="section-card">
        <div class="section-header">
          <div class="section-heading">Forward-Test & Backtest Dossiers</div>
          <button class="btn btn-outline" onclick="loadRuns()">↻ Reload Runs</button>
        </div>
        <div class="table-container">
          <table id="runs-table">
            <thead>
              <tr>
                <th>Session ID</th>
                <th>Strategy</th>
                <th>Symbol</th>
                <th>Status</th>
                <th>Realized P&L</th>
                <th>Trades</th>
                <th>Bars</th>
                <th>Dossier</th>
              </tr>
            </thead>
            <tbody id="runs-body">
              <tr><td colspan="8" style="text-align: center;">Scanning runs/ directory...</td></tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- 4. Dataset Inspector Tab -->
    <div id="tab-inspect" class="tab-pane">
      <div class="section-card">
        <div class="section-header">
          <div class="section-heading">Inspect CSV Market Dataset</div>
        </div>
        <p style="font-size: 0.85rem; color: var(--text-muted); margin-bottom: 14px;">
          Detects NSE Intraday 1m/5m, Bhavcopy (CM/FO), and Index historical schemas. Verifies price envelopes, dates, and missing quotes before running simulations.
        </p>
        <div class="input-group">
          <input type="text" id="inspect-path" placeholder="Path to CSV (e.g. data/nifty_sample.csv)">
          <button class="btn btn-primary" onclick="inspectDataset()">Inspect Dataset</button>
        </div>
        <div id="inspect-results" style="display: none;">
          <div class="metric-grid" style="margin-top: 20px;">
            <div class="card">
              <div class="card-title">Detected Format</div>
              <div class="metric-val mono neutral" id="ins-format">-</div>
            </div>
            <div class="card">
              <div class="card-title">Parsed Bars</div>
              <div class="metric-val mono" id="ins-bars">0</div>
            </div>
            <div class="card">
              <div class="card-title">Timeframe</div>
              <div class="metric-val mono" id="ins-tf">-</div>
            </div>
            <div class="card">
              <div class="card-title">Replay Readiness</div>
              <div class="metric-val mono" id="ins-ready">-</div>
            </div>
          </div>
          <div class="section-card" style="margin-top: 14px;">
            <div class="section-heading" style="font-size: 0.9rem; margin-bottom: 8px;">Inspection Details & Warnings</div>
            <pre class="code-block" id="ins-details"></pre>
          </div>
        </div>
      </div>
    </div>

  </main>

  <!-- AST Detail Modal -->
  <div class="modal-backdrop" id="ast-modal">
    <div class="modal">
      <div class="modal-header">
        <h3 style="color: var(--text-bright);" id="modal-title">Strategy AST</h3>
        <button class="modal-close" onclick="closeModal()">✕</button>
      </div>
      <pre class="code-block" id="modal-content"></pre>
    </div>
  </div>

  <script>
    // State
    let currentStatus = null;
    let registeredStrategies = [];

    // Tab Navigation
    function switchTab(tabId) {
      document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
      document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
      const targetBtn = Array.from(document.querySelectorAll('.tab-btn')).find(b => b.getAttribute('onclick').includes(tabId));
      if (targetBtn) targetBtn.classList.add('active');
      const targetPane = document.getElementById('tab-' + tabId);
      if (targetPane) targetPane.classList.add('active');

      if (tabId === 'strategies' && registeredStrategies.length === 0) loadStrategies();
      if (tabId === 'runs') loadRuns();
    }

    // Currency Formatter
    function formatINR(val) {
      if (val === null || val === undefined) return '₹0.00';
      const num = Number(val);
      const sign = num < 0 ? '-' : '';
      const absVal = Math.abs(num).toFixed(2);
      const parts = absVal.split('.');
      let integer = parts[0];
      const decimal = parts[1];
      const lastThree = integer.substring(integer.length - 3);
      const otherNumbers = integer.substring(0, integer.length - 3);
      if (otherNumbers !== '') {
        integer = otherNumbers.replace(/\\B(?=(\\d{2})+(?!\\d))/g, ",") + "," + lastThree;
      } else {
        integer = lastThree;
      }
      return sign + '₹' + integer + '.' + decimal;
    }

    // Load System & Portfolio Status
    async function loadStatus() {
      try {
        const res = await fetch('/api/status');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const data = await res.json();
        currentStatus = data;

        // Feed Badge
        const feedBadge = document.getElementById('feed-badge');
        const feedStatus = data.kotak_neo ? data.kotak_neo.feed_status : 'SIMULATED_REHEARSAL';
        feedBadge.textContent = feedStatus;
        feedBadge.className = 'badge';
        if (feedStatus === 'LIVE_CONNECTED') feedBadge.classList.add('badge-live');
        else if (feedStatus === 'SIMULATED_REHEARSAL' || feedStatus === 'CSV_REPLAY') feedBadge.classList.add('badge-sim');
        else if (feedStatus === 'LIVE_CONNECTING') feedBadge.classList.add('badge-sim');
        else feedBadge.classList.add('badge-alert');

        // Metrics
        const port = data.paper_portfolio || {};
        document.getElementById('m-capital').textContent = formatINR(port.total_capital || 1000000);
        document.getElementById('m-available').textContent = 'Avail: ' + formatINR(port.current_cash || 1000000);

        const realElem = document.getElementById('m-realized');
        const realVal = port.realized_pnl || 0;
        realElem.textContent = formatINR(realVal);
        realElem.className = 'metric-val mono ' + (realVal > 0 ? 'positive' : realVal < 0 ? 'negative' : '');

        const unElem = document.getElementById('m-unrealized');
        const unVal = port.unrealized_pnl || 0;
        unElem.textContent = formatINR(unVal);
        unElem.className = 'metric-val mono ' + (unVal > 0 ? 'positive' : unVal < 0 ? 'negative' : '');

        const utilPct = ((port.margin_utilization || 0) * 100).toFixed(1);
        document.getElementById('m-margin-pct').textContent = utilPct + '%';

        // Positions Table
        const posBody = document.getElementById('positions-body');
        if (data.active_positions && data.active_positions.length > 0) {
          posBody.innerHTML = '';
          data.active_positions.forEach(p => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
              <td class="mono"><strong>\${p.symbol}</strong></td>
              <td class="mono">\${p.qty}</td>
              <td class="mono">\${formatINR(p.avg_price)}</td>
              <td class="mono">\${formatINR(p.current_price || p.avg_price)}</td>
              <td class="mono \${(p.unrealized_pnl || 0) >= 0 ? 'positive' : 'negative'}">\${formatINR(p.unrealized_pnl || 0)}</td>
              <td><span class="badge badge-paper">\${p.side || 'NET'}</span></td>
            `;
            posBody.appendChild(tr);
          });
        }

        // Trades Table
        const trdBody = document.getElementById('trades-body');
        if (data.recent_trades && data.recent_trades.length > 0) {
          trdBody.innerHTML = '';
          data.recent_trades.forEach(t => {
            const tr = document.createElement('tr');
            const totalFee = (t.stt || 0) + (t.charges || 0);
            tr.innerHTML = `
              <td class="mono">\${t.timestamp ? t.timestamp.substring(11, 19) : '-'}</td>
              <td class="mono">\${t.trade_id}</td>
              <td class="mono"><strong>\${t.symbol}</strong></td>
              <td><span class="badge \${t.side === 'BUY' ? 'badge-live' : 'badge-alert'}">\${t.side}</span></td>
              <td class="mono">\${t.qty}</td>
              <td class="mono">\${formatINR(t.fill_price)}</td>
              <td class="mono">\${formatINR(t.slippage)}</td>
              <td class="mono">\${formatINR(totalFee)}</td>
            `;
            trdBody.appendChild(tr);
          });
        }

      } catch (err) {
        console.error('Failed to load status:', err);
      }
    }

    // Load Strategies
    async function loadStrategies() {
      try {
        const res = await fetch('/api/strategies');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const list = await res.json();
        registeredStrategies = list;
        const body = document.getElementById('strategies-body');
        body.innerHTML = '';
        list.forEach((s, idx) => {
          const tr = document.createElement('tr');
          const dna = s.dna || {};
          const dnaTag = dna.delta_type ? `\${dna.delta_type} | Theta: \${dna.theta_bias || 'NEUTRAL'}` : 'Linear Rules';
          tr.innerHTML = `
            <td>
              <strong style="color: var(--text-bright);">\${s.name}</strong>
              <div style="font-size: 0.75rem; color: var(--text-muted);">\${s.id} (v\${s.version})</div>
            </td>
            <td class="mono">\${s.underlying}</td>
            <td class="mono">\${s.timeframe}</td>
            <td><span class="badge badge-sim">\${dnaTag}</span></td>
            <td><span class="badge badge-live">INSTITUTIONAL APPROVED</span></td>
            <td>
              <button class="btn btn-outline" style="min-height: 32px; padding: 4px 10px;" onclick="viewAst(\${idx})">Inspect AST</button>
            </td>
          `;
          body.appendChild(tr);
        });
      } catch (err) {
        console.error('Failed to load strategies:', err);
      }
    }

    function viewAst(idx) {
      const s = registeredStrategies[idx];
      if (!s) return;
      document.getElementById('modal-title').textContent = s.name + ' (AST JSON)';
      document.getElementById('modal-content').textContent = JSON.stringify(s.dsl || s, null, 2);
      document.getElementById('ast-modal').classList.add('active');
    }

    function closeModal() {
      document.getElementById('ast-modal').classList.remove('active');
    }

    // Load Runs
    async function loadRuns() {
      try {
        const res = await fetch('/api/runs');
        if (!res.ok) throw new Error('HTTP ' + res.status);
        const runs = await res.json();
        const body = document.getElementById('runs-body');
        body.innerHTML = '';
        if (runs.length === 0) {
          body.innerHTML = '<tr><td colspan="8" style="text-align: center; color: var(--text-muted);">No forward session dossiers recorded in runs/</td></tr>';
          return;
        }
        runs.forEach(r => {
          const tr = document.createElement('tr');
          const pnlVal = r.realized_pnl || 0;
          tr.innerHTML = `
            <td class="mono">\${r.session_id}</td>
            <td><strong>\${r.strategy}</strong></td>
            <td class="mono">\${r.symbol}</td>
            <td><span class="badge \${r.status === 'COMPLETED' ? 'badge-live' : 'badge-sim'}">\${r.status}</span></td>
            <td class="mono \${pnlVal >= 0 ? 'positive' : 'negative'}">\${formatINR(pnlVal)}</td>
            <td class="mono">\${r.trades_count}</td>
            <td class="mono">\${r.bars_count}</td>
            <td><a href="/api/runs/\${encodeURIComponent(r.session_id)}" target="_blank" style="color: var(--blue); text-decoration: none;">View JSON ↗</a></td>
          `;
          body.appendChild(tr);
        });
      } catch (err) {
        console.error('Failed to load runs:', err);
      }
    }

    // Inspect Dataset
    async function inspectDataset() {
      const pathInput = document.getElementById('inspect-path');
      const filePath = pathInput.value.trim();
      if (!filePath) {
        alert('Please enter a CSV file path.');
        return;
      }
      const resultsElem = document.getElementById('inspect-results');
      try {
        const res = await fetch('/api/inspect-data', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ file_path: filePath })
        });
        const rep = await res.json();
        if (!res.ok) {
          alert('Inspection error: ' + (rep.error || 'Failed'));
          return;
        }

        resultsElem.style.display = 'block';
        document.getElementById('ins-format').textContent = rep.detected_format;
        document.getElementById('ins-bars').textContent = rep.parsed_bars;
        document.getElementById('ins-tf').textContent = rep.timeframe_detected;
        const readyElem = document.getElementById('ins-ready');
        readyElem.textContent = rep.is_valid_replayable ? 'READY' : 'INVALID';
        readyElem.className = 'metric-val mono ' + (rep.is_valid_replayable ? 'positive' : 'negative');

        document.getElementById('ins-details').textContent = JSON.stringify(rep, null, 2);
      } catch (err) {
        alert('Failed to inspect dataset: ' + err.message);
      }
    }

    // Periodic Heartbeat Poll
    setInterval(loadStatus, 3000);
    window.addEventListener('DOMContentLoaded', () => {
      loadStatus();
    });
  </script>
</body>
</html>
"""
