"""Options Interactive Payoff — interactive multi-leg option payoff explorer.

100% local computation: Black-Scholes engine + yfinance market data.
NO LLM / NO AI calls of any kind.

Run with:  streamlit run app.py
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from datetime import date, datetime
from typing import Any, Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure
from mpl_toolkits.mplot3d import Axes3D  # pylint: disable=unused-import

import data as market_data
from models import (
    DEFAULT_MULTIPLIER,
    Direction,
    ExpiryChain,
    OptionKind,
    OptionLeg,
    PayoffConfig,
    PayoffResult,
    Position,
)
from payoff_engine import compute_payoff, implied_vol

KIND_LABELS = {OptionKind.CALL: "call", OptionKind.PUT: "put"}
DIRECTION_LABELS = {Direction.LONG: "long", Direction.SHORT: "short"}

# Surface views: the first two do NOT require WebGL (safe default).
SURFACE_VIEWS = (
    "Superficie 3D (matplotlib, no WebGL)",
    "Heatmap 2D (Plotly, no WebGL)",
    "Plotly 3D (WebGL)",
)

# ── session-state keys for the leg builder ───────────────────────────────
# ``LEGS_BASE_KEY`` holds the *stable* table passed to ``st.data_editor``.
# ``LEGS_EDITOR_KEY`` is the widget key: per Streamlit, the pending edits live
# in Session State under this key (a ``DataEditorState``), so the widget is the
# single source of truth for user edits and the base is never written back.
LEGS_BASE_KEY = "legs_base"
LEGS_EDITOR_KEY = "legs_editor"

# Demo legs: BS-consistent at spot 65, rate 5%, 80 days to 2026-12-18
# (long 59 call @ IV 60% ≈ 10.71, short 70 call @ IV 55% ≈ 4.96 → net debit 5.75).
DEMO_LEGS = pd.DataFrame(
    [
        {"Tipo": "call", "Direzione": "long", "Strike": 59.0, "Scadenza": "2026-12-18",
         "Qty": 1, "Premio": 10.71, "IV": 0.60},
        {"Tipo": "call", "Direzione": "short", "Strike": 70.0, "Scadenza": "2026-12-18",
         "Qty": 1, "Premio": 4.96, "IV": 0.55},
    ]
)
DEMO_TICKER = "DRAM"
DEMO_SPOT = 65.0


# ── cached market data ───────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner=False)
def cached_spot(ticker: str) -> Optional[float]:
    """Cached spot price fetch."""
    return market_data.fetch_spot(ticker)


@st.cache_data(ttl=300, show_spinner=False)
def cached_expirations(ticker: str) -> list[date]:
    """Cached option expirations fetch."""
    return market_data.fetch_expirations(ticker)


@st.cache_data(ttl=600, show_spinner=False)
def cached_rate() -> float:
    """Cached risk-free rate fetch (^IRX)."""
    return market_data.fetch_risk_free_rate()


@st.cache_data(ttl=300, show_spinner=False)
def cached_chain(ticker: str, expiry_iso: str, spot: float, rate: float) -> Optional[ExpiryChain]:
    """Cached option chain snapshot for a single expiry."""
    return market_data.fetch_chain(
        ticker, datetime.strptime(expiry_iso, "%Y-%m-%d").date(), spot, rate
    )


# ── helpers ──────────────────────────────────────────────────────────────
def parse_legs(frame: pd.DataFrame) -> list[OptionLeg]:
    """Convert an edited DataFrame into validated OptionLeg models."""
    legs: list[OptionLeg] = []
    for _, row in frame.iterrows():
        if pd.isna(row.get("Strike")):
            continue
        try:
            expiry = datetime.strptime(str(row["Scadenza"])[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        iv = row.get("IV")
        legs.append(
            OptionLeg(
                kind=OptionKind(str(row["Tipo"]).strip().lower()),
                direction=Direction(str(row["Direzione"]).strip().lower()),
                strike=float(row["Strike"]),
                expiry=expiry,
                quantity=int(row.get("Qty") or 1),
                entry_premium=float(row.get("Premio") or 0.0),
                iv=float(iv) if iv is not None and not pd.isna(iv) and float(iv) > 0 else None,
            )
        )
    return legs


def prefill_from_chain(
    frame: pd.DataFrame, ticker: str, spot: float, rate: float, today: date
) -> pd.DataFrame:
    """Fill premiums (mid) and IV (solved per-strike) from the market chain."""
    out = frame.copy()
    for idx, row in out.iterrows():
        try:
            expiry = datetime.strptime(str(row["Scadenza"])[:10], "%Y-%m-%d").date()
        except (ValueError, TypeError):
            continue
        chain = cached_chain(ticker, expiry.isoformat(), spot, rate)
        if chain is None:
            continue
        kind = OptionKind(str(row["Tipo"]).strip().lower())
        mid = chain.mid_for(kind, float(row["Strike"]))
        if mid is None:
            continue
        out.at[idx, "Premio"] = round(mid, 2)
        tau = max((expiry - today).days, 1) / 365.0
        solved = implied_vol(mid, spot, float(row["Strike"]), tau, rate, kind)
        if solved is not None:
            out.at[idx, "IV"] = round(solved, 4)
    return out


def apply_editor_state(
    base: pd.DataFrame, state: Optional[Mapping[str, Any]]
) -> pd.DataFrame:
    """Resolve the effective leg table from a base table and a ``DataEditorState``.

    When ``st.data_editor`` runs with a widget ``key``, the pending edits live in
    Session State as a ``DataEditorState`` (``edited_rows``, ``added_rows``,
    ``deleted_rows``) instead of being returned as a full frame. Streamlit
    addresses rows by *position*; the same rule is reproduced here so the
    effective table can be read before the widget renders. ``base`` is never
    mutated.
    """
    frame = base.copy().reset_index(drop=True)
    if not isinstance(state, Mapping):
        return frame

    for position, changes in (state.get("edited_rows") or {}).items():
        if not isinstance(changes, Mapping):
            continue
        row_pos = int(position)
        if not 0 <= row_pos < len(frame):
            continue
        for column, value in changes.items():
            if column in frame.columns:
                frame.iat[row_pos, frame.columns.get_loc(column)] = value

    deleted = [
        int(position)
        for position in (state.get("deleted_rows") or [])
        if 0 <= int(position) < len(frame)
    ]
    if deleted:
        frame = frame.drop(index=frame.index[deleted])

    added = state.get("added_rows") or []
    if added:
        frame = pd.concat(
            [frame, pd.DataFrame(added, columns=frame.columns)], ignore_index=True
        )

    return frame.reset_index(drop=True)


def expiry_curve_figure(result, position: Position) -> go.Figure:
    """P&L at expiry with fan chart overlay."""
    fig = go.Figure()
    for slice_date, series in result.fan.items():
        if slice_date == result.slice_dates[-1]:
            continue
        fig.add_trace(
            go.Scatter(x=result.prices, y=series, mode="lines",
                       line={"width": 1, "color": "rgba(120,120,120,0.45)"},
                       name=f"MTM {slice_date}", showlegend=False, hoverinfo="skip")
        )
    fig.add_trace(go.Scatter(x=result.prices, y=result.at_expiry, mode="lines",
                             line={"width": 3, "color": "#2E86AB"}, name="A scadenza"))
    if position.underlying_price:
        fig.add_vline(x=position.underlying_price, line_dash="dot",
                      line_color="#888", annotation_text="spot")
    fig.add_hline(y=0, line_color="#333", line_width=1)
    for be in result.breakevens:
        fig.add_vline(x=be, line_dash="dash", line_color="#E4572E",
                      annotation_text=f"BE {be:.2f}")
    fig.update_layout(title=f"{position.ticker} — P&L a scadenza + fan chart MTM",
                      xaxis_title="Prezzo sottostante", yaxis_title="P&L ($)",
                      hovermode="x unified", height=480)
    return fig


def fan_figure(result, position: Position) -> go.Figure:
    """Dedicated fan chart: one line per date slice."""
    fig = go.Figure()
    colors = ["#2E86AB", "#A23B72", "#F18F01", "#C73E1D", "#3B1F2B"]
    for i, slice_date in enumerate(result.slice_dates):
        fig.add_trace(go.Scatter(x=result.prices, y=result.fan[slice_date], mode="lines",
                                 line={"color": colors[i % len(colors)], "width": 1.6},
                                 name=slice_date))
    if position.underlying_price:
        fig.add_vline(x=position.underlying_price, line_dash="dot", line_color="#888")
    fig.add_hline(y=0, line_color="#333", line_width=1)
    fig.update_layout(title="Fan chart — P&L nel tempo", xaxis_title="Prezzo sottostante",
                      yaxis_title="P&L ($)", height=460)
    return fig


def surface_figure(result) -> go.Figure:
    """3D P&L surface: price x time."""
    slices = result.slice_dates
    x_axis = list(range(len(slices)))
    fig = go.Figure(
        data=[go.Surface(x=x_axis, y=result.prices, z=result.surface_z,
                         colorscale="RdYlGn", colorbar={"title": "P&L ($)"})]
    )
    fig.update_layout(
        title="Superficie 3D — P&L vs (prezzo x tempo)",
        scene={"xaxis": {"title": "tempo", "ticktext": slices,
                         "tickvals": x_axis, "tickangle": -45},
               "yaxis": {"title": "prezzo"},
               "zaxis": {"title": "P&L ($)"},
               "camera": {"eye": {"x": 1.6, "y": -1.6, "z": 0.9}}},
        height=620,
    )
    return fig


def heatmap_figure(result, position: Position) -> go.Figure:
    """2D P&L heatmap (price x time) — pure Plotly, no WebGL required."""
    fig = go.Figure(
        data=go.Heatmap(
            x=result.slice_dates,
            y=result.prices,
            z=result.surface_z,
            colorscale="RdYlGn",
            colorbar={"title": "P&L ($)"},
            hovertemplate="tempo=%{x}<br>prezzo=%{y:.2f}<br>P&L=$%{z:.2f}<extra></extra>",
        )
    )
    if position.underlying_price:
        fig.add_hline(y=position.underlying_price, line_dash="dot", line_color="#333",
                      annotation_text="spot")
    fig.update_layout(title=f"{position.ticker} — Heatmap P&L (prezzo × tempo)",
                      xaxis_title="tempo", yaxis_title="prezzo", height=560)
    return fig


def surface_matplotlib_png(result, position: Position) -> bytes:
    """Render the 3D P&L surface with matplotlib (no WebGL) and return PNG bytes."""
    prices = np.asarray(result.prices, dtype=float)
    time_index = np.arange(len(result.slice_dates), dtype=float)
    z_values = np.asarray(result.surface_z, dtype=float)
    time_grid, price_grid = np.meshgrid(time_index, prices)

    fig = Figure(figsize=(9, 6), dpi=110, constrained_layout=True)
    FigureCanvasAgg(fig)  # non-GUI Agg canvas: no WebGL, no display required
    ax = fig.add_subplot(111, projection="3d")
    surface = ax.plot_surface(time_grid, price_grid, z_values, cmap="RdYlGn",
                              linewidth=0, antialiased=True)
    fig.colorbar(surface, ax=ax, shrink=0.6, pad=0.1, label="P&L ($)")

    if position.underlying_price:
        ax.plot(
            [time_index[0], time_index[-1]],
            [position.underlying_price, position.underlying_price],
            zs=[float(np.nanmin(z_values)), float(np.nanmax(z_values))],
            color="#333", linestyle="--", linewidth=1,
        )

    step = max(1, len(result.slice_dates) // 6)
    ticks = list(range(0, len(result.slice_dates), step))
    ax.set_xticks(ticks)
    ax.set_xticklabels([result.slice_dates[i] for i in ticks], rotation=45,
                       ha="right", fontsize=7)
    ax.set_xlabel("tempo", labelpad=12)
    ax.set_ylabel("prezzo", labelpad=8)
    ax.set_zlabel("P&L ($)", labelpad=8)
    ax.set_title(f"{position.ticker} — Superficie 3D P&L (matplotlib, no WebGL)")
    ax.view_init(elev=22, azim=-60)

    buffer = io.BytesIO()
    fig.savefig(buffer, format="png")
    return buffer.getvalue()


def payoff_table(result) -> pd.DataFrame:
    """Price grid table with P&L columns per slice."""
    frame = pd.DataFrame({"Prezzo": result.prices, "P&L scadenza": result.at_expiry})
    for slice_date in result.slice_dates:
        frame[f"MTM {slice_date}"] = result.fan[slice_date]
    return frame


def format_extreme(value: Optional[float], unbounded_label: str) -> str:
    """Format an analytic extreme; ``None`` is rendered as an unbounded label."""
    if value is None:
        return f"illimitato ({unbounded_label})"
    return f"${value:,.2f}"


def position_warnings(position: Position) -> list[str]:
    """Sanity warnings on user-supplied premiums and implied volatilities."""
    warnings: list[str] = []
    for index, leg in enumerate(position.legs, start=1):
        label = f"Leg {index} ({KIND_LABELS[leg.kind]} {leg.strike:,.2f})"
        if leg.entry_premium <= 0:
            warnings.append(
                f"{label}: premio {leg.entry_premium:,.2f} non positivo — "
                "il P&L e i livelli chiave saranno sfalsati."
            )
        if leg.iv is not None and not 0.01 <= leg.iv <= 3.0:
            warnings.append(
                f"{label}: IV {leg.iv:.3f} irrealistica (atteso 0.01–3.0)."
            )
    return warnings


def leg_echo_table(position: Position) -> pd.DataFrame:
    """Table of the legs actually parsed and sent to the engine."""
    return pd.DataFrame(
        {
            "Leg": list(range(1, len(position.legs) + 1)),
            "Tipo": [KIND_LABELS[leg.kind] for leg in position.legs],
            "Direzione": [DIRECTION_LABELS[leg.direction] for leg in position.legs],
            "Strike": [leg.strike for leg in position.legs],
            "Scadenza": [leg.expiry.isoformat() for leg in position.legs],
            "Contratti": [leg.quantity for leg in position.legs],
            "Premio": [leg.entry_premium for leg in position.legs],
            "IV": [leg.iv for leg in position.legs],
        }
    )


def render_input_echo(
    position: Position, config: PayoffConfig, result: PayoffResult
) -> None:
    """Show the inputs (parsed legs, spot, rate, grid) used in the computation."""
    with st.expander("Input usati nel calcolo (leg parsati)", expanded=False):
        st.dataframe(leg_echo_table(position), width="stretch", hide_index=True)
        spot_text = (
            f"{position.underlying_price:,.2f}"
            if position.underlying_price
            else "n/d"
        )
        st.caption(
            f"Spot usato: {spot_text} · rate: {position.rate:.4f} · "
            f"moltiplicatore: {position.multiplier} · "
            f"griglia: {config.price_min:,.2f}–{config.price_max:,.2f} "
            f"({config.n_points} punti)"
        )
        st.caption(
            "Il P&L dipende dai **premi inseriti dall'utente** e dall'IV per leg "
            "(se assente si usa il fallback 0.30). "
            f"Net debit risultante: ${result.net_debit:,.2f}."
        )


def render_validation(position: Position) -> None:
    """Surface input sanity warnings before the metrics."""
    for message in position_warnings(position):
        st.warning(message)


# ── UI ───────────────────────────────────────────────────────────────────
def render_header() -> None:
    """Configure the page and render the title."""
    st.set_page_config(page_title="Options Interactive Payoff", page_icon="📈", layout="wide")
    st.title("📈 Options Interactive Payoff")
    st.caption("Calcolo 100% locale (Black-Scholes + yfinance) · nessuna dipendenza da LLM/AI")


def render_sidebar() -> dict:
    """Ticker + market inputs. Returns the sidebar state dict."""
    st.sidebar.header("1 · Ticker & mercato")
    ticker = st.sidebar.text_input("Ticker", value=st.session_state.get("ticker", DEMO_TICKER))
    ticker = ticker.strip().upper()
    load = st.sidebar.button("⬇️ Carica dati di mercato", width="stretch")
    use_manual_rate = st.sidebar.checkbox("Risch-free rate manuale", value=False)
    manual_rate = st.sidebar.number_input("Rate (%)", value=4.5, step=0.1,
                                          disabled=not use_manual_rate)

    if load:
        st.session_state["ticker"] = ticker
        with st.spinner("Scarico spot, scadenze e rate…"):
            spot = cached_spot(ticker)
            st.session_state["spot"] = spot
            st.session_state["expirations"] = cached_expirations(ticker)
            st.session_state["rate"] = cached_rate()

    spot = st.session_state.get("spot")
    expirations = st.session_state.get("expirations", [])
    rate = (manual_rate / 100.0) if use_manual_rate else st.session_state.get("rate", 0.05)

    if spot:
        st.sidebar.metric("Spot", f"${spot:,.2f}")
    elif st.session_state.get("ticker"):
        st.sidebar.info("Spot non disponibile: usa il preset demo o imposta manualmente.")
    st.sidebar.metric("Rate", f"{rate * 100:.2f}%")
    if expirations:
        st.sidebar.caption(f"{len(expirations)} scadenze · {expirations[0]} → {expirations[-1]}")

    return {"ticker": ticker, "spot": spot, "expirations": expirations, "rate": rate}


def legs_base() -> pd.DataFrame:
    """The stable table passed to ``st.data_editor`` (never overwritten by edits)."""
    if LEGS_BASE_KEY not in st.session_state:
        st.session_state[LEGS_BASE_KEY] = DEMO_LEGS.copy().reset_index(drop=True)
    return st.session_state[LEGS_BASE_KEY]


def set_legs_base(frame: pd.DataFrame) -> None:
    """Replace the editable table programmatically (preset / prefill).

    The widget key is the single source of truth, so a programmatic update must
    swap the base table *and* drop the pending widget state
    (``st.session_state.pop`` before the editor renders). Writing the editor's
    own output back as ``data`` is the documented double-input anti-pattern that
    makes edits disappear.
    """
    st.session_state[LEGS_BASE_KEY] = frame.copy().reset_index(drop=True)
    st.session_state.pop(LEGS_EDITOR_KEY, None)


def current_legs() -> pd.DataFrame:
    """Effective table (base + pending data_editor edits), readable before render."""
    return apply_editor_state(legs_base(), st.session_state.get(LEGS_EDITOR_KEY))


def render_leg_builder(state: dict, today: date) -> pd.DataFrame:
    """Editable multi-leg position builder.

    State pattern (idiomatic Streamlit): ``data=legs_base()`` is a *stable*
    frame and ``key=LEGS_EDITOR_KEY`` is the single source of truth for user
    edits. The editor's return value is never stored back into the base: with
    ``num_rows="dynamic"`` Streamlit includes the data in the widget identity,
    so feeding edits back would change the element id on every rerun and drop
    the pending edit (the "must type it twice" bug).
    """
    st.subheader("2 · Builder posizioni multi-leg")
    legs_base()  # ensure the base exists before the buttons below read it

    col_a, col_b, _ = st.columns([1, 1, 2])
    if col_a.button("Preset DRAM 59/70", width="stretch"):
        set_legs_base(DEMO_LEGS)
        st.session_state["ticker"] = DEMO_TICKER
        st.session_state["spot"] = DEMO_SPOT
        st.rerun()
    if col_b.button("Precompila dal mid", width="stretch",
                    disabled=state["spot"] is None):
        set_legs_base(
            prefill_from_chain(
                current_legs(), state["ticker"], state["spot"], state["rate"], today
            )
        )
        st.success("Premi e IV precompilati dalla catena (mid + IV per-strike).")

    expiry_options = [e.isoformat() for e in state["expirations"]] or ["2026-12-18"]
    edited = st.data_editor(
        legs_base(),
        num_rows="dynamic",
        width="stretch",
        column_config={
            "Tipo": st.column_config.SelectboxColumn(
                "Tipo", options=["call", "put"], required=True
            ),
            "Direzione": st.column_config.SelectboxColumn("Direzione", options=["long", "short"],
                                                           required=True),
            "Strike": st.column_config.NumberColumn("Strike", min_value=0.0, format="%.2f"),
            "Scadenza": st.column_config.SelectboxColumn("Scadenza", options=expiry_options,
                                                          required=True),
            "Qty": st.column_config.NumberColumn("Qty", min_value=1, step=1, default=1),
            "Premio": st.column_config.NumberColumn("Premio (per share)", min_value=0.0,
                                                     format="%.2f"),
            "IV": st.column_config.NumberColumn("IV (decimale)", min_value=0.0, format="%.3f"),
        },
        key=LEGS_EDITOR_KEY,
    )
    return edited


def render_config(state: dict) -> PayoffConfig:
    """Price-grid and time-slice configuration."""
    st.subheader("3 · Griglia & slice")
    spot = state["spot"] or DEMO_SPOT
    c1, c2, c3, c4 = st.columns(4)
    price_min = c1.number_input("Prezzo min", value=round(spot * 0.6, 2), step=1.0)
    price_max = c2.number_input("Prezzo max", value=round(spot * 1.4, 2), step=1.0)
    n_points = c3.slider("Punti griglia", min_value=20, max_value=400, value=121, step=1)
    n_slices = c4.slider("Slice temporali", min_value=2, max_value=40, value=12, step=1)
    return PayoffConfig(
        price_min=float(price_min), price_max=float(price_max),
        n_points=int(n_points), n_slices=int(n_slices),
    )


def render_surface_view(result, position: Position) -> None:
    """P&L surface selector with a non-WebGL-safe default (matplotlib / heatmap)."""
    view = st.radio(
        "Vista superficie P&L (prezzo × tempo)",
        SURFACE_VIEWS,
        index=0,
        horizontal=True,
        key="surface_view",
        help="La vista Plotly 3D richiede WebGL attivo nel browser.",
    )
    if view == SURFACE_VIEWS[0]:
        st.image(
            surface_matplotlib_png(result, position),
            width="stretch",
            caption="Superficie 3D con matplotlib: immagine statica, non richiede WebGL.",
        )
    elif view == SURFACE_VIEWS[1]:
        st.plotly_chart(heatmap_figure(result, position), width="stretch")
    else:
        st.plotly_chart(surface_figure(result), width="stretch")
    st.caption(
        "Default non-WebGL. Se la superficie 3D di Plotly non compare "
        "(WebGL disabilitato nel browser), usa la vista matplotlib o la heatmap 2D."
    )


def render_results(position: Position, config: PayoffConfig, today: date) -> None:
    """Compute and render all interactive outputs."""
    if not position.legs:
        st.warning("Aggiungi almeno un leg.")
        return
    if config.price_max <= config.price_min:
        st.error("Il prezzo massimo deve essere maggiore del minimo.")
        return

    with st.spinner("Calcolo payoff…"):
        result = compute_payoff(position, config, today=today)

    st.subheader("4 · Livelli chiave & Greci netti")
    render_validation(position)
    render_input_echo(position, config, result)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Max loss (reale)", format_extreme(result.max_loss, "−∞"))
    m2.metric("Max profit (reale)", format_extreme(result.max_profit, "+∞"))
    be = ", ".join(f"{b:,.2f}" for b in result.breakevens) or "nessuno nel range"
    m3.metric("Break-even", be)
    m4.metric("Net debit", f"${result.net_debit:,.2f}")
    if result.spot_pnl is not None:
        m5.metric("P&L @ spot", f"${result.spot_pnl:,.2f}")

    st.caption(
        "**Max loss/profit = estremi analitici a scadenza** su S ∈ [0, +∞) "
        "(punti notevoli: S=0, tutti gli strike, asintoto) — indipendenti dalla "
        "griglia scelta. "
        f"P&L sulla griglia {config.price_min:,.2f}–{config.price_max:,.2f}: "
        f"min ${result.grid_min:,.2f} / max ${result.grid_max:,.2f}. "
        "«illimitato» = estremo non limitato (net long/short call sull'ala destra)."
    )

    g1, g2, g3, g4 = st.columns(4)
    g1.metric("Delta", f"{result.net_greeks.delta:,.2f}")
    g2.metric("Gamma", f"{result.net_greeks.gamma:,.3f}")
    g3.metric("Theta", f"{result.net_greeks.theta:,.2f}")
    g4.metric("Vega", f"{result.net_greeks.vega:,.2f}")

    st.subheader("5 · Curve & superficie interattive")
    st.plotly_chart(expiry_curve_figure(result, position), width="stretch")
    st.plotly_chart(fan_figure(result, position), width="stretch")
    with st.expander("Superficie 3D P&L (prezzo × tempo)", expanded=True):
        render_surface_view(result, position)
    with st.expander("Tabella P&L sulla griglia prezzi"):
        st.dataframe(payoff_table(result), width="stretch", height=360)


def main() -> None:
    """Streamlit entry point."""
    render_header()
    today = date.today()
    state = render_sidebar()
    legs_frame = render_leg_builder(state, today)
    config = render_config(state)

    legs = parse_legs(legs_frame)
    spot = state["spot"] or (DEMO_SPOT if state["ticker"] == DEMO_TICKER else None)
    position = Position(
        ticker=state["ticker"] or "N/A",
        legs=legs,
        underlying_price=spot,
        multiplier=DEFAULT_MULTIPLIER,
        rate=state["rate"],
    )
    render_results(position, config, today)


if __name__ == "__main__":
    main()
