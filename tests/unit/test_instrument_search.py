"""Unit and integration tests for Instrument Search & Selection subsystem."""

import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from aditrader.data.adapters.base import ContractMetadata
from aditrader.data.adapters.kotak_neo import KotakNeoAdapter
from aditrader.data.instruments.index import InstrumentIndex
from aditrader.data.instruments.matcher import (
    extract_underlying,
    parse_query,
    score_contract,
)
from aditrader.data.instruments.models import (
    InstrumentFilter,
    MatchQuality,
)
from aditrader.data.instruments.service import InstrumentSearchService


@pytest.fixture
def sample_contracts() -> list[ContractMetadata]:
    """Representative cross-section of Indian market instruments."""
    exp_dec = datetime(2024, 12, 26, 15, 30, tzinfo=UTC)
    exp_jan = datetime(2025, 1, 30, 15, 30, tzinfo=UTC)

    return [
        # NIFTY Equity & Derivatives
        ContractMetadata(
            symbol="NIFTY",
            trading_symbol="NIFTY 50",
            exchange="NSE",
            instrument_type="EQ",
            lot_size=1,
            tick_size=0.05,
            token="26000",
        ),
        ContractMetadata(
            symbol="NIFTY24DECFUT",
            trading_symbol="NIFTY 26-DEC-2024 FUT",
            exchange="NFO",
            instrument_type="FUTIDX",
            lot_size=25,
            tick_size=0.05,
            token="45000",
            expiry_date=exp_dec,
        ),
        ContractMetadata(
            symbol="NIFTY25JANFUT",
            trading_symbol="NIFTY 30-JAN-2025 FUT",
            exchange="NFO",
            instrument_type="FUTIDX",
            lot_size=25,
            tick_size=0.05,
            token="45010",
            expiry_date=exp_jan,
        ),
        ContractMetadata(
            symbol="NIFTY24DEC24000CE",
            trading_symbol="NIFTY 26-DEC-2024 CE 24000",
            exchange="NFO",
            instrument_type="OPTIDX",
            lot_size=25,
            tick_size=0.05,
            token="45001",
            strike_price=24000.0,
            expiry_date=exp_dec,
            option_type="CE",
        ),
        ContractMetadata(
            symbol="NIFTY24DEC24000PE",
            trading_symbol="NIFTY 26-DEC-2024 PE 24000",
            exchange="NFO",
            instrument_type="OPTIDX",
            lot_size=25,
            tick_size=0.05,
            token="45002",
            strike_price=24000.0,
            expiry_date=exp_dec,
            option_type="PE",
        ),
        ContractMetadata(
            symbol="NIFTY24DEC24200CE",
            trading_symbol="NIFTY 26-DEC-2024 CE 24200",
            exchange="NFO",
            instrument_type="OPTIDX",
            lot_size=25,
            tick_size=0.05,
            token="45003",
            strike_price=24200.0,
            expiry_date=exp_dec,
            option_type="CE",
        ),
        ContractMetadata(
            symbol="NIFTY24DEC23800PE",
            trading_symbol="NIFTY 26-DEC-2024 PE 23800",
            exchange="NFO",
            instrument_type="OPTIDX",
            lot_size=25,
            tick_size=0.05,
            token="45004",
            strike_price=23800.0,
            expiry_date=exp_dec,
            option_type="PE",
        ),
        # RELIANCE Equity & Derivatives
        ContractMetadata(
            symbol="RELIANCE",
            trading_symbol="RELIANCE-EQ",
            exchange="NSE",
            instrument_type="EQ",
            lot_size=1,
            tick_size=0.05,
            token="2885",
        ),
        ContractMetadata(
            symbol="RELIANCE24DECFUT",
            trading_symbol="RELIANCE 26-DEC-2024 FUT",
            exchange="NFO",
            instrument_type="FUTSTK",
            lot_size=250,
            tick_size=0.05,
            token="55000",
            expiry_date=exp_dec,
        ),
        ContractMetadata(
            symbol="RELIANCE24DEC2500CE",
            trading_symbol="RELIANCE 26-DEC-2024 CE 2500",
            exchange="NFO",
            instrument_type="OPTSTK",
            lot_size=250,
            tick_size=0.05,
            token="55001",
            strike_price=2500.0,
            expiry_date=exp_dec,
            option_type="CE",
        ),
        ContractMetadata(
            symbol="RELIANCE24DEC2500PE",
            trading_symbol="RELIANCE 26-DEC-2024 PE 2500",
            exchange="NFO",
            instrument_type="OPTSTK",
            lot_size=250,
            tick_size=0.05,
            token="55002",
            strike_price=2500.0,
            expiry_date=exp_dec,
            option_type="PE",
        ),
        # TCS Cash Equity only
        ContractMetadata(
            symbol="TCS",
            trading_symbol="TCS-EQ",
            exchange="NSE",
            instrument_type="EQ",
            lot_size=1,
            tick_size=0.05,
            token="11536",
        ),
    ]


