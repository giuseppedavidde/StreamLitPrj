"""
Option utilities — Black-Scholes Greeks + Historical Volatility.
Uses scipy.stats.norm for cumulative/probability density functions.
"""

import math
import numpy as np
import pandas as pd
from datetime import datetime
from scipy.stats import norm


def black_scholes_greeks(
    S: float,
    K: float,
    T_days: int,
    r: float = 0.05,
    sigma: float = 0.30,
    option_type: str = "C",
) -> dict:
    """
    Calculate Black-Scholes Greeks for a European option.

    Args:
        S: Current underlying price
        K: Strike price
        T_days: Days to expiration
        r: Risk-free rate (annualized, decimal). Default 5%.
        sigma: Volatility (annualized, decimal). Default 30%.
        option_type: 'C' for Call, 'P' for Put

    Returns:
        dict with: price, delta, gamma, theta (daily), vega (per 1% vol change)
    """
    if T_days <= 0 or S <= 0 or K <= 0 or sigma <= 0:
        return {
            "price": 0.0,
            "delta": 0.0,
            "gamma": 0.0,
            "theta": 0.0,
            "vega": 0.0,
        }

    T = T_days / 365.0
    sqrt_T = math.sqrt(T)

    d1 = (math.log(S / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    # Common terms
    Nd1 = norm.cdf(d1)
    Nd2 = norm.cdf(d2)
    nd1 = norm.pdf(d1)  # Standard normal density
    discount = math.exp(-r * T)

    if option_type.upper() == "C":
        price = S * Nd1 - K * discount * Nd2
        delta = Nd1
        theta = -(S * nd1 * sigma) / (2 * sqrt_T) - r * K * discount * Nd2
    else:  # Put
        Nmd1 = norm.cdf(-d1)
        Nmd2 = norm.cdf(-d2)
        price = K * discount * Nmd2 - S * Nmd1
        delta = Nd1 - 1  # Negative for puts
        theta = -(S * nd1 * sigma) / (2 * sqrt_T) + r * K * discount * Nmd2

    gamma = nd1 / (S * sigma * sqrt_T)
    vega = S * nd1 * sqrt_T / 100  # Per 1% change in vol

    return {
        "price": round(price, 4),
        "delta": round(delta, 4),
        "gamma": round(gamma, 4),
        "theta": round(theta / 365, 4),  # Daily theta
        "vega": round(vega, 4),
    }


def historical_volatility(df: pd.DataFrame, window: int = 20) -> float:
    """
    Calculate annualized historical volatility from a DataFrame with 'close' column.
    Uses log returns over the specified window.

    Returns volatility as a decimal (e.g., 0.30 = 30%).
    """
    if df is None or df.empty or len(df) < window + 1:
        return 0.30  # Default 30% if not enough data

    try:
        log_returns = np.log(df["close"] / df["close"].shift(1)).dropna()
        if len(log_returns) < window:
            return 0.30

        hv = log_returns.rolling(window=window).std().iloc[-1]
        # Annualize: multiply by sqrt(trading periods per year)
        # For hourly data (6.5h/day * 252 days ≈ 1638), for daily (252)
        # Initialize default to prevent assignment error
        periods_per_year = 252

        # Detect from index frequency
        if hasattr(df.index, "freq") and df.index.freq:
            freq = df.index.freq

        # Estimate from median time delta for accurate intra-day annualization
        if len(df) > 1:
            diffs = df.index.to_series().diff().dropna()
            if not diffs.empty:
                median_delta = diffs.median()
                hours = median_delta.total_seconds() / 3600
                if hours > 0:
                    if hours <= 1.5:  # Intraday (e.g., 1 hour, 5 mins)
                        bars_per_day = 6.5 / hours
                        periods_per_year = 252 * bars_per_day
                    elif hours <= 24.0:  # Daily
                        periods_per_year = 252
                    else:  # Weekly or Monthly
                        periods_per_year = 252 / (hours / 24)

        annualized = hv * math.sqrt(periods_per_year)
        return round(float(annualized), 4) if not math.isnan(annualized) else 0.30

    except Exception as e:
        print(f"Historical volatility calculation failed: {e}")
        return 0.30


def days_to_expiry(expiry_str: str) -> int:
    """Calculate days from now to expiry date string (YYYYMMDD format)."""
    try:
        expiry = datetime.strptime(expiry_str, "%Y%m%d")
        delta = (expiry - datetime.now()).days
        return max(delta, 1)
    except ValueError:
        return 30  # Default 30 days


def compute_greeks_table(
    underlying_price: float,
    strikes: list,
    expiry_str: str,
    hist_vol: float,
    rate: float = 0.05,
) -> list:
    """
    Compute Greeks for all given strikes at a single expiry.
    Returns a list of dicts (one per strike, both Call and Put).
    """
    dte = days_to_expiry(expiry_str)
    results = []

    for strike in strikes:
        call_greeks = black_scholes_greeks(
            underlying_price, strike, dte, rate, hist_vol, "C"
        )
        put_greeks = black_scholes_greeks(
            underlying_price, strike, dte, rate, hist_vol, "P"
        )
        results.append(
            {
                "strike": strike,
                "expiry": expiry_str,
                "dte": dte,
                "call": call_greeks,
                "put": put_greeks,
            }
        )

    return results


# ─── YFinance Option Helpers ───────────────────────────────────────────────
# These functions are used as fallback when IBKR is not connected.
# They mirror the data format of ibkr_connector methods.

RISK_FREE_RATE = 0.045


def safe_float_yf(val) -> float:
    try:
        v = float(val)
        if math.isnan(v) or math.isinf(v):
            return 0.0
        return v
    except (TypeError, ValueError):
        return 0.0


def get_option_chain_yfinance(ticker: str) -> tuple[list[str], list[float]]:
    """Fetch option expirations and strikes from Yahoo Finance.

    Returns:
        (sorted_expirations_yyyymmdd, sorted_strikes)
    """
    import yfinance as yf
    yf_ticker = yf.Ticker(ticker)
    expirations = yf_ticker.options
    if not expirations:
        return [], []
    # Normalize to YYYYMMDD format (same as IBKR)
    exps = sorted(e.replace("-", "") for e in expirations)
    # Collect all strikes across all expirations
    all_strikes: set[float] = set()
    for exp in expirations[:5]:  # sample first 5 to avoid rate limits
        try:
            chain = yf_ticker.option_chain(exp)
            for s in chain.calls["strike"]:
                all_strikes.add(float(s))
            for s in chain.puts["strike"]:
                all_strikes.add(float(s))
        except Exception:
            pass
    if not all_strikes:
        return exps, []
    strikes = sorted(all_strikes)
    return exps, strikes


def get_option_greeks_from_yfinance(
    ticker: str,
    expiry_str: str,
    strikes: list[float],
    underlying_price: float,
    rate: float = 0.05,
) -> list[dict]:
    """Compute Greeks table from Yahoo Finance option chain IV.

    Returns the same format as ibkr_connector.get_real_greeks_table():
    [{"strike": s, "expiry": expiry_str, "dte": dte,
      "call": {price, delta, gamma, theta, vega},
      "put":  {price, delta, gamma, theta, vega}}, ...]
    """
    import yfinance as yf
    dte = days_to_expiry(expiry_str.replace("-", ""))
    if dte <= 0:
        return []

    yf_ticker = yf.Ticker(ticker)
    exp_formatted = expiry_str[:4] + "-" + expiry_str[4:6] + "-" + expiry_str[6:8]
    try:
        chain = yf_ticker.option_chain(exp_formatted)
    except Exception:
        return []

    calls = chain.calls
    puts = chain.puts
    results = []

    for strike in strikes:
        # Find closest match in yfinance chain
        c_match = calls.iloc[(calls["strike"] - strike).abs().idxmin()] if not calls.empty else None
        p_match = puts.iloc[(puts["strike"] - strike).abs().idxmin()] if not puts.empty else None

        c_iv = safe_float_yf(c_match["impliedVolatility"]) if c_match is not None else 0.3
        p_iv = safe_float_yf(p_match["impliedVolatility"]) if p_match is not None else 0.3
        if c_iv <= 0:
            c_iv = 0.3
        if p_iv <= 0:
            p_iv = 0.3

        c_greeks = black_scholes_greeks(underlying_price, strike, dte, rate, c_iv, "C")
        p_greeks = black_scholes_greeks(underlying_price, strike, dte, rate, p_iv, "P")

        results.append({
            "strike": strike,
            "expiry": expiry_str,
            "dte": dte,
            "call": c_greeks,
            "put": p_greeks,
        })

    return results


def get_iv_rank_yfinance(ticker: str, expiry_str: str) -> tuple[float, float]:
    """Fetch average IV and IV rank from Yahoo Finance option chain.

    Returns:
        (avg_iv as decimal, iv_rank as 0-100)
    """
    import yfinance as yf
    yf_ticker = yf.Ticker(ticker)
    exp_formatted = expiry_str[:4] + "-" + expiry_str[4:6] + "-" + expiry_str[6:8]
    try:
        chain = yf_ticker.option_chain(exp_formatted)
    except Exception:
        return 0.3, 50.0

    ivs = []
    for _, row in chain.calls.iterrows():
        iv = safe_float_yf(row.get("impliedVolatility"))
        if iv > 0:
            ivs.append(iv)
    for _, row in chain.puts.iterrows():
        iv = safe_float_yf(row.get("impliedVolatility"))
        if iv > 0:
            ivs.append(iv)

    if len(ivs) < 5:
        return 0.3, 50.0

    avg_iv = float(np.mean(ivs))
    iv_low = float(np.min(ivs))
    iv_high = float(np.max(ivs))
    if iv_high - iv_low < 0.001:
        return avg_iv, 50.0
    iv_rank = (avg_iv - iv_low) / (iv_high - iv_low) * 100
    return avg_iv, iv_rank


def compute_volume_profile_yfinance(ticker: str, n_bins: int = 60) -> dict | None:
    """Compute Volume Profile (1 year) from Yahoo Finance historical data.

    Returns dict with: vpoc, vah, val, hvn_zones, lvn_zones
    or None if insufficient data.
    """
    import yfinance as yf
    yf_ticker = yf.Ticker(ticker)
    hist = yf_ticker.history(period="1y")
    if hist.empty or len(hist) < 20:
        return None

    prices = hist["Close"].values
    volumes = hist["Volume"].values
    lo, hi = float(np.min(prices)), float(np.max(prices))
    if hi - lo < 0.01:
        return None

    bins = np.linspace(lo, hi, n_bins + 1)
    bin_centers = (bins[:-1] + bins[1:]) / 2
    bin_idx = np.digitize(prices, bins) - 1
    bin_idx = np.clip(bin_idx, 0, n_bins - 1)

    vol_per_bin = np.zeros(n_bins)
    for i, idx in enumerate(bin_idx):
        vol_per_bin[idx] += volumes[i]

    total_vol = vol_per_bin.sum()
    if total_vol == 0:
        return None

    vpoc_idx = int(np.argmax(vol_per_bin))
    vpoc = float(bin_centers[vpoc_idx])

    sorted_idx = np.argsort(vol_per_bin)[::-1]
    cum_vol = 0.0
    va_bins = []
    for idx in sorted_idx:
        va_bins.append(idx)
        cum_vol += vol_per_bin[idx]
        if cum_vol >= total_vol * 0.70:
            break

    vah = float(bin_centers[max(va_bins)])
    val = float(bin_centers[min(va_bins)])

    avg_vol_per_bin = total_vol / n_bins

    hvn_indices = [i for i in range(n_bins) if vol_per_bin[i] > avg_vol_per_bin * 2]
    hvn_zones = []
    if hvn_indices:
        hvn_indices.sort()
        start = hvn_indices[0]
        for i in range(1, len(hvn_indices)):
            if hvn_indices[i] - hvn_indices[i - 1] > 2:
                hvn_zones.append((float(bin_centers[start]), float(bin_centers[hvn_indices[i - 1]])))
                start = hvn_indices[i]
        hvn_zones.append((float(bin_centers[start]), float(bin_centers[hvn_indices[-1]])))

    lvn_indices = [i for i in range(n_bins) if vol_per_bin[i] < avg_vol_per_bin * 0.3]
    lvn_zones = []
    if lvn_indices:
        lvn_indices.sort()
        start = lvn_indices[0]
        for i in range(1, len(lvn_indices)):
            if lvn_indices[i] - lvn_indices[i - 1] > 2:
                lvn_zones.append((float(bin_centers[start]), float(bin_centers[lvn_indices[i - 1]])))
                start = lvn_indices[i]
        lvn_zones.append((float(bin_centers[start]), float(bin_centers[lvn_indices[-1]])))

    return {
        "vpoc": round(vpoc, 2),
        "vah": round(vah, 2),
        "val": round(val, 2),
        "hvn_zones": [(round(a, 2), round(b, 2)) for a, b in hvn_zones],
        "lvn_zones": [(round(a, 2), round(b, 2)) for a, b in lvn_zones],
    }


def compute_sentiment_yfinance(ticker: str, expiry_str: str, iv_rank: float | None) -> dict:
    """Compute Put/Call sentiment from Yahoo Finance option chain.

    Returns dict with: pc_oi_ratio, pc_vol_ratio, oi_signal, vol_signal,
    iv_signal, contrarian_signal.
    """
    import yfinance as yf
    yf_ticker = yf.Ticker(ticker)
    exp_formatted = expiry_str[:4] + "-" + expiry_str[4:6] + "-" + expiry_str[6:8]
    try:
        chain = yf_ticker.option_chain(exp_formatted)
    except Exception:
        return {
            "pc_oi_ratio": None,
            "pc_vol_ratio": None,
            "oi_signal": "neutral",
            "vol_signal": "neutral",
            "iv_signal": "neutral",
            "contrarian_signal": None,
        }

    calls = chain.calls
    puts = chain.puts

    call_oi = int(calls["openInterest"].sum()) if not calls.empty else 0
    put_oi = int(puts["openInterest"].sum()) if not puts.empty else 0
    call_vol = int(calls["volume"].sum()) if not calls.empty else 0
    put_vol = int(puts["volume"].sum()) if not puts.empty else 0

    pc_oi = put_oi / call_oi if call_oi > 0 else None
    pc_vol = put_vol / call_vol if call_vol > 0 else None

    oi_signal = "neutral"
    if pc_oi is not None:
        if pc_oi < 0.5:
            oi_signal = "bullish (many calls open)"
        elif pc_oi > 1.2:
            oi_signal = "bearish (many puts open)"

    vol_signal = "neutral"
    if pc_vol is not None:
        if pc_vol < 0.6:
            vol_signal = "bullish (more calls trading)"
        elif pc_vol > 1.3:
            vol_signal = "bearish (more puts trading)"

    iv_signal = "neutral"
    if iv_rank is not None:
        if iv_rank > 80:
            iv_signal = f"IV high ({iv_rank:.0f}% rank) → options expensive, good to sell premium"
        elif iv_rank < 20:
            iv_signal = f"IV low ({iv_rank:.0f}% rank) → options cheap, good to buy premium"
        else:
            iv_signal = f"IV moderate ({iv_rank:.0f}% rank) → no extreme"

    contrarian_signal = None
    if pc_oi is not None and pc_vol is not None:
        if oi_signal.startswith("bullish") and vol_signal.startswith("bearish"):
            contrarian_signal = "Possible short-term reversal: OI bullish but volume bearish"
        elif oi_signal.startswith("bearish") and vol_signal.startswith("bullish"):
            contrarian_signal = "Possible short-term reversal: OI bearish but volume bullish"

    return {
        "pc_oi_ratio": round(pc_oi, 2) if pc_oi is not None else None,
        "pc_vol_ratio": round(pc_vol, 2) if pc_vol is not None else None,
        "oi_signal": oi_signal,
        "vol_signal": vol_signal,
        "iv_signal": iv_signal,
        "contrarian_signal": contrarian_signal,
    }


def vectorized_black_scholes(
    S_array: np.ndarray,
    K: float,
    T_days: float,
    r: float = 0.05,
    sigma: float = 0.30,
    option_type: str = "C",
) -> np.ndarray:
    """
    Calculate Black-Scholes prices for an array of underlying prices.
    Used for plotting dynamic P/L profiles.

    Args:
        S_array: numpy array of underlying prices
        K: Strike price
        T_days: Days to expiration (can be float)
        r: Risk-free rate
        sigma: Volatility
        option_type: 'C' or 'P'

    Returns:
        numpy array of option prices corresponding to S_array
    """
    if T_days <= 0 or K <= 0 or sigma <= 0:
        if option_type.upper() == "C":
            return np.maximum(S_array - K, 0)
        else:
            return np.maximum(K - S_array, 0)

    T = T_days / 365.0
    sqrt_T = np.sqrt(T)

    # Prevent division by zero if S_array contains exactly 0
    S_safe = np.where(S_array <= 0, 1e-9, S_array)

    d1 = (np.log(S_safe / K) + (r + 0.5 * sigma**2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    Nd1 = norm.cdf(d1)
    Nd2 = norm.cdf(d2)
    discount = np.exp(-r * T)

    if option_type.upper() == "C":
        price_array = S_array * Nd1 - K * discount * Nd2
    else:
        Nmd1 = norm.cdf(-d1)
        Nmd2 = norm.cdf(-d2)
        price_array = K * discount * Nmd2 - S_array * Nmd1

    # Clamp bounds explicitly to exact intrinsic value at bounds
    price_array = np.maximum(price_array, 0)
    return price_array
