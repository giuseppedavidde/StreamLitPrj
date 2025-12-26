import requests
import pandas as pd
import streamlit as st

@st.cache_data(ttl=900)  # Cache for 15 minutes
def get_bitpanda_prices():
    """
    Fetches all available crypto prices from Bitpanda's public API.
    Returns a dictionary: {SYMBOL: PRICE_EUR}
    """
    url = "https://api.bitpanda.com/v1/ticker"
    try:
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            # Data format: {"BTC": {"EUR": "123.45", ...}, ...}
            prices = {}
            for symbol, rates in data.items():
                if "EUR" in rates:
                    try:
                        prices[symbol] = float(rates["EUR"])
                    except ValueError:
                        pass
            return prices
    except Exception as e:
        st.error(f"Error fetching Bitpanda prices: {e}")
    
    return {}

def calculate_gain_loss(df, prices_dict):
    """
    Calculates Gain/Loss using the provided dictionary of current prices.
    Optimized to avoid row-by-row API calls.
    """
    results = []
    
    for _, row in df.iterrows():
        symbol = row["asset_collect"]
        shares = row["amount_asset_collect"]
        invested = row["amount_fiat_collect"]
        median_price = row["median_price"]
        
        # Get current price from dictionary
        current_price = prices_dict.get(symbol)
        
        # Handle cases where symbol might differ slightly or be missing
        # Bitpanda usually returns standard symbols like BTC, ETH, etc. which match our asset_collect
        
        if current_price is not None:
            current_value = shares * current_price
            gain = current_value - invested
            gain_pct = (gain / invested) * 100 if invested != 0 else 0
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
