"""Budget App"""

import time
import os
import sys

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
from dotenv import load_dotenv
from pydantic import BaseModel, Field

# Carica variabili d'ambiente
load_dotenv()

# Import AI Provider
try:
    from agents.ai_provider import AIProvider
    from agents.cloud_manager import CloudManager
    from agents.bank_importer import BankImporter
    from agents.opencode_agent import OpencodeAgent, OpencodeConfig
except ImportError as e:
    AIProvider = None
    CloudManager = None
    BankImporter = None
    OpencodeAgent = None

try:
    from agents.cloud_ui import render_cloud_sync_ui
except ImportError:

    def render_cloud_sync_ui(DATA_FILE, is_sidebar=True):
        import streamlit as _st
        _st.error("Funzione Cloud UI non disponibile")


DATA_FILE = "budget_database.csv"

import db


# --- Data Models (Pydantic) ---
class ForecastPoint(BaseModel):
    """Singolo punto della proiezione futura (netto mensile + IC)."""

    date: str
    net: float
    lower: float
    upper: float


class ForecastResult(BaseModel):
    """Risultato della proiezione deterministico (trend + stagionalità)."""

    method: str = "linear_trend_seasonal"
    ci_level: float = 0.80
    points: list[ForecastPoint] = Field(default_factory=list)


# --- Calcoli ---
def calculate_metrics(df):
    """Calcola le metriche"""
    cols = df.columns.tolist()

    # Colonne da escludere dai calcoli di somma (metadati o colonne calcolate esistenti)
    excluded_from_sum = [
        "Year",
        "MonthNum",
        "Month",
        "Notes",
        "Reddito meno spese",
        "Risparmio %",
        "Totale Entrate",
        "Totale Uscite",
    ]

    # Definisci esplicitamente le entrate (evita match parziali errati)
    income_cols = ["Stipendio", "Reddito aggiuntivo"]

    # Verifica che le colonne esistano effettivamente nel DF (per sicurezza)
    income_cols = [c for c in income_cols if c in cols]

    # Tutto il resto (non escluso e non entrata) è una spesa
    expense_cols = [
        c for c in cols if c not in income_cols and c not in excluded_from_sum
    ]

    # Calcolo Totali
    df["Totale Entrate"] = df[income_cols].sum(axis=1)
    df["Totale Uscite"] = df[expense_cols].sum(axis=1)

    # Ricalcolo colonne derivate (sovrascrive quelle del CSV per coerenza)
    df["Reddito meno spese"] = df["Totale Entrate"] - df["Totale Uscite"]

    # Gestione divisione per zero (vettorializzato)
    with np.errstate(divide="ignore", invalid="ignore"):
        df["Risparmio %"] = np.where(
            df["Totale Entrate"] != 0,
            df["Reddito meno spese"] / df["Totale Entrate"] * 100.0,
            0.0,
        )

    return df, expense_cols, income_cols


def prepare_timeseries(df):
    """Prepara la serie temporale: DateObj, sort asc, Patrimonio e Investimenti cumulativi.

    Restituisce (df_sorted_asc, df_desc).
    """
    df = df.copy()
    df["DateStr"] = (
        df["Year"].astype(str) + "-" + df["MonthNum"].astype(str).str.zfill(2)
    )
    df["DateObj"] = pd.to_datetime(df["DateStr"])
    # Ordiniamo dal passato al presente per calcolo cumulativo corretto
    df_sorted_asc = df.sort_values("DateObj", ascending=True)
    df_sorted_asc["Patrimonio"] = df_sorted_asc["Reddito meno spese"].cumsum()

    # Calcolo Cumulativo Investimenti
    if "Investimenti" in df_sorted_asc.columns:
        df_sorted_asc["Investimenti_Cumulativo"] = (
            df_sorted_asc["Investimenti"].fillna(0).cumsum()
        )
    else:
        df_sorted_asc["Investimenti_Cumulativo"] = 0.0

    df_desc = df_sorted_asc.sort_values("DateObj", ascending=False)
    return df_sorted_asc, df_desc


# --- P1.4 Forecast deterministico (no statsmodels) ---
def build_forecast(df_sorted_asc, months=12, ci_z=1.28):
    """Proiezione del netto mensile ("Reddito meno spese") con:
    - trend lineare (numpy polyfit);
    - stagionalità per mese di calendario (media dei residui detrendizzati);
    - intervallo di confidenza empirico = z * deviazione standard dei residui.

    `ci_z=1.28` corrisponde a ~80% di confidenza.
    """
    series = df_sorted_asc["Reddito meno spese"].astype(float).reset_index(drop=True)
    dates = pd.Series(df_sorted_asc["DateObj"].reset_index(drop=True))
    n = len(series)

    if n < 2:
        return ForecastResult(method="insufficient_data", points=[])

    t = np.arange(n, dtype=float)
    slope, intercept = np.polyfit(t, series.values, 1)
    trend = slope * t + intercept
    resid = series.values - trend

    month_idx = dates.dt.month.values
    seasonal = np.zeros(13)
    for m in range(1, 13):
        mask = month_idx == m
        if mask.any():
            seasonal[m] = resid[mask].mean()

    fitted = trend + np.array([seasonal[m] for m in month_idx])
    resid_full = series.values - fitted
    resid_std = float(resid_full.std(ddof=1)) if n > 2 else 0.0

    last_date = dates.iloc[-1]
    points = []
    for h in range(1, months + 1):
        future_date = last_date + pd.DateOffset(months=h)
        fm = future_date.month
        pred = slope * (n + h - 1) + intercept + seasonal[fm]
        band = ci_z * resid_std
        points.append(
            ForecastPoint(
                date=future_date.strftime("%Y-%m-%d"),
                net=float(pred),
                lower=float(pred - band),
                upper=float(pred + band),
            )
        )

    return ForecastResult(points=points)


