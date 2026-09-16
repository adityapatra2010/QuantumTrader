"""Central runtime state management for the TUI Workstation."""

from __future__ import annotations

from typing import Any


class TUIState:
    """Encapsulates UI focus, active screens, selections, and cached data."""

    TAB_NAMES: list[str] = [
        "Overview",
        "Strategies",
        "Data",
        "Validation",
        "Simulation",
        "Runs",
        "Settings",
    ]

    def __init__(self) -> None:
        self.current_tab: int = 0
        self.selected_indices: dict[str, int] = {tab.lower(): 0 for tab in self.TAB_NAMES}
        self.scroll_offsets: dict[str, int] = {tab.lower(): 0 for tab in self.TAB_NAMES}

        # Modals / Inspection dialogs
        self.modal_visible: bool = False
        self.modal_title: str = ""
        self.modal_lines: list[str] = []
        self.modal_scroll: int = 0

        # Status / Feedback toast
        self.status_message: str = "Workstation ready · Strict Paper Execution (ADR 002)"
        self.status_level: str = "info"  # "info" | "success" | "warning" | "error"

        # Help overlay
        self.show_help: bool = False

        # Live session cache
        self.cache: dict[str, Any] = {}
        self.is_running: bool = True

    @property
    def active_screen_name(self) -> str:
        """Name of active screen tab."""
        return self.TAB_NAMES[self.current_tab].lower()

    @property
    def selected_index(self) -> int:
        """Current selection index on active screen."""
        return self.selected_indices.get(self.active_screen_name, 0)

    @selected_index.setter
    def selected_index(self, val: int) -> None:
        self.selected_indices[self.active_screen_name] = max(0, val)

    @property
    def scroll_offset(self) -> int:
        """Current vertical scroll offset on active screen."""
        return self.scroll_offsets.get(self.active_screen_name, 0)

    @scroll_offset.setter
    def scroll_offset(self, val: int) -> None:
        self.scroll_offsets[self.active_screen_name] = max(0, val)

    def set_status(self, msg: str, level: str = "info") -> None:
        """Update transient status message."""
        self.status_message = msg
        self.status_level = level

    def show_dialog(self, title: str, lines: list[str]) -> None:
        """Open scrollable text inspection modal."""
        self.modal_title = title
        self.modal_lines = lines
        self.modal_scroll = 0
        self.modal_visible = True

    def close_dialog(self) -> None:
        """Dismiss active modal."""
        self.modal_visible = False
        self.modal_lines = []
        self.modal_title = ""
        self.modal_scroll = 0
