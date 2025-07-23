import base64

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from modules.collect_data_utils import collect_bitpanda_data, sort_data_by_asset
from modules.portfolio_utils import aggregate_portfolio, filter_crypto_df
from modules.yahoo_utils import calculate_gain_loss, portfolio_history

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

crypto_df = None
if uploaded_file is not None:
    path = uploaded_file
    data_collected = collect_bitpanda_data(path)
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
    st.subheader("Crypto Portfolio Aggregato per Asset")
    st.dataframe(crypto_df)
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
    st.plotly_chart(fig, use_container_width=True)
    # Bar chart per prezzo medio
    fig2 = go.Figure(
        data=[go.Bar(x=crypto_df["asset_collect"], y=crypto_df["median_price"])]
    )
    fig2.update_layout(
        title_text="Prezzo Medio di Acquisto (DCA) per Asset",
        xaxis_title="Asset",
        yaxis_title="Prezzo Medio",
    )
    st.plotly_chart(fig2, use_container_width=True)
    # Tabella Gain/Loss
    gain_df = calculate_gain_loss(crypto_df)
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
        st.plotly_chart(fig3, use_container_width=True)
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
        "Carica un file CSV Bitpanda per iniziare l'analisi del portafoglio crypto."
    )

st.caption("Dashboard informativa. Fai sempre le tue ricerche prima di investire.")
