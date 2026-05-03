import pandas as pd
import pandas_ta as ta
import yfinance as yf


def get_holders_info(ticker: str) -> dict:
    """
    Fetches institutional and mutual fund (ETF) holders for a given ticker using yfinance.
    Returns a dictionary summarizing the top holders and their volumes.
    """
    holders_data = {
        "institutional_holders": [],
        "etf_mutualfund_holders": []
    }
    try:
        t = yf.Ticker(ticker)
        
        # Institutional Holders
        inst_df = t.institutional_holders
        if inst_df is not None and not inst_df.empty:
            # Sort by Shares descending to get top holders
            if "Shares" in inst_df.columns:
                inst_df = inst_df.sort_values(by="Shares", ascending=False).head(5)
            
            for _, row in inst_df.iterrows():
                holders_data["institutional_holders"].append({
                    "Holder": str(row.get("Holder", "Unknown")),
                    "Shares": int(row.get("Shares", 0)) if pd.notna(row.get("Shares")) else 0,
                    "pctHeld": float(row.get("pctHeld", 0.0)) if pd.notna(row.get("pctHeld")) else 0.0,
                    "Date Reported": str(row.get("Date Reported", ""))[:10]
                })
                
        # Mutual Fund / ETF Holders
        mf_df = t.mutualfund_holders
        if mf_df is not None and not mf_df.empty:
            if "Shares" in mf_df.columns:
                mf_df = mf_df.sort_values(by="Shares", ascending=False).head(5)
                
            for _, row in mf_df.iterrows():
                holders_data["etf_mutualfund_holders"].append({
                    "Holder": str(row.get("Holder", "Unknown")),
                    "Shares": int(row.get("Shares", 0)) if pd.notna(row.get("Shares")) else 0,
                    "pctHeld": float(row.get("pctHeld", 0.0)) if pd.notna(row.get("pctHeld")) else 0.0,
                    "Date Reported": str(row.get("Date Reported", ""))[:10]
                })
    except Exception as e:
        print(f"Failed to fetch holders info for {ticker}: {e}")
        
    return holders_data


