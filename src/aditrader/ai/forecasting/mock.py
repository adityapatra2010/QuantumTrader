"""Deterministic Heuristic and Mock Forecasting Engine.

Provides mathematically consistent, offline probabilistic forecasts
strictly adhering to ADR 005 and ADR 012 without external ML dependencies.
"""

from __future__ import annotations

import hashlib
import math
from datetime import UTC, datetime, timedelta
from typing import Any

from aditrader.ai.base import ForecastEngine
from aditrader.ai.errors import AIMalformedOutputError
from aditrader.ai.models import AISourceType, ForecastResult, ProvenanceRecord
from aditrader.core.models.market_data import Bar


def compute_bars_hash(history: list[Bar]) -> str:
    """Compute deterministic SHA-256 digest of input historical bars."""
    components = [
        f"{b.timestamp.isoformat()}:{b.open:.4f}:{b.high:.4f}:{b.low:.4f}:{b.close:.4f}:{b.volume}"
        for b in history
    ]
    return hashlib.sha256(";".join(components).encode("utf-8")).hexdigest()


class HeuristicForecastEngine(ForecastEngine):
    """Deterministic offline forecasting engine using EWMA drift and ATR volatility bands."""

    def __init__(
        self,
        model_id: str = "heuristic-drift-v1",
        model_version: str = "1.0.0",
        provider: str = "local",
        default_interval: timedelta = timedelta(minutes=5),
        volatility_multiplier: float = 1.5,
        **_extra: Any,
    ) -> None:
        self.model_id = model_id
        self.model_version = model_version
        self.provider = provider
        self.default_interval = default_interval
        self.volatility_multiplier = volatility_multiplier

    def is_available(self) -> bool:
        """Local heuristic engine is always available offline."""
        return True

    def forecast(self, history: list[Bar], horizon_bars: int = 5) -> ForecastResult:
        """Generate point-in-time future price trajectory."""
        if not history:
            raise AIMalformedOutputError(
                "Cannot generate forecast from empty historical bar series"
            )
        if horizon_bars <= 0:
            raise AIMalformedOutputError(f"horizon_bars must be positive, got {horizon_bars}")

        # Strict Monotonicity & Anti-Lookahead Validation (ADR 012)
        for idx in range(len(history) - 1):
            t_curr = history[idx].timestamp
            t_next = history[idx + 1].timestamp
            if t_next <= t_curr:
                raise AIMalformedOutputError(
                    f"Historical bars must be strictly monotonically increasing in time. "
                    f"Violation at index {idx} ({t_curr.isoformat()}) >= index {idx + 1} ({t_next.isoformat()})."
                )

        last_bar = history[-1]
        cutoff = last_bar.timestamp
        if cutoff.tzinfo is None or cutoff.tzinfo.utcoffset(cutoff) is None:
            cutoff = cutoff.replace(tzinfo=UTC)
        else:
            cutoff = cutoff.astimezone(UTC)

        # Determine interval from history
        if len(history) >= 2:
            step = history[-1].timestamp - history[-2].timestamp
            if step <= timedelta(0):
                step = self.default_interval
        else:
            step = self.default_interval

        # Calculate drift and volatility from history
        last_close = last_bar.close
        if len(history) >= 2:
            returns = [
                (history[i].close - history[i - 1].close) / history[i - 1].close
                for i in range(1, len(history))
            ]
            mean_drift = sum(returns) / len(returns)
            # Bound drift to avoid explosive projections (-2% to +2% per bar max)
            bounded_drift = max(-0.02, min(0.02, mean_drift))
            # Sample standard deviation of returns
            var = sum((r - mean_drift) ** 2 for r in returns) / len(returns)
            volatility = math.sqrt(var) if var > 0 else 0.005
        else:
            bounded_drift = 0.0
            volatility = 0.005

        timestamps: list[datetime] = []
        pred_close: list[float] = []
        pred_high: list[float] = []
        pred_low: list[float] = []

        cur_time = cutoff
        cur_price = last_close

        for i in range(1, horizon_bars + 1):
            cur_time = cur_time + step
            timestamps.append(cur_time)

            # Projected median close with diminishing drift
            decay = 1.0 / math.sqrt(i)
            cur_price = cur_price * (1.0 + (bounded_drift * decay))
            cur_price = max(0.01, cur_price)
            pred_close.append(round(cur_price, 2))

            # Expanding uncertainty cone
            band_spread = cur_price * volatility * math.sqrt(i) * self.volatility_multiplier
            band_spread = max(cur_price * 0.002, band_spread)  # Minimum 20 bps spread

            h = round(cur_price + band_spread, 2)
            low = round(max(0.01, cur_price - band_spread), 2)
            # Ensure price envelope consistency: low <= close <= high
            if low > cur_price:
                low = cur_price
            if h < cur_price:
                h = cur_price

            pred_high.append(h)
            pred_low.append(low)

        input_hash = compute_bars_hash(history)
        avg_spread = (
            sum((pred_high[i] - pred_low[i]) / pred_close[i] for i in range(horizon_bars))
            / horizon_bars
        )

        provenance = ProvenanceRecord(
            source_type=AISourceType.PROBABILISTIC_FORECAST,
            model_id=self.model_id,
            model_version=self.model_version,
            provider=self.provider,
            generated_at=datetime.now(UTC),
            input_hash=input_hash,
            is_deterministic=True,
            confidence=0.85,
        )

        return ForecastResult(
            cutoff_timestamp=cutoff,
            horizon_bars=horizon_bars,
            timestamps=timestamps,
            predicted_close=pred_close,
            predicted_high=pred_high,
            predicted_low=pred_low,
            confidence_spread=round(avg_spread, 4),
            provenance=provenance,
        )
