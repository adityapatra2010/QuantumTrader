"""Unit and integration tests verifying ForwardTestRunner replaying CSV datasets."""

from pathlib import Path

import pytest

from aditrader.cli.commands import cmd_forward_test
from aditrader.core.models.enums import OrderSide, OrderStatus
from aditrader.core.models.market_data import Bar
from aditrader.data.feeds.csv_feed import CSVDataFeed
from aditrader.data.forward import ForwardTestStatus
from aditrader.data.forward_runner import ForwardTestConfig, ForwardTestRunner
from aditrader.strategy.builder.schema import (
    ASTOperator,
    ConditionCategory,
    ConditionGroup,
    ConditionNode,
    StrategyDSL,
)


class DummyArgs:
    """Helper mock for CLI arguments."""

    def __init__(self, **kwargs: object) -> None:
        self.__dict__.update(kwargs)


def _get_linear_test_strategy() -> StrategyDSL:
    """Helper constructing linear strategy for CSV replay forward testing."""
    return StrategyDSL(
        schema_version="1.0",
        name="csv_replay_test_strategy",
        underlying="NIFTY",
        timeframe="1m",
        entry_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="close",
                    operator=ASTOperator.GREATER_THAN,
                    threshold=21510.0,
                )
            ],
        ),
        exit_conditions=ConditionGroup(
            operator=ASTOperator.AND,
            conditions=[
                ConditionNode(
                    category=ConditionCategory.INDICATOR,
                    field="close",
                    operator=ASTOperator.LESS_THAN,
                    threshold=21500.0,
                )
            ],
        ),
    )


def test_forward_test_runner_with_csv_feed(tmp_path: Path) -> None:
    """Verify ForwardTestRunner replays CSV feed without lookahead and without fabricating quotes."""
    csv_file = tmp_path / "fwd_replay.csv"
    csv_content = """Date,Time,Open,High,Low,Close,Volume
2024-01-15,09:15:00,21500.0,21505.0,21495.0,21502.0,1000
2024-01-15,09:16:00,21505.0,21520.0,21500.0,21515.0,1500
2024-01-15,09:17:00,21515.0,21525.0,21510.0,21520.0,1200
2024-01-15,09:18:00,21520.0,21525.0,21490.0,21495.0,1100
"""
    csv_file.write_text(csv_content, encoding="utf-8")

    csv_feed = CSVDataFeed(csv_file, symbol="NIFTY", timeframe="1m")
    assert len(csv_feed) == 4

    config = ForwardTestConfig(
        symbol="NIFTY",
        timeframe="1m",
        qty=10,
        initial_capital=500_000.0,
        slippage_bps=2.0,
        enable_ledger_persistence=False,
    )

    strategy = _get_linear_test_strategy()

    received_bars: list[Bar] = []
    received_trades_count = 0

    def on_bar(b: Bar) -> None:
        received_bars.append(b)

    def on_trade(t: object) -> None:
        nonlocal received_trades_count
        received_trades_count += 1

    runner = ForwardTestRunner(
        config=config,
        strategy=strategy,
        feed=csv_feed,
        on_bar_callback=on_bar,
        on_trade_callback=on_trade,
    )

    result = runner.run()

    assert result.session.status == ForwardTestStatus.COMPLETED
    assert result.session.total_ticks == 4
    # 3 bars closed during streaming; 4th in-progress bar flushed on shutdown without callback (ADR 013)
    assert len(received_bars) == 3

    # Verify orders and fills were generated based on strategy condition (close > 21510 -> BUY)
    orders = runner.broker.get_orders()
    assert len(orders) >= 1
    first_order = orders[0]
    assert first_order.symbol == "NIFTY"
    assert first_order.side == OrderSide.BUY
    assert first_order.status == OrderStatus.FILLED

    # Verify trades executed
    trades = runner.broker.get_trades()
    assert len(trades) >= 1
    # Trade execution price should be around close of the triggering bar
    assert trades[0].fill_price > 0.0


def test_cli_cmd_forward_test_with_csv(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Verify aditrader forward-test --strategy <name> --csv <path> CLI execution."""
    csv_file = tmp_path / "cli_fwd.csv"
    csv_content = """Date,Time,Open,High,Low,Close,Volume
2024-01-15,09:15:00,24000.0,24010.0,23990.0,24005.0,500
2024-01-15,09:16:00,24005.0,24015.0,24000.0,24010.0,600
"""
    csv_file.write_text(csv_content, encoding="utf-8")

    out_dossier = tmp_path / "cli_session_dossier.json"
    args = DummyArgs(
        strategy="test_ma_crossover",
        instrument=None,
        timeframe="1m",
        qty=25,
        volume_mode="TRADED_VOLUME",
        capital=1_000_000.0,
        slippage_bps=2.5,
        mock=False,
        ticks=None,
        bars=None,
        duration=None,
        output=str(out_dossier),
        strict_quality=False,
        csv=str(csv_file),
    )

    exit_code = cmd_forward_test(args)  # type: ignore[arg-type]
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "Forward Paper Testing" in captured.out
    assert "SIMULATION / CSV_REPLAY" in captured.out
    assert "Forward-Testing Session Summary" in captured.out
    assert "Bars Completed:   2" in captured.out
    assert out_dossier.is_file()