# ----------------------------------------------------------------------
# 1. Matcher and Underlying Extraction Tests
# ----------------------------------------------------------------------


def test_extract_underlying(sample_contracts: list[ContractMetadata]) -> None:
    # EQ
    assert extract_underlying(sample_contracts[0]) == "NIFTY"
    assert extract_underlying(sample_contracts[7]) == "RELIANCE"
    assert extract_underlying(sample_contracts[11]) == "TCS"

    # Derivatives
    assert extract_underlying(sample_contracts[1]) == "NIFTY"  # NIFTY FUT
    assert extract_underlying(sample_contracts[3]) == "NIFTY"  # NIFTY CE
    assert extract_underlying(sample_contracts[9]) == "RELIANCE"  # RELIANCE CE


def test_parse_query_structured() -> None:
    q1 = parse_query("NIFTY 24000 CE")
    assert q1.underlying == "NIFTY"
    assert q1.strike == 24000.0
    assert q1.option_type == "CE"
    assert q1.is_future is False

    q2 = parse_query("reliance fut")
    assert q2.underlying == "RELIANCE"
    assert q2.is_future is True
    assert q2.strike is None

    q3 = parse_query("24000 pe")
    assert q3.strike == 24000.0
    assert q3.option_type == "PE"


def test_score_contract_exact_token(sample_contracts: list[ContractMetadata]) -> None:
    c = sample_contracts[0]  # NIFTY token 26000
    parsed = parse_query("26000")
    scored = score_contract(c, "26000", parsed, "NIFTY")
    assert scored is not None
    score, quality, field = scored
    assert score == 100.0
    assert quality == MatchQuality.EXACT_TOKEN
    assert field == "token"


def test_score_contract_exact_symbol(sample_contracts: list[ContractMetadata]) -> None:
    c = sample_contracts[0]  # NIFTY
    parsed = parse_query("NIFTY")
    scored = score_contract(c, "NIFTY", parsed, "NIFTY")
    assert scored is not None
    score, quality, _ = scored
    assert score >= 96.0


def test_score_contract_structured_derivative(sample_contracts: list[ContractMetadata]) -> None:
    c = sample_contracts[3]  # NIFTY 24000 CE
    parsed = parse_query("NIFTY 24000 CE")
    scored = score_contract(c, "NIFTY 24000 CE", parsed, "NIFTY")
    assert scored is not None
    score, quality, _ = scored
    assert score >= 90.0
    assert quality == MatchQuality.STRUCTURED_DERIVATIVE


# ----------------------------------------------------------------------
# 2. Index Construction & Hierarchical Resolution Tests
# ----------------------------------------------------------------------


def test_index_initialization(sample_contracts: list[ContractMetadata]) -> None:
    idx = InstrumentIndex(sample_contracts)
    assert idx.count() == len(sample_contracts)

    assert "NIFTY" in idx.get_underlyings()
    assert "RELIANCE" in idx.get_underlyings()
    assert "TCS" in idx.get_underlyings()


def test_index_get_by_symbol_and_token(sample_contracts: list[ContractMetadata]) -> None:
    idx = InstrumentIndex(sample_contracts)

    nifty_eq = idx.get_by_symbol("NIFTY")
    assert nifty_eq is not None
    assert nifty_eq.instrument_type == "EQ"
    assert nifty_eq.token == "26000"

    c_token = idx.get_by_token("45001", exchange="NFO")
    assert c_token is not None
    assert c_token.symbol == "NIFTY24DEC24000CE"


def test_index_derivatives_hierarchy(sample_contracts: list[ContractMetadata]) -> None:
    idx = InstrumentIndex(sample_contracts)

    h_nifty = idx.get_derivatives_hierarchy("NIFTY")
    assert h_nifty is not None
    assert h_nifty.has_equity is True
    assert h_nifty.has_futures is True
    assert len(h_nifty.futures_expiries) == 2  # Dec & Jan
    assert h_nifty.has_options is True
    assert len(h_nifty.options_expiries) == 1  # Dec
    assert len(h_nifty.strikes_by_expiry["2024-12-26"]) == 3  # 23800, 24000, 24200
    assert h_nifty.lot_sizes["OPT"] == 25
    assert h_nifty.lot_sizes["FUT"] == 25

    h_tcs = idx.get_derivatives_hierarchy("TCS")
    assert h_tcs is not None
    assert h_tcs.has_equity is True
    assert h_tcs.has_futures is False
    assert h_tcs.has_options is False


