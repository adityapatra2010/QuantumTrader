"""Main event loop, layout compositor, and input router for the Curses TUI."""

from __future__ import annotations

import contextlib
import curses
from typing import Any

from aditrader.cli.tui.colors import (
    PAIR_ACCENT,
    PAIR_CARD_TITLE,
    PAIR_DEFAULT,
    PAIR_ERROR,
    PAIR_HEADER,
    PAIR_MUTED,
    PAIR_SUCCESS,
    PAIR_TAB_ACTIVE,
    PAIR_TAB_INACTIVE,
    PAIR_WARNING,
    get_attr,
    init_colors,
)
from aditrader.cli.tui.screens import draw_box, safe_addstr
from aditrader.cli.tui.screens.data import DataScreen
from aditrader.cli.tui.screens.overview import OverviewScreen
from aditrader.cli.tui.screens.runs import RunsScreen
from aditrader.cli.tui.screens.settings import SettingsScreen
from aditrader.cli.tui.screens.simulation import SimulationScreen
from aditrader.cli.tui.screens.strategies import StrategiesScreen
from aditrader.cli.tui.screens.validation import ValidationScreen
from aditrader.cli.tui.state import TUIState


class TUIEngine:
    """Curses terminal application compositor and lifecycle manager."""

    def __init__(self) -> None:
        self.state = TUIState()
        self.screens = [
            OverviewScreen,
            StrategiesScreen,
            DataScreen,
            ValidationScreen,
            SimulationScreen,
            RunsScreen,
            SettingsScreen,
        ]

    def run(self) -> int:
        """Execute the curses application wrapped safely."""
        return curses.wrapper(self._main_loop)

    def _main_loop(self, stdscr: Any) -> int:
        init_colors()
        with contextlib.suppress(Exception):
            curses.curs_set(0)

        stdscr.nodelay(False)
        stdscr.keypad(True)

        while self.state.is_running:
            stdscr.clear()
            max_y, max_x = stdscr.getmaxyx()

            # Terminal size validation
            if max_y < 20 or max_x < 75:
                msg = f"Terminal too small ({max_x}x{max_y}). Min 75x20 required. [q to exit]"
                safe_addstr(
                    stdscr,
                    max_y // 2,
                    max(0, (max_x - len(msg)) // 2),
                    msg,
                    get_attr(PAIR_ERROR, bold=True),
                )
                stdscr.refresh()
                key = stdscr.getch()
                if key in (ord("q"), ord("Q")):
                    break
                continue

            # 1. Header Bar
            header_text = "  AdiTrader Workstation  │  Institutional Quantitative Research & Paper OS  │  v1.0  "
            safe_addstr(stdscr, 0, 0, f"{header_text:<{max_x}}", get_attr(PAIR_HEADER, bold=True))

            # 2. Top Navigation Tabs
            tab_x = 2
            nav_y = 1
            safe_addstr(stdscr, nav_y, 0, " " * max_x, get_attr(PAIR_DEFAULT))
            for i, name in enumerate(self.state.TAB_NAMES):
                label = f" [{i + 1}] {name} "
                if i == self.state.current_tab:
                    safe_addstr(stdscr, nav_y, tab_x, label, get_attr(PAIR_TAB_ACTIVE, bold=True))
                else:
                    safe_addstr(stdscr, nav_y, tab_x, label, get_attr(PAIR_TAB_INACTIVE))
                tab_x += len(label) + 1

            # 3. Render Active Screen
            active_screen: Any = self.screens[self.state.current_tab]
            try:
                active_screen.render(stdscr, self.state)
            except Exception as e:
                safe_addstr(stdscr, 5, 4, f"Screen rendering error: {e}", get_attr(PAIR_ERROR))

            # 4. Bottom Status & Hotkey Bar
            bottom_y = max_y - 1
            safe_addstr(stdscr, bottom_y, 0, " " * max_x, get_attr(PAIR_DEFAULT))

            # Status message on left
            st_col = PAIR_DEFAULT
            if self.state.status_level == "success":
                st_col = PAIR_SUCCESS
            elif self.state.status_level == "warning":
                st_col = PAIR_WARNING
            elif self.state.status_level == "error":
                st_col = PAIR_ERROR
            elif self.state.status_level == "info":
                st_col = PAIR_ACCENT

            st_prefix = "● " if self.state.status_level != "info" else "ℹ "
            safe_addstr(
                stdscr,
                bottom_y,
                2,
                f"{st_prefix}{self.state.status_message[: max_x - 55]}",
                get_attr(st_col, bold=True),
            )

            # Hotkeys guide on right
            hotkey_guide = "[1-7] Tabs │ [←/→] Nav │ [Enter] Action │ [?] Help │ [q] Quit"
            safe_addstr(
                stdscr,
                bottom_y,
                max(0, max_x - len(hotkey_guide) - 2),
                hotkey_guide,
                get_attr(PAIR_MUTED),
            )

            # 5. Overlays (Modal or Help)
            if self.state.modal_visible:
                self._render_modal(stdscr, max_y, max_x)
            elif self.state.show_help:
                self._render_help(stdscr, max_y, max_x)

            stdscr.refresh()

            # 6. Read and Dispatch Keystroke
            try:
                key = stdscr.getch()
            except KeyboardInterrupt:
                break

            if key == curses.KEY_RESIZE:
                continue

            self._dispatch_key(key)

        return 0

    def _render_modal(self, win: Any, max_y: int, max_x: int) -> None:
        """Render scrollable modal dialog."""
        m_w = min(max_x - 8, 90)
        m_h = min(max_y - 6, 26)
        top = (max_y - m_h) // 2
        left = (max_x - m_w) // 2

        # Draw modal background and border
        for row in range(top, top + m_h):
            safe_addstr(win, row, left, " " * m_w, get_attr(PAIR_DEFAULT))

        draw_box(
            win,
            top=top,
            left=left,
            height=m_h,
            width=m_w,
            title=self.state.modal_title or "Details",
            title_attr=get_attr(PAIR_CARD_TITLE, bold=True),
            border_attr=get_attr(PAIR_ACCENT),
        )

        lines = self.state.modal_lines
        visible_lines = m_h - 4
        scroll = self.state.modal_scroll

        for i in range(visible_lines):
            line_idx = scroll + i
            if line_idx >= len(lines):
                break
            safe_addstr(
                win, top + 2 + i, left + 3, lines[line_idx][: m_w - 6], get_attr(PAIR_DEFAULT)
            )

        scroll_hint = f" Line {scroll + 1}/{len(lines)} │ [↑/↓] Scroll │ [Esc / Enter] Close "
        safe_addstr(
            win,
            top + m_h - 1,
            left + max(2, (m_w - len(scroll_hint)) // 2),
            scroll_hint,
            get_attr(PAIR_MUTED),
        )

    def _render_help(self, win: Any, max_y: int, max_x: int) -> None:
        """Render keyboard shortcuts reference overlay."""
        m_w = min(max_x - 8, 76)
        m_h = min(max_y - 6, 22)
        top = (max_y - m_h) // 2
        left = (max_x - m_w) // 2

        for row in range(top, top + m_h):
            safe_addstr(win, row, left, " " * m_w, get_attr(PAIR_DEFAULT))

        draw_box(
            win,
            top=top,
            left=left,
            height=m_h,
            width=m_w,
            title="AdiTrader Workstation — Keyboard Shortcuts",
            title_attr=get_attr(PAIR_CARD_TITLE, bold=True),
            border_attr=get_attr(PAIR_ACCENT),
        )

        help_items = [
            ("1 - 7", "Jump directly to screen tab (Overview, Strategies, Data, etc.)"),
            ("Left / h", "Navigate to previous screen tab"),
            ("Right / l", "Navigate to next screen tab"),
            ("Tab", "Cycle through screens sequentially"),
            ("Up / k", "Move selection cursor up in table / catalog"),
            ("Down / j", "Move selection cursor down in table / catalog"),
            ("Enter", "Select / activate / inspect current item"),
            ("d", "Inspect deep details (AST, DNA, Dossier, etc.)"),
            ("r", "Refresh data / rescan datasets from disk"),
            ("p", "Cycle validation policy (Institutional, Moderate, Research)"),
            ("m", "Switch simulation mode (Historical Replay vs Forward Paper)"),
            ("x", "Execute simulation run"),
            ("i", "Initialize SQLite database tables (in Settings screen)"),
            ("?", "Toggle this keyboard shortcuts help overlay"),
            ("Esc", "Close active modal / dismiss overlay"),
            ("q", "Quit AdiTrader Terminal Workstation safely"),
        ]

        for idx, (hotkey, desc) in enumerate(help_items[: m_h - 4]):
            safe_addstr(
                win, top + 2 + idx, left + 4, f"{hotkey:<12}", get_attr(PAIR_ACCENT, bold=True)
            )
            safe_addstr(win, top + 2 + idx, left + 18, desc[: m_w - 22], get_attr(PAIR_DEFAULT))

        dismiss_hint = " Press [Esc] or [?] to close "
        safe_addstr(
            win,
            top + m_h - 1,
            left + (m_w - len(dismiss_hint)) // 2,
            dismiss_hint,
            get_attr(PAIR_MUTED),
        )

    def _dispatch_key(self, key: int) -> None:
        """Route keystroke to active overlay or screen."""
        # 1. Active modal handling
        if self.state.modal_visible:
            if key in (27, ord("q"), ord("Q"), curses.KEY_ENTER, 10, 13):
                self.state.close_dialog()
            elif key in (curses.KEY_UP, ord("k")):
                self.state.modal_scroll = max(0, self.state.modal_scroll - 1)
            elif key in (curses.KEY_DOWN, ord("j")):
                max_scroll = max(0, len(self.state.modal_lines) - 10)
                self.state.modal_scroll = min(max_scroll, self.state.modal_scroll + 1)
            elif key == curses.KEY_PPAGE:  # Page up
                self.state.modal_scroll = max(0, self.state.modal_scroll - 8)
            elif key == curses.KEY_NPAGE:  # Page down
                max_scroll = max(0, len(self.state.modal_lines) - 10)
                self.state.modal_scroll = min(max_scroll, self.state.modal_scroll + 8)
            return

        # 2. Help overlay handling
        if self.state.show_help:
            if key in (27, ord("?"), ord("q"), ord("Q"), curses.KEY_ENTER, 10, 13):
                self.state.show_help = False
            return

        # 3. Global hotkeys
        if key in (ord("q"), ord("Q")):
            self.state.is_running = False
            return
        elif key == ord("?"):
            self.state.show_help = True
            return
        elif ord("1") <= key <= ord("7"):
            self.state.current_tab = key - ord("1")
            return
        elif key in (curses.KEY_LEFT, ord("h")):
            self.state.current_tab = (self.state.current_tab - 1) % len(self.state.TAB_NAMES)
            return
        elif key in (curses.KEY_RIGHT, ord("l"), 9):  # 9 is Tab
            self.state.current_tab = (self.state.current_tab + 1) % len(self.state.TAB_NAMES)
            return

        # 4. Delegate to active screen
        active_screen: Any = self.screens[self.state.current_tab]
        active_screen.handle_input(key, self.state)
