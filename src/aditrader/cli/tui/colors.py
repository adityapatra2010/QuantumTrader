"""Color constants and initialization for Curses TUI."""

from __future__ import annotations

import curses
from typing import Final

# Color pair IDs
PAIR_DEFAULT: Final[int] = 1
PAIR_HEADER: Final[int] = 2
PAIR_TAB_ACTIVE: Final[int] = 3
PAIR_TAB_INACTIVE: Final[int] = 4
PAIR_SUCCESS: Final[int] = 5
PAIR_ERROR: Final[int] = 6
PAIR_WARNING: Final[int] = 7
PAIR_MUTED: Final[int] = 8
PAIR_ACCENT: Final[int] = 9
PAIR_SELECTED_ROW: Final[int] = 10
PAIR_BORDER: Final[int] = 8
PAIR_CARD_TITLE: Final[int] = 9


def init_colors() -> None:
    """Initialize curses color pairs safely."""
    if not curses.has_colors():
        return

    curses.start_color()
    try:
        curses.use_default_colors()
        bg = -1
    except Exception:
        bg = curses.COLOR_BLACK

    curses.init_pair(PAIR_DEFAULT, curses.COLOR_WHITE, bg)
    curses.init_pair(PAIR_HEADER, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(PAIR_TAB_ACTIVE, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(PAIR_TAB_INACTIVE, curses.COLOR_CYAN, bg)
    curses.init_pair(PAIR_SUCCESS, curses.COLOR_GREEN, bg)
    curses.init_pair(PAIR_ERROR, curses.COLOR_RED, bg)
    curses.init_pair(PAIR_WARNING, curses.COLOR_YELLOW, bg)
    curses.init_pair(PAIR_MUTED, curses.COLOR_BLUE, bg)
    curses.init_pair(PAIR_ACCENT, curses.COLOR_CYAN, bg)
    curses.init_pair(PAIR_SELECTED_ROW, curses.COLOR_BLACK, curses.COLOR_CYAN)


def get_attr(pair_id: int, bold: bool = False, dim: bool = False) -> int:
    """Safely get curses attribute combination."""
    try:
        attr = curses.color_pair(pair_id) if curses.has_colors() else 0
    except Exception:
        attr = 0

    try:
        if bold:
            attr |= curses.A_BOLD
        if dim:
            attr |= curses.A_DIM
    except Exception:
        pass
    return attr
