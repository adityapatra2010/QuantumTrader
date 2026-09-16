"""Integration and unit tests for Phase 7 AI Web Workstation REST API routes.

Verifies:
- /api/ai/catalog
- /api/ai/explain/{strategy_id}
- /api/ai/suggest
- /api/ai/review/{strategy_id}
- /api/ai/forecast
- /api/ai/dossier/{strategy_id}
- Path traversal rejection on dataset_path
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Generator
from typing import Any

import pytest

from aditrader.web.server import DashboardServer


@pytest.fixture(scope="module")
def web_server() -> Generator[str, None, None]:
    """Launch ephemeral DashboardServer for route verification."""
    server = DashboardServer(host="127.0.0.1", port=0)
    server.start(background=True)
    base_url = server.url
    yield base_url
    server.stop()


def _request_json(
    url: str,
    method: str = "GET",
    data: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any]]:
    """Helper to perform HTTP JSON request."""
    req = urllib.request.Request(url, method=method)
    req.add_header("Content-Type", "application/json")
    body_bytes = json.dumps(data).encode("utf-8") if data is not None else None

    try:
        with urllib.request.urlopen(req, data=body_bytes, timeout=5.0) as resp:
            status = resp.getcode()
            content = json.loads(resp.read().decode("utf-8"))
            return status, content
    except urllib.error.HTTPError as exc:
        err_content = json.loads(exc.read().decode("utf-8"))
        return exc.code, err_content


def test_api_ai_catalog(web_server: str) -> None:
    """Verify GET /api/ai/catalog returns registered models and security flags."""
    status, payload = _request_json(f"{web_server}/api/ai/catalog")
    assert status == 200
    assert payload["air_gap_enforced"] is True
    assert payload["offline_mode"] is True
    assert payload["provenance_standard"] == "ADR 012"
    assert len(payload["models"]) > 0
    model_ids = [m["model_id"] for m in payload["models"]]
    assert "heuristic-drift-v1" in model_ids


def test_api_ai_explain_success(web_server: str) -> None:
    """Verify GET /api/ai/explain/{id} returns educational explanation with provenance."""
    status, payload = _request_json(f"{web_server}/api/ai/explain/tpl-nifty-bull-call-spread-v1")
    assert status == 200
    assert payload["strategy_name"] == "Nifty Bull Call Spread"
    assert payload["source_type"] == "AI_ADVISORY"
    assert "content" in payload
    assert payload["provenance"]["model_id"] == "strategy-explainer-v1"


def test_api_ai_explain_not_found(web_server: str) -> None:
    """Verify GET /api/ai/explain/{id} returns 404 on missing strategy."""
    status, payload = _request_json(f"{web_server}/api/ai/explain/non-existent-strategy-xyz")
    assert status == 404
    assert "error" in payload


def test_api_ai_suggest_advisory(web_server: str) -> None:
    """Verify POST /api/ai/suggest proposes template adhering to 60/40 selling bias."""
    status, payload = _request_json(
        f"{web_server}/api/ai/suggest",
        method="POST",
        data={"regime": "NORMAL_VOLATILITY", "symbol": "NIFTY"},
    )
    assert status == 200
    assert payload["bias_applied"]["sell_pct"] == 0.60
    assert payload["strategy_name"] == "Nifty Weekly Iron Condor"
    assert payload["is_validated"] is False
    assert payload["validation_status"] == "UNVALIDATED"
    assert payload["provenance"]["input_hash"] is not None


def test_api_ai_suggest_with_validation(web_server: str) -> None:
    """Verify POST /api/ai/suggest with validate=True runs validation gates."""
    status, payload = _request_json(
        f"{web_server}/api/ai/suggest",
        method="POST",
        data={"regime": "HIGH_VOLATILITY", "symbol": "NIFTY", "validate": True},
    )
    assert status == 200
    assert payload["is_validated"] is True
    assert payload["validation_status"] == "APPROVED"


def test_api_ai_review_success(web_server: str) -> None:
    """Verify GET /api/ai/review/{id} returns hostile critique with validation status."""
    status, payload = _request_json(f"{web_server}/api/ai/review/tpl-nifty-iron-condor-v1")
    assert status == 200
    assert payload["validation_status"] == "APPROVED"
    assert payload["source_type"] == "AI_ADVISORY"
    assert "Adversarial Structural Review" in payload["content"]


def test_api_ai_forecast_success(web_server: str) -> None:
    """Verify POST /api/ai/forecast generates step trajectory and bounds."""
    status, payload = _request_json(
        f"{web_server}/api/ai/forecast",
        method="POST",
        data={"symbol": "NIFTY", "horizon": 5, "model": "heuristic-drift-v1"},
    )
    assert status == 200
    assert payload["symbol"] == "NIFTY"
    assert payload["horizon_bars"] == 5
    assert len(payload["trajectory"]) == 5
    assert "current_close" in payload
    assert "target_close" in payload
    assert "direction" in payload
    assert payload["provenance"]["is_deterministic"] is True


def test_api_ai_forecast_path_traversal_blocked(web_server: str) -> None:
    """Verify POST /api/ai/forecast rejects path traversal attempts."""
    status, payload = _request_json(
        f"{web_server}/api/ai/forecast",
        method="POST",
        data={"symbol": "NIFTY", "dataset_path": "/etc/passwd"},
    )
    assert status == 403
    assert "Access denied" in payload["error"]


def test_api_ai_dossier_success(web_server: str) -> None:
    """Verify GET /api/ai/dossier/{id} returns multi-section institutional dossier."""
    status, payload = _request_json(f"{web_server}/api/ai/dossier/tpl-nifty-bull-call-spread-v1")
    assert status == 200
    assert "dossier_id" in payload
    assert "markdown" in payload
    assert "Institutional Quantitative Research Dossier" in payload["markdown"]
    assert len(payload["sections"]) >= 4
    section_titles = [s["title"] for s in payload["sections"]]
    assert any("Executive Overview" in t for t in section_titles)
    assert any("Strategy Mechanism" in t or "Explanation" in t for t in section_titles)
    assert any("Validation Gates" in t for t in section_titles)
