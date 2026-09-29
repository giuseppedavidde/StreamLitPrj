"""Offline tests for the non-WebGL P&L surface (matplotlib PNG + Plotly heatmap).

Also smoke-tests the Streamlit app render via ``streamlit.testing.v1.AppTest``
with the default (non-WebGL) surface view.
"""

# pylint: disable=wrong-import-position

from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

import plotly.graph_objects as go
from streamlit.testing.v1 import AppTest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import SURFACE_VIEWS, heatmap_figure, surface_matplotlib_png
from models import PayoffConfig
from payoff_engine import build_bull_call_spread, compute_payoff

DRAM_EXPIRY = date(2026, 12, 18)
TODAY = date(2026, 9, 29)
APP_PATH = Path(__file__).resolve().parent.parent / "app.py"


def _dram_position():
    return build_bull_call_spread(
        ticker="DRAM",
        long_strike=59.0,
        short_strike=70.0,
        expiry=DRAM_EXPIRY,
        long_premium=10.71,
        short_premium=4.96,
        spot=65.0,
        rate=0.05,
        long_iv=0.60,
        short_iv=0.55,
    )


def _result(n_points: int = 41, n_slices: int = 6):
    config = PayoffConfig(
        price_min=40.0, price_max=90.0, n_points=n_points, n_slices=n_slices
    )
    return compute_payoff(_dram_position(), config, today=TODAY)


# ── matplotlib surface (no WebGL) ────────────────────────────────────────
def test_matplotlib_surface_png_is_valid_and_non_empty():
    """The matplotlib surface must produce a non-empty, valid PNG."""
    png = surface_matplotlib_png(_result(), _dram_position())
    assert isinstance(png, bytes)
    assert png.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(png) > 5000


def test_matplotlib_png_written_to_disk_is_non_empty(tmp_path):
    """The generated PNG can be persisted and is non-empty on disk."""
    png = surface_matplotlib_png(_result(), _dram_position())
    out = tmp_path / "surface.png"
    out.write_bytes(png)
    assert out.stat().st_size == len(png)
    assert out.stat().st_size > 0


# ── Plotly heatmap (no WebGL) ────────────────────────────────────────────
def test_heatmap_figure_has_matching_grid():
    """The heatmap grid must match the price/slice dimensions."""
    result = _result(n_points=41, n_slices=6)
    fig = heatmap_figure(result, _dram_position())
    heatmaps = [trace for trace in fig.data if isinstance(trace, go.Heatmap)]
    assert len(heatmaps) == 1
    assert len(heatmaps[0].y) == 41
    assert len(heatmaps[0].x) == 6


def test_surface_views_default_is_non_webgl():
    """The first (default) view is the matplotlib one, WebGL-free."""
    assert SURFACE_VIEWS[0] == "Superficie 3D (matplotlib, no WebGL)"
    assert "no WebGL" in SURFACE_VIEWS[1]
    assert SURFACE_VIEWS[2] == "Plotly 3D (WebGL)"


# ── Streamlit render smoke tests ─────────────────────────────────────────
def _run_app():
    app = AppTest.from_file(str(APP_PATH), default_timeout=60)
    app.run()
    return app


def test_streamlit_app_renders_default_view_without_exception():
    """The app renders with the default non-WebGL view and no exception."""
    app = _run_app()
    assert not app.exception
    assert len(app.radio) >= 1
    assert app.radio[0].value == SURFACE_VIEWS[0]  # pylint: disable=no-member


def test_streamlit_view_switching_does_not_raise():
    """Switching between all surface views never raises."""
    app = _run_app()
    for view in SURFACE_VIEWS[1:]:
        app.radio[0].set_value(view).run()  # pylint: disable=no-member
        assert not app.exception
