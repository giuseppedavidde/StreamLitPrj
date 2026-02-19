import pandas as pd
import pandas_ta as ta


def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Adds technical indicators to the DataFrame.
    Assumes index is Datetime and columns include Open, High, Low, Close, Volume.
    """
    if df is None or df.empty:
        return df

    # Ensure column names are lowercase for pandas_ta or handle case sensitivity
    # pandas_ta usually expects 'open', 'high', 'low', 'close', 'volume'
    # ib_insync returns 'open', 'high', 'low', 'close', 'volume' (lowercase) usually.

    # RSI
    df["RSI_14"] = ta.rsi(df["close"], length=14)

    # VWAP
    # VWAP requires 'high', 'low', 'close', 'volume' and a datetime index
    try:
        # Check if df index is datetime, if not try to parse or fail gracefully for VWAP
        if not isinstance(df.index, pd.DatetimeIndex):
            print("Warning: Index is not DatetimeIndex, VWAP might fail or return NaN.")

        df["VWAP"] = ta.vwap(df["high"], df["low"], df["close"], df["volume"])
    except Exception as e:
        print(f"VWAP calculation failed: {e}")

    # MACD
    try:
        macd = ta.macd(df["close"])
        if macd is not None:
            df = pd.concat(
                [df, macd], axis=1
            )  # MACD_12_26_9, MACDh_12_26_9, MACDs_12_26_9
    except Exception as e:
        print(f"MACD calculation failed: {e}")

    # Bollinger Bands
    try:
        bbands = ta.bbands(df["close"], length=20, std=2)
        if bbands is not None:
            df = pd.concat([df, bbands], axis=1)  # BBL_20_2.0, BBM_20_2.0, BBU_20_2.0
    except Exception as e:
        print(f"Bollinger Bands calculation failed: {e}")

    # EMA
    try:
        df["EMA_20"] = ta.ema(df["close"], length=20)
        df["EMA_50"] = ta.ema(df["close"], length=50)
        df["EMA_200"] = ta.ema(df["close"], length=200)
    except Exception as e:
        print(f"EMA calculation failed: {e}")

    return df


def detect_patterns(df: pd.DataFrame) -> dict:
    """
    Analyzes the latest data point for specific patterns.
    Returns a dictionary of detected patterns and market state.
    """
    if df is None or df.empty:
        return {}

    latest = df.iloc[-1]
    # Handle missing columns gracefully

    analysis = {
        "current_price": latest["close"] if "close" in latest else 0.0,
        "rsi": latest.get("RSI_14", None),
        "trend": "Neutral",
        "volume_spike": False,
        "patterns": [],
    }

    # Trend Detection
    if "EMA_50" in df.columns and "EMA_200" in df.columns:
        ema50 = latest.get("EMA_50")
        ema200 = latest.get("EMA_200")
        price = latest["close"]
        if pd.notna(ema50) and pd.notna(ema200):
            if price > ema50 > ema200:
                analysis["trend"] = "Strong Uptrend"
            elif price < ema50 < ema200:
                analysis["trend"] = "Strong Downtrend"
            elif price > ema50:
                analysis["trend"] = "Uptrend"
            elif price < ema50:
                analysis["trend"] = "Downtrend"
        elif pd.notna(ema50):
            if price > ema50:
                analysis["trend"] = "Uptrend"
            elif price < ema50:
                analysis["trend"] = "Downtrend"

    # Store raw EMA values for AI strategy analysis
    if "EMA_20" in df.columns and pd.notna(latest.get("EMA_20")):
        analysis["ema_20"] = float(latest["EMA_20"])
    if "EMA_50" in df.columns and pd.notna(latest.get("EMA_50")):
        analysis["ema_50"] = float(latest["EMA_50"])
    if "EMA_200" in df.columns and pd.notna(latest.get("EMA_200")):
        analysis["ema_200"] = float(latest["EMA_200"])

    # VWAP
    if "VWAP" in df.columns and pd.notna(latest.get("VWAP")):
        analysis["vwap"] = float(latest["VWAP"])

    # Volume stats
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

    # Historical Volatility (annualized, from log returns)
    try:
        import numpy as np

        log_ret = np.log(df["close"] / df["close"].shift(1)).dropna()
        if len(log_ret) >= 20:
            import math

            hv_20 = log_ret.rolling(20).std().iloc[-1]
            # Estimate annualization factor from index
            if len(df) > 1:
                avg_hours = (
                    (df.index[-1] - df.index[0]).total_seconds() / 3600 / len(df)
                )
                if avg_hours < 2:
                    periods = 252 * 6.5
                elif avg_hours < 24:
                    periods = 252 * (6.5 / avg_hours)
                else:
                    periods = 252
            else:
                periods = 252
            annualized_hv = float(hv_20 * math.sqrt(periods))
            if not math.isnan(annualized_hv):
                analysis["hist_volatility"] = round(annualized_hv, 4)
    except Exception:
        pass

    # MACD Signal
    if "MACD_12_26_9" in df.columns and "MACDs_12_26_9" in df.columns:
        macd_val = latest.get("MACD_12_26_9")
        macd_sig = latest.get("MACDs_12_26_9")
        if pd.notna(macd_val) and pd.notna(macd_sig):
            analysis["macd"] = round(float(macd_val), 4)
            analysis["macd_signal"] = round(float(macd_sig), 4)
            analysis["macd_histogram"] = round(float(macd_val - macd_sig), 4)

    # Bollinger Band Width (volatility proxy)
    if "BBU_20_2.0" in df.columns and "BBL_20_2.0" in df.columns:
        bbu = latest.get("BBU_20_2.0")
        bbl = latest.get("BBL_20_2.0")
        bbm = latest.get("BBM_20_2.0")
        if pd.notna(bbu) and pd.notna(bbl) and pd.notna(bbm) and bbm > 0:
            analysis["bb_upper"] = round(float(bbu), 2)
            analysis["bb_lower"] = round(float(bbl), 2)
            analysis["bb_width"] = round(float((bbu - bbl) / bbm), 4)

    # RSI Conditions
    rsi = latest.get("RSI_14", 50)
    if pd.notna(rsi):
        if rsi > 70:
            analysis["patterns"].append("RSI Overbought")
        elif rsi < 30:
            analysis["patterns"].append("RSI Oversold")

    # Simple Candlestick Patterns (Example: Bullish Engulfing)
    if len(df) > 1:
        prev = df.iloc[-2]

        # Bullish Engulfing: Previous red, Current green and engulfs
        prev_open, prev_close = prev["open"], prev["close"]
        curr_open, curr_close = latest["open"], latest["close"]

        is_prev_red = prev_close < prev_open
        is_curr_green = curr_close > curr_open
        engulfs = (curr_open < prev_close) and (
            curr_close > prev_open
        )  # Basic definition

        if is_prev_red and is_curr_green and engulfs:
            analysis["patterns"].append("Bullish Engulfing")

    return analysis