def test_index_resolve_derivative(sample_contracts: list[ContractMetadata]) -> None:
    idx = InstrumentIndex(sample_contracts)
    exp_dec = datetime(2024, 12, 26, 15, 30, tzinfo=UTC)

    # Resolve futures
    fut = idx.resolve_derivative("NIFTY", "FUT", exp_dec)
    assert fut is not None
    assert fut.symbol == "NIFTY24DECFUT"

    # Resolve Call option
    ce = idx.resolve_derivative("NIFTY", "CE", exp_dec, strike=24000.0)
    assert ce is not None
    assert ce.symbol == "NIFTY24DEC24000CE"

    # Resolve Put option
    pe = idx.resolve_derivative("NIFTY", "PE", exp_dec, strike=24000.0)
    assert pe is not None
    assert pe.symbol == "NIFTY24DEC24000PE"

    # Non-existent strike returns None
    missing = idx.resolve_derivative("NIFTY", "CE", exp_dec, strike=99999.0)
    assert missing is None


def test_index_get_option_pair(sample_contracts: list[ContractMetadata]) -> None:
    idx = InstrumentIndex(sample_contracts)
    exp_dec = datetime(2024, 12, 26, 15, 30, tzinfo=UTC)

    ce, pe = idx.get_option_pair("NIFTY", exp_dec, strike=24000.0)
    assert ce is not None and ce.option_type == "CE"
    assert pe is not None and pe.option_type == "PE"


# ----------------------------------------------------------------------
# 3. Search Queries & Deterministic Ranking Tests
# ----------------------------------------------------------------------


def test_search_underlying_equity_priority(sample_contracts: list[ContractMetadata]) -> None:
    idx = InstrumentIndex(sample_contracts)
    results = idx.search("NIFTY")

    assert len(results) > 0
    # Top result should be Cash Equity when generic root name is queried
    top = results[0]
    assert top.contract.symbol == "NIFTY"
    assert top.contract.instrument_type == "EQ"


def test_search_prefix_symbol(sample_contracts: list[ContractMetadata]) -> None:
    idx = InstrumentIndex(sample_contracts)
    results = idx.search("REL")

    assert len(results) > 0
    top = results[0]
    assert top.contract.symbol == "RELIANCE"
    assert top.match_quality in (MatchQuality.PREFIX_SYMBOL, MatchQuality.PREFIX_TRADING_SYMBOL)


def test_search_structured_derivative_query(sample_contracts: list[ContractMetadata]) -> None:
    idx = InstrumentIndex(sample_contracts)
    results = idx.search("NIFTY 24000 CE")

    assert len(results) > 0
    top = results[0]
    assert top.contract.symbol == "NIFTY24DEC24000CE"
    assert top.score >= 90.0


def test_search_filters(sample_contracts: list[ContractMetadata]) -> None:
    idx = InstrumentIndex(sample_contracts)

    # Filter by Exchange
    nse_only = idx.search("NIFTY", filters=InstrumentFilter(exchange="NSE"))
    assert all(r.contract.exchange == "NSE" for r in nse_only)
    assert len(nse_only) == 1

    # Filter by Instrument Types
    futs_only = idx.search("NIFTY", filters=InstrumentFilter(instrument_types=["FUTIDX"]))
    assert all(r.contract.instrument_type == "FUTIDX" for r in futs_only)
    assert len(futs_only) == 2

    # Filter by Strike Range
    strikes_filtered = idx.search(
        "NIFTY",
        filters=InstrumentFilter(strike_min=24100.0, strike_max=24300.0),
    )
    assert len(strikes_filtered) == 1
    assert strikes_filtered[0].contract.strike_price == 24200.0


def test_search_fuzzy_subsequence(sample_contracts: list[ContractMetadata]) -> None:
    idx = InstrumentIndex(sample_contracts)
    results = idx.search("relce")  # subsequence of RELIANCE

    assert len(results) > 0
    assert any("RELIANCE" in r.contract.symbol for r in results)


# ----------------------------------------------------------------------
# 4. Service Layer & Parquet Persistence Tests
# ----------------------------------------------------------------------


def test_service_parquet_roundtrip(sample_contracts: list[ContractMetadata]) -> None:
    svc = InstrumentSearchService(contracts=sample_contracts)

    with tempfile.TemporaryDirectory() as tmpdir:
        pq_path = Path(tmpdir) / "scrip_master.parquet"
        saved = svc.save_to_parquet(pq_path)
        assert saved.is_file()

        # Load into fresh service
        svc2 = InstrumentSearchService()
        count = svc2.load_from_parquet(pq_path)
        assert count == len(sample_contracts)
        assert svc2.index.count() == len(sample_contracts)

        # Verify search works identically
        res = svc2.search("NIFTY 24000 CE")
        assert len(res) > 0
        assert res[0].contract.symbol == "NIFTY24DEC24000CE"


def test_service_with_kotak_neo_adapter() -> None:
    adapter = KotakNeoAdapter(mock_mode=True)
    adapter.authenticate()

    svc = InstrumentSearchService(adapter=adapter)
    loaded = svc.load_from_adapter()
    assert loaded >= 3
    assert "NIFTY" in svc.get_underlyings()
