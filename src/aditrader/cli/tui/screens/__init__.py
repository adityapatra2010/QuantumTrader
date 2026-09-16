"""Screen renderers for the AdiTrader TUI Workstation."""

from __future__ import annotations

import contextlib
from typing import Any

__all__ = ["draw_box", "safe_addstr"]


def safe_addstr(
    win: Any,
    y: int,
    x: int,
    text: str,
    attr: int = 0,
    max_len: int | None = None,
) -> None:
    """Write text safely to window without throwing error at boundaries."""
    max_y, max_x = win.getmaxyx()
    if y < 0 or y >= max_y or x < 0 or x >= max_x:
        return
    available = max_x - x
    if available <= 0:
        return
    if max_len is not None:
        text = text[:max_len]
    if len(text) >= available:
        text = text[: available - 1]
    with contextlib.suppress(Exception):
        win.addstr(y, x, text, attr)


def draw_box(
    win: Any,
    top: int,
    left: int,
    height: int,
    width: int,
    title: str = "",
    title_attr: int = 0,
    border_attr: int = 0,
) -> None:
    """Draw a clean ASCII bordered box with optional title."""
    max_y, max_x = win.getmaxyx()
    if top >= max_y or left >= max_x or height < 2 or width < 4:
        return

    actual_h = min(height, max_y - top)
    actual_w = min(width, max_x - left)

    # Corners and lines
    horiz = "─" * (actual_w - 2)
    safe_addstr(win, top, left, f"┌{horiz}┐", border_attr)
    for row in range(top + 1, top + actual_h - 1):
        safe_addstr(win, row, left, "│", border_attr)
        safe_addstr(win, row, left + actual_w - 1, "│", border_attr)
    safe_addstr(win, top + actual_h - 1, left, f"└{horiz}┘", border_attr)

    if title:
        trimmed_title = f" {title[: actual_w - 6]} "
        safe_addstr(win, top, left + 2, trimmed_title, title_attr or border_attr)
