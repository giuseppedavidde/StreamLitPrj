import pandas as pd


def filter_crypto_df(df):
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
    return df


def aggregate_portfolio(df):
    # Depositi BTC
    btc_deposit_amount = df.loc[
        (df["asset_collect"] == "BTC") & (df["trans_type_collect"] == "deposit"),
        "amount_asset_collect",
    ].sum()
    btc_deposit_median_price = 34279.00569
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
    # BTC: aggiusta con depositi
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
    return grouped
