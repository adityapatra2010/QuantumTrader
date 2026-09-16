"""Unit and integration tests verifying responsive web dashboard server and REST endpoints."""

import json
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path

import pytest

from aditrader.cli.commands import cmd_dashboard
from aditrader.web.server import DashboardServer, _is_safe_file_path
from aditrader.web.services import mask_secret


class DummyArgs:
    """Helper mock for CLI arguments."""

    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


def test_secret_masking() -> None:
    """Verify secrets are masked to prevent leakage in logs or UI."""
    assert mask_secret(None) == "Not configured"
    assert mask_secret("") == "Not configured"
    assert mask_secret("12345") == "***"
    assert mask_secret("my_secret_token") == "my***en"


def test_path_traversal_safety() -> None:
    """Verify security check blocks sensitive system paths and secrets."""
    assert _is_safe_file_path(Path("data/nifty.csv")) is True
    assert _is_safe_file_path(Path("runs/forward/session.json")) is True
    assert _is_safe_file_path(Path(".env")) is False
    assert _is_safe_file_path(Path(".env.local")) is False
    assert _is_safe_file_path(Path(".git/config")) is False
    assert _is_safe_file_path(Path("/etc/passwd")) is False


def test_dashboard_server_lifecycle_and_endpoints() -> None:
    """Verify dashboard server boots on ephemeral port and serves UI and REST APIs."""
    server = DashboardServer(host="127.0.0.1", port=0)
    server.start(background=True)
    base_url = server.url

    try:
        # 1. GET / (Single Page App HTML)
        with urllib.request.urlopen(f"{base_url}/") as res:
            assert res.status == HTTPStatus.OK
            assert "text/html" in res.headers["Content-Type"]
            body = res.read().decode("utf-8")
            assert "AdiTrader" in body
            assert "QuantumValidator" in body
            assert "Paper simulation only. All executions route to local PaperBroker" in body
            assert "#0E1117" in body  # Design language theme color
            assert "#161B22" in body

        # 2. GET /api/status (System & Portfolio status JSON)
        with urllib.request.urlopen(f"{base_url}/api/status") as res:
            assert res.status == HTTPStatus.OK
            assert "application/json" in res.headers["Content-Type"]
            data = json.loads(res.read().decode("utf-8"))
            assert data["system_status"] == "HEALTHY"
            assert "kotak_neo" in data
            assert "database" in data
            assert "paper_portfolio" in data
            assert data["paper_portfolio"]["initial_capital"] == 1_000_000.0

        # 3. GET /api/strategies (Built-in strategies)
        with urllib.request.urlopen(f"{base_url}/api/strategies") as res:
            assert res.status == HTTPStatus.OK
            strategies = json.loads(res.read().decode("utf-8"))
            assert isinstance(strategies, list)
            assert len(strategies) >= 3
            names = [s["name"] for s in strategies]
            assert any("Iron Condor" in n or "iron_condor" in n for n in names)

        # 4. GET /api/runs
        with urllib.request.urlopen(f"{base_url}/api/runs") as res:
            assert res.status == HTTPStatus.OK
            runs = json.loads(res.read().decode("utf-8"))
            assert isinstance(runs, list)

        # 5. 404 on unknown endpoint
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(f"{base_url}/api/unknown-route")
        assert exc_info.value.code == HTTPStatus.NOT_FOUND

    finally:
        server.stop()