# --- P0.1 + P1.4: Evoluzione Patrimonio con proiezione ---
def build_patrimonio_figure(df_sorted_asc, forecast=None):
    """Grafico Evoluzione Patrimonio. Se `forecast` è fornito, estende la
    serie storica con linea tratteggiata, fascia di incertezza (IC) e barre
    semi-trasparenti del netto mensile futuro su asse secondario."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Scatter(
            x=df_sorted_asc["DateObj"],
            y=df_sorted_asc["Patrimonio"],
            fill="tozeroy",
            mode="lines+markers",
            name="Patrimonio",
            line=dict(color="#3498db", width=3),
            fillcolor="rgba(52, 152, 219, 0.15)",
            hovertemplate="%{x|%b %Y}: € %{y:,.2f}<extra></extra>",
        ),
        secondary_y=False,
    )

    if forecast is not None and forecast.points:
        last_pat = float(df_sorted_asc["Patrimonio"].iloc[-1])
        f_dates = [pd.to_datetime(p.date) for p in forecast.points]
        f_net = np.array([p.net for p in forecast.points], dtype=float)
        f_lower = np.array([p.lower for p in forecast.points], dtype=float)
        f_upper = np.array([p.upper for p in forecast.points], dtype=float)

        f_pat = last_pat + np.cumsum(f_net)
        f_pat_lower = last_pat + np.cumsum(f_lower)
        f_pat_upper = last_pat + np.cumsum(f_upper)

        # Fascia di incertezza (IC)
        fig.add_trace(
            go.Scatter(
                x=f_dates + f_dates[::-1],
                y=np.concatenate([f_pat_upper, f_pat_lower[::-1]]),
                fill="toself",
                fillcolor="rgba(52, 152, 219, 0.18)",
                line=dict(color="rgba(0,0,0,0)"),
                hoverinfo="skip",
                name="Intervallo 80%",
            ),
            secondary_y=False,
        )

        # Linea proiezione patrimonio (tratteggiata)
        fig.add_trace(
            go.Scatter(
                x=f_dates,
                y=f_pat,
                mode="lines",
                name="Proiezione Patrimonio",
                line=dict(color="#3498db", width=2, dash="dash"),
                hovertemplate="%{x|%b %Y}: € %{y:,.2f}<extra></extra>",
            ),
            secondary_y=False,
        )

        # Barre semi-trasparenti del netto mensile futuro (asse secondario)
        fig.add_trace(
            go.Bar(
                x=f_dates,
                y=f_net,
                name="Netto mensile (futuro)",
                marker_color=["#2ecc71" if v >= 0 else "#e74c3c" for v in f_net],
                opacity=0.35,
                hovertemplate="%{x|%b %Y}: € %{y:,.2f}<extra></extra>",
            ),
            secondary_y=True,
        )

        # Area futura evidenziata
        fig.add_vrect(
            x0=f_dates[0],
            x1=f_dates[-1],
            fillcolor="rgba(241, 196, 15, 0.06)",
            line_width=0,
        )

    fig.add_hline(
        y=0, line_dash="dash", line_color="white", opacity=0.3, secondary_y=False
    )
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis_title="",
        yaxis_title="Patrimonio (€)",
        xaxis=dict(type="date", tickformat="%b %Y"),
        hovermode="x unified",
        margin=dict(l=0, r=0, t=30, b=0),
        height=380,
        legend=dict(orientation="h", y=1.1),
    )
    fig.update_layout(yaxis2_title="Netto mensile (€)")
    fig.update_yaxes(showgrid=False, secondary_y=True)
    return fig


# --- P1.1 Trend spese per categoria (stacked area) ---
def build_trend_category_figure(df_sorted_asc, expense_cols, top_n=5):
    """Stacked area delle voci di spesa per mese: top N categorie + 'Altro'."""
    monthly = df_sorted_asc.set_index("DateObj")[expense_cols].fillna(0).copy()
    totals = monthly.sum(axis=0)
    top_cats = totals.sort_values(ascending=False).head(top_n).index.tolist()
    other_cats = [c for c in expense_cols if c not in top_cats]

    data = monthly[top_cats].copy()
    if other_cats:
        data["Altro"] = monthly[other_cats].sum(axis=1)

    colors = px.colors.qualitative.Plotly[: len(data.columns)]

    fig = go.Figure()
    for i, col in enumerate(data.columns):
        fig.add_trace(
            go.Scatter(
                x=data.index,
                y=data[col],
                mode="lines",
                stackgroup="one",
                name=col,
                line=dict(width=0.6, color=colors[i % len(colors)]),
                hovertemplate="%{x|%b %Y}: € %{y:,.2f}<extra>%{fullData.name}</extra>",
            )
        )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis_title="",
        yaxis_title="€ Euro",
        xaxis=dict(type="date", tickformat="%b %Y"),
        hovermode="x unified",
        margin=dict(l=0, r=0, t=30, b=0),
        height=350,
        legend=dict(orientation="h", y=1.1),
    )
    return fig


# --- P1.2 Confronto YoY (stesso mese negli anni) ---
def build_yoy_figure(df, sel_month, sel_year, years=3):
    """Grouped bar: Entrate vs Uscite per lo stesso mese nei `years` anni."""
    target_years = list(range(sel_year - (years - 1), sel_year + 1))
    rows = df[
        (df["Month"] == sel_month) & (df["Year"].isin(target_years))
    ].sort_values("Year")

    if rows.empty:
        return go.Figure()

    x_labels = [f"{sel_month} {int(y)}" for y in rows["Year"]]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(
            x=x_labels,
            y=rows["Totale Entrate"],
            name="Entrate",
            marker_color="#2ecc71",
            hovertemplate="€ %{y:,.2f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Bar(
            x=x_labels,
            y=rows["Totale Uscite"],
            name="Uscite",
            marker_color="#e74c3c",
            hovertemplate="€ %{y:,.2f}<extra></extra>",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=x_labels,
            y=rows["Reddito meno spese"],
            name="Netto",
            mode="lines+markers",
            line=dict(color="#f1c40f", width=3),
            hovertemplate="€ %{y:,.2f}<extra></extra>",
        )
    )

    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis_title="",
        yaxis_title="€ Euro",
        barmode="group",
        hovermode="x unified",
        margin=dict(l=0, r=0, t=30, b=0),
        height=350,
        legend=dict(orientation="h", y=1.1),
    )
    return fig


# --- P1.3 Run-rate / burn-rate KPI ---
def compute_runrate_metrics(df_sorted_asc, window=12):
    """Metriche run-rate sugli ultimi `window` mesi."""
    tail = df_sorted_asc.tail(window)
    avg_income = float(tail["Totale Entrate"].mean()) if not tail.empty else 0.0
    avg_expense = float(tail["Totale Uscite"].mean()) if not tail.empty else 0.0
    avg_savings = avg_income - avg_expense
    savings_rate = (avg_savings / avg_income * 100.0) if avg_income else 0.0

    return {
        "avg_income": avg_income,
        "avg_expense": avg_expense,
        "avg_savings": avg_savings,
        "savings_rate": savings_rate,
        "income_series": tail["Totale Entrate"].astype(float).tolist(),
        "expense_series": tail["Totale Uscite"].astype(float).tolist(),
        "net_series": tail["Reddito meno spese"].astype(float).tolist(),
        "savings_rate_series": tail["Risparmio %"].astype(float).tolist(),
    }


def build_sparkline(values, color, fill=True):
    """Micro sparkline (linea compatta) per le KPI cards."""
    fig = go.Figure(
        go.Scatter(
            y=list(values),
            mode="lines",
            line=dict(color=color, width=2),
            fill="tozeroy" if fill else None,
        )
    )
    fig.update_layout(
        height=60,
        margin=dict(l=0, r=0, t=0, b=0),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        showlegend=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    return fig


# --- P2.2 Waterfall mensile ---
def build_waterfall_figure(df, sel_month, sel_year, expense_cols, top_n=6):
    """Bridge Entrate → principali spese → Risparmio netto per il mese."""
    rows = df[(df["Month"] == sel_month) & (df["Year"] == sel_year)]
    if rows.empty:
        return go.Figure()
    row = rows.iloc[0]

    income = float(row["Totale Entrate"])
    exp = row[expense_cols].astype(float)
    exp_nonzero = exp[exp != 0].sort_values(ascending=False)
    top = exp_nonzero.head(top_n)
    other = float(exp_nonzero.iloc[top_n:].sum()) if len(exp_nonzero) > top_n else 0.0

    x = ["Entrate"]
    y = [income]
    measure = ["absolute"]

    for cat, val in top.items():
        x.append(cat)
        y.append(-float(val))
        measure.append("relative")

    if other > 0:
        x.append("Altre spese")
        y.append(-other)
        measure.append("relative")

    x.append("Risparmio Netto")
    y.append(0.0)
    measure.append("total")

    fig = go.Figure(
        go.Waterfall(
            x=x,
            y=y,
            measure=measure,
            textposition="outside",
            connector=dict(line=dict(color="rgba(255,255,255,0.3)")),
            increasing=dict(marker=dict(color="#2ecc71")),
            decreasing=dict(marker=dict(color="#e74c3c")),
            totals=dict(marker=dict(color="#3498db")),
            hovertemplate="%{x}: € %{y:,.2f}<extra></extra>",
        )
    )
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis_title="",
        yaxis_title="€ Euro",
        margin=dict(l=0, r=0, t=30, b=0),
        height=380,
    )
    fig.update_xaxes(tickangle=-25)
    return fig


# --- P2.3 Benchmark vs budget pianificato ---
def build_benchmark_figure(df, sel_month, sel_year, expense_cols, targets):
    """Bar affiancate: spesa effettiva vs target per categoria (mese)."""
    rows = df[(df["Month"] == sel_month) & (df["Year"] == sel_year)]
    if rows.empty:
        return go.Figure()
    row = rows.iloc[0]

    cats = [c for c in targets if c in expense_cols]
    actual = [float(row.get(c, 0.0)) for c in cats]
    target = [float(targets[c]) for c in cats]

    fig = go.Figure()
    fig.add_trace(
        go.Bar(x=cats, y=actual, name="Effettivo", marker_color="#3498db")
    )
    fig.add_trace(
        go.Bar(
            x=cats,
            y=target,
            name="Target",
            marker_color="#95a5a6",
            opacity=0.7,
        )
    )
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis_title="",
        yaxis_title="€ Euro",
        barmode="group",
        margin=dict(l=0, r=0, t=30, b=0),
        height=350,
        legend=dict(orientation="h", y=1.1),
    )
    fig.update_xaxes(tickangle=-25)
    return fig


def build_benchmark_delta_figure(df, sel_month, sel_year, expense_cols, targets):
    """Bar divergenti: eccesso (rosso) / deficit (verde) rispetto al target."""
    rows = df[(df["Month"] == sel_month) & (df["Year"] == sel_year)]
    if rows.empty:
        return go.Figure()
    row = rows.iloc[0]

    cats = [c for c in targets if c in expense_cols]
    delta = [float(row.get(c, 0.0)) - float(targets[c]) for c in cats]
    colors = ["#e74c3c" if d > 0 else "#2ecc71" for d in delta]

    fig = go.Figure(
        go.Bar(
            x=cats,
            y=delta,
            marker_color=colors,
            name="Delta",
            hovertemplate="%{x}: € %{y:,.2f}<extra></extra>",
        )
    )
    fig.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.3)
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis_title="",
        yaxis_title="Delta € (verde = sotto budget)",
        margin=dict(l=0, r=0, t=30, b=0),
        height=350,
        showlegend=False,
    )
    fig.update_xaxes(tickangle=-25)
    return fig


# --- Cached data loader (invalidato dopo ogni scrittura su DB) ---
@st.cache_data(ttl=300)
def load_data_cached():
    """Wrapper cacheato di db.load_data()."""
    return db.load_data()


def main():
    st.set_page_config(page_title="Budget Manager", page_icon="💰", layout="wide")

    db.init_db()
    if load_data_cached().empty and os.path.exists(DATA_FILE):
        db.migrate_from_csv(DATA_FILE)
        st.cache_data.clear()

    st.title("💰 Gestione Budget Personale")

    df = load_data_cached()

    if not df.empty:
        df, expense_cols, income_cols = calculate_metrics(df)

        # Sidebar per navigazione
        page = st.sidebar.radio(
            "Navigazione",
            ["Dashboard", "Gestione Dati", "Gestione Mese", "💬 Assistant AI"],
        )

        # --- AI CONFIGURATION UNIFICATA (Sidebar — SEMPRE VISIBILE, AUTO-ATTIVAZIONE) ---
        st.sidebar.divider()
        with st.sidebar.expander("🤖 AI Configuration", expanded=False):
            if AIProvider and OpencodeAgent:
                provider, model = AIProvider.render_streamlit_sidebar()

                # Auto-attiva al cambiamento di provider/modello, oppure se
                # l'agente manca (sessione stantia da un errore precedente).
                config_key = f"{provider}|{model or ''}"
                prev_key = st.session_state.get("_ai_config_key", "")
                needs_agent = (
                    provider == "opencode"
                    and "opencode_agent" not in st.session_state
                )

                if config_key != prev_key or needs_agent:
                    st.session_state["_ai_config_key"] = config_key
                    if provider and model:
                        try:
                            # Configura sempre AIProvider
                            st.session_state["ai_provider"] = AIProvider(
                                provider_type=provider,
                                model_name=model,
                            )
                            # Se OpenCode Go, configura anche OpencodeAgent
                            if provider == "opencode":
                                oc_model = (
                                    model
                                    if model.startswith("opencode-go/")
                                    else f"opencode-go/{model}"
                                )
                                st.session_state["opencode_agent"] = OpencodeAgent(
                                    OpencodeConfig(model=oc_model, timeout=300)
                                )
                            else:
                                st.session_state.pop("opencode_agent", None)
                        except Exception:
                            st.session_state.pop("_ai_config_key", None)
                            st.session_state.pop("opencode_agent", None)
                            st.session_state.pop("ai_provider", None)

        # --- DATABASE STATUS (Sidebar — SEMPRE VISIBILE) ---
        st.sidebar.divider()
        with st.sidebar.expander("💾 Database", expanded=False):
            info = db.get_db_info()
            st.caption(f"**File:** `{info['db_path']}`")
            st.caption(f"**Dimensione:** {info['db_size_kb']:.1f} KB")
            st.caption(f"**Records:** {info['row_count']}")
            if info['last_backup_time']:
                st.caption(f"**Ultimo backup:** {info['last_backup_time']}")
            if st.button("📥 Export CSV", key="db_export_csv"):
                db.export_to_csv(DATA_FILE)
                st.toast("CSV exportato!", icon="✅")

        # --- PAGINA DASHBOARD ---
        if page == "Dashboard":
            # Custom CSS per card effect
            st.markdown(
                """
            <style>
            .metric-card {
                background-color: #1E1E1E;
                padding: 15px;
                border-radius: 10px;
                border: 1px solid #333;
                box-shadow: 0 4px 6px rgba(0,0,0,0.3);
            }
            </style>
            """,
                unsafe_allow_html=True,
            )

            st.header("📊 Dashboard")

            # --- 0. PREPARAZIONE DATI GLOBALE ---
            df_sorted_asc, df = prepare_timeseries(df)

            # --- 1b. CLOUD DATA SYNC (Sidebar) ---
            # Esegui export+migrate UNA SOLA VOLTA all'avvio; re-importa solo
            # se il CSV cambia su disco (es. dopo un Pull dal cloud).
            if not st.session_state.get("_db_synced_once", False):
                db.export_to_csv(DATA_FILE)
                db.migrate_from_csv(DATA_FILE, force=True)
                st.session_state["_db_synced_once"] = True
                st.session_state["_csv_mtime"] = os.path.getmtime(DATA_FILE)
            render_cloud_sync_ui(DATA_FILE, is_sidebar=True)
            try:
                cur_mtime = os.path.getmtime(DATA_FILE)
                if cur_mtime != st.session_state.get("_csv_mtime"):
                    db.migrate_from_csv(DATA_FILE, force=True)
                    st.session_state["_csv_mtime"] = cur_mtime
                    st.cache_data.clear()
                    st.rerun()
            except OSError:
                pass

            # --- 2. FILTRI TEMPORALI (Sidebar) ---
            st.sidebar.divider()
            st.sidebar.subheader("📅 Filtri Temporali")

            # Selettore Mese
            available_months = (df["Month"] + " " + df["Year"].astype(str)).tolist()
            selected_month_str = st.sidebar.selectbox(
                "Seleziona Mese", available_months, index=0
            )

            # Filtro Orizzonte Temporale (Globale per Trend e Patrimonio)
            time_options = [3, 6, 12, 24, "All"]
            selected_time_window = st.sidebar.select_slider(
                "Orizzonte Trend (Mesi)", options=time_options, value=12
            )

            # --- DATI MESE SELEZIONATO ---
            sel_month, sel_year = selected_month_str.split(" ")
            sel_year = int(sel_year)
            selected_row = df[(df["Month"] == sel_month) & (df["Year"] == sel_year)].iloc[0]

            # --- 2. NET WORTH & GROWTH (Top Section) ---
            current_net_worth = selected_row["Patrimonio"]
            current_invested = selected_row.get("Investimenti_Cumulativo", 0.0)

            growth_val = 0
            growth_pct = 0
            has_growth_data = False

            inv_growth_val = 0
            inv_growth_pct = 0
            has_inv_growth = False

            if selected_time_window != "All":
                months_back = int(selected_time_window)
                target_date = selected_row["DateObj"] - pd.DateOffset(months=months_back)
                past_records = df[df["DateObj"] <= target_date]

                if not past_records.empty:
                    past_row = past_records.iloc[0]

                    past_net_worth = past_row["Patrimonio"]
                    growth_val = current_net_worth - past_net_worth
                    growth_pct = (
                        (growth_val / abs(past_net_worth) * 100)
                        if past_net_worth != 0
                        else 0
                    )
                    has_growth_data = True

                    past_invested = past_row.get("Investimenti_Cumulativo", 0.0)
                    inv_growth_val = current_invested - past_invested
                    inv_growth_pct = (
                        (inv_growth_val / abs(past_invested) * 100)
                        if past_invested != 0
                        else 0
                    )
                    has_inv_growth = True
            else:
                growth_val = current_net_worth
                has_growth_data = True

                inv_growth_val = current_invested
                has_inv_growth = True

            # Display Top Metrics
            with st.container(border=True):
                tc1, tc2, tc3 = st.columns([2, 2, 1])

                tc1.metric(
                    label="🏦 PATRIMONIO TOTALE PROIETTATO",
                    value=f"€ {current_net_worth:,.2f}",
                    delta=(
                        f"{'+' if growth_val >= 0 else ''}€ {growth_val:,.2f} ({growth_pct:.1f}%)"
                        if has_growth_data
                        else None
                    ),
                )

                tc2.metric(
                    label="📈 TOTALE INVESTITO PROIETTATO",
                    value=f"€ {current_invested:,.2f}",
                    delta=(
                        f"{'+' if inv_growth_val >= 0 else ''}€ {inv_growth_val:,.2f} ({inv_growth_pct:.1f}%)"
                        if has_inv_growth
                        else None
                    ),
                )

                tc3.caption(
                    f"Dati al:\n{selected_row['Month']} {selected_row['Year']}\n(Orizzonte {selected_time_window} mesi)"
                )

            # --- 2a. MESE DI RIFERIMENTO ---
            MONTHS_IT = {
                "January": "Gennaio",
                "February": "Febbraio",
                "March": "Marzo",
                "April": "Aprile",
                "May": "Maggio",
                "June": "Giugno",
                "July": "Luglio",
                "August": "Agosto",
                "September": "Settembre",
                "October": "Ottobre",
                "November": "Novembre",
                "December": "Dicembre",
            }
            ref_month_it = MONTHS_IT.get(sel_month, sel_month)
            first_date = df_sorted_asc["DateObj"].min()
            last_date = df_sorted_asc["DateObj"].max()
            storico_inizio = (
                f"{MONTHS_IT.get(first_date.strftime('%B'), first_date.strftime('%B'))} "
                f"{first_date.year}"
            )
            storico_fine = (
                f"{MONTHS_IT.get(last_date.strftime('%B'), last_date.strftime('%B'))} "
                f"{last_date.year}"
            )

            with st.container(border=True):
                st.subheader(f"📅 Mese di riferimento: {ref_month_it} {sel_year}")
                st.caption(f"Storico: {storico_inizio} → {storico_fine}")

            # --- P1.3 RUN-RATE & KPI ---
            st.subheader("⚡ Run-rate & KPI (ultimi 12 mesi)")
            runrate = compute_runrate_metrics(df_sorted_asc, window=12)
            rc1, rc2, rc3, rc4 = st.columns(4)
            with rc1:
                st.metric("Media Entrate", f"€ {runrate['avg_income']:,.0f}")
                st.plotly_chart(
                    build_sparkline(runrate["income_series"], "#2ecc71"),
                    width="stretch",
                )
            with rc2:
                st.metric("Media Uscite", f"€ {runrate['avg_expense']:,.0f}")
                st.plotly_chart(
                    build_sparkline(runrate["expense_series"], "#e74c3c"),
                    width="stretch",
                )
            with rc3:
                st.metric("Risparmio Medio", f"€ {runrate['avg_savings']:,.0f}")
                st.plotly_chart(
                    build_sparkline(runrate["net_series"], "#f1c40f"),
                    width="stretch",
                )
            with rc4:
                st.metric("Tasso Risparmio", f"{runrate['savings_rate']:.1f}%")
                st.plotly_chart(
                    build_sparkline(runrate["savings_rate_series"], "#3498db"),
                    width="stretch",
                )

            # --- 2b. EVOLUZIONE PATRIMONIO (P0.1 + P1.4 forecast) ---
            st.subheader("📈 Evoluzione Patrimonio (con proiezione 12 mesi)")

            forecast = build_forecast(df_sorted_asc, months=12)
            fig_patrimonio = build_patrimonio_figure(df_sorted_asc, forecast)
            st.plotly_chart(fig_patrimonio, width="stretch")
            # TODO (layer LLM): qui agganciare la narrativa/avvisi sulla proiezione.

            # --- 2c. ANDAMENTO INVESTIMENTI (P0.3) ---
            st.subheader("📈 Andamento Investimenti")

            col_inv_area, col_inv_bar = st.columns([1, 1])

            with col_inv_area:
                st.caption("Cumulativo")
                fig_inv_cum = go.Figure()
                fig_inv_cum.add_trace(
                    go.Scatter(
                        x=df_sorted_asc["DateObj"],
                        y=df_sorted_asc["Investimenti_Cumulativo"],
                        fill="tozeroy",
                        mode="lines+markers",
                        name="Investimenti Cumulativo",
                        line=dict(color="#9b59b6", width=3),
                        fillcolor="rgba(155, 89, 182, 0.15)",
                        hovertemplate="%{x|%b %Y}: € %{y:,.2f}<extra></extra>",
                    )
                )
                fig_inv_cum.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    xaxis_title="",
                    yaxis_title="€ Euro",
                    xaxis=dict(type="date", tickformat="%b %Y"),
                    hovermode="x unified",
                    margin=dict(l=0, r=0, t=30, b=0),
                    height=300,
                    showlegend=False,
                )
                st.plotly_chart(fig_inv_cum, width="stretch")

            with col_inv_bar:
                st.caption("Mensile")
                invest_vals = df_sorted_asc["Investimenti"].fillna(0)
                invest_colors = [
                    "#2ecc71" if v >= 0 else "#e74c3c" for v in invest_vals
                ]
                fig_inv_bar = go.Figure(
                    go.Bar(
                        x=df_sorted_asc["DateObj"],
                        y=invest_vals,
                        name="Investimenti Mensili",
                        marker_color=invest_colors,
                        hovertemplate="%{x|%b %Y}: € %{y:,.2f}<extra></extra>",
                    )
                )
                fig_inv_bar.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    xaxis_title="",
                    yaxis_title="€ Euro",
                    xaxis=dict(type="date", tickformat="%b %Y"),
                    hovermode="x unified",
                    margin=dict(l=0, r=0, t=30, b=0),
                    height=300,
                    showlegend=False,
                )
                st.plotly_chart(fig_inv_bar, width="stretch")

            # --- 3. TOP ROW (Gauge + KPI) ---
            col_gauge, col_kpi = st.columns([1, 2])

            with col_gauge:
                fig_gauge = go.Figure(
                    go.Indicator(
                        mode="gauge+number+delta",
                        value=selected_row["Risparmio %"],
                        title={"text": "Risparmio Mensile %"},
                        delta={
                            "reference": 20,
                            "increasing": {"color": "green"},
                        },
                        gauge={
                            "axis": {
                                "range": [-100, 100],
                                "tickwidth": 1,
                                "tickcolor": "white",
                            },
                            "bar": {
                                "color": (
                                    "#2ecc71"
                                    if selected_row["Risparmio %"] > 0
                                    else "#e74c3c"
                                )
                            },
                            "bgcolor": "rgba(0,0,0,0)",
                            "borderwidth": 2,
                            "bordercolor": "#333",
                            "steps": [
                                {"range": [-100, 0], "color": "#550000"},
                                {"range": [0, 20], "color": "#555500"},
                                {"range": [20, 100], "color": "#005500"},
                            ],
                        },
                    )
                )
                fig_gauge.update_layout(
                    paper_bgcolor="rgba(0,0,0,0)",
                    font={"color": "white"},
                    margin=dict(l=20, r=20, t=50, b=20),
                    height=300,
                )
                st.plotly_chart(fig_gauge, width="stretch")

                st.markdown(
                    f"<h3 style='text-align: center; color: {'#2ecc71' if selected_row['Reddito meno spese'] > 0 else '#e74c3c'}'>€ {selected_row['Reddito meno spese']:,.2f}</h3>",
                    unsafe_allow_html=True,
                )

            with col_kpi:
                with st.container(border=True):
                    c1, c2 = st.columns(2)
                    c1.metric(
                        "Entrate Totali",
                        f"€ {selected_row['Totale Entrate']:,.2f}",
                        delta="Incassato",
                    )
                    c2.metric(
                        "Uscite Totali",
                        f"€ {selected_row['Totale Uscite']:,.2f}",
                        delta="- Speso",
                        delta_color="inverse",
                    )

                st.write("")

                expenses_only = selected_row[expense_cols]
                top_cat = expenses_only.idxmax()
                top_val = expenses_only.max()

                with st.container(border=True):
                    st.subheader("⚠️ Categoria Critica")
                    st.write(f"**{top_cat}**: € {top_val:,.2f}")
                    st.progress(
                        min(top_val / (selected_row["Totale Entrate"] or 1), 1.0),
                        text="Pressione sul Budget",
                    )

            # --- 4. MIDDLE ROW (Cash Flow Trend) ---
            df_trend = df.sort_values("DateObj")

            st.subheader("🌊 Flusso di Cassa")

            selected_date_obj = pd.to_datetime(selected_row["DateStr"])

            df_trend = df_trend[df_trend["DateObj"] <= selected_date_obj]

            if selected_time_window != "All":
                df_trend = df_trend.tail(int(selected_time_window))

            fig_trend = go.Figure()
            fig_trend.add_trace(
                go.Scatter(
                    x=df_trend["DateObj"],
                    y=df_trend["Totale Entrate"],
                    fill="tozeroy",
                    mode="lines",
                    name="Entrate",
                    line=dict(color="#2ecc71", width=3),
                    fillcolor="rgba(46, 204, 113, 0.1)",
                )
            )
            fig_trend.add_trace(
                go.Scatter(
                    x=df_trend["DateObj"],
                    y=df_trend["Totale Uscite"],
                    fill="tozeroy",
                    mode="lines",
                    name="Uscite",
                    line=dict(color="#e74c3c", width=3),
                    fillcolor="rgba(231, 76, 60, 0.1)",
                )
            )

            avg_income = df_trend["Totale Entrate"].mean()
            avg_expense = df_trend["Totale Uscite"].mean()

            fig_trend.add_hline(
                y=avg_income,
                line_dash="dot",
                line_color="#2ecc71",
                opacity=0.7,
                annotation_text=f"Media Entrate: €{avg_income:,.0f}",
                annotation_position="top left",
            )
            fig_trend.add_hline(
                y=avg_expense,
                line_dash="dot",
                line_color="#e74c3c",
                opacity=0.7,
                annotation_text=f"Media Uscite: €{avg_expense:,.0f}",
                annotation_position="bottom left",
            )

            fig_trend.add_vline(
                x=selected_date_obj.timestamp() * 1000,
                line_width=1,
                line_dash="dash",
                line_color="white",
                annotation_text="Selected",
            )

            fig_trend.update_layout(
                template="plotly_dark",
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis_title="",
                yaxis_title="€ Euro",
                xaxis=dict(type="date"),
                hovermode="x unified",
                margin=dict(l=0, r=0, t=30, b=0),
                height=350,
                legend=dict(orientation="h", y=1.1),
            )
            st.plotly_chart(fig_trend, width="stretch")

            # --- P2.2 WATERFALL MENSILE ---
            with st.container(border=True):
                st.subheader(f"🌊 Waterfall — {ref_month_it} {sel_year}")
                fig_waterfall = build_waterfall_figure(
                    df, sel_month, sel_year, expense_cols, top_n=6
                )
                st.plotly_chart(fig_waterfall, width="stretch")

            # --- 4. BOTTOM ROW (Breakdown) ---
            c_donut, c_details = st.columns([1, 1])

            with c_donut:
                st.subheader("🍩 Breakdown Spese")
                pie_data = expenses_only[expenses_only > 0]

                fig_pie = px.pie(
                    values=pie_data.values,
                    names=pie_data.index,
                    hole=0.6,
                    color_discrete_sequence=px.colors.qualitative.Pastel,
                )
                fig_pie.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=0, r=0, t=30, b=0),
                    showlegend=True,
                    height=350,
                )
                st.plotly_chart(fig_pie, width="stretch")

            with c_details:
                st.subheader("📋 Dettaglio Spese")

                tab_mese, tab_periodo = st.tabs(["Mese Selezionato", f"Periodo ({selected_time_window} mesi)" if selected_time_window != "All" else "Tutto lo storico"])

                with tab_mese:
                    table_data = expenses_only[expenses_only != 0]

                    sorted_expenses = table_data.sort_values(ascending=False).to_frame(
                        name="Importo"
                    )

                    total_positive_expenses = expenses_only[expenses_only > 0].sum()

                    if total_positive_expenses > 0:
                        sorted_expenses["%"] = (
                            sorted_expenses["Importo"] / total_positive_expenses * 100
                        ).astype(float).round(1).astype(str) + "%"
                    else:
                        sorted_expenses["%"] = "0%"

                    st.write("**Top 5 Voci**")
                    st.dataframe(
                        sorted_expenses.head(5).style.format({"Importo": "€ {:,.2f}"}),
                        width="stretch",
                        height=250,
                    )

                    if len(sorted_expenses) > 5:
                        has_negatives = (sorted_expenses["Importo"] < 0).any()
                        label_expander = (
                            "🔍 Altre Spese e Rimborsi" if has_negatives else "🔍 Altre Spese"
                        )

                        with st.expander(label_expander):
                            st.dataframe(
                                sorted_expenses.iloc[5:].style.format({"Importo": "€ {:,.2f}"}),
                                width="stretch",
                            )

                with tab_periodo:
                    period_expenses_sum = df_trend[expense_cols].sum()
                    period_expenses_mean = df_trend[expense_cols].mean()

                    period_table_data = period_expenses_sum[period_expenses_sum != 0]

                    sorted_period = period_table_data.sort_values(ascending=False).to_frame(name="Totale")
                    sorted_period["Media Mensile"] = period_expenses_mean[sorted_period.index]

                    total_positive_period = period_expenses_sum[period_expenses_sum > 0].sum()

                    if total_positive_period > 0:
                        sorted_period["% Incidenza"] = (sorted_period["Totale"] / total_positive_period * 100).astype(float).round(1).astype(str) + "%"
                    else:
                        sorted_period["% Incidenza"] = "0%"

                    sorted_period = sorted_period[["Totale", "Media Mensile", "% Incidenza"]]

                    st.write(f"**Analisi su {len(df_trend)} mensilità**")

                    st.dataframe(
                        sorted_period.style.format({
                            "Totale": "€ {:,.2f}",
                            "Media Mensile": "€ {:,.2f}"
                        }),
                        width="stretch",
                        height=400,
                    )

            st.divider()

            # --- P2.1 DRILL-DOWN GIORNALIERO ---
            with st.container(border=True):
                st.subheader("🧾 Transazioni Giornaliere")
                month_ref = f"{sel_month} {sel_year}"
                txs = db.load_transactions(month_ref)
                if txs.empty:
                    st.info(
                        "Nessuna transazione giornaliera per questo mese. "
                        "Importa un estratto conto banca (Gestione Mese) per popolare il dettaglio."
                    )
                else:
                    st.caption(
                        f"{len(txs)} transazioni registrate per {ref_month_it} {sel_year}"
                    )
                    display_txs = txs[["date", "description", "category", "amount"]].copy()
                    display_txs.columns = ["Data", "Descrizione", "Categoria", "Importo €"]
                    st.dataframe(
                        display_txs.style.format({"Importo €": "€ {:,.2f}"}),
                        width="stretch",
                        height=300,
                    )

            # --- P2.3 BENCHMARK VS BUDGET PIANIFICATO ---
            with st.container(border=True):
                st.subheader("🎯 Benchmark: Spesa Effettiva vs Budget Pianificato")

                targets = db.get_budget_targets()
                historical_mean = df_sorted_asc[expense_cols].mean().astype(float)
                defaults = {c: float(historical_mean.get(c, 0.0)) for c in expense_cols}

                with st.expander("⚙️ Imposta Target Mensili per Categoria", expanded=False):
                    if not targets:
                        st.caption(
                            "Nessun target salvato: prefill con la media storica, poi clicca 'Salva Target'."
                        )
                    editor_df = pd.DataFrame(
                        {
                            "Categoria": list(expense_cols),
                            "Target Mensile €": [
                                round(targets.get(c, defaults.get(c, 0.0)), 2)
                                for c in expense_cols
                            ],
                        }
                    )
                    edited_targets = st.data_editor(
                        editor_df,
                        num_rows="fixed",
                        width="stretch",
                        hide_index=True,
                        column_config={
                            "Categoria": st.column_config.TextColumn(
                                "Categoria", disabled=True, width="large"
                            ),
                            "Target Mensile €": st.column_config.NumberColumn(
                                "Target Mensile €", format="€ %.2f"
                            ),
                        },
                        key="budget_targets_editor",
                    )
                    if st.button("💾 Salva Target", key="save_budget_targets"):
                        tgt = {
                            str(r["Categoria"]): float(r["Target Mensile €"])
                            for _, r in edited_targets.iterrows()
                        }
                        db.save_budget_targets(tgt)
                        st.toast("Target salvati!", icon="✅")

                if targets:
                    effective = {
                        c: float(targets.get(c, defaults.get(c, 0.0)))
                        for c in expense_cols
                    }
                    c_bench, c_delta = st.columns(2)
                    with c_bench:
                        st.caption("Effettivo vs Target")
                        st.plotly_chart(
                            build_benchmark_figure(
                                df, sel_month, sel_year, expense_cols, effective
                            ),
                            width="stretch",
                        )
                    with c_delta:
                        st.caption("Scostamento (verde = sotto budget)")
                        st.plotly_chart(
                            build_benchmark_delta_figure(
                                df, sel_month, sel_year, expense_cols, effective
                            ),
                            width="stretch",
                        )
                else:
                    st.info("Imposta i target (⚙️ sopra) per vedere il confronto effettivo vs budget.")

            # --- 5. ADVANCED STATS SECTION ---
            st.header("🏆 Analisi Risparmio Avanzata")

            with st.container(border=True):
                st.subheader("📈 Andamento % Risparmio")
                fig_sav = go.Figure()

                df_trend_all = df.sort_values("DateObj")

                fig_sav.add_trace(
                    go.Scatter(
                        x=df_trend_all["DateObj"],
                        y=df_trend_all["Risparmio %"],
                        mode="lines+markers",
                        name="Risparmio %",
                        line=dict(width=3, color="#f1c40f"),
                        hovertemplate="%{y:.1f}%<extra></extra>",
                    )
                )

                fig_sav.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.3)
                fig_sav.add_hline(
                    y=20,
                    line_dash="dash",
                    line_color="#2ecc71",
                    opacity=0.5,
                    annotation_text="Obiettivo 20%",
                )

                fig_sav.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    xaxis_title="",
                    yaxis_title="%",
                    height=300,
                    margin=dict(l=0, r=0, t=30, b=0),
                )
                st.plotly_chart(fig_sav, width="stretch")

                c_best, c_drivers = st.columns([1, 1])

                with c_best:
                    st.subheader("🌟 Mesi Migliori")
                    best_months = df.sort_values("Risparmio %", ascending=False).head(3)

                    for i, (_, row) in enumerate(best_months.iterrows()):
                        with st.container(border=True):
                            cols = st.columns([1, 2])
                            cols[0].metric(f"#{i+1}", f"{row['Risparmio %']:.1f}%")
                            cols[1].write(f"**{row['Month']} {row['Year']}**")
                            cols[1].caption(f"Netto: € {row['Reddito meno spese']:,.0f}")

                with c_drivers:
                    st.subheader("🔍 Driver di Successo")
                    if not best_months.empty:
                        best_month_row = best_months.iloc[0]
                        avg_expenses = df[expense_cols].mean()
                        best_month_expenses = best_month_row[expense_cols]

                        diffs = best_month_expenses - avg_expenses

                        savings_drivers = diffs.sort_values().head(3)

                        st.write(
                            f"Nel tuo mese migliore (**{best_month_row['Month']} {best_month_row['Year']}**), hai speso molto meno della media in:"
                        )

                        for cat, diff in savings_drivers.items():
                            if diff < 0:
                                st.markdown(
                                    f"- **{cat}**: :green[**€ {diff:,.0f}**] rispetto alla media"
                                )
                            else:
                                st.write(
                                    "Nessuna riduzione significativa di spese trovata rispetto alla media."
                                )

                        avg_income = df["Totale Entrate"].mean()
                        income_diff = best_month_row["Totale Entrate"] - avg_income
                        if income_diff > 0:
                            st.markdown(
                                f"💰 Inoltre, hai guadagnato :green[**€ {income_diff:,.0f}**] in più della media."
                            )
                    else:
                        st.info("Dati insufficienti per l'analisi.")

            # --- 6. RISPARMIO NETTO MENSILE (P0.2) ---
            with st.container(border=True):
                st.subheader("💶 Risparmio Netto Mensile")

                net = df_sorted_asc["Reddito meno spese"]
                net_colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in net]
                net_ma = net.rolling(window=6, min_periods=1).mean()

                fig_net = go.Figure()
                fig_net.add_trace(
                    go.Bar(
                        x=df_sorted_asc["DateObj"],
                        y=net,
                        name="Netto mensile",
                        marker_color=net_colors,
                        hovertemplate="%{x|%b %Y}: € %{y:,.2f}<extra></extra>",
                    )
                )
                fig_net.add_trace(
                    go.Scatter(
                        x=df_sorted_asc["DateObj"],
                        y=net_ma,
                        name="Media mobile 6 mesi",
                        mode="lines",
                        line=dict(color="#f1c40f", width=3),
                        hovertemplate="%{x|%b %Y}: € %{y:,.2f}<extra></extra>",
                    )
                )
                fig_net.add_hline(
                    y=0, line_dash="dash", line_color="white", opacity=0.3
                )
                fig_net.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    xaxis_title="",
                    yaxis_title="€ Euro",
                    xaxis=dict(type="date", tickformat="%b %Y"),
                    hovermode="x unified",
                    margin=dict(l=0, r=0, t=30, b=0),
                    height=350,
                    legend=dict(orientation="h", y=1.1),
                )
                st.plotly_chart(fig_net, width="stretch")

            # --- 7. HEATMAP ANNUALE (P0.4) ---
            with st.container(border=True):
                st.subheader("🗓️ Heatmap Spese Mensili (Anno × Mese)")

                heat_pivot = df_sorted_asc.pivot_table(
                    index="Year",
                    columns="MonthNum",
                    values="Totale Uscite",
                    aggfunc="sum",
                )
                heat_pivot = heat_pivot.reindex(columns=range(1, 13))

                month_labels = [
                    "Gen", "Feb", "Mar", "Apr", "Mag", "Giu",
                    "Lug", "Ago", "Set", "Ott", "Nov", "Dic",
                ]

                fig_heat = px.imshow(
                    heat_pivot,
                    x=month_labels,
                    y=heat_pivot.index.astype(str),
                    labels=dict(x="Mese", y="Anno", color="Totale Uscite (€)"),
                    color_continuous_scale="RdYlGn_r",
                    aspect="auto",
                    text_auto=".0f",
                )
                fig_heat.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="rgba(0,0,0,0)",
                    plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=0, r=0, t=30, b=0),
                    height=400,
                    coloraxis_colorbar=dict(title="€"),
                )
                fig_heat.update_xaxes(side="top")
                st.plotly_chart(fig_heat, width="stretch")

            # --- P1.1 TREND SPESE PER CATEGORIA ---
            with st.container(border=True):
                st.subheader("📊 Trend Spese per Categoria")
                fig_trend_cat = build_trend_category_figure(
                    df_sorted_asc, expense_cols, top_n=5
                )
                st.plotly_chart(fig_trend_cat, width="stretch")

            # --- P1.2 CONFRONTO YoY ---
            with st.container(border=True):
                st.subheader(f"🔁 Confronto Anno su Anno — {ref_month_it}")
                fig_yoy = build_yoy_figure(df, sel_month, sel_year, years=3)
                st.plotly_chart(fig_yoy, width="stretch")

        # --- PAGINA GESTIONE DATI (EDIT) ---
        elif page == "Gestione Dati":
            st.header("📝 Modifica Dati")
            st.info(
                "Modifica i valori direttamente nella tabella qui sotto. Le colonne dei Totali sono calcolate automaticamente."
            )

            editable_cols = ["Year", "MonthNum", "Month"] + income_cols + expense_cols

            edited_df = st.data_editor(
                df[editable_cols],
                num_rows="dynamic",
                width="stretch",
                height=600,
                column_config={
                    "Year": st.column_config.NumberColumn("Anno", format="%d"),
                    "MonthNum": st.column_config.NumberColumn("Mese (Num)", format="%d"),
                },
            )

            if st.button("Salva Modifiche", type="primary"):
                full_df = db.load_data()
                for col in edited_df.columns:
                    if col in full_df.columns:
                        full_df.loc[edited_df.index.intersection(full_df.index), col] = (
                            edited_df.loc[edited_df.index.intersection(full_df.index), col]
                        )
                new_rows = edited_df[~edited_df.index.isin(full_df.index)]
                if not new_rows.empty:
                    full_df = pd.concat([full_df, new_rows], ignore_index=True)
                db.save_data(full_df)
                st.rerun()

        # --- PAGINA GESTIONE MESE (AGGIUNGI/INCREMENTA) ---
        elif page == "Gestione Mese":
            st.header("➕ Gestione Mese")

            with st.expander("📂 Importa da Estratto Conto Banca (AI)", expanded=True):
                st.info(
                    "Carica il file della banca (CSV o PDF). L'AI estrarrà e categorizzerà le spese."
                )

                uploaded_bank_file = st.file_uploader(
                    "Carica File Banca", type=["csv", "pdf"], key="bank_uploader"
                )

                if uploaded_bank_file is not None and BankImporter:
                    has_ai = (
                        "ai_provider" in st.session_state
                        and st.session_state["ai_provider"] is not None
                    )
                    has_oc = (
                        "opencode_agent" in st.session_state
                        and st.session_state["opencode_agent"] is not None
                    )
                    if not has_ai and not has_oc:
                        st.error(
                            "⚠️ AI non configurata! Seleziona un provider e modello nella sidebar (🤖 AI Configuration)."
                        )
                    else:
                        if st.button("🚀 Analizza e Categorizza"):
                            progress_bar = st.progress(0, text="Avvio analisi...")
                            try:
                                if has_oc:
                                    importer = BankImporter(
                                        opencode_agent=st.session_state["opencode_agent"]
                                    )
                                else:
                                    importer = BankImporter(
                                        ai_provider=st.session_state["ai_provider"]
                                    )
                                target_cats = income_cols + expense_cols

                                def update_progress(p, msg):
                                    progress_bar.progress(p, text=msg)

                                results = importer.process_file(
                                    uploaded_bank_file,
                                    target_cats,
                                    income_cols,
                                    progress_callback=update_progress,
                                )

                                st.session_state["import_results"] = results

                                st.success("Analisi Completata!")
                                time.sleep(1)
                                progress_bar.empty()
                            except Exception as e:
                                st.error(f"Errore durante l'analisi: {e}")

                if (
                    "import_results" in st.session_state
                    and st.session_state["import_results"] is not None
                ):
                    results = st.session_state["import_results"]
                    detailed_df = results["detailed_df"]
                    report_md = results.get("report_md", "")
                    agg_df = results["aggregated_df"]

                    st.subheader("🔍 Revisione Categorizzazione")

                    target_cats = sorted(income_cols + expense_cols)

                    edit_df = detailed_df[["Std_Date", "Std_Description", "Betrag_Float", "Analyzed_Category", "New_Category"]].copy()
                    edit_df.columns = ["Data", "Descrizione", "Importo €", "Categoria Originale", "Categoria AI"]
                    edit_df["🗑️ Elimina"] = False
                    edit_df["Descrizione"] = edit_df["Descrizione"].astype(str).str[:50]

                    edited = st.data_editor(
                        edit_df,
                        column_config={
                            "Data": st.column_config.TextColumn("📅 Data", disabled=True),
                            "Descrizione": st.column_config.TextColumn("📝 Descrizione", disabled=True, width="large"),
                            "Importo €": st.column_config.NumberColumn("💶 Importo", format="€ %.2f", disabled=True),
                            "Categoria Originale": st.column_config.TextColumn("📁 Originale", disabled=True),
                            "Categoria AI": st.column_config.SelectboxColumn(
                                "🏷️ Categoria AI",
                                options=target_cats,
                                required=True,
                                width="medium",
                            ),
                            "🗑️ Elimina": st.column_config.CheckboxColumn("🗑️", default=False, width="small"),
                        },
                        use_container_width=True,
                        hide_index=True,
                        num_rows="fixed",
                        key="inline_category_editor",
                        height=min(len(edit_df) * 35 + 60, 600),
                    )

                    if st.button("✅ Applica Modifiche", type="secondary", key="apply_inline_edits"):
                        for i, orig_idx in enumerate(detailed_df.index):
                            new_cat = edited.iloc[i]["Categoria AI"]
                            if new_cat and new_cat in target_cats:
                                detailed_df.at[orig_idx, "New_Category"] = new_cat

                        rows_to_delete = edited[edited["🗑️ Elimina"] == True].index.tolist()
                        if rows_to_delete:
                            orig_indices_to_drop = [detailed_df.index[i] for i in rows_to_delete]
                            detailed_df = detailed_df.drop(orig_indices_to_drop)

                        dummy_importer = BankImporter(None)
                        new_agg = dummy_importer.aggregate_data(
                            detailed_df, target_cats, income_cols
                        )
                        new_rep = dummy_importer.generate_report(detailed_df)

                        st.session_state["import_results"]["detailed_df"] = detailed_df
                        st.session_state["import_results"]["aggregated_df"] = new_agg
                        st.session_state["import_results"]["report_md"] = new_rep

                        n_deleted = len(rows_to_delete)
                        msg = "Categorie aggiornate!"
                        if n_deleted > 0:
                            msg += f" {n_deleted} righe eliminate."
                        st.toast(msg, icon="✅")
                        time.sleep(0.5)
                        st.rerun()

                    st.divider()
                    st.subheader("📊 Totali Mensili (Anteprima)")
                    st.dataframe(agg_df)

                    if st.button("💾 Conferma e Salva nel Database", type="primary"):
                        try:
                            for _, new_row in agg_df.iterrows():
                                year = new_row["Year"]
                                month = new_row["Month"]

                                mask = (df["Year"] == year) & (df["Month"] == month)

                                if df[mask].any().any():
                                    for col in agg_df.columns:
                                        if col in df.columns and col not in [
                                            "Year",
                                            "Month",
                                            "MonthNum",
                                        ]:
                                            df.loc[mask, col] += new_row[col]
                                    st.toast(
                                        f"Aggiornato mese {month} {year} (Incrementale)",
                                        icon="➕",
                                    )
                                else:
                                    valid_cols = [
                                        c for c in agg_df.columns if c in df.columns
                                    ]
                                    filtered_row = new_row[valid_cols].to_frame().T
                                    df = pd.concat([df, filtered_row], ignore_index=True)
                                    st.toast(f"Creato nuovo mese {month} {year}", icon="✨")

                            db.save_data(df)

                            # P2.1: persiste le singole transazioni giornaliere
                            if BankImporter:
                                try:
                                    txn_records = BankImporter.build_transaction_records(
                                        detailed_df
                                    )
                                    db.save_transactions(txn_records)
                                except Exception as e:
                                    st.warning(
                                        f"Salvataggio transazioni giornaliere non riuscito: {e}"
                                    )

                            st.success(
                                "Importazione completata con successo! I dati sono stati salvati."
                            )

                            del st.session_state["import_results"]
                            time.sleep(2)
                            st.rerun()

                        except Exception as e:
                            st.error(f"Errore durante il salvataggio: {e}")

            st.divider()
            st.write("Oppure gestisci manualmente:")
            st.write(
                "Seleziona il mese e l'anno. Se il mese esiste già, potrai **aggiungere** importi a quelli esistenti (incrementale). Se non esiste, verrà creato."
            )

            col_y, col_m = st.columns(2)
            today = pd.Timestamp.now()
            year_input = col_y.number_input(
                "Anno", min_value=2020, max_value=2030, value=today.year
            )
            month_input = col_m.selectbox(
                "Mese",
                list(df["Month"].unique()),
                index=today.month - 1 if today.month <= 12 else 0,
            )

            month_map = {
                "January": 1,
                "February": 2,
                "March": 3,
                "April": 4,
                "May": 5,
                "June": 6,
                "July": 7,
                "August": 8,
                "September": 9,
                "October": 10,
                "November": 11,
                "December": 12,
            }
            month_num = month_map.get(month_input, 1)

            existing_mask = (df["Year"] == year_input) & (df["Month"] == month_input)
            is_existing = df[existing_mask].any().any()

            existing_row = None
            if is_existing:
                existing_row = df[existing_mask].iloc[0]
                st.info(
                    f"📅 **Mese Trovato:** {month_input} {year_input}. **Modalità Incrementale Attiva** (Gli importi inseriti verranno SOMMATI a quelli attuali)."
                )
                with st.expander("Vedi Valori Attuali", expanded=False):
                    st.dataframe(existing_row.to_frame().T)
            else:
                st.success(
                    f"✨ **Nuovo Mese:** {month_input} {year_input}. **Modalità Creazione**."
                )

            with st.form("month_manage_form"):
                st.subheader("Entrate (Aggiungi)")
                new_incomes = {}
                cols = st.columns(len(income_cols))
                for i, col_name in enumerate(income_cols):
                    base_val = 0.0
                    curr_label = ""
                    if is_existing:
                        curr_val = existing_row[col_name]
                        curr_label = f" (Attuale: €{curr_val:,.2f})"

                    new_incomes[col_name] = cols[i % len(cols)].number_input(
                        f"{col_name}{curr_label}", value=0.0, step=100.0
                    )

                st.subheader("Uscite (Aggiungi)")
                new_expenses = {}
                cols = st.columns(3)
                for i, col_name in enumerate(expense_cols):
                    curr_label = ""
                    if is_existing:
                        curr_val = existing_row[col_name]
                        curr_label = f" (Att: €{curr_val:,.0f})"

                    new_expenses[col_name] = cols[i % 3].number_input(
                        f"{col_name}{curr_label}", value=0.0, step=10.0
                    )

                btn_label = "Aggiorna Mese" if is_existing else "Crea Mese"
                submitted = st.form_submit_button(btn_label)

                if submitted:
                    if is_existing:
                        for col, val in new_incomes.items():
                            if val != 0:
                                df.loc[existing_mask, col] += val

                        for col, val in new_expenses.items():
                            if val != 0:
                                df.loc[existing_mask, col] += val

                        db.save_data(df)
                        st.success(f"Dati aggiornati per {month_input} {year_input}!")
                        st.rerun()

                    else:
                        new_row = {
                            "Year": year_input,
                            "Month": month_input,
                            "MonthNum": month_num,
                        }
                        new_row.update(new_incomes)
                        new_row.update(new_expenses)

                        base_df = df[
                            ["Year", "MonthNum", "Month"] + income_cols + expense_cols
                        ]
                        new_df = pd.DataFrame([new_row])
                        updated_df = pd.concat([new_df, base_df], ignore_index=True)

                        db.save_data(updated_df)
                        st.success("Mese creato con successo!")
                        st.rerun()

        # --- PAGINA AI ASSISTANT ---
        elif page == "💬 Assistant AI":
            st.header("💬 Financial Assistant")
            st.caption("Chiedi al tuo assistente personale informazioni sul tuo budget.")

            has_ai = (
                "ai_provider" in st.session_state
                and st.session_state["ai_provider"] is not None
            )
            has_oc = (
                "opencode_agent" in st.session_state
                and st.session_state["opencode_agent"] is not None
            )
            if not has_ai and not has_oc:
                st.warning(
                    "⚠️ Seleziona un provider e modello nella sidebar (🤖 AI Configuration) per parlare con l'assistente."
                )
            else:
                if "messages" not in st.session_state:
                    st.session_state.messages = []

                for message in st.session_state.messages:
                    with st.chat_message(message["role"]):
                        st.markdown(message["content"])

                uploaded_files = st.file_uploader(
                    "Allega file (Immagini/PDF)",
                    type=["png", "jpg", "jpeg", "pdf"],
                    accept_multiple_files=True,
                    key="chat_file_uploader_budget",
                )

                if prompt := st.chat_input("Chiedi qualcosa sui tuoi numeri..."):
                    display_msg = prompt
                    if uploaded_files:
                        display_msg += f"\n\n📎 *{len(uploaded_files)} file allegati*"

                    st.session_state.messages.append(
                        {"role": "user", "content": display_msg}
                    )
                    with st.chat_message("user"):
                        st.markdown(display_msg)

                    with st.chat_message("assistant"):
                        def get_data_context(df_in):
                            """Crea un contesto testuale dai dati recenti."""
                            limit = len(df_in)
                            df_ctx = df_in.head(limit).copy()
                            cols_to_drop = ["DateObj", "Notes", "DateStr"] + [
                                c for c in df_ctx.columns if c.startswith("Unnamed")
                            ]
                            df_ctx = df_ctx.drop(
                                columns=[c for c in cols_to_drop if c in df_ctx.columns],
                                errors="ignore",
                            )

                            csv_data = df_ctx.to_csv(index=False)
                            return f"""
                            SEI UN ESPERTO ANALISTA FINANZIARIO.
                            Analizza i seguenti dati di budget personale (ultimi {limit} mesi).
                            Rispondi in italiano. Sii conciso e diretto. Usa markdown per tabelle o grassetto.

                            ISTRUZIONE IMPORTANTE:
                            Prima di dare la risposta finale, scrivi un blocco riga per riga indicando cosa stai analizzando, iniziando con 'Thinking:'.
                            Esempio:
                            Thinking: Analizzo le entrate degli ultimi 3 mesi...
                            Thinking: Controllo le spese straordinarie...
                            Thinking: Calcolo la media del risparmio...

                            [RISPOSTA FINALE QUI]

                            DATI CSV:
                            {csv_data}
                            """

                        try:
                            system_context = get_data_context(df)
                            final_prompt_text = (
                                f"{system_context}\n\nDOMANDA UTENTE: {prompt}"
                            )

                            final_prompt = [final_prompt_text]
                            if uploaded_files:
                                for uploaded_file in uploaded_files:
                                    bytes_data = uploaded_file.getvalue()
                                    mime_type = uploaded_file.type
                                    final_prompt.append(
                                        {"mime_type": mime_type, "data": bytes_data}
                                    )

                            if has_oc and not uploaded_files:
                                stream_gen = st.session_state["opencode_agent"].stream_chat(
                                    final_prompt_text, "budget_assistant"
                                )
                            else:
                                if len(final_prompt) == 1:
                                    final_prompt = final_prompt[0]
                                stream_gen = (
                                    st.session_state["ai_provider"]
                                    .get_model()
                                    .generate_stream(final_prompt)
                                )
                            response_text = st.write_stream(stream_gen)

                            st.session_state.messages.append(
                                {"role": "assistant", "content": response_text}
                            )

                        except Exception as e:
                            err_msg = f"Errore durante l'analisi: {e}"
                            st.error(err_msg)
                            st.session_state.messages.append(
                                {"role": "assistant", "content": err_msg}
                            )

    else:
        # --- SETUP MODE ---
        st.info("👋 Benvenuto! Nessun database trovato. Iniziamo con il setup.")
        st.divider()

        col_cloud, col_local = st.columns(2)

        with col_cloud:
            st.subheader("☁️ Scarica da Cloud (GitHub)")
            st.write("Collega il tuo account GitHub per scaricare il database.")
            db.export_to_csv(DATA_FILE)
            render_cloud_sync_ui(DATA_FILE, is_sidebar=False)
            db.migrate_from_csv(DATA_FILE, force=True)

        with col_local:
            st.subheader("📂 Carica CSV Locale")
            st.write("Se hai un file `budget_database.csv` locale, caricalo qui.")
            uploaded_file = st.file_uploader("Scegli un file CSV", type="csv")

            if uploaded_file is not None:
                try:
                    df_uploaded = pd.read_csv(uploaded_file)
                    db.save_data(df_uploaded)
                    st.success("Database importato! Riavvio app...")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Errore importazione: {e}")


if __name__ == "__main__":
    main()