def get_financial_info(ticker: str) -> dict:
    """
    Fetches fundamental financial data for a given ticker using yfinance.
    Returns a dictionary of key financial metrics.
    """
    financials = {}
    try:
        t = yf.Ticker(ticker)
        info = t.info
        
        keys = [
            'marketCap', 'trailingPE', 'forwardPE', 'dividendYield', 
            'profitMargins', 'operatingMargins', 'returnOnAssets', 
            'returnOnEquity', 'revenueGrowth', 'earningsGrowth', 
            'debtToEquity', 'freeCashflow'
        ]
        
        for k in keys:
            val = info.get(k)
            if val is not None:
                financials[k] = val
                
    except Exception as e:
        print(f"Failed to fetch financial info for {ticker}: {e}")
        
    return financials


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds technical indicators to the DataFrame grouped by category.
    Assumes index is Datetime and columns include Open, High, Low, Close, Volume.
    """
    if df is None or df.empty:
        return df

    # Ensure index is DatetimeIndex if possible
    if not isinstance(df.index, pd.DatetimeIndex):
        try:
            df.index = pd.to_datetime(df.index)
        except Exception as e:
            print(f"Warning: Index could not be converted to DatetimeIndex. {e}")

    # ==========================
    # MOMENTUM INDICATORS
    # ==========================
    try:
        df["RSI_14"] = ta.rsi(df["close"], length=14)
    except Exception as e:
        print(f"RSI calculation failed: {e}")

    try:
        stoch = ta.stoch(df["high"], df["low"], df["close"], k=14, d=3, smooth_k=3)
        if stoch is not None:
            df = pd.concat([df, stoch], axis=1)  # STOCHk_14_3_3, STOCHd_14_3_3
    except Exception as e:
        print(f"Stochastic calculation failed: {e}")

    try:
        df["WILLR_14"] = ta.willr(df["high"], df["low"], df["close"], length=14)
    except Exception as e:
        print(f"Williams %R calculation failed: {e}")

    # ==========================
    # TREND INDICATORS
    # ==========================
    try:
        df["SMA_20"] = ta.sma(df["close"], length=20)
        df["SMA_50"] = ta.sma(df["close"], length=50)
        df["SMA_200"] = ta.sma(df["close"], length=200)
    except Exception as e:
        print(f"SMA calculation failed: {e}")

    try:
        df["EMA_20"] = ta.ema(df["close"], length=20)
        df["EMA_50"] = ta.ema(df["close"], length=50)
        df["EMA_200"] = ta.ema(df["close"], length=200)
    except Exception as e:
        print(f"EMA calculation failed: {e}")

    try:
        macd = ta.macd(df["close"], fast=12, slow=26, signal=9)
        if macd is not None:
            df = pd.concat([df, macd], axis=1)  # MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
    except Exception as e:
        print(f"MACD calculation failed: {e}")

    try:
        adx = ta.adx(df["high"], df["low"], df["close"], length=14)
        if adx is not None:
            df = pd.concat([df, adx], axis=1)  # ADX_14, DMP_14, DMN_14
    except Exception as e:
        print(f"ADX calculation failed: {e}")

    try:
        df["CCI_14"] = ta.cci(df["high"], df["low"], df["close"], length=14)
    except Exception as e:
        print(f"CCI calculation failed: {e}")

    # ==========================
    # VOLATILITY INDICATORS
    # ==========================
    try:
        bbands = ta.bbands(df["close"], length=20, std=2)
        if bbands is not None:
            df = pd.concat([df, bbands], axis=1)  # BBL_20_2.0, BBM_20_2.0, BBU_20_2.0
    except Exception as e:
        print(f"Bollinger Bands calculation failed: {e}")

    try:
        atr = ta.atr(df["high"], df["low"], df["close"], length=14)
        if atr is not None:
            df["ATR_14"] = atr
    except Exception as e:
        print(f"ATR calculation failed: {e}")

    # ==========================
    # VOLUME INDICATORS
    # ==========================
    try:
        df["VWAP"] = ta.vwap(df["high"], df["low"], df["close"], df["volume"])
    except Exception as e:
        print(f"VWAP calculation failed: {e}")

    try:
        df["OBV"] = ta.obv(df["close"], df["volume"])
    except Exception as e:
        print(f"OBV calculation failed: {e}")

    return df


def detect_patterns(df: pd.DataFrame) -> dict:
    """
    Analyzes the latest data point for specific patterns and market state.
    Returns a dictionary of detected conditions.
    """
    if df is None or df.empty:
        return {}

    latest = df.iloc[-1]

    analysis = {
        "current_price": latest["close"] if "close" in latest else 0.0,
        "trend": "Neutral",
        "trend_strength": "Weak",
        "volume_spike": False,
        "patterns": [],
    }

    price = latest.get("close", 0.0)

    # --------------------------
    # Trend Detection (EMA)
    # --------------------------
    if "EMA_50" in df.columns and "EMA_200" in df.columns:
        ema50 = latest.get("EMA_50")
        ema200 = latest.get("EMA_200")
        if pd.notna(ema50) and pd.notna(ema200):
            if price > ema50 > ema200:
                analysis["trend"] = "Strong Uptrend"
            elif price < ema50 < ema200:
                analysis["trend"] = "Strong Downtrend"
            elif price > ema50:
                analysis["trend"] = "Uptrend"
            elif price < ema50:
                analysis["trend"] = "Downtrend"

    # Store raw EMA values
    for period in [20, 50, 200]:
        col = f"EMA_{period}"
        if col in df.columns and pd.notna(latest.get(col)):
            analysis[col.lower()] = float(latest[col])
        sma_col = f"SMA_{period}"
        if sma_col in df.columns and pd.notna(latest.get(sma_col)):
            analysis[sma_col.lower()] = float(latest[sma_col])

    # --------------------------
    # Trend Strength (ADX)
    # --------------------------
    if "ADX_14" in df.columns:
        adx_val = latest.get("ADX_14")
        if pd.notna(adx_val):
            analysis["adx"] = round(float(adx_val), 2)
            if adx_val > 25:
                analysis["trend_strength"] = "Strong"
            elif adx_val < 20:
                analysis["trend_strength"] = "Weak/Sideways"

    # --------------------------
    # Momentum (RSI, Stoch, CCI, Williams %R)
    # --------------------------
    rsi = latest.get("RSI_14")
    if pd.notna(rsi):
        analysis["rsi"] = round(float(rsi), 2)
        if rsi > 70:
            analysis["patterns"].append("RSI Overbought")
        elif rsi < 30:
            analysis["patterns"].append("RSI Oversold")

    stoch_k = latest.get("STOCHk_14_3_3")
    stoch_d = latest.get("STOCHd_14_3_3")
    if pd.notna(stoch_k) and pd.notna(stoch_d):
        analysis["stoch_k"] = round(float(stoch_k), 2)
        analysis["stoch_d"] = round(float(stoch_d), 2)
        if stoch_k > 80 and stoch_d > 80:
            analysis["patterns"].append("Stochastic Overbought")
        elif stoch_k < 20 and stoch_d < 20:
            analysis["patterns"].append("Stochastic Oversold")

    cci = latest.get("CCI_14")
    if pd.notna(cci):
        analysis["cci"] = round(float(cci), 2)
        if cci > 100:
            analysis["patterns"].append("CCI Bullish")
        elif cci < -100:
            analysis["patterns"].append("CCI Bearish")

    willr = latest.get("WILLR_14")
    if pd.notna(willr):
        analysis["williams_r"] = round(float(willr), 2)
        if willr > -20:
            analysis["patterns"].append("Williams %R Overbought")
        elif willr < -80:
            analysis["patterns"].append("Williams %R Oversold")

    # --------------------------
    # MACD Signal
    # --------------------------
    if "MACD_12_26_9" in df.columns and "MACDs_12_26_9" in df.columns:
        macd_val = latest.get("MACD_12_26_9")
        macd_sig = latest.get("MACDs_12_26_9")
        if pd.notna(macd_val) and pd.notna(macd_sig):
            analysis["macd"] = round(float(macd_val), 4)
            analysis["macd_signal"] = round(float(macd_sig), 4)
            analysis["macd_histogram"] = round(float(macd_val - macd_sig), 4)
            
            # Simple MACD cross detection (requires previous bar)
            if len(df) > 1:
                prev_macd = df.iloc[-2].get("MACD_12_26_9")
                prev_sig = df.iloc[-2].get("MACDs_12_26_9")
                if pd.notna(prev_macd) and pd.notna(prev_sig):
                    if prev_macd < prev_sig and macd_val > macd_sig:
                        analysis["patterns"].append("MACD Bullish Cross")
                    elif prev_macd > prev_sig and macd_val < macd_sig:
                        analysis["patterns"].append("MACD Bearish Cross")

    # --------------------------
    # Volatility (Bollinger Bands, ATR)
    # --------------------------
    if "BBU_20_2.0" in df.columns and "BBL_20_2.0" in df.columns:
        bbu = latest.get("BBU_20_2.0")
        bbl = latest.get("BBL_20_2.0")
        bbm = latest.get("BBM_20_2.0")
        if pd.notna(bbu) and pd.notna(bbl) and pd.notna(bbm) and bbm > 0:
            analysis["bb_upper"] = round(float(bbu), 2)
            analysis["bb_lower"] = round(float(bbl), 2)
            analysis["bb_width"] = round(float((bbu - bbl) / bbm), 4)
            
            if price > bbu:
                analysis["patterns"].append("Price Above Upper BB")
            elif price < bbl:
                analysis["patterns"].append("Price Below Lower BB")

    if "ATR_14" in df.columns and pd.notna(latest.get("ATR_14")):
        analysis["atr"] = round(float(latest["ATR_14"]), 4)

    # Historical Volatility (annualized, from log returns)
    try:
        import numpy as np
        log_ret = np.log(df["close"] / df["close"].shift(1)).dropna()
        if len(log_ret) >= 20:
            import math
            hv_20 = log_ret.rolling(20).std().iloc[-1]
            if len(df) > 1:
                diffs = df.index.to_series().diff().dropna()
                if not diffs.empty:
                    median_hours = diffs.median().total_seconds() / 3600
                    if median_hours > 0:
                        if median_hours <= 1.5:
                            periods = 252 * (6.5 / median_hours)
                        else:
                            periods = 252 / max(1, (median_hours / 24))
                    else:
                        periods = 252
                else:
                    periods = 252
            else:
                periods = 252
            annualized_hv = float(hv_20 * math.sqrt(periods))
            if not math.isnan(annualized_hv):
                analysis["hist_volatility"] = round(annualized_hv, 4)
    except Exception:
        pass

    # --------------------------
    # Volume (VWAP, OBV, Spikes)
    # --------------------------
    if "VWAP" in df.columns and pd.notna(latest.get("VWAP")):
        analysis["vwap"] = float(latest["VWAP"])

    if "OBV" in df.columns and pd.notna(latest.get("OBV")):
        analysis["obv"] = float(latest["OBV"])

    if "volume" in df.columns:
        latest_vol = latest["volume"]
        avg_vol = df["volume"].rolling(20).mean().iloc[-1]
        if pd.notna(avg_vol) and avg_vol > 0:
            analysis["avg_volume_20"] = float(avg_vol)
            analysis["latest_volume"] = float(latest_vol)
            analysis["volume_ratio"] = round(float(latest_vol / avg_vol), 2)
            if latest_vol > avg_vol * 1.5:
                analysis["volume_spike"] = True
                analysis["patterns"].append("High Volume")

    # --------------------------
    # Simple Candlestick Patterns
    # --------------------------
    if len(df) > 1:
        prev = df.iloc[-2]
        prev_open, prev_close = prev["open"], prev["close"]
        curr_open, curr_close = latest["open"], latest["close"]

        is_prev_red = prev_close < prev_open
        is_curr_green = curr_close > curr_open
        is_prev_green = prev_close > prev_open
        is_curr_red = curr_close < curr_open

        # Bullish Engulfing
        bull_engulfs = (curr_open < prev_close) and (curr_close > prev_open)
        if is_prev_red and is_curr_green and bull_engulfs:
            analysis["patterns"].append("Bullish Engulfing")

        # Bearish Engulfing
        bear_engulfs = (curr_open > prev_close) and (curr_close < prev_open)
        if is_prev_green and is_curr_red and bear_engulfs:
            analysis["patterns"].append("Bearish Engulfing")

    return analysis