def test_dashboard_post_inspect_data(tmp_path: Path) -> None:
    """Verify POST /api/inspect-data returns validation diagnostics."""
    csv_file = tmp_path / "web_inspect_sample.csv"
    csv_file.write_text(
        "Date,Time,Open,High,Low,Close,Volume\n2024-01-15,09:15:00,21500,21520,21490,21510,100\n",
        encoding="utf-8",
    )

    server = DashboardServer(host="127.0.0.1", port=0)
    server.start(background=True)
    base_url = server.url

    try:
        req_data = json.dumps({"file_path": str(csv_file)}).encode("utf-8")
        req = urllib.request.Request(
            f"{base_url}/api/inspect-data",
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req) as res:
            assert res.status == HTTPStatus.OK
            report = json.loads(res.read().decode("utf-8"))
            assert report["detected_format"] == "NSE_INTRADAY"
            assert report["parsed_bars"] == 1
            assert report["is_valid_replayable"] is True

        # Reject forbidden paths
        req_bad = urllib.request.Request(
            f"{base_url}/api/inspect-data",
            data=json.dumps({"file_path": "/etc/passwd"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc_info:
            urllib.request.urlopen(req_bad)
        assert exc_info.value.code == HTTPStatus.FORBIDDEN

    finally:
        server.stop()


def test_cli_cmd_dashboard_notice(capsys: pytest.CaptureFixture[str]) -> None:
    """Verify cmd_dashboard informs user of Phase 8 roadmap and provides instructions."""
    args = DummyArgs(port=8050, host="127.0.0.1", serve=False)
    exit_code = cmd_dashboard(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "scheduled for Phase 8" in captured.out
    assert "aditrader dashboard --serve" in captured.out


def test_dashboard_system_and_utilities_endpoints() -> None:
    """Verify new REST endpoints for system diagnostics, db init, search, feed smoke, option chain, and audit."""
    server = DashboardServer(host="127.0.0.1", port=0)
    server.start(background=True)
    base_url = server.url

    try:
        # 1. GET /api/system/diagnostics
        with urllib.request.urlopen(f"{base_url}/api/system/diagnostics") as res:
            assert res.status == HTTPStatus.OK
            diag = json.loads(res.read().decode("utf-8"))
            assert "overall_status" in diag
            assert "checks" in diag

        # 2. POST /api/system/init-db
        req_db = urllib.request.Request(
            f"{base_url}/api/system/init-db",
            data=b"{}",
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_db) as res:
            assert res.status == HTTPStatus.OK
            db_res = json.loads(res.read().decode("utf-8"))
            assert "tables" in db_res

        # 3. GET /api/instruments/search?q=NIFTY
        with urllib.request.urlopen(f"{base_url}/api/instruments/search?q=NIFTY&limit=3") as res:
            assert res.status == HTTPStatus.OK
            search_res = json.loads(res.read().decode("utf-8"))
            assert isinstance(search_res, list)

        # 4. POST /api/strategies/audit
        audit_payload = json.dumps(
            {"content": '{"name":"Audit Test","underlying":"NIFTY"}', "filename": "test.json"}
        ).encode("utf-8")
        req_audit = urllib.request.Request(
            f"{base_url}/api/strategies/audit",
            data=audit_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_audit) as res:
            assert res.status == HTTPStatus.OK
            audit_res = json.loads(res.read().decode("utf-8"))
            assert audit_res["success"] is True
            assert "warnings" in audit_res

        # 5. POST /api/feed/smoke
        smoke_payload = json.dumps({"symbol": "NIFTY", "ticks": 2, "mock": True}).encode("utf-8")
        req_smoke = urllib.request.Request(
            f"{base_url}/api/feed/smoke",
            data=smoke_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_smoke) as res:
            assert res.status == HTTPStatus.OK
            smoke_res = json.loads(res.read().decode("utf-8"))
            assert smoke_res["symbol"] == "NIFTY"
            assert smoke_res["received_ticks"] == 2

        # 6. GET /api/options/chain?underlying=NIFTY
        with urllib.request.urlopen(
            f"{base_url}/api/options/chain?underlying=NIFTY&count=4&mock=true"
        ) as res:
            assert res.status == HTTPStatus.OK
            chain_res = json.loads(res.read().decode("utf-8"))
            assert chain_res["underlying"] == "NIFTY"
            assert "strikes" in chain_res
            assert len(chain_res["strikes"]) > 0

        # 7. POST /api/kotak/discover
        disc_payload = json.dumps({"mock": True}).encode("utf-8")
        req_disc = urllib.request.Request(
            f"{base_url}/api/kotak/discover",
            data=disc_payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req_disc) as res:
            assert res.status == HTTPStatus.OK
            disc_res = json.loads(res.read().decode("utf-8"))
            assert "tests" in disc_res
            assert disc_res["tests_total"] >= 5

    finally:
        server.stop()
