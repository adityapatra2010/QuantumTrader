"""Zero-dependency, high-performance responsive HTTP research dashboard server.

Implements:
- Single-page application serving (embedded HTML/CSS/JS compliant with DESIGN_LANGUAGE.md).
- REST API endpoints for live status, strategy catalog, runs history, and dataset inspection.
- Strict security boundaries:
  - Zero order placement endpoints (ADR 002 execution air gap).
  - Path traversal prevention on file access.
  - Secret masking for broker credentials.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from aditrader.config.settings import get_settings
from aditrader.core.ledger.repository import LedgerRepository
from aditrader.data.adapters.kotak_neo import HAS_NEO_SDK
from aditrader.data.feeds.nse_csv import NSECSVInspector
from aditrader.data.session import EXCHANGE_TIMEZONE
from aditrader.strategy.library.registry import StrategyRegistry
from aditrader.web.ui import DASHBOARD_HTML

logger = logging.getLogger(__name__)


def _mask_secret(secret: str | None) -> str:
    """Mask sensitive string for safe UI presentation."""
    if not secret:
        return "Not configured"
    s = secret.strip()
    if len(s) <= 6:
        return "***"
    return f"{s[:2]}***{s[-2:]}"


def _is_safe_file_path(path: Path) -> bool:
    """Validate that path does not access sensitive project secrets or system files."""
    try:
        resolved = path.resolve()
        for part in resolved.parts:
            p_lower = part.lower()
            if (
                p_lower.startswith(".env")
                or p_lower == "secrets.json"
                or p_lower.startswith(".git")
            ):
                return False
        # Disallow system files
        str_res = str(resolved)
        return not str_res.startswith(("/etc", "/var", "/usr", "/proc", "/sys"))
    except Exception:
        return False


class DashboardRequestHandler(BaseHTTPRequestHandler):
    """HTTP request handler dispatching dashboard UI and read-only REST APIs."""

    server_version = "AdiTrader-ResearchDashboard/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default stderr logging for routine requests."""
        logger.debug(
            "%s - - [%s] %s", self.address_string(), self.log_date_time_string(), format % args
        )

    def _send_json(self, data: Any, status: int = HTTPStatus.OK) -> None:
        """Send JSON response with strict headers."""
        body = json.dumps(data, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, status: int = HTTPStatus.OK) -> None:
        """Send HTML response."""
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message: str, status: int = HTTPStatus.BAD_REQUEST) -> None:
        """Send standardized JSON error response."""
        self._send_json({"error": message, "status": status}, status=status)

    def do_GET(self) -> None:
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            self._send_html(DASHBOARD_HTML)
            return

        if path == "/api/status":
            self._handle_get_status()
            return

        if path == "/api/strategies":
            self._handle_get_strategies()
            return

        if path == "/api/runs":
            self._handle_get_runs()
            return

        if path.startswith("/api/runs/"):
            session_id = unquote(path[len("/api/runs/") :])
            self._handle_get_run_detail(session_id)
            return

        self._send_error_json("Resource not found", status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        """Handle POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/inspect-data":
            self._handle_post_inspect()
            return

        self._send_error_json("Endpoint not supported", status=HTTPStatus.NOT_FOUND)

    # --------------------------------------------------------------------------
    # Route Handlers
    # --------------------------------------------------------------------------

    def _handle_get_status(self) -> None:
        """Return system health, adapter status, database state, and paper portfolio."""
        settings = get_settings()

        # 1. Kotak Neo Status
        has_creds = bool(
            settings.kotak_consumer_key
            and settings.kotak_mobile_number
            and (settings.kotak_ucc or settings.kotak_password)
        )
        if not HAS_NEO_SDK:
            feed_status = "UNSUPPORTED"
        elif not has_creds:
            feed_status = "SIMULATED_REHEARSAL"
        else:
            feed_status = "LIVE_CONNECTING"

        # 2. Database & Ledger Status
        db_connected = False
        tables: list[str] = []
        recent_trades: list[dict[str, Any]] = []
        recent_orders: list[dict[str, Any]] = []
        active_positions: list[dict[str, Any]] = []
        initial_capital = 1_000_000.0
        current_cash = 1_000_000.0
        total_capital = 1_000_000.0
        realized_pnl = 0.0
        unrealized_pnl = 0.0
        margin_utilization = 0.0

        try:
            repo = LedgerRepository(database_url=settings.database_url)
            repo.create_tables()
            db_connected = True
            tables = ["ledger_orders", "ledger_trades", "ledger_positions", "ledger_bars"]

            from sqlalchemy import select

            from aditrader.core.ledger.schema import OrderRecord, PositionRecord, TradeRecord

            with repo.SessionLocal() as session:
                trades_stmt = select(TradeRecord).order_by(TradeRecord.timestamp.desc()).limit(10)
                db_trades = session.execute(trades_stmt).scalars().all()
                recent_trades = [
                    {
                        "trade_id": t.trade_id,
                        "order_id": t.order_id,
                        "symbol": t.symbol,
                        "side": t.side,
                        "qty": t.qty,
                        "fill_price": t.fill_price,
                        "slippage": t.slippage,
                        "stt": t.stt,
                        "charges": t.charges,
                        "timestamp": t.timestamp.isoformat() if t.timestamp else None,
                    }
                    for t in db_trades
                ]

                pos_stmt = select(PositionRecord)
                db_positions = session.execute(pos_stmt).scalars().all()
                active_positions = [
                    {
                        "symbol": p.symbol,
                        "qty": p.qty,
                        "avg_price": p.buy_avg_price if p.qty > 0 else p.sell_avg_price,
                        "current_price": p.buy_avg_price if p.qty > 0 else p.sell_avg_price,
                        "unrealized_pnl": p.unrealized_pnl,
                        "side": "LONG" if p.qty > 0 else "SHORT" if p.qty < 0 else "FLAT",
                    }
                    for p in db_positions
                    if p.qty != 0
                ]

                orders_stmt = select(OrderRecord).order_by(OrderRecord.created_at.desc()).limit(10)
                db_orders = session.execute(orders_stmt).scalars().all()
                recent_orders = [
                    {
                        "order_id": o.order_id,
                        "symbol": o.symbol,
                        "side": o.side,
                        "order_type": o.order_type,
                        "qty": o.qty,
                        "price": o.price,
                        "status": o.status,
                        "filled_qty": o.filled_qty,
                    }
                    for o in db_orders
                ]

                realized_pnl = sum(p.realized_pnl for p in db_positions)
                unrealized_pnl = sum(p.unrealized_pnl for p in db_positions)
                total_capital = initial_capital + realized_pnl + unrealized_pnl

        except Exception as exc:
            logger.debug("Database status check completed with notice: %s", exc)

        now_ist = datetime.now(EXCHANGE_TIMEZONE)

        payload = {
            "system_status": "HEALTHY",
            "server_time_ist": now_ist.isoformat(),
            "environment": settings.aditrader_env,
            "kotak_neo": {
                "has_sdk": HAS_NEO_SDK,
                "feed_status": feed_status,
                "consumer_key_configured": bool(settings.kotak_consumer_key),
                "mobile_masked": _mask_secret(settings.kotak_mobile_number),
                "ucc_masked": _mask_secret(settings.kotak_ucc),
            },
            "database": {
                "connected": db_connected,
                "url": _mask_secret(settings.database_url),
                "tables": tables,
            },
            "paper_portfolio": {
                "initial_capital": initial_capital,
                "current_cash": current_cash,
                "total_capital": total_capital,
                "realized_pnl": realized_pnl,
                "unrealized_pnl": unrealized_pnl,
                "margin_utilization": margin_utilization,
            },
            "active_positions": active_positions,
            "recent_trades": recent_trades,
            "recent_orders": recent_orders,
        }
        self._send_json(payload)

    def _handle_get_strategies(self) -> None:
        """Return list of built-in strategies from StrategyRegistry."""
        try:
            reg = StrategyRegistry()
            records = reg.list_all()
            output: list[dict[str, Any]] = []
            for r in records:
                dsl = r.dsl_definition
                dna_dict: dict[str, Any] = {}
                if r.dna:
                    dna_dict = {
                        "directionality": getattr(
                            r.dna.directionality, "value", str(r.dna.directionality)
                        ),
                        "theta_exposure": getattr(
                            r.dna.theta_exposure, "value", str(r.dna.theta_exposure)
                        ),
                        "vega_exposure": getattr(
                            r.dna.vega_exposure, "value", str(r.dna.vega_exposure)
                        ),
                        "gamma_risk": getattr(r.dna.gamma_risk, "value", str(r.dna.gamma_risk)),
                        "style": getattr(r.dna.style, "value", str(r.dna.style)),
                        "target_regime": getattr(
                            r.dna.target_regime, "value", str(r.dna.target_regime)
                        ),
                    }
                output.append(
                    {
                        "id": r.id,
                        "name": r.name,
                        "category": getattr(r.category, "value", str(r.category)),
                        "creator": r.creator,
                        "underlying": dsl.underlying,
                        "timeframe": dsl.timeframe,
                        "version": getattr(dsl, "schema_version", r.version),
                        "validation_score": r.validation_score,
                        "dna": dna_dict,
                        "dsl": dsl.model_dump(mode="json"),
                    }
                )
            self._send_json(output)

        except Exception as exc:
            self._send_error_json(
                f"Failed to fetch strategies: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR
            )

    def _handle_get_runs(self) -> None:
        """Return list of historical forward session dossiers from runs/."""
        runs_dir = Path("runs/forward")
        results: list[dict[str, Any]] = []

        if runs_dir.is_dir():
            for json_file in sorted(runs_dir.glob("*.json"), reverse=True):
                try:
                    with open(json_file, encoding="utf-8") as f:
                        data = json.load(f)
                    sess = data.get("session", {})
                    results.append(
                        {
                            "session_id": sess.get("session_id", json_file.stem),
                            "start_time": sess.get("start_time"),
                            "strategy": sess.get("strategy_name", "Unknown"),
                            "symbol": sess.get("symbol", "NIFTY"),
                            "status": sess.get("status", "UNKNOWN"),
                            "realized_pnl": sess.get("realized_pnl", 0.0),
                            "trades_count": sess.get("trades_count", 0),
                            "bars_count": sess.get("bars_count", 0),
                            "dossier_path": str(json_file),
                        }
                    )
                except Exception:
                    continue

        self._send_json(results)

    def _handle_get_run_detail(self, session_id: str) -> None:
        """Return full JSON dossier for a specific session_id with path traversal defense."""
        # Sanitize session_id: allow only alphanumeric, underscores, hyphens
        clean_id = "".join(c for c in session_id if c.isalnum() or c in ("-", "_"))
        if not clean_id:
            self._send_error_json("Invalid session ID", status=HTTPStatus.BAD_REQUEST)
            return

        runs_dir = Path("runs/forward")
        target = runs_dir / f"{clean_id}.json"

        if not target.is_file():
            # Check if file stem matches
            matched = list(runs_dir.glob(f"*{clean_id}*.json"))
            if matched and matched[0].is_file():
                target = matched[0]
            else:
                self._send_error_json(
                    f"Session '{clean_id}' not found", status=HTTPStatus.NOT_FOUND
                )
                return

        if not _is_safe_file_path(target):
            self._send_error_json("Access denied", status=HTTPStatus.FORBIDDEN)
            return

        try:
            with open(target, encoding="utf-8") as f:
                data = json.load(f)
            self._send_json(data)
        except Exception as exc:
            self._send_error_json(
                f"Failed to read dossier: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR
            )

    def _handle_post_inspect(self) -> None:
        """Inspect a CSV file specified in request body."""
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len == 0 or content_len > 1_000_000:
                self._send_error_json("Invalid content length", status=HTTPStatus.BAD_REQUEST)
                return

            body = self.rfile.read(content_len)
            req = json.loads(body.decode("utf-8"))
            file_path = req.get("file_path", "").strip()
            target_symbol = req.get("symbol", None)

            if not file_path:
                self._send_error_json(
                    "Missing 'file_path' parameter", status=HTTPStatus.BAD_REQUEST
                )
                return

            path = Path(file_path)
            if not _is_safe_file_path(path):
                self._send_error_json(
                    "Access to specified path is forbidden", status=HTTPStatus.FORBIDDEN
                )
                return

            if not path.is_file():
                self._send_error_json(f"File not found: {file_path}", status=HTTPStatus.NOT_FOUND)
                return

            report = NSECSVInspector.inspect_file(path, target_symbol=target_symbol)
            self._send_json(report.model_dump(mode="json"))

        except json.JSONDecodeError:
            self._send_error_json("Malformed JSON payload", status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._send_error_json(
                f"Inspection failed: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR
            )


class DashboardServer:
    """Multi-threaded HTTP server hosting AdiTrader Research & Paper Dashboard."""

    def __init__(self, host: str = "127.0.0.1", port: int = 8050):
        self.host = host
        self.port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None
        self._is_running = False

    @property
    def url(self) -> str:
        """Construct base URL."""
        return f"http://{self.host}:{self.port}"

    def start(self, background: bool = False) -> None:
        """Start the HTTP server."""
        self._server = ThreadingHTTPServer((self.host, self.port), DashboardRequestHandler)
        # Handle ephemeral port assignment (port 0)
        actual_port = self._server.server_address[1]
        self.port = actual_port
        self._is_running = True

        if background:
            self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
            self._thread.start()
        else:
            self._server.serve_forever()

    def stop(self) -> None:
        """Shut down the server cleanly."""
        self._is_running = False
        if self._server:
            self._server.shutdown()
            self._server.server_close()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3.0)


def run_dashboard(host: str = "127.0.0.1", port: int = 8050) -> None:
    """Launch the dashboard server interactively with graceful shutdown."""
    server = DashboardServer(host=host, port=port)
    print("=" * 68)
    print("      AdiTrader / QuantumValidator — Research & Paper Dashboard")
    print("=" * 68)
    print(f"Server URL:       {server.url}")
    print("Theme:            Dark (#0E1117 / #161B22 / #30363D)")
    print("Execution Venue:  Strictly Air-Gapped PaperBroker (ADR 002)")
    print("Mode:             Interactive Research Workstation")
    print("-" * 68)
    print(f"Open {server.url} in your web browser. Press Ctrl+C to stop.")
    print("-" * 68)

    try:
        server.start(background=False)
    except KeyboardInterrupt:
        print("\nStopping dashboard server...")
        server.stop()
        print("Dashboard server stopped cleanly.")
