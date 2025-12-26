"""Crypto Portfolio DCA Dashboard

Questo dashboard permette di analizzare e visualizzare il tuo portafoglio Crypto Bitpanda con strategie DCA.
"""
import base64
import os
import io

from dotenv import load_dotenv

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Load environment variables
load_dotenv()
from agents.cloud_ui import render_cloud_ui
from modules.collect_data_utils import collect_bitpanda_data, sort_data_by_asset, load_portfolio_snapshot
from modules.portfolio_utils import aggregate_portfolio, filter_crypto_df
from modules.yahoo_utils import portfolio_history
from modules.price_utils import get_bitpanda_prices, calculate_gain_loss

st.set_page_config(page_title="Crypto Portfolio DCA Dashboard", layout="wide")
st.title("Crypto Portfolio DCA Dashboard")
st.caption(
    "Analizza e visualizza il tuo portafoglio Crypto Bitpanda con strategie DCA."
)

# --- File Upload Section ---
st.sidebar.header("Bitpanda CSV Upload")
uploaded_file = st.sidebar.file_uploader(
    "Carica il CSV Bitpanda delle transazioni",
    type=["csv"],
    help="Carica il file esportato da Bitpanda con le tue transazioni crypto.",
)

# --- Cloud Sync Section ---
# --- Cloud Sync Section ---
LOCAL_DATA_FILE = "Crypto_Portfolio_csv.csv" # Still referenced but maybe unused if in-memory
render_cloud_ui(is_sidebar=True)

crypto_df = None

if uploaded_file is not None:
    # Bitpanda Logic
    data_collected = collect_bitpanda_data(uploaded_file)
    data_collected = sort_data_by_asset(data_collected)
    df = pd.DataFrame(data_collected)
    # Conversione colonne numeriche
    df["amount_asset_collect"] = pd.to_numeric(
        df["amount_asset_collect"], errors="coerce"
    )
    df["amount_fiat_collect"] = pd.to_numeric(
        df["amount_fiat_collect"], errors="coerce"
    )
    df["asset_market_price_collect"] = pd.to_numeric(
        df["asset_market_price_collect"], errors="coerce"
    )
    # Filtri e aggregazione
    df = filter_crypto_df(df)
    grouped = aggregate_portfolio(df)
    crypto_df = grouped

elif 'cloud_data' in st.session_state and st.session_state['cloud_data']:
    st.sidebar.success("Uso dati da Cloud (In-Memory)")
    # Snapshot Logic - from buffer
    raw_data = st.session_state['cloud_data']
    if isinstance(raw_data, bytes):
        raw_data = io.BytesIO(raw_data)
    else:
        raw_data = io.StringIO(raw_data)
        
    crypto_df = load_portfolio_snapshot(raw_data)

elif os.path.exists(LOCAL_DATA_FILE):
    # Fallback: if local file still exists (maybe from manual save), use it but warn? 
    # Or just ignore it as per user request "NON deve essere scaricato".
    # User said "NON deve essere scaricato", but maybe it exists from previous runs.
    # We should prioritize cloud_data. If cloud_data is missing, we could try to load local if exists,
    # or just show nothing.
    # Let's support it for now but clearly mark it.
    st.sidebar.warning(f"File locale rilevato: {LOCAL_DATA_FILE}")
    crypto_df = load_portfolio_snapshot(LOCAL_DATA_FILE)

if crypto_df is not None and not crypto_df.empty:
    st.subheader("Crypto Portfolio Aggregato per Asset")
    # Configure column formats for high precision
    # Use %.8f to show up to 8 decimals as requested
    st.dataframe(
        crypto_df,
        column_config={
            "amount_asset_collect": st.column_config.NumberColumn(
                "Shares (Quantità)",
                format="%.8f"
            ),
            "median_price": st.column_config.NumberColumn(
                "DCA Price (Prezzo Medio)",
                format="%.8f"
            ),
            "amount_fiat_collect": st.column_config.NumberColumn(
                "Invested (EUR)",
                format="%.2f"
            ),
            "date_last_update_buy": st.column_config.TextColumn("Last Update (Buy/Sell)"),
            "date_last_update_staking": st.column_config.TextColumn("Last Update (Staking)")
        },
        width="stretch"
    )
    st.markdown("---")
    st.markdown("### Visualizzazione Grafica")
    # Pie chart per asset
    fig = go.Figure(
        data=[
            go.Pie(
                labels=crypto_df["asset_collect"],
                values=crypto_df["amount_fiat_collect"],
                hole=0.3,
            )
        ]
    )
    fig.update_layout(title_text="Distribuzione Investimento per Asset")
    st.plotly_chart(fig, width="stretch")
    # Bar chart per prezzo medio
    fig2 = go.Figure(
        data=[go.Bar(x=crypto_df["asset_collect"], y=crypto_df["median_price"])]
    )
    fig2.update_layout(
        title_text="Prezzo Medio di Acquisto (DCA) per Asset",
        xaxis_title="Asset",
        yaxis_title="Prezzo Medio",
    )
    st.plotly_chart(fig2, width="stretch")
    # Tabella Gain/Loss
    prices_dict = get_bitpanda_prices()
    gain_df = calculate_gain_loss(crypto_df, prices_dict)
    st.subheader("Gain/Loss Portfolio")
    st.dataframe(gain_df)
    # Grafico storico portafoglio
    st.markdown("### Andamento Storico del Portafoglio")
    history_df = portfolio_history(crypto_df)
    if not history_df.empty:
        fig3 = go.Figure()
        fig3.add_trace(
            go.Scatter(
                x=history_df.index,
                y=history_df["total_value"],
                mode="lines",
                name="Valore Totale",
            )
        )
        fig3.update_layout(
            title="Valore del Portafoglio nel Tempo (EUR)",
            xaxis_title="Data",
            yaxis_title="Valore Totale (EUR)",
        )
        st.plotly_chart(fig3, width="stretch")
    else:
        st.info("Storico non disponibile per uno o più asset.")
    # Download CSV aggregato
    csv = crypto_df.to_csv(index=False)
    b64 = base64.b64encode(csv.encode()).decode()
    st.download_button(
        label="Scarica CSV aggregato",
        data=csv,
        file_name="crypto_portfolio_aggregato.csv",
        mime="text/csv",
    )
else:
    st.info(
        "Carica un file CSV per iniziare l'analisi del portafoglio crypto."
    )

st.caption("Dashboard informativa. Fai sempre le tue ricerche prima di investire.")
