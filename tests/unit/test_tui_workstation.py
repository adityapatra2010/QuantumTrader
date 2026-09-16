"""Unit tests verifying Curses TUI state, screen rendering, and interactive mechanics."""

from unittest.mock import MagicMock, patch

from aditrader.cli.commands import cmd_tui
from aditrader.cli.tui.screens.data import DataScreen
from aditrader.cli.tui.screens.overview import OverviewScreen
from aditrader.cli.tui.screens.runs import RunsScreen
from aditrader.cli.tui.screens.settings import SettingsScreen
from aditrader.cli.tui.screens.simulation import SimulationScreen
from aditrader.cli.tui.screens.strategies import StrategiesScreen
from aditrader.cli.tui.screens.validation import ValidationScreen
from aditrader.cli.tui.state import TUIState


def create_mock_window(height: int = 40, width: int = 120) -> MagicMock:
    """Create a mock curses window for headless testing."""
    win = MagicMock()
    win.getmaxyx.return_value = (height, width)
    win.bkgd.return_value = None
    win.erase.return_value = None
    win.noutrefresh.return_value = None
    win.refresh.return_value = None
    win.addstr.return_value = None
    win.subwin.return_value = win
    return win


def test_tui_state_initialization_and_tabs() -> None:
    """Verify TUIState tab navigation and modal lifecycle."""
    state = TUIState()
    assert state.current_tab == 0
    assert state.active_screen_name == "overview"
    assert state.is_running is True

    # Tab switching
    state.current_tab = 1
    assert state.active_screen_name == "strategies"

    state.selected_index = 3
    assert state.selected_index == 3
    assert state.selected_indices["strategies"] == 3

    # Status toast
    state.set_status("Operation succeeded", level="success")
    assert state.status_message == "Operation succeeded"
    assert state.status_level == "success"

    # Modal lifecycle
    state.show_dialog("Inspection", ["Line 1", "Line 2"])
    assert state.modal_visible is True
    assert state.modal_title == "Inspection"
    assert len(state.modal_lines) == 2

    state.close_dialog()
    assert state.modal_visible is False


def test_overview_screen_render() -> None:
    """Verify Overview screen renders without error on mock window."""
    win = create_mock_window()
    state = TUIState()
    OverviewScreen.render(win, state)
    assert win.addstr.called


def test_strategies_screen_render_and_input() -> None:
    """Verify Strategies screen renders and handles selection/enter key."""
    win = create_mock_window()
    state = TUIState()
    state.current_tab = 1
    StrategiesScreen.render(win, state)
    assert win.addstr.called

    # Press Enter / 10 to inspect
    handled = StrategiesScreen.handle_input(10, state)
    assert handled is True
    assert state.modal_visible is True
    assert "Strategy" in state.modal_title


def test_data_screen_render_and_input() -> None:
    """Verify Data screen renders and cycles items."""
    win = create_mock_window()
    state = TUIState()
    state.current_tab = 2
    DataScreen.render(win, state)
    assert win.addstr.called

    # Press 't' to smoke test
    handled = DataScreen.handle_input(ord("t"), state)
    assert handled is True
    assert "smoke test" in state.status_message.lower()


def test_validation_screen_render_and_input() -> None:
    """Verify Validation screen renders and toggles policies."""
    win = create_mock_window()
    state = TUIState()
    state.current_tab = 3
    ValidationScreen.render(win, state)
    assert win.addstr.called

    # Press 'p' to toggle policy
    handled = ValidationScreen.handle_input(ord("p"), state)
    assert handled is True
    assert state.cache.get("val_policy_idx") == 1

    # Press 'v' to validate
    handled_val = ValidationScreen.handle_input(ord("v"), state)
    assert handled_val is True
    assert "Validation complete" in state.status_message


def test_simulation_screen_render_and_input() -> None:
    """Verify Simulation screen renders and toggles execution modes."""
    win = create_mock_window()
    state = TUIState()
    state.current_tab = 4
    SimulationScreen.render(win, state)
    assert win.addstr.called

    # Press 'm' to toggle mode between BACKTEST and FORWARD
    handled_m = SimulationScreen.handle_input(ord("m"), state)
    assert handled_m is True
    assert state.cache.get("sim_mode_idx") == 1

    # Toggle back
    SimulationScreen.handle_input(ord("m"), state)
    assert state.cache.get("sim_mode_idx") == 0


def test_runs_screen_render_and_input() -> None:
    """Verify Runs screen renders and filters."""
    win = create_mock_window()
    state = TUIState()
    state.current_tab = 5
    RunsScreen.render(win, state)
    assert win.addstr.called

    # Press 'f' to cycle filter
    handled_f = RunsScreen.handle_input(ord("f"), state)
    assert handled_f is True
    assert state.cache.get("runs_filter_idx") == 1


def test_settings_screen_render_and_input() -> None:
    """Verify Settings screen renders and triggers doctor/init-db."""
    win = create_mock_window()
    state = TUIState()
    state.current_tab = 6
    SettingsScreen.render(win, state)
    assert win.addstr.called

    # Press 'd' for diagnostics refresh
    handled_d = SettingsScreen.handle_input(ord("d"), state)
    assert handled_d is True
    assert "Diagnostics re-run" in state.status_message

    # Press 'i' for db init
    handled_i = SettingsScreen.handle_input(ord("i"), state)
    assert handled_i is True
    assert "Database initialized" in state.status_message


def test_cmd_tui_non_interactive_guard() -> None:
    """Verify cmd_tui exits with error code 1 when stdin is not a TTY."""
    mock_args = MagicMock()
    with patch("sys.stdin.isatty", return_value=False):
        exit_code = cmd_tui(mock_args)
        assert exit_code == 1
