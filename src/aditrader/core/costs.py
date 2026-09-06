"""Indian market statutory charges and slippage calculations."""

from dataclasses import dataclass
from typing import Literal

from aditrader.core.models.enums import OrderSide

InstrumentClass = Literal["OPTIONS", "FUTURES", "EQUITY_INTRADAY", "EQUITY_DELIVERY"]


@dataclass(frozen=True)
class IndianMarketCharges:
    """Breakdown of regulatory fees and taxes in Indian markets."""

    brokerage: float
    stt: float
    exchange_charges: float
    sebi_charges: float
    stamp_duty: float
    gst: float
    total_charges: float


class CostCalculator:
    """Statutory cost estimator enforcing NSE regulatory tax schedules."""

    # Regulatory Rates
    GST_RATE: float = 0.18  # 18% GST on (Brokerage + Exchange Charges + SEBI Fees)
    SEBI_RATE: float = 0.000001  # ₹10 per crore (0.0001%)

    @classmethod
    def calculate(
        cls,
        *,
        side: OrderSide,
        qty: int,
        price: float,
        instrument: InstrumentClass = "OPTIONS",
        brokerage_per_order: float = 20.0,
    ) -> IndianMarketCharges:
        """
        Compute accurate statutory taxes according to NSE rules.

        - STT: Options (0.1% on Sell premium), Futures (0.02% on Sell), Equity Intraday (0.025% on Sell).
        - Exchange charges: Options (0.05% on premium turnover), Futures (0.002%), Equity (0.00345%).
        - Stamp Duty: Buy side only (Options: 0.003%, Futures: 0.002%, Equity Delivery: 0.015%).
        - GST: 18% on (Brokerage + Exchange + SEBI).
        """
        turnover = float(qty) * price
        brokerage = brokerage_per_order

        # 1. Securities Transaction Tax (STT)
        stt = 0.0
        if side == OrderSide.SELL:
            if instrument == "OPTIONS":
                stt = round(turnover * 0.001, 2)  # 0.1% on sell premium
            elif instrument == "FUTURES":
                stt = round(turnover * 0.0002, 2)  # 0.02% on sell
            elif instrument == "EQUITY_INTRADAY":
                stt = round(turnover * 0.00025, 2)  # 0.025% on sell
            elif instrument == "EQUITY_DELIVERY":
                stt = round(turnover * 0.001, 2)  # 0.1%
        elif side == OrderSide.BUY and instrument == "EQUITY_DELIVERY":
            stt = round(turnover * 0.001, 2)

        # 2. Exchange Turnover Charges
        if instrument == "OPTIONS":
            exchange_charges = round(turnover * 0.0005, 2)  # 0.05% of premium turnover
        elif instrument == "FUTURES":
            exchange_charges = round(turnover * 0.00002, 2)  # 0.002%
        else:
            exchange_charges = round(turnover * 0.0000345, 2)  # 0.00345%

        # 3. SEBI Turnover Charges
        sebi_charges = round(turnover * cls.SEBI_RATE, 2)

        # 4. Stamp Duty (Buy Side Only)
        stamp_duty = 0.0
        if side == OrderSide.BUY:
            if instrument == "OPTIONS":
                stamp_duty = round(turnover * 0.00003, 2)  # 0.003%
            elif instrument == "FUTURES":
                stamp_duty = round(turnover * 0.00002, 2)  # 0.002%
            elif instrument == "EQUITY_DELIVERY":
                stamp_duty = round(turnover * 0.00015, 2)  # 0.015%
            else:
                stamp_duty = round(turnover * 0.00003, 2)

        # 5. GST (18% on Brokerage + Exchange + SEBI)
        taxable_base = brokerage + exchange_charges + sebi_charges
        gst = round(taxable_base * cls.GST_RATE, 2)

        total = round(brokerage + stt + exchange_charges + sebi_charges + stamp_duty + gst, 2)

        return IndianMarketCharges(
            brokerage=brokerage,
            stt=stt,
            exchange_charges=exchange_charges,
            sebi_charges=sebi_charges,
            stamp_duty=stamp_duty,
            gst=gst,
            total_charges=total,
        )


class SlippageModel:
    """Configurable slippage simulation applying market friction penalties."""

    def __init__(self, fixed_points: float = 0.0, percentage: float = 0.0005):
        """
        Initialize slippage model.

        :param fixed_points: Absolute slippage points to add/subtract.
        :param percentage: Fraction of execution price (default 0.05% / 5 bps).
        """
        self.fixed_points = max(0.0, fixed_points)
        self.percentage = max(0.0, percentage)

    def calculate_fill_price(self, price: float, side: OrderSide) -> tuple[float, float]:
        """
        Calculate realistic fill price and estimated slippage penalty.

        Returns (fill_price, slippage_amount).
        """
        slippage_amount = round((price * self.percentage) + self.fixed_points, 2)
        if side == OrderSide.BUY:
            fill_price = round(price + slippage_amount, 2)
        else:
            fill_price = round(max(0.05, price - slippage_amount), 2)
        return fill_price, slippage_amount
