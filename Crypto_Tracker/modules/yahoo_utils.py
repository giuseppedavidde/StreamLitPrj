import pandas as pd
import yfinance as yf


def get_current_price(symbol):
    try:
        ticker = yf.Ticker(symbol)
        data = ticker.history(period="1d")
        if not data.empty:
            return float(data["Close"].iloc[-1])
    except Exception:
        return None
    return None


def calculate_gain_loss(df):
    results = []
    for _, row in df.iterrows():
        symbol = row["asset_collect"]
        shares = row["amount_asset_collect"]
        invested = row["amount_fiat_collect"]
        median_price = row["median_price"]
        # Yahoo Finance symbol conversion (EUR pair)
        if "-" not in symbol:
            yf_symbol = f"{symbol}-EUR"
        else:
            yf_symbol = symbol
        current_price = get_current_price(yf_symbol)
        if current_price is not None:
            current_value = shares * current_price
            gain = current_value - invested
            gain_pct = (gain / invested) * 100 if invested else 0
        else:
            current_value = None
            gain = None
            gain_pct = None
        results.append(
            {
                "asset": symbol,
                "shares": shares,
                "invested": invested,
                "median_price": median_price,
                "current_price": current_price,
                "current_value": current_value,
                "gain": gain,
                "gain_pct": gain_pct,
            }
        )
    return pd.DataFrame(results)


def portfolio_history(df):
    history_dict = {}
    for _, row in df.iterrows():
        symbol = row["asset_collect"]
        shares = row["amount_asset_collect"]
        # Yahoo Finance symbol conversion (EUR pair)
        # Generic fallback: append -EUR if not present
        if "-" not in symbol:
            yf_symbol = f"{symbol}-EUR"
        else:
            yf_symbol = symbol
        try:
            ticker = yf.Ticker(yf_symbol)
            hist = ticker.history(period="max")
            if not hist.empty:
                # Moltiplica il prezzo di chiusura per le quantità
                history_dict[symbol] = hist["Close"] * shares
        except Exception:
            continue
    # Unisci tutte le serie temporali per sommare il valore totale del portafoglio
    if not history_dict:
        return pd.DataFrame()
    portfolio_df = pd.DataFrame(history_dict)
    portfolio_df["total_value"] = portfolio_df.sum(axis=1)
    return portfolio_df
