"""Unit tests for QuantumValidator GUI workflows, REST endpoints, and security gates."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from http import HTTPStatus
from pathlib import Path
from typing import Any

import pytest

from aditrader.web.server import DashboardServer


def _make_request(
    url: str,
    method: str = "GET",
    data: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, Any, dict[str, str]]:
    """Helper to perform HTTP requests against the test server."""
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)

    body_bytes = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body_bytes, headers=hdrs, method=method)

    try:
        with urllib.request.urlopen(req) as res:
            res_body = res.read().decode("utf-8")
            parsed = json.loads(res_body) if res_body else {}
            res_headers = dict(res.headers)
            return res.status, parsed, res_headers
    except urllib.error.HTTPError as err:
        err_body = err.read().decode("utf-8")
        parsed_err = json.loads(err_body) if err_body else {}
        return err.code, parsed_err, dict(err.headers)


@pytest.fixture(scope="module")
def web_server() -> Any:
    """Spins up a background DashboardServer on an ephemeral port."""
    server = DashboardServer(host="127.0.0.1", port=0)
    server.start(background=True)
    yield server
    server.stop()


def test_gui_html_shell_and_tokens(web_server: DashboardServer) -> None:
    """Verify single-page application serves all 7 screens and Design Language tokens."""
    url = f"{web_server.url}/"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req) as res:
        assert res.status == HTTPStatus.OK
        assert "text/html" in res.headers["Content-Type"]
        body = res.read().decode("utf-8")

        # Visual Design Tokens from DESIGN_LANGUAGE.md
        assert "#0E1117" in body  # Technical dark background
        assert "#161B22" in body  # Surface color
        assert "#30363D" in body  # Border color
        assert "JetBrains Mono" in body or "ui-monospace" in body

        # Air-gap safety notices
        assert "Paper simulation only. All executions route to local PaperBroker" in body
        assert "PAPER BROKER" in body

        # All 7 tabs present
        assert "tab-overview" in body
        assert "tab-strategies" in body
        assert "tab-datasets" in body
        assert "tab-validation" in body
        assert "tab-simulation" in body
        assert "tab-results" in body
        assert "tab-settings" in body

        # NIFTY CE Dynamic Premium Bands explicitly mentioned
        assert "₹50.00 – ₹59.50" in body or "50.00" in body
        assert "₹100.00 – ₹109.50" in body or "109.50" in body  # Special features
        assert (
            "Entry price (the <em>premium</em>), not the strike, determines which contract to trade."
            in body
        )


def test_auth_session_lifecycle(web_server: DashboardServer) -> None:
    """Verify local researcher session status, unlocking, and logout."""
    base_url = web_server.url

    # 1. GET /api/auth/session
    status, data, _ = _make_request(f"{base_url}/api/auth/session")
    assert status == HTTPStatus.OK
    assert data["user_id"] == "local_researcher"
    assert data["status"] in ("SIGNED_IN", "ACTIVE")

    # 2. POST /api/auth/session with invalid password
    status, err_data, _ = _make_request(
        f"{base_url}/api/auth/session",
        method="POST",
        data={"action": "unlock", "password": "incorrect_pin"},
    )
    assert status == HTTPStatus.UNAUTHORIZED
    assert "Invalid credentials" in err_data.get("error", "")

    # 3. POST /api/auth/session with valid researcher PIN/password
    status, unlock_data, _ = _make_request(
        f"{base_url}/api/auth/session",
        method="POST",
        data={"action": "unlock", "password": "aditrader2026"},
    )
    assert status == HTTPStatus.OK
    assert unlock_data["authenticated"] is True
    assert "token" in unlock_data
    token = unlock_data["token"]

    # 4. POST /api/auth/logout with token
    status, logout_data, _ = _make_request(
        f"{base_url}/api/auth/logout",
        method="POST",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert status == HTTPStatus.OK
    assert logout_data["status"] == "SIGNED_OUT"


def test_strategy_catalog_and_nifty_ce_ladder(web_server: DashboardServer) -> None:
    """Verify strategy catalog exposes NIFTY CE Dynamic Ladder with explicit premium bands."""
    base_url = web_server.url

    # 1. GET /api/strategies
    status, strategies, _ = _make_request(f"{base_url}/api/strategies")
    assert status == HTTPStatus.OK
    assert isinstance(strategies, list)
    assert len(strategies) >= 3

    strat_ids = [s["id"] for s in strategies]
    assert "tpl-nifty-ce-premium-ladder-v1" in strat_ids or "nifty_ce_premium_ladder" in strat_ids

    # 2. GET /api/strategies/nifty_ce_premium_ladder
    status, detail, _ = _make_request(f"{base_url}/api/strategies/nifty_ce_premium_ladder")
    assert status == HTTPStatus.OK
    assert detail["id"] in ("nifty_ce_premium_ladder", "tpl-nifty-ce-premium-ladder-v1")
    assert detail["underlying"] == "NIFTY"
    assert detail["is_options"] is True

    # Check explicit premium bands
    pb = detail.get("premium_bands", {})
    assert "bands" in pb
    bands = pb["bands"]
    assert len(bands) == 6
    assert bands[0]["label"] == "Band 50"
    assert bands[0]["min_premium"] == 50.0
    assert bands[0]["max_premium"] == 59.50
    assert bands[5]["label"] == "Band 100"
    assert bands[5]["min_premium"] == 100.0
    assert bands[5]["max_premium"] == 109.50

    # Ratio hedge: 4 hedges around ₹5
    hedge = detail.get("ratio_hedge", {})
    assert hedge.get("target_premium") == 5.0
    assert hedge.get("buy_ratio") == 4

    # Trailing stop ratchet
    trail = detail.get("trailing_stop", {})
    assert trail.get("ratchet_step") in (5.0, 10.0)
    assert trail.get("stop_distance") == 5.0

    # Theoretical options payoff
    payoff = detail.get("theoretical_payoff", {})
    assert "lower_breakeven" in payoff
    assert "upper_breakeven" in payoff
    assert payoff.get("max_profit") is not None


def test_dataset_scanning_and_classification(web_server: DashboardServer) -> None:
    """Verify dataset discovery and 3-pillar classification."""
    base_url = web_server.url

    status, datasets, _ = _make_request(f"{base_url}/api/datasets")
    assert status == HTTPStatus.OK
    assert isinstance(datasets, list)
    assert len(datasets) >= 2

    # Check for nifty_sample.csv
    nifty_ds = next((d for d in datasets if "nifty_sample.csv" in d["path"]), None)
    assert nifty_ds is not None
    assert nifty_ds["detected_format"] == "NSE_INTRADAY"
    assert nifty_ds["is_replayable"] is True
    assert nifty_ds["is_chain_aware"] is False  # Spot linear CSV

    # Check for reliance_derivative_sample.csv
    fno_ds = next((d for d in datasets if "reliance_derivative_sample.csv" in d["path"]), None)
    if fno_ds:
        assert fno_ds["is_chain_aware"] is True


def test_compatibility_gate_blocking_and_allowing(web_server: DashboardServer) -> None:
    """Verify compatibility gate blocks option strategies on spot CSVs and permits linear strategies."""
    base_url = web_server.url

    # Incompatible pairing: Options strategy + Spot CSV
    status, blocked_rep, _ = _make_request(
        f"{base_url}/api/check-compatibility",
        method="POST",
        data={
            "strategy_id": "nifty_ce_premium_ladder",
            "dataset_path": "data/nifty_sample.csv",
        },
    )
    assert status == HTTPStatus.OK
    assert blocked_rep["compatible"] is False
    assert "lacks multi-strike option chain quotes" in blocked_rep["reason"]

    # Compatible pairing: Linear intraday strategy + Intraday CSV
    status, ok_rep, _ = _make_request(
        f"{base_url}/api/check-compatibility",
        method="POST",
        data={
            "strategy_id": "tpl-nifty-intraday-trend-v1",
            "dataset_path": "data/nifty_sample.csv",
        },
    )
    assert status == HTTPStatus.OK
    assert ok_rep["compatible"] is True
    assert "compatible" in ok_rep["reason"].lower()


def test_strategy_validation_studio(web_server: DashboardServer) -> None:
    """Verify Institutional Mode strategy validation runs and evaluates risk gates."""
    base_url = web_server.url

    status, rep, _ = _make_request(
        f"{base_url}/api/validate-strategy",
        method="POST",
        data={
            "strategy_id": "nifty_ce_premium_ladder",
            "dataset_path": "data/nifty_sample.csv",
            "policy_level": "INSTITUTIONAL",
        },
    )
    assert status == HTTPStatus.OK
    assert rep["status"] in ("APPROVED", "REJECTED")
    assert "metrics" in rep
    assert "mathematical_expectancy" in rep["metrics"]
    assert "risk_gates" in rep
    assert any(g["name"] == "Tail Risk Gate" for g in rep["risk_gates"])
    assert "payoff_structure" in rep


def test_simulation_execution_and_active_monitoring(
    web_server: DashboardServer, tmp_path: Path
) -> None:
    """Verify background simulation run starts, tracks progress, and completes with a dossier."""
    base_url = web_server.url

    # Start simulation with linear strategy on nifty_sample.csv
    status, start_rep, _ = _make_request(
        f"{base_url}/api/runs/start",
        method="POST",
        data={
            "strategy_id": "tpl-nifty-intraday-trend-v1",
            "dataset_path": "data/nifty_sample.csv",
            "initial_capital": 1_000_000.0,
            "slippage_model": "FLAT_0_05",
        },
    )
    assert status == HTTPStatus.OK
    assert start_rep["status"] == "RUNNING"
    run_id = start_rep["run_id"]
    assert run_id.startswith("run_")

    # Poll active run status until completed (or max 5 seconds)
    completed = False
    for _ in range(15):
        time.sleep(0.3)
        poll_status, active_state, _ = _make_request(f"{base_url}/api/runs/active/{run_id}")
        assert poll_status == HTTPStatus.OK
        assert active_state["run_id"] == run_id
        if active_state["status"] == "COMPLETED":
            completed = True
            assert active_state["progress_pct"] == 100.0
            assert active_state["bars_processed"] > 0
            assert len(active_state["equity_curve"]) > 0
            break

    assert completed is True

    # Verify run is now listed in /api/runs
    status, runs_list, _ = _make_request(f"{base_url}/api/runs")
    assert status == HTTPStatus.OK
    assert isinstance(runs_list, list)
    assert any(isinstance(r, dict) and r.get("session_id") == run_id for r in runs_list)

    # Verify dossier retrieval via /api/runs/<id>
    status, dossier, _ = _make_request(f"{base_url}/api/runs/{run_id}")
    assert status == HTTPStatus.OK
    assert isinstance(dossier, dict)
    assert dossier.get("session_id") == run_id
    assert dossier.get("status") == "COMPLETED"


def test_settings_provider_secret_masking_and_testing(web_server: DashboardServer) -> None:
    """Verify credentials remain masked in settings and provider tests succeed."""
    base_url = web_server.url

    # 1. GET /api/settings
    status, settings_data, _ = _make_request(f"{base_url}/api/settings")
    assert status == HTTPStatus.OK
    assert "providers" in settings_data
    providers = settings_data["providers"]

    # Verify Kotak Neo secret masking
    kotak = providers.get("kotak_neo", {})
    masked_key = kotak.get("consumer_key_masked", "")
    assert masked_key == "Not configured" or "***" in masked_key or "••••" in masked_key

    # Verify Gemini secret masking
    gemini = providers.get("gemini", {})
    masked_api_key = gemini.get("api_key_masked", "")
    assert masked_api_key == "Not configured" or "***" in masked_api_key or "••••" in masked_api_key

    # 2. POST /api/settings/providers/test for Kotak Neo
    status, test_rep, _ = _make_request(
        f"{base_url}/api/settings/providers/test",
        method="POST",
        data={"provider": "kotak_neo"},
    )
    assert status == HTTPStatus.OK
    assert test_rep["status"] in ("SUCCESS", "READY", "NOT_CONFIGURED", "SIMULATED_SUCCESS")

    # 3. POST /api/settings/providers/test for Gemini
    status, test_gemini, _ = _make_request(
        f"{base_url}/api/settings/providers/test",
        method="POST",
        data={"provider": "gemini"},
    )
    assert status == HTTPStatus.OK
    assert test_gemini["status"] in ("SUCCESS", "READY", "NOT_CONFIGURED", "SIMULATED_SUCCESS")
