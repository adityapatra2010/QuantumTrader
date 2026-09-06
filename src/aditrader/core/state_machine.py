"""Order state machine governing valid order lifecycle transitions."""

from datetime import datetime

from aditrader.core.models.enums import OrderStatus
from aditrader.core.models.order import Order


class InvalidOrderStateTransitionError(Exception):
    """Raised when an illegal order state transition is attempted."""

    def __init__(self, from_state: OrderStatus, to_state: OrderStatus, order_id: str):
        self.from_state = from_state
        self.to_state = to_state
        self.order_id = order_id
        super().__init__(
            f"Cannot transition order '{order_id}' from {from_state.value} to {to_state.value}"
        )


class OrderStateMachine:
    """State transition validator and factory for immutable orders."""

    # Explicit transition matrix
    _ALLOWED_TRANSITIONS: dict[OrderStatus, set[OrderStatus]] = {
        OrderStatus.CREATED: {
            OrderStatus.SUBMITTED,
            OrderStatus.REJECTED,
        },
        OrderStatus.SUBMITTED: {
            OrderStatus.FILLED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
        },
        OrderStatus.PARTIALLY_FILLED: {
            OrderStatus.FILLED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.CANCELLED,
        },
        OrderStatus.FILLED: set(),  # Terminal state
        OrderStatus.CANCELLED: set(),  # Terminal state
        OrderStatus.REJECTED: set(),  # Terminal state
    }

    @classmethod
    def can_transition(cls, from_status: OrderStatus, to_status: OrderStatus) -> bool:
        """Check if a transition between two states is valid."""
        return to_status in cls._ALLOWED_TRANSITIONS.get(from_status, set())

    @classmethod
    def transition(
        cls,
        order: Order,
        new_status: OrderStatus,
        *,
        timestamp: datetime,
        filled_qty: int | None = None,
        average_fill_price: float | None = None,
        rejection_reason: str | None = None,
    ) -> Order:
        """
        Validate and apply a state transition to an immutable order.

        Returns a new immutable Order instance with updated status and audit fields.
        """
        if not cls.can_transition(order.status, new_status):
            raise InvalidOrderStateTransitionError(order.status, new_status, order.order_id)

        # Compute updated fill quantities
        next_filled_qty = order.filled_qty if filled_qty is None else filled_qty
        next_avg_price = (
            order.average_fill_price if average_fill_price is None else average_fill_price
        )
        next_rejection_reason = (
            rejection_reason if new_status == OrderStatus.REJECTED else order.rejection_reason
        )

        return order.model_copy(
            update={
                "status": new_status,
                "updated_at": timestamp,
                "filled_qty": next_filled_qty,
                "average_fill_price": next_avg_price,
                "rejection_reason": next_rejection_reason,
            }
        )
