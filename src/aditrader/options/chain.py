"""Dynamic option chain ladder construction, ATM strike discovery, and Greeks derivation."""

from datetime import datetime
from typing import Any

from aditrader.data.adapters.base import ContractMetadata
from aditrader.data.session import normalize_to_ist
from aditrader.options.greeks import calculate_greeks
from aditrader.options.iv import DEFAULT_RISK_FREE_RATE, solve_implied_volatility
from aditrader.options.models import ChainRow, ChainStrikeData


class OptionChainEngine:
    """
    Constructs normalized option chains dynamically from scrip master contracts (ADR 009).

    Indian Market Specifics:
    - Expirations and lot sizes are derived strictly from ContractMetadata, never hardcoded.
    - Resolves both Index (NIFTY/BANKNIFTY) and Stock options into uniform ChainRow ladders.
    """

    @staticmethod
    def get_available_expiries(contracts: list[ContractMetadata]) -> list[datetime]:
        """Extract unique expiration datetimes sorted ascending from scrip master contracts."""
        expiries: set[datetime] = set()
        for c in contracts:
            if c.expiry_date is not None:
                expiries.add(normalize_to_ist(c.expiry_date))
        return sorted(expiries)

    @staticmethod
    def get_atm_strike(spot_price: float, available_strikes: list[float]) -> float:
        """Identify the At-The-Money (ATM) strike closest to the current underlying spot price."""
        if not available_strikes:
            raise ValueError("No strikes provided for ATM strike determination")
        return min(available_strikes, key=lambda k: abs(k - spot_price))

    @classmethod
    def build_chain(
        cls,
        contracts: list[ContractMetadata],
        spot_price: float,
        target_expiry: datetime,
        quotes: dict[str, dict[str, Any]] | None = None,
        evaluation_time: datetime | None = None,
        risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
        dividend_yield: float = 0.0,
    ) -> list[ChainRow]:
        """
        Construct structured ChainRow records for a specific expiry date.

        Calculates IV and Black-Scholes Greeks for each strike where quote LTP is available.
        """
        now = (
            normalize_to_ist(evaluation_time)
            if evaluation_time
            else normalize_to_ist(datetime.now())
        )
        target_exp_ist = normalize_to_ist(target_expiry)

        # Compute time to expiry in annual years (calendar basis / 365.0)
        t_seconds = max(0.0, (target_exp_ist - now).total_seconds())
        time_to_expiry = t_seconds / (365.0 * 86400.0)

        # Filter contracts for this target expiry and separate by strike & type
        strike_map: dict[float, dict[str, ContractMetadata]] = {}
        for c in contracts:
            if c.expiry_date is None or c.strike_price is None or c.option_type is None:
                continue

            c_exp_ist = normalize_to_ist(c.expiry_date)
            if c_exp_ist.date() == target_exp_ist.date():
                k = float(c.strike_price)
                if k not in strike_map:
                    strike_map[k] = {}
                strike_map[k][c.option_type] = c

        all_quotes = quotes or {}
        rows: list[ChainRow] = []

        for strike in sorted(strike_map.keys()):
            contracts_at_k = strike_map[strike]
            ce_contract = contracts_at_k.get("CE")
            pe_contract = contracts_at_k.get("PE")

            # Build Call side
            call_data: ChainStrikeData | None = None
            if ce_contract:
                q = all_quotes.get(ce_contract.symbol, all_quotes.get(ce_contract.token, {}))
                ltp = float(q.get("ltp", 0.0))
                bid = float(q["bid"]) if "bid" in q and q["bid"] is not None else None
                ask = float(q["ask"]) if "ask" in q and q["ask"] is not None else None
                vol = int(q.get("volume", 0))
                oi = int(q.get("oi", 0))

                iv = None
                greeks = None
                if ltp > 0.0 and time_to_expiry > 0.0:
                    iv = solve_implied_volatility(
                        market_price=ltp,
                        spot=spot_price,
                        strike=strike,
                        time_to_expiry=time_to_expiry,
                        risk_free_rate=risk_free_rate,
                        dividend_yield=dividend_yield,
                        option_type="CE",
                    )
                    if iv is not None and iv > 0.0:
                        greeks = calculate_greeks(
                            spot=spot_price,
                            strike=strike,
                            time_to_expiry=time_to_expiry,
                            volatility=iv,
                            risk_free_rate=risk_free_rate,
                            dividend_yield=dividend_yield,
                            option_type="CE",
                        )

                call_data = ChainStrikeData(
                    ltp=ltp,
                    bid=bid,
                    ask=ask,
                    volume=vol,
                    oi=oi,
                    iv=iv,
                    greeks=greeks,
                )

            # Build Put side
            put_data: ChainStrikeData | None = None
            if pe_contract:
                q = all_quotes.get(pe_contract.symbol, all_quotes.get(pe_contract.token, {}))
                ltp = float(q.get("ltp", 0.0))
                bid = float(q["bid"]) if "bid" in q and q["bid"] is not None else None
                ask = float(q["ask"]) if "ask" in q and q["ask"] is not None else None
                vol = int(q.get("volume", 0))
                oi = int(q.get("oi", 0))

                iv = None
                greeks = None
                if ltp > 0.0 and time_to_expiry > 0.0:
                    iv = solve_implied_volatility(
                        market_price=ltp,
                        spot=spot_price,
                        strike=strike,
                        time_to_expiry=time_to_expiry,
                        risk_free_rate=risk_free_rate,
                        dividend_yield=dividend_yield,
                        option_type="PE",
                    )
                    if iv is not None and iv > 0.0:
                        greeks = calculate_greeks(
                            spot=spot_price,
                            strike=strike,
                            time_to_expiry=time_to_expiry,
                            volatility=iv,
                            risk_free_rate=risk_free_rate,
                            dividend_yield=dividend_yield,
                            option_type="PE",
                        )

                put_data = ChainStrikeData(
                    ltp=ltp,
                    bid=bid,
                    ask=ask,
                    volume=vol,
                    oi=oi,
                    iv=iv,
                    greeks=greeks,
                )

            row = ChainRow(
                strike=strike,
                expiry=target_exp_ist,
                call=call_data,
                put=put_data,
            )
            rows.append(row)

        return rows
