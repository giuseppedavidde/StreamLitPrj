"""Market data access via yfinance — local only, no AI.

Thin wrappers around yfinance with graceful failures, returning Pydantic
models/primitive types used by the engine and the Streamlit UI.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Optional

import yfinance as yf

from models import ExpiryChain, OptionQuote

RATE_TICKER = "^IRX"
DEFAULT_RATE = 0.05


def _to_date(value: object) -> Optional[date]:
    """Best-effort conversion of a yfinance expiry into a ``date``."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _safe_float(value: object) -> Optional[float]:
    """Return a finite float or None."""
    try:
        if value is None:
            return None
        result = float(value)
        if result is None or math.isnan(result):
            return None
        return result
    except (TypeError, ValueError):
        return None


def fetch_spot(ticker: str) -> Optional[float]:
    """Last traded/closing price for the ticker."""
    try:
        ticker_obj = yf.Ticker(ticker)
        fast = ticker_obj.fast_info
        for key in ("last_price", "lastPrice", "regular_market_price"):
            price = _safe_float(fast.get(key) if hasattr(fast, "get") else None)
            if price and price > 0:
                return price
        history = ticker_obj.history(period="5d")
        if not history.empty:
            return _safe_float(history["Close"].iloc[-1])
    except (KeyError, ValueError, TypeError):
        return None
    return None


def fetch_expirations(ticker: str) -> list[date]:
    """Available option expiries as ``date`` objects (sorted)."""
    try:
        raw = yf.Ticker(ticker).options
    except (KeyError, ValueError, TypeError):
        return []
    result = []
    for item in raw or []:
        parsed = _to_date(item)
        if parsed:
            result.append(parsed)
    return sorted(result)


def fetch_risk_free_rate() -> float:
    """Risk-free rate from ^IRX (13-week T-bill) as a decimal."""
    try:
        history = yf.Ticker(RATE_TICKER).history(period="5d")
        if not history.empty:
            value = _safe_float(history["Close"].iloc[-1])
            if value and value > 0:
                return value / 100.0
    except (KeyError, ValueError, TypeError):
        pass
    return DEFAULT_RATE


def _quotes(frame: object) -> list[OptionQuote]:
    """Convert a yfinance calls/puts DataFrame into OptionQuote models."""
    quotes: list[OptionQuote] = []
    if frame is None or getattr(frame, "empty", True):
        return quotes
    for _, row in frame.iterrows():
        strike = _safe_float(row.get("strike"))
        if not strike:
            continue
        quotes.append(
            OptionQuote(
                strike=strike,
                bid=_safe_float(row.get("bid")),
                ask=_safe_float(row.get("ask")),
                last=_safe_float(row.get("lastPrice")),
                implied_vol=_safe_float(row.get("impliedVolatility")),
                open_interest=_safe_float(row.get("openInterest")),
                volume=_safe_float(row.get("volume")),
            )
        )
    quotes.sort(key=lambda q: q.strike)
    return quotes


def fetch_chain(
    ticker: str, expiry: date, spot: float, rate: float
) -> Optional[ExpiryChain]:
    """Fetch the full option chain snapshot for a ticker/expiry."""
    try:
        chain = yf.Ticker(ticker).option_chain(expiry.isoformat())
    except (KeyError, ValueError, TypeError):
        return None
    if chain is None:
        return None
    calls = _quotes(getattr(chain, "calls", None))
    puts = _quotes(getattr(chain, "puts", None))
    if not calls and not puts:
        return None
    return ExpiryChain(
        ticker=ticker,
        expiry=expiry,
        spot=spot,
        rate=rate,
        calls=calls,
        puts=puts,
    )
