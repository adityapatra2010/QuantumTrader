"""Unit tests verifying OptionChainEngine strike ladders, dynamic discovery, and ATM detection."""

from datetime import UTC, datetime

from aditrader.data.adapters.base import ContractMetadata
from aditrader.options.chain import OptionChainEngine


def test_chain_engine_available_expiries_and_atm_strike() -> None:
    """Verify dynamic discovery of expirations and nearest ATM strike."""
    exp1 = datetime(2024, 12, 19, 15, 30, tzinfo=UTC)
    exp2 = datetime(2024, 12, 26, 15, 30, tzinfo=UTC)

    contracts = [
        ContractMetadata(
            symbol="NIFTY24DEC1924000CE",
            trading_symbol="NIFTY 19-DEC-2024 CE 24000",
            exchange="NFO",
            instrument_type="OPTIDX",
            lot_size=25,
            token="101",
            strike_price=24000.0,
            expiry_date=exp1,
            option_type="CE",
        ),
        ContractMetadata(
            symbol="NIFTY24DEC2624000CE",
            trading_symbol="NIFTY 26-DEC-2024 CE 24000",
            exchange="NFO",
            instrument_type="OPTIDX",
            lot_size=25,
            token="102",
            strike_price=24000.0,
            expiry_date=exp2,
            option_type="CE",
        ),
    ]

    discovered_expiries = OptionChainEngine.get_available_expiries(contracts)
    assert len(discovered_expiries) == 2
    assert discovered_expiries[0].date() == exp1.date()
    assert discovered_expiries[1].date() == exp2.date()

    # ATM Strike Discovery
    strikes = [23800.0, 23900.0, 24000.0, 24100.0, 24200.0]
    atm_at_24018 = OptionChainEngine.get_atm_strike(24018.0, strikes)
    assert atm_at_24018 == 24000.0

    atm_at_24075 = OptionChainEngine.get_atm_strike(24075.0, strikes)
    assert atm_at_24075 == 24100.0


def test_build_chain_with_quotes_and_greeks() -> None:
    """Verify build_chain constructs sorted strike ladder and computes IV and Greeks."""
    exp = datetime(2024, 12, 26, 15, 30, tzinfo=UTC)
    eval_time = datetime(2024, 12, 1, 9, 15, tzinfo=UTC)

    contracts = [
        ContractMetadata(
            symbol="NIFTY24DEC23900CE",
            trading_symbol="NIFTY 26-DEC-2024 CE 23900",
            exchange="NFO",
            instrument_type="OPTIDX",
            lot_size=25,
            token="101",
            strike_price=23900.0,
            expiry_date=exp,
            option_type="CE",
        ),
        ContractMetadata(
            symbol="NIFTY24DEC23900PE",
            trading_symbol="NIFTY 26-DEC-2024 PE 23900",
            exchange="NFO",
            instrument_type="OPTIDX",
            lot_size=25,
            token="102",
            strike_price=23900.0,
            expiry_date=exp,
            option_type="PE",
        ),
        ContractMetadata(
            symbol="NIFTY24DEC24000CE",
            trading_symbol="NIFTY 26-DEC-2024 CE 24000",
            exchange="NFO",
            instrument_type="OPTIDX",
            lot_size=25,
            token="103",
            strike_price=24000.0,
            expiry_date=exp,
            option_type="CE",
        ),
        ContractMetadata(
            symbol="NIFTY24DEC24000PE",
            trading_symbol="NIFTY 26-DEC-2024 PE 24000",
            exchange="NFO",
            instrument_type="OPTIDX",
            lot_size=25,
            token="104",
            strike_price=24000.0,
            expiry_date=exp,
            option_type="PE",
        ),
    ]

    quotes = {
        "NIFTY24DEC24000CE": {
            "ltp": 250.0,
            "volume": 5000,
            "oi": 80000,
            "bid": 249.5,
            "ask": 250.5,
        },
        "NIFTY24DEC24000PE": {
            "ltp": 160.0,
            "volume": 4200,
            "oi": 65000,
            "bid": 159.5,
            "ask": 160.5,
        },
        "NIFTY24DEC23900CE": {"ltp": 320.0, "volume": 3000, "oi": 40000},
        "NIFTY24DEC23900PE": {"ltp": 120.0, "volume": 2800, "oi": 35000},
    }

    chain = OptionChainEngine.build_chain(
        contracts=contracts,
        spot_price=24000.0,
        target_expiry=exp,
        quotes=quotes,
        evaluation_time=eval_time,
    )

    assert len(chain) == 2
    # Verify strikes sorted ascending
    assert chain[0].strike == 23900.0
    assert chain[1].strike == 24000.0

    # Verify ATM strike data and Greeks
    atm_row = chain[1]
    assert atm_row.call is not None
    assert atm_row.call.ltp == 250.0
    assert atm_row.call.iv is not None
    assert 0.05 <= atm_row.call.iv <= 0.50
    assert atm_row.call.greeks is not None
    assert 0.40 <= atm_row.call.greeks.delta <= 0.65

    assert atm_row.put is not None
    assert atm_row.put.ltp == 160.0
    assert atm_row.put.iv is not None
    assert atm_row.put.greeks is not None
    assert -0.65 <= atm_row.put.greeks.delta <= -0.40
