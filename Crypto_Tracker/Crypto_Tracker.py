import base64

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from modules.collect_data_utils import collect_bitpanda_data, sort_data_by_asset

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
    # Leggi il file in memoria
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
    # Filtra stake e transfer
    df = df[~df["trans_type_collect"].isin(["stake", "transfer"])]
    # Escludi ETH, EUR, BNB
    df = df[~df["asset_collect"].isin(["ETH", "EUR", "BNB"])]
    # Per SOL, considera solo le operazioni di acquisto (buy)
    df = df[~((df["asset_collect"] == "SOL") & (df["trans_type_collect"] != "buy"))]
    # Per XRP, considera solo le transazioni dalla transazione specificata in poi
    xrp_start_id = "T80949796-c9a0-46d1-9e07-09d63d79b6e4"
    if "XRP" in df["asset_collect"].values:
        xrp_mask = (df["asset_collect"] != "XRP") | (
            df["trans_id_collect"] >= xrp_start_id
        )
        df = df[xrp_mask]
    # Segno negativo per le vendite
    df.loc[df["trans_type_collect"] == "sell", "amount_asset_collect"] *= -1
    # Depositi BTC
    btc_deposit_amount = df.loc[
        (df["asset_collect"] == "BTC") & (df["trans_type_collect"] == "deposit"),
        "amount_asset_collect",
    ].sum()
    btc_deposit_median_price = 34279.00569  # Puoi renderlo dinamico se serve
    # Rimuovi depositi BTC
    df = df[~((df["asset_collect"] == "BTC") & (df["trans_type_collect"] == "deposit"))]
    # Aggrega per asset
    grouped = (
        df.groupby("asset_collect")
        .agg({"amount_asset_collect": "sum", "amount_fiat_collect": "sum"})
        .reset_index()
    )
    grouped["median_price"] = (
        grouped["amount_fiat_collect"] / grouped["amount_asset_collect"]
    )
    # DOGE: aggiungi il deposito iniziale come acquisto
    doge_initial_price = 0.08632094
    if "DOGE" in grouped["asset_collect"].values:
        doge_row = grouped[grouped["asset_collect"] == "DOGE"]
        doge_total_amount = doge_row["amount_asset_collect"].values[0]
        doge_total_fiat = doge_total_amount * doge_initial_price
        grouped.loc[grouped["asset_collect"] == "DOGE", "amount_fiat_collect"] = (
            doge_total_fiat
        )
        grouped.loc[grouped["asset_collect"] == "DOGE", "median_price"] = (
            doge_initial_price
        )
    # Aggiusta BTC con depositi
    if "BTC" in grouped["asset_collect"].values:
        btc_row = grouped[grouped["asset_collect"] == "BTC"]
        btc_total_amount = (
            btc_row["amount_asset_collect"].values[0] + btc_deposit_amount
        )
        btc_total_fiat = btc_row["amount_fiat_collect"].values[0] + (
            btc_deposit_amount * btc_deposit_median_price
        )
        btc_final_median_price = btc_total_fiat / btc_total_amount
        grouped.loc[grouped["asset_collect"] == "BTC", "amount_asset_collect"] = (
            btc_total_amount
        )
        grouped.loc[grouped["asset_collect"] == "BTC", "amount_fiat_collect"] = (
            btc_total_fiat
        )
        grouped.loc[grouped["asset_collect"] == "BTC", "median_price"] = (
            btc_final_median_price
        )
    else:
        grouped = pd.concat(
            [
                grouped,
                pd.DataFrame(
                    {
                        "asset_collect": ["BTC"],
                        "amount_asset_collect": [btc_deposit_amount],
                        "amount_fiat_collect": [
                            btc_deposit_amount * btc_deposit_median_price
                        ],
                        "median_price": [btc_deposit_median_price],
                    }
                ),
            ],
            ignore_index=True,
        )
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
