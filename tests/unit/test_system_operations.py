"""Unit tests verifying SystemOperationsService methods across CLI, GUI, and TUI."""

from pathlib import Path

from aditrader.system.operations import SystemOperationsService, _mask_secret


def test_mask_secret() -> None:
    """Verify secret masking logic."""
    assert _mask_secret(None) == "Not configured"
    assert _mask_secret("") == "Not configured"
    assert _mask_secret("123") == "***"
    assert _mask_secret("123456") == "***"
    assert _mask_secret("1234567") == "12***67"
    assert _mask_secret("secret_token_abc") == "se***bc"


def test_run_diagnostics() -> None:
    """Verify run_diagnostics returns structured checks and summary."""
    diag = SystemOperationsService.run_diagnostics()
    assert "overall_status" in diag
    assert diag["overall_status"] in ("READY", "WARNING", "ERROR")
    assert "checks" in diag
    assert isinstance(diag["checks"], list)
    assert len(diag["checks"]) > 0

    categories = {c["category"] for c in diag["checks"]}
    assert "Runtime" in categories
    assert "Storage" in categories
    assert "Database" in categories
    assert "Configuration" in categories


def test_initialize_database() -> None:
    """Verify initialize_database creates tables and stamps schema."""
    res = SystemOperationsService.initialize_database()
    assert res["status"] in ("INITIALIZED", "FAILED")
    assert "tables" in res
    raw_tables = res.get("tables", [])
    assert isinstance(raw_tables, list)
    table_names = [str(t) for t in raw_tables]
    assert "orders" in table_names
    assert "trades" in table_names


def test_search_instruments() -> None:
    """Verify instrument search works with query."""
    res = SystemOperationsService.search_instruments("NIFTY", limit=5)
    assert isinstance(res, list)
    if res:
        assert "symbol" in res[0]


def test_inspect_strategy_content_valid_json() -> None:
    """Verify inspect_strategy_content parses and audits JSON DSL."""
    sample_json = """{
        "name": "Sample Strategy",
        "underlying": "NIFTY",
        "timeframe": "1m",
        "entry_conditions": [],
        "exit_conditions": []
    }"""
    res = SystemOperationsService.inspect_strategy_content(sample_json, "test_strat.json")
    assert res["success"] is True
    assert res["file_path"] == "test_strat.json"
    assert "warnings" in res


def test_inspect_strategy_content_invalid() -> None:
    """Verify inspect_strategy_content handles malformed input."""
    res = SystemOperationsService.inspect_strategy_content("not json or pine script {{{", "bad.txt")
    assert res["success"] is True
    assert "rejection_reasons" in res
    assert len(res["rejection_reasons"]) > 0


def test_run_feed_smoke_test_mock() -> None:
    """Verify mock feed smoke test returns simulated ticks."""
    res = SystemOperationsService.run_feed_smoke_test(
        symbol="NIFTY", ticks=3, timeout=5.0, mock=True
    )
    assert res["symbol"] == "NIFTY"
    assert res["received_ticks"] == 3
    assert len(res["ticks"]) == 3
    assert res["mode"] == "MOCK_REHEARSAL"


def test_get_option_chain_snapshot_mock() -> None:
    """Verify option chain snapshot returns multi-strike ladder with Greeks."""
    res = SystemOperationsService.get_option_chain_snapshot(underlying="NIFTY", count=5, mock=True)
    assert res["underlying"] == "NIFTY"
    assert res["spot_price"] > 0
    assert "strikes" in res
    assert len(res["strikes"]) > 0

    first = res["strikes"][0]
    assert "strike" in first
    assert "ce_ltp" in first
    assert "pe_ltp" in first
    assert "ce_delta" in first
    assert "pe_delta" in first


def test_run_broker_discovery_mock(tmp_path: Path) -> None:
    """Verify broker discovery suite runs in mock mode."""
    res = SystemOperationsService.run_broker_discovery(
        output_dir=str(tmp_path / "discovery"), mock=True
    )
    assert res["mode"] == "OFFLINE_MOCK"
    assert "tests" in res
    assert res["tests_total"] >= 5
