"""Market data quality auditing, envelope validation, and anomaly detection.

Guarantees:
- Impossible OHLC relationships rejected
- Timestamp ordering and session boundary enforcement
- Crossed bid/ask quotes and negative volume/OI detection
- Transparent reporting without silent corruption or data repair
"""

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict, Field

from aditrader.core.models.market_data import Bar, Tick
from aditrader.data.session import is_market_open


class DataQualityError(ValueError):
    """Raised when market data violates strict physical or exchange validity rules."""


class DataQualityWarning(UserWarning):
    """Warning emitted for non-fatal market data anomalies or off-session observations."""


class DataQualityReport(BaseModel):
    """Deterministic audit summary of a validated market data sequence."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    total_records: int = Field(ge=0, description="Total observations inspected")
    valid_records: int = Field(ge=0, description="Number of fully compliant observations")
    errors: list[str] = Field(default_factory=list, description="Critical validity violations")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal data warnings")
    has_duplicates: bool = Field(
        default=False, description="True if identical timestamp observations detected"
    )
    has_out_of_order: bool = Field(
        default=False, description="True if chronological ordering violations detected"
    )
    has_session_violations: bool = Field(
        default=False, description="True if records outside NSE trading hours detected"
    )

    @property
    def is_clean(self) -> bool:
        """Return True if sequence contains zero errors and zero out-of-order anomalies."""
        return len(self.errors) == 0 and not self.has_out_of_order


class MarketDataQualityValidator:
    """Validator performing deterministic checks on individual observations and sequences."""

    @classmethod
    def validate_bar(
        cls,
        bar: Bar,
        strict: bool = False,
        session_check: bool = False,
    ) -> list[str]:
        """Validate an individual Bar against physical and exchange constraints.

        Returns list of error messages. If strict=True, raises DataQualityError on first error.
        """
        errors: list[str] = []

        # 1. Price envelope checks
        if bar.open <= 0.0 or bar.high <= 0.0 or bar.low <= 0.0 or bar.close <= 0.0:
            errors.append(
                f"Bar prices must be strictly positive: O={bar.open}, H={bar.high}, L={bar.low}, C={bar.close}"
            )

        if bar.high < bar.low:
            errors.append(f"Impossible OHLC: High ({bar.high}) cannot be less than Low ({bar.low})")

        if bar.high < max(bar.open, bar.close):
            errors.append(
                f"Impossible OHLC: High ({bar.high}) must be >= Open ({bar.open}) and Close ({bar.close})"
            )

        if bar.low > min(bar.open, bar.close):
            errors.append(
                f"Impossible OHLC: Low ({bar.low}) must be <= Open ({bar.open}) and Close ({bar.close})"
            )

        # 2. Volume and OI checks
        if bar.volume < 0:
            errors.append(f"Bar volume cannot be negative: {bar.volume}")

        if bar.oi < 0:
            errors.append(f"Bar open interest cannot be negative: {bar.oi}")

        # 3. Timestamp timezone check
        if bar.timestamp.tzinfo is None:
            errors.append("Bar timestamp is timezone-naive; must be localized to Asia/Kolkata")

        # 4. Symbol check if provided
        if bar.symbol is not None and not bar.symbol.strip():
            errors.append("Bar symbol is empty or whitespace")

        # 5. Session check
        if session_check and bar.timestamp.tzinfo is not None and not is_market_open(bar.timestamp):
            errors.append(
                f"Bar timestamp {bar.timestamp.isoformat()} is outside regular NSE session hours"
            )

        if strict and errors:
            raise DataQualityError("; ".join(errors))

        return errors

    @classmethod
    def validate_tick(
        cls,
        tick: Tick,
        strict: bool = False,
        session_check: bool = False,
    ) -> list[str]:
        """Validate an individual Tick against physical and exchange constraints.

        Returns list of error messages. If strict=True, raises DataQualityError on first error.
        """
        errors: list[str] = []

        # 1. Symbol validity
        if not tick.symbol or not tick.symbol.strip():
            errors.append("Tick symbol cannot be empty")

        # 2. LTP validity
        if tick.ltp < 0.0:
            errors.append(f"Tick LTP cannot be negative: {tick.ltp}")

        # 3. Volume and OI
        if tick.volume < 0:
            errors.append(f"Tick volume cannot be negative: {tick.volume}")

        if tick.oi is not None and tick.oi < 0:
            errors.append(f"Tick open interest cannot be negative: {tick.oi}")

        # 4. Bid/Ask prices & quantities
        if tick.bid is not None and tick.bid < 0.0:
            errors.append(f"Tick bid price cannot be negative: {tick.bid}")

        if tick.ask is not None and tick.ask < 0.0:
            errors.append(f"Tick ask price cannot be negative: {tick.ask}")

        if (
            tick.bid is not None
            and tick.ask is not None
            and tick.bid > 0.0
            and tick.ask > 0.0
            and tick.bid > tick.ask
        ):
            errors.append(f"Crossed market: Bid price ({tick.bid}) exceeds Ask price ({tick.ask})")

        if tick.bid_qty is not None and tick.bid_qty < 0:
            errors.append(f"Tick bid quantity cannot be negative: {tick.bid_qty}")

        if tick.ask_qty is not None and tick.ask_qty < 0:
            errors.append(f"Tick ask quantity cannot be negative: {tick.ask_qty}")

        # 5. Timestamp timezone check
        if tick.timestamp.tzinfo is None:
            errors.append("Tick timestamp is timezone-naive; must be localized to Asia/Kolkata")

        # 6. Session check
        if (
            session_check
            and tick.timestamp.tzinfo is not None
            and not is_market_open(tick.timestamp)
        ):
            errors.append(
                f"Tick timestamp {tick.timestamp.isoformat()} is outside regular NSE session hours"
            )

        if strict and errors:
            raise DataQualityError("; ".join(errors))

        return errors

    @classmethod
    def validate_bar_sequence(
        cls,
        bars: Sequence[Bar],
        strict: bool = False,
        session_check: bool = False,
    ) -> DataQualityReport:
        """Perform batch quality audit across a sequential Bar history."""
        errors: list[str] = []
        warnings: list[str] = []
        has_duplicates = False
        has_out_of_order = False
        has_session_violations = False
        valid_count = 0

        prev_bar: Bar | None = None
        for i, bar in enumerate(bars):
            item_errors = cls.validate_bar(bar, strict=False, session_check=False)

            # Check sequence continuity
            if prev_bar is not None:
                if bar.timestamp < prev_bar.timestamp:
                    has_out_of_order = True
                    item_errors.append(
                        f"Out-of-order bar at index {i}: {bar.timestamp.isoformat()} < previous {prev_bar.timestamp.isoformat()}"
                    )
                elif bar.timestamp == prev_bar.timestamp:
                    has_duplicates = True
                    warnings.append(
                        f"Duplicate timestamp at index {i}: {bar.timestamp.isoformat()}"
                    )

            if (
                session_check
                and bar.timestamp.tzinfo is not None
                and not is_market_open(bar.timestamp)
            ):
                has_session_violations = True
                warnings.append(
                    f"Bar at index {i} ({bar.timestamp.isoformat()}) is outside regular market hours"
                )

            if item_errors:
                errors.extend(item_errors)
            else:
                valid_count += 1

            prev_bar = bar

        if strict and (errors or has_out_of_order):
            raise DataQualityError(
                "; ".join(errors) if errors else "Sequence contains out-of-order observations"
            )

        return DataQualityReport(
            total_records=len(bars),
            valid_records=valid_count,
            errors=errors,
            warnings=warnings,
            has_duplicates=has_duplicates,
            has_out_of_order=has_out_of_order,
            has_session_violations=has_session_violations,
        )

    @classmethod
    def validate_tick_sequence(
        cls,
        ticks: Sequence[Tick],
        strict: bool = False,
        session_check: bool = False,
    ) -> DataQualityReport:
        """Perform batch quality audit across a sequential Tick stream."""
        errors: list[str] = []
        warnings: list[str] = []
        has_duplicates = False
        has_out_of_order = False
        has_session_violations = False
        valid_count = 0

        prev_tick: Tick | None = None
        for i, tick in enumerate(ticks):
            item_errors = cls.validate_tick(tick, strict=False, session_check=False)

            if prev_tick is not None:
                if tick.timestamp < prev_tick.timestamp:
                    has_out_of_order = True
                    item_errors.append(
                        f"Out-of-order tick at index {i}: {tick.timestamp.isoformat()} < previous {prev_tick.timestamp.isoformat()}"
                    )
                elif (
                    tick.timestamp == prev_tick.timestamp
                    and tick.symbol == prev_tick.symbol
                    and tick.ltp == prev_tick.ltp
                    and tick.volume == prev_tick.volume
                ):
                    has_duplicates = True
                    warnings.append(
                        f"Identical duplicate tick at index {i}: {tick.timestamp.isoformat()}"
                    )

            if (
                session_check
                and tick.timestamp.tzinfo is not None
                and not is_market_open(tick.timestamp)
            ):
                has_session_violations = True
                warnings.append(
                    f"Tick at index {i} ({tick.timestamp.isoformat()}) is outside regular market hours"
                )

            if item_errors:
                errors.extend(item_errors)
            else:
                valid_count += 1

            prev_tick = tick

        if strict and (errors or has_out_of_order):
            raise DataQualityError(
                "; ".join(errors) if errors else "Sequence contains out-of-order observations"
            )

        return DataQualityReport(
            total_records=len(ticks),
            valid_records=valid_count,
            errors=errors,
            warnings=warnings,
            has_duplicates=has_duplicates,
            has_out_of_order=has_out_of_order,
            has_session_violations=has_session_violations,
        )
