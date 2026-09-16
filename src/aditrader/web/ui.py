"""Embedded responsive HTML interface loader for AdiTrader Web Dashboard.

Loads the single-page application from static/index.html using importlib.resources.
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path


def get_dashboard_html() -> str:
    """Load the primary responsive dashboard HTML from static/index.html."""
    try:
        res = importlib.resources.files("aditrader.web").joinpath("static", "index.html")
        return res.read_text(encoding="utf-8")
    except Exception:
        fallback = Path(__file__).parent / "static" / "index.html"
        if fallback.is_file():
            return fallback.read_text(encoding="utf-8")
    return "<!DOCTYPE html><html><body><h1>AdiTrader Dashboard: index.html not found</h1></body></html>"


DASHBOARD_HTML = get_dashboard_html()
