"""Unit tests verifying Broker Adapter interfaces, Kotak Neo scrip discovery, and security isolation."""

from datetime import datetime

import pytest

from aditrader.core.models.market_data import Tick
from aditrader.data.adapters.kotak_neo import KotakNeoAdapter
from aditrader.data.session import EXCHANGE_TIMEZONE


def test_broker_adapter_air_gap_security_veto() -> None:
    """Verify broker adapters programmatically prohibit real order execution (ADR 002)."""
    adapter = KotakNeoAdapter(mock_mode=True)
    adapter.authenticate()

    with pytest.raises(NotImplementedError, match="CRITICAL SECURITY VETO"):
        adapter.place_order(symbol="NIFTY", qty=50)


def test_kotak_neo_scrip_master_discovery() -> None:
    """Verify scrip master retrieval and normalization into ContractMetadata."""
    adapter = KotakNeoAdapter(mock_mode=True)
    adapter.authenticate()

    contracts = adapter.fetch_scrip_master()
    assert len(contracts) >= 3

    symbols = {c.symbol for c in contracts}
    assert "NIFTY" in symbols
    assert "NIFTY24DEC24000CE" in symbols
    assert "NIFTY24DEC24000PE" in symbols

    ce_contract = next(c for c in contracts if c.symbol == "NIFTY24DEC24000CE")
    assert ce_contract.strike_price == 24000.0
    assert ce_contract.option_type == "CE"
    assert ce_contract.lot_size == 25


def test_kotak_neo_parse_csv_row() -> None:
    """Verify parsing raw Kotak Neo dictionary rows into ContractMetadata."""
    adapter = KotakNeoAdapter(mock_mode=True)
    raw_row = {
        "pSymbol": "BANKNIFTY24DEC50000PE",
        "pTrdSymbol": "BANKNIFTY 26-DEC-2024 PE 50000",
        "pExchSeg": "NFO",
        "pInstType": "OPTIDX",
        "pSymbolToken": "98765",
        "pLotSize": "15",
        "pTickSize": "0.05",
        "pStrikePrice": "50000.0",
        "pExpiryDate": "26-Dec-2024",
        "pOptionType": "PE",
    }

    contract = adapter.parse_scrip_csv_row(raw_row)
    assert contract.symbol == "BANKNIFTY24DEC50000PE"
    assert contract.exchange == "NFO"
    assert contract.lot_size == 15
    assert contract.strike_price == 50000.0
    assert contract.option_type == "PE"
    assert contract.expiry_date is not None
    assert contract.expiry_date.year == 2024
    assert contract.expiry_date.month == 12
    assert contract.expiry_date.day == 26


def test_kotak_neo_tick_subscription_dispatch() -> None:
    """Verify tick subscriptions and callback reception."""
    adapter = KotakNeoAdapter(mock_mode=True)
    adapter.authenticate()

    received_ticks: list[Tick] = []

    def on_tick(t: Tick) -> None:
        received_ticks.append(t)

    adapter.subscribe_ticks(["NIFTY"], on_tick)

    t0 = datetime(2024, 12, 2, 9, 15, 0, tzinfo=EXCHANGE_TIMEZONE)
    tick = Tick(
        symbol="NIFTY", ltp=24000.0, bid=23999.0, ask=24001.0, volume=100, oi=50000, timestamp=t0
    )

    adapter.emit_mock_tick(tick)
    assert len(received_ticks) == 1
    assert received_ticks[0] == tick

    # Unsubscribe
    adapter.unsubscribe_ticks(["NIFTY"])
    adapter.emit_mock_tick(tick)
    assert len(received_ticks) == 1  # No second tick received
