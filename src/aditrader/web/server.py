"""Zero-dependency, high-performance responsive HTTP research dashboard server.

Implements:
- Single-page application serving (embedded HTML/CSS/JS compliant with DESIGN_LANGUAGE.md).
- REST API endpoints for:
  - System status, paper portfolio & active positions
  - Strategy catalog, deep inspection & AST presentation
  - Dataset library, quality inspection & compatibility auditing
  - Tri-path institutional validation & options theoretical payoff
  - Guided run configuration, compatibility gate & live execution monitoring
  - Historical run dossiers and results review
  - Provider credential management with strict secret masking
  - Local workstation authentication & session lifecycle
- Strict security boundaries:
  - Zero order placement endpoints (ADR 002 execution air gap).
  - Path traversal prevention on file access.
  - Secret masking for all provider credentials.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from aditrader.config.settings import get_settings
from aditrader.core.ledger.repository import LedgerRepository
from aditrader.data.adapters.kotak_neo import HAS_NEO_SDK
from aditrader.data.feeds.nse_csv import NSECSVInspector
from aditrader.data.session import EXCHANGE_TIMEZONE
from aditrader.strategy.library.registry import StrategyRegistry
from aditrader.web.services import (
    ActiveRunManager,
    DatasetService,
    ProviderSettingsManager,
    SessionManager,
    ValidationServiceBridge,
    mask_secret,
)
from aditrader.web.ui import DASHBOARD_HTML

logger = logging.getLogger(__name__)


def _mask_secret(secret: str | None) -> str:
    """Mask sensitive string for safe UI presentation."""
    return mask_secret(secret)


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

    def _read_json_payload(self) -> dict[str, Any] | None:
        """Safely read and deserialize JSON request body."""
        try:
            content_len = int(self.headers.get("Content-Length", 0))
            if content_len == 0 or content_len > 1_000_000:
                self._send_error_json("Invalid content length", status=HTTPStatus.BAD_REQUEST)
                return None
            body = self.rfile.read(content_len)
            data = json.loads(body.decode("utf-8"))
            if not isinstance(data, dict):
                self._send_error_json(
                    "JSON payload must be an object", status=HTTPStatus.BAD_REQUEST
                )
                return None
            return data
        except json.JSONDecodeError:
            self._send_error_json("Malformed JSON payload", status=HTTPStatus.BAD_REQUEST)
            return None
        except Exception as exc:
            self._send_error_json(f"Payload error: {exc}", status=HTTPStatus.BAD_REQUEST)
            return None

    def _get_auth_token(self) -> str | None:
        """Extract session token from header or query string."""
        auth_header = self.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:].strip()
        parsed = urlparse(self.path)
        if parsed.query and "token=" in parsed.query:
            for param in parsed.query.split("&"):
                if param.startswith("token="):
                    return unquote(param[6:])
        return None

    # --------------------------------------------------------------------------
    # Request Dispatcher
    # --------------------------------------------------------------------------

    def do_GET(self) -> None:
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            self._send_html(DASHBOARD_HTML)
            return

        if path == "/favicon.ico":
            self.send_response(HTTPStatus.NO_CONTENT)
            self.end_headers()
            return

        # 1. System & Session APIs
        if path == "/api/status":
            self._handle_get_status()
            return

        if path == "/api/auth/session":
            self._handle_get_session()
            return

        # 2. Strategies APIs
        if path == "/api/strategies":
            self._handle_get_strategies()
            return

        if path.startswith("/api/strategies/"):
            strategy_id = unquote(path[len("/api/strategies/") :])
            self._handle_get_strategy_detail(strategy_id)
            return

        # 3. Datasets APIs
        if path == "/api/datasets":
            self._handle_get_datasets()
            return

        # 4. Runs APIs
        if path == "/api/runs":
            self._handle_get_runs()
            return

        if path.startswith("/api/runs/active/"):
            run_id = unquote(path[len("/api/runs/active/") :])
            self._handle_get_active_run(run_id)
            return

        if path.startswith("/api/runs/"):
            session_id = unquote(path[len("/api/runs/") :])
            self._handle_get_run_detail(session_id)
            return

        # 5. Verification & Provenance APIs
        if path == "/api/verify/kat":
            self._handle_get_verify_kat()
            return

        if path == "/api/verify/trace":
            self._handle_get_verify_trace(parsed.query)
            return

        if path.startswith("/api/verify/evidence/"):
            bundle_id = unquote(path[len("/api/verify/evidence/") :])
            self._handle_get_verify_evidence(bundle_id)
            return

        # 6. Settings & Providers APIs
        if path == "/api/settings":
            self._handle_get_settings()
            return

        self._send_error_json("Resource not found", status=HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        """Handle POST requests."""
        parsed = urlparse(self.path)
        path = parsed.path

        # 1. Session APIs
        if path == "/api/auth/session":
            self._handle_post_session_unlock()
            return

        if path == "/api/auth/logout":
            self._handle_post_session_logout()
            return

        # 2. Datasets & Inspection
        if path == "/api/inspect-data":
            self._handle_post_inspect()
            return

        # 3. Strategy Validation & Compatibility
        if path == "/api/validate-strategy":
            self._handle_post_validate_strategy()
            return

        if path == "/api/check-compatibility":
            self._handle_post_check_compatibility()
            return

        if path == "/api/verify/recalculate":
            self._handle_post_verify_recalculate()
            return

        # 4. Simulation Runs
        if path == "/api/runs/start":
            self._handle_post_start_run()
            return

        if path.startswith("/api/runs/active/") and path.endswith("/stop"):
            # /api/runs/active/{run_id}/stop
            parts = path.split("/")
            if len(parts) >= 5:
                run_id = unquote(parts[4])
                self._handle_post_stop_run(run_id)
                return

        # 5. Settings & Providers
        if path == "/api/settings/providers/test":
            self._handle_post_test_provider()
            return

        if path in ("/api/settings/providers", "/api/settings/providers/update"):
            self._handle_post_update_provider()
            return

        self._send_error_json("Endpoint not supported", status=HTTPStatus.NOT_FOUND)

    # --------------------------------------------------------------------------
    # Handlers: System & Session
    # --------------------------------------------------------------------------

    def _handle_get_status(self) -> None:
        """Return system health, adapter status, database state, and paper portfolio."""
        settings = get_settings()
        session_mgr = SessionManager()
        token = self._get_auth_token()
        session_info = session_mgr.get_session(token)

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
        blocked_margin = 0.0
        realized_pnl = 0.0
        unrealized_pnl = 0.0
        margin_utilization = 0.0
        total_trades_count = 0
        total_orders_count = 0

        try:
            repo = LedgerRepository(database_url=settings.database_url)
            repo.create_tables()
            db_connected = True

            from sqlalchemy import func, inspect, select

            from aditrader.core.ledger.schema import (
                AccountBalanceRecord,
                OrderRecord,
                PositionRecord,
                TradeRecord,
            )

            inspector = inspect(repo.engine)
            tables = inspector.get_table_names()

            with repo.SessionLocal() as session:
                total_trades_count = (
                    session.execute(select(func.count(TradeRecord.id))).scalar() or 0
                )
                total_orders_count = (
                    session.execute(select(func.count(OrderRecord.id))).scalar() or 0
                )

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

                bal_stmt = (
                    select(AccountBalanceRecord)
                    .order_by(AccountBalanceRecord.timestamp.desc(), AccountBalanceRecord.id.desc())
                    .limit(1)
                )
                latest_bal = session.execute(bal_stmt).scalars().first()
                if latest_bal is not None:
                    total_capital = latest_bal.total_capital
                    current_cash = latest_bal.available_margin
                    blocked_margin = latest_bal.used_margin
                    realized_pnl = latest_bal.realized_pnl
                    unrealized_pnl = latest_bal.unrealized_pnl
                    margin_utilization = (
                        (latest_bal.used_margin / latest_bal.total_capital)
                        if latest_bal.total_capital > 0
                        else 0.0
                    )
                else:
                    realized_pnl = sum(p.realized_pnl for p in db_positions)
                    unrealized_pnl = sum(p.unrealized_pnl for p in db_positions)
                    total_capital = initial_capital + realized_pnl + unrealized_pnl
                    current_cash = total_capital
                    blocked_margin = 0.0
                    margin_utilization = 0.0

        except Exception as exc:
            logger.debug("Database status check completed with notice: %s", exc)

        now_ist = datetime.now(EXCHANGE_TIMEZONE)

        # 3. Strategy & Dataset counts
        registry = StrategyRegistry()
        strategies_count = len(registry.list_all())
        datasets = DatasetService.list_datasets()

        payload = {
            "system_status": "HEALTHY",
            "execution_mode": "PAPER_RESEARCH_ONLY",
            "server_time_ist": now_ist.isoformat(),
            "environment": settings.aditrader_env,
            "session": {
                "status": session_info.status,
                "user_id": session_info.user_id,
                "username": session_info.username,
                "role": session_info.role,
                "token": session_info.session_token,
            },
            "summary_counts": {
                "strategies": strategies_count,
                "datasets": len(datasets),
                "replayable_datasets": sum(1 for d in datasets if d.get("is_replayable")),
            },
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
                "blocked_margin": blocked_margin,
                "margin_utilization": margin_utilization,
                "total_trades_count": total_trades_count,
                "total_orders_count": total_orders_count,
                "active_positions_count": len(active_positions),
            },
            "active_positions": active_positions,
            "recent_trades": recent_trades,
            "recent_orders": recent_orders,
        }
        self._send_json(payload)

    def _handle_get_session(self) -> None:
        """Return active session information."""
        session_mgr = SessionManager()
        token = self._get_auth_token()
        sess = session_mgr.get_session(token)
        self._send_json(
            {
                "status": sess.status,
                "user_id": sess.user_id,
                "username": sess.username,
                "role": sess.role,
                "permissions": sess.permissions,
                "created_at": sess.created_at.isoformat(),
                "expires_at": sess.expires_at.isoformat(),
                "token": sess.session_token,
            }
        )

    def _handle_post_session_unlock(self) -> None:
        """Unlock or sign in to session."""
        payload = self._read_json_payload()
        if payload is not None:
            password = payload.get("password")
            pin = (
                os.environ.get("WORKSTATION_PIN")
                or os.environ.get("ADITRADER_SESSION_PIN")
                or "aditrader2026"
            )
            if password != pin:
                self._send_error_json("Invalid credentials", status=HTTPStatus.UNAUTHORIZED)
                return

        session_mgr = SessionManager()
        token = self._get_auth_token()
        sess = session_mgr.unlock_session(token)
        self._send_json(
            {
                "status": sess.status,
                "authenticated": True,
                "user_id": sess.user_id,
                "username": sess.username,
                "role": sess.role,
                "token": sess.session_token,
                "message": "Local session unlocked successfully.",
            }
        )

    def _handle_post_session_logout(self) -> None:
        """Lock workstation session."""
        session_mgr = SessionManager()
        token = self._get_auth_token()
        sess = session_mgr.lock_session(token)
        self._send_json(
            {
                "status": sess.status,
                "message": "Workstation session locked.",
            }
        )

    # --------------------------------------------------------------------------
    # Handlers: Strategies
    # --------------------------------------------------------------------------

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

                is_options = bool(dsl.legs)
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
                        "is_options_strategy": is_options,
                        "legs_count": len(dsl.legs),
                        "dna": dna_dict,
                        "dsl": dsl.model_dump(mode="json"),
                    }
                )
            self._send_json(output)

        except Exception as exc:
            self._send_error_json(
                f"Failed to fetch strategies: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR
            )

    def _handle_get_strategy_detail(self, strategy_id: str) -> None:
        """Return deep technical detail for a specific strategy."""
        clean_id = "".join(c for c in strategy_id if c.isalnum() or c in ("-", "_"))
        detail = ValidationServiceBridge.get_strategy_detail(clean_id)
        if not detail:
            self._send_error_json(f"Strategy '{clean_id}' not found", status=HTTPStatus.NOT_FOUND)
            return
        self._send_json(detail)

    def _handle_post_validate_strategy(self) -> None:
        """Validate a strategy against a chosen policy."""
        payload = self._read_json_payload()
        if payload is None:
            return

        strategy_id = payload.get("strategy_id")
        strategy_dsl = payload.get("dsl")
        policy_name = payload.get("policy", "InstitutionalPolicy")
        dataset_path = payload.get("dataset_path") or payload.get("dataset")

        try:
            val_res = ValidationServiceBridge.validate_strategy_definition(
                strategy_id=strategy_id,
                strategy_dsl_dict=strategy_dsl,
                policy_name=policy_name,
                dataset_path=dataset_path,
            )
            self._send_json(val_res)
        except Exception as exc:
            self._send_error_json(f"Validation failed: {exc}", status=HTTPStatus.BAD_REQUEST)

    # --------------------------------------------------------------------------
    # Handlers: Datasets & Compatibility
    # --------------------------------------------------------------------------

    def _handle_get_datasets(self) -> None:
        """Return discovered datasets with format classification and replayability flags."""
        datasets = DatasetService.list_datasets()
        self._send_json(datasets)

    def _handle_post_inspect(self) -> None:
        """Inspect a CSV file specified in request body."""
        payload = self._read_json_payload()
        if payload is None:
            return

        file_path = payload.get("file_path", "").strip()
        target_symbol = payload.get("symbol", None)

        if not file_path:
            self._send_error_json("Missing 'file_path' parameter", status=HTTPStatus.BAD_REQUEST)
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

        try:
            report = NSECSVInspector.inspect_file(path, target_symbol=target_symbol)
            self._send_json(report.model_dump(mode="json"))
        except Exception as exc:
            self._send_error_json(
                f"Inspection failed: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR
            )

    def _handle_post_check_compatibility(self) -> None:
        """Evaluate whether a strategy and dataset are compatible for deterministic replay."""
        payload = self._read_json_payload()
        if payload is None:
            return

        strategy_id = payload.get("strategy_id", "").strip()
        dataset_path = payload.get("dataset_path", "").strip()

        if not strategy_id or not dataset_path:
            self._send_error_json(
                "Missing 'strategy_id' or 'dataset_path'", status=HTTPStatus.BAD_REQUEST
            )
            return

        path = Path(dataset_path)
        if not _is_safe_file_path(path):
            self._send_error_json(
                "Access to specified dataset path is forbidden", status=HTTPStatus.FORBIDDEN
            )
            return

        compat = ValidationServiceBridge.check_strategy_dataset_compatibility(
            strategy_id, dataset_path
        )
        self._send_json(compat)

    # --------------------------------------------------------------------------
    # Handlers: Simulation Runs
    # --------------------------------------------------------------------------

    def _handle_post_start_run(self) -> None:
        """Launch a paper trading or deterministic replay simulation."""
        payload = self._read_json_payload()
        if payload is None:
            return

        strategy_id = payload.get("strategy_id", "").strip()
        dataset_path = payload.get("dataset_path", "").strip()
        capital = float(payload.get("initial_capital", 1_000_000.0))
        slippage_bps = float(payload.get("slippage_bps", 2.5))

        if not strategy_id or not dataset_path:
            self._send_error_json(
                "Missing required simulation parameters", status=HTTPStatus.BAD_REQUEST
            )
            return

        path = Path(dataset_path)
        if not _is_safe_file_path(path):
            self._send_error_json(
                "Access to specified dataset is forbidden", status=HTTPStatus.FORBIDDEN
            )
            return

        try:
            res = ActiveRunManager().start_simulation(
                strategy_id=strategy_id,
                dataset_path=dataset_path,
                initial_capital=capital,
                slippage_bps=slippage_bps,
            )
            self._send_json(res)
        except ValueError as exc:
            # Blocked run
            self._send_error_json(str(exc), status=HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._send_error_json(
                f"Failed to start simulation: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR
            )

    def _handle_get_active_run(self, run_id: str) -> None:
        """Return live progress of active simulation."""
        clean_id = "".join(c for c in run_id if c.isalnum() or c in ("-", "_"))
        status_info = ActiveRunManager().get_run_status(clean_id)
        if not status_info:
            self._send_error_json(f"Active run '{clean_id}' not found", status=HTTPStatus.NOT_FOUND)
            return
        self._send_json(status_info)

    def _handle_post_stop_run(self, run_id: str) -> None:
        """Halt active simulation."""
        clean_id = "".join(c for c in run_id if c.isalnum() or c in ("-", "_"))
        stopped = ActiveRunManager().stop_simulation(clean_id)
        if not stopped:
            self._send_error_json(f"Run '{clean_id}' is not running", status=HTTPStatus.BAD_REQUEST)
            return
        self._send_json({"run_id": clean_id, "status": "STOPPING", "message": "Stop requested."})

    def _handle_get_runs(self) -> None:
        """Return list of historical forward session dossiers from runs/."""
        runs_dir = Path("runs/forward")
        results: list[dict[str, Any]] = []

        if runs_dir.is_dir():
            files = sorted(runs_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            for json_file in files[:100]:
                try:
                    with open(json_file, encoding="utf-8") as f:
                        data = json.load(f)
                    sess = data.get("session", {})
                    trades_list = data.get("trades", [])
                    bars_list = data.get("bars", [])
                    trades_cnt = sess.get("trades_count")
                    if trades_cnt is None:
                        trades_cnt = len(trades_list)
                    bars_cnt = sess.get("bars_count")
                    if bars_cnt is None:
                        bars_cnt = len(bars_list)

                    results.append(
                        {
                            "session_id": sess.get("session_id", json_file.stem),
                            "start_time": sess.get("started_at") or sess.get("start_time"),
                            "strategy": sess.get("strategy_name")
                            or sess.get("strategy_id")
                            or f"Session {json_file.stem[-6:]}",
                            "symbol": sess.get("symbol", "NIFTY"),
                            "status": sess.get("status", "UNKNOWN"),
                            "realized_pnl": sess.get("realized_pnl", 0.0),
                            "trades_count": trades_cnt,
                            "bars_count": bars_cnt,
                            "dossier_path": str(json_file),
                        }
                    )
                except Exception:
                    continue

        self._send_json(results)

    def _handle_get_run_detail(self, session_id: str) -> None:
        """Return full JSON dossier for a specific session_id with path traversal defense."""
        clean_id = "".join(c for c in session_id if c.isalnum() or c in ("-", "_"))
        if not clean_id:
            self._send_error_json("Invalid session ID", status=HTTPStatus.BAD_REQUEST)
            return

        runs_dir = Path("runs/forward")
        target = runs_dir / f"{clean_id}.json"

        if not target.is_file():
            # Check prefix / suffix / case-insensitively
            clean_lower = clean_id.lower()
            matched = [
                p
                for p in runs_dir.glob("*.json")
                if clean_lower in p.name.lower() or p.stem.lower() == clean_lower
            ]
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
            if "session_id" not in data and "session" in data:
                data["session_id"] = data["session"].get("session_id")
                data["status"] = data["session"].get("status")
                data["strategy_id"] = data["session"].get("strategy_id")
                data["realized_pnl"] = data["session"].get("realized_pnl")
            self._send_json(data)
        except Exception as exc:
            self._send_error_json(
                f"Failed to read dossier: {exc}", status=HTTPStatus.INTERNAL_SERVER_ERROR
            )

    # --------------------------------------------------------------------------
    # Handlers: Settings & Providers
    # --------------------------------------------------------------------------

    def _handle_get_settings(self) -> None:
        """Return system configuration, masked provider credentials, and security guarantees."""
        settings = get_settings()
        providers = ProviderSettingsManager.get_providers_info()

        payload = {
            "general": {
                "environment": settings.aditrader_env,
                "log_level": settings.log_level,
                "timezone": settings.timezone,
            },
            "security": {
                "execution_mode": "AIR_GAPPED_PAPER_ONLY",
                "live_order_routing": "DISABLED (ADR 002)",
                "options_live_execution": "DISABLED (ADR 011)",
                "dynamic_python_eval": "DISABLED (AST Only)",
                "secret_masking_active": True,
            },
            "risk_limits": {
                "initial_capital": settings.initial_capital,
                "max_margin_utilization": settings.max_margin_utilization,
                "intraday_max_drawdown": settings.intraday_max_drawdown,
            },
            "storage": {
                "database_url": _mask_secret(settings.database_url),
                "redis_url": _mask_secret(settings.redis_url)
                if settings.redis_url
                else "Not configured",
                "runs_directory": "runs/forward",
                "data_directory": "data",
            },
            "providers": {p["id"]: p for p in providers},
            "providers_list": providers,
        }
        self._send_json(payload)

    def _handle_post_update_provider(self) -> None:
        """Update or remove provider credentials safely."""
        payload = self._read_json_payload()
        if payload is None:
            return

        provider_id = (payload.get("provider_id") or payload.get("provider") or "").strip()
        action = payload.get("action", "update").lower()

        if not provider_id:
            self._send_error_json("Missing 'provider_id'", status=HTTPStatus.BAD_REQUEST)
            return

        if action == "remove":
            res = ProviderSettingsManager.remove_provider_credentials(provider_id)
            self._send_json(res)
            return

        credentials = payload.get("credentials")
        if isinstance(credentials, dict):
            res = ProviderSettingsManager.update_provider_credentials(provider_id, credentials)
            self._send_json(res)
            return

        field_name = payload.get("field", "").strip()
        value = payload.get("value", "").strip()

        if not field_name or not value:
            self._send_error_json(
                "Missing 'field' and 'value', or 'credentials' dict", status=HTTPStatus.BAD_REQUEST
            )
            return

        res = ProviderSettingsManager.update_provider_credential(provider_id, field_name, value)
        self._send_json(res)

    def _handle_post_test_provider(self) -> None:
        """Test provider connectivity without leaking secrets."""
        payload = self._read_json_payload()
        if payload is None:
            return

        provider_id = (payload.get("provider_id") or payload.get("provider") or "").strip()
        if not provider_id:
            self._send_error_json(
                "Missing 'provider' or 'provider_id'", status=HTTPStatus.BAD_REQUEST
            )
            return

        res = ProviderSettingsManager.test_provider_connection(provider_id)
        self._send_json(res)

    def _handle_get_verify_kat(self) -> None:
        """Return execution results for the deterministic Known-Answer Test suite."""
        try:
            suite_data = ValidationServiceBridge.get_kat_suite()
            self._send_json(suite_data)
        except Exception as exc:
            self._send_error_json(f"KAT execution failed: {exc}")

    def _handle_get_verify_trace(self, query_string: str) -> None:
        """Return step-by-step mathematical provenance trace for a target metric or trade."""
        try:
            params = {k: v[0] for k, v in parse_qs(query_string).items()}
            target_metric = params.get("metric", "expectancy")
            trace_data = ValidationServiceBridge.get_trace(target_metric, params)
            self._send_json(trace_data)
        except Exception as exc:
            self._send_error_json(f"Trace generation failed: {exc}")

    def _handle_get_verify_evidence(self, bundle_id: str) -> None:
        """Return evidence bundle by ID."""
        bundle_data = ValidationServiceBridge.get_evidence_bundle(bundle_id)
        if not bundle_data:
            self._send_error_json(
                f"Evidence bundle '{bundle_id}' not found", status=HTTPStatus.NOT_FOUND
            )
            return
        self._send_json(bundle_data)

    def _handle_post_verify_recalculate(self) -> None:
        """Recalculate stored result fresh and return side-by-side reproducibility comparison."""
        payload = self._read_json_payload()
        if not payload:
            return

        strategy_id = payload.get("strategy_id")
        run_id = payload.get("run_id")
        dataset_path = payload.get("dataset_path")

        if not strategy_id and not run_id:
            self._send_error_json("Either 'strategy_id' or 'run_id' must be specified.")
            return

        # Security: sanitize run_id against directory traversal
        if run_id:
            import re

            sanitized_run_id = re.sub(r"[^A-Za-z0-9_-]", "", str(run_id))
            if sanitized_run_id != run_id:
                self._send_error_json("Invalid characters in 'run_id'")
                return
            run_id = sanitized_run_id

        # Security: sanitize dataset_path to prevent path traversal outside workspace
        if dataset_path:
            norm_path = Path(dataset_path).resolve()
            project_root = Path.cwd().resolve()
            if not str(norm_path).startswith(str(project_root)):
                self._send_error_json("Access denied: 'dataset_path' must reside within workspace")
                return

        try:
            result = ValidationServiceBridge.recalculate_result(
                strategy_id=strategy_id or "",
                run_id=run_id,
                dataset_path=dataset_path,
            )
            self._send_json(result)
        except Exception as exc:
            self._send_error_json(f"Recalculation failed: {exc}")


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
