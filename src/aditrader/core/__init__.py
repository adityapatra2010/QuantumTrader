"""Core trading domain, paper broker, and state execution engine."""

from aditrader.core.broker import PaperBroker
from aditrader.core.costs import CostCalculator, IndianMarketCharges, SlippageModel
from aditrader.core.models import (
    AccountBalance,
    Bar,
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
    Signal,
    SignalDirection,
    Tick,
    Trade,
)
from aditrader.core.risk import (
    RiskCheckResult,
    RiskEngine,
    RiskLimits,
    RiskRejectionReason,
)
from aditrader.core.state_machine import (
    InvalidOrderStateTransitionError,
    OrderStateMachine,
)

__all__ = [
    "AccountBalance",
    "Bar",
    "CostCalculator",
    "IndianMarketCharges",
    "InvalidOrderStateTransitionError",
    "Order",
    "OrderSide",
    "OrderStatus",
    "OrderStateMachine",
    "OrderType",
    "PaperBroker",
    "Position",
    "RiskCheckResult",
    "RiskEngine",
    "RiskLimits",
    "RiskRejectionReason",
    "Signal",
    "SignalDirection",
    "SlippageModel",
    "Tick",
    "Trade",
]
