"""
Option utilities — Black-Scholes Greeks + Historical Volatility.
Uses scipy.stats.norm (available via pandas_ta dependency).
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
        # Detect from index frequency
        if hasattr(df.index, "freq") and df.index.freq:
            freq = df.index.freq
        else:
            # Estimate from average time delta
            if len(df) > 1:
                avg_delta = (df.index[-1] - df.index[0]) / len(df)
                hours = avg_delta.total_seconds() / 3600
                if hours < 2:  # Sub-hourly or hourly
                    periods_per_year = 252 * 6.5  # ~1638
                elif hours < 24:
                    periods_per_year = 252 * (6.5 / hours)
                else:
                    periods_per_year = 252
            else:
                periods_per_year = 252

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
