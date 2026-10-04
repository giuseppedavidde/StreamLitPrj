"""Open-position reconstruction from the Trade History ledger.

Pure pandas/Pydantic logic (no Streamlit). Prices are fetched lazily so the
netting math can be unit-tested without network access.
"""

from __future__ import annotations

import pandas as pd
from pydantic import BaseModel

OPTION_MULTIPLIER = 100.0
_EPS = 1e-9


class OpenPosition(BaseModel):
    """A still-open instrument derived by netting the ledger."""

    key: str = ""
    symbol: str = ""
    sec_type: str = ""
    currency: str = ""
    expiry: str = ""
    strike: float = 0.0
    right: str = ""
    quantity: float = 0.0
    avg_cost: float = 0.0
    multiplier: float = 1.0
    first_trade: str = ""
    last_trade: str = ""
    market_price: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None
    price_source: str = ""


def _instrument_key(symbol: str, sec_type: str, expiry: str, strike: float, right: str) -> str:
    """Stable key identifying a single contract/symbol."""
    if sec_type.upper() == "OPT":
        return f"{symbol}|OPT|{expiry}|{strike:g}|{right.upper()}"
    return f"{symbol}|{sec_type.upper()}"


def _is_bot(side: str) -> bool:
    return str(side).strip().upper() in {"BOT", "BUY"}


def _is_sld(side: str) -> bool:
    return str(side).strip().upper() in {"SLD", "SELL"}


def compute_open_positions(df: pd.DataFrame | None) -> list[OpenPosition]:
    """Net the ledger into open positions.

    Long adds to the net quantity, short subtracts. A position is closed (and
    dropped) when its net quantity returns to zero. The average cost follows
    the chronological average-cost method, resetting when a position flips
    side. Returns positions sorted by symbol.
    """
    if df is None or df.empty or "time" not in df.columns:
        return []

    work = df.copy()
    work["time"] = pd.to_datetime(work["time"], errors="coerce", utc=True)
    work = work.dropna(subset=["time"]).sort_values("time")
    if work.empty:
        return []

    for column in ("symbol", "sec_type", "currency", "expiry", "right", "side"):
        if column not in work.columns:
            work[column] = ""
    for column in ("shares", "price", "strike"):
        work[column] = (
            pd.to_numeric(work[column], errors="coerce").fillna(0.0)
            if column in work.columns
            else 0.0
        )

    state: dict[str, dict] = {}
    for _, row in work.iterrows():
        side = row["side"]
        if not (_is_bot(side) or _is_sld(side)):
            continue
        shares = abs(float(row["shares"]))
        if shares <= 0:
            continue
        price = float(row["price"])
        symbol = str(row["symbol"])
        sec_type = str(row["sec_type"])
        key = _instrument_key(symbol, sec_type, str(row["expiry"]), float(row["strike"]), str(row["right"]))

        entry = state.get(key)
        if entry is None:
            entry = {
                "symbol": symbol,
                "sec_type": sec_type,
                "currency": str(row["currency"]),
                "expiry": str(row["expiry"]),
                "strike": float(row["strike"]),
                "right": str(row["right"]),
                "qty": 0.0,
                "avg": 0.0,
                "first": row["time"],
                "last": row["time"],
            }
            state[key] = entry

        delta = shares if _is_bot(side) else -shares
        net = entry["qty"]
        if abs(net) <= _EPS:
            new_net, new_avg = delta, price
        elif (net > 0) == (delta > 0):
            new_net = net + delta
            new_avg = (net * entry["avg"] + delta * price) / new_net if abs(new_net) > _EPS else 0.0
        else:
            new_net = net + delta
            if abs(new_net) <= _EPS:
                new_avg = 0.0
            elif (new_net > 0) == (net > 0):
                new_avg = entry["avg"]
            else:
                new_avg = price
        entry["qty"], entry["avg"] = new_net, new_avg
        entry["last"] = row["time"]

    positions: list[OpenPosition] = []
    for key, entry in state.items():
        if abs(entry["qty"]) <= _EPS:
            continue
        sec_type = entry["sec_type"].upper()
        positions.append(
            OpenPosition(
                key=key,
                symbol=entry["symbol"],
                sec_type=entry["sec_type"],
                currency=entry["currency"],
                expiry=entry["expiry"],
                strike=entry["strike"],
                right=entry["right"],
                quantity=entry["qty"],
                avg_cost=entry["avg"],
                multiplier=OPTION_MULTIPLIER if sec_type == "OPT" else 1.0,
                first_trade=str(entry["first"]),
                last_trade=str(entry["last"]),
            )
        )
    positions.sort(key=lambda item: item.symbol)
    return positions


def apply_market_prices(
    positions: list[OpenPosition],
    prices: dict[str, float] | None,
    sources: dict[str, str] | None = None,
) -> list[OpenPosition]:
    """Attach market price / value / unrealised P&L to priced positions."""
    prices = prices or {}
    sources = sources or {}
    result: list[OpenPosition] = []
    for position in positions:
        price = prices.get(position.key)
        if price is None:
            result.append(position.model_copy(deep=True))
            continue
        multiplier = position.multiplier
        market_value = position.quantity * price * multiplier
        pnl = (price - position.avg_cost) * position.quantity * multiplier
        pct = (
            (price - position.avg_cost) / abs(position.avg_cost) * 100.0
            if abs(position.avg_cost) > _EPS
            else None
        )
        result.append(
            position.model_copy(
                update={
                    "market_price": float(price),
                    "market_value": market_value,
                    "unrealized_pnl": pnl,
                    "unrealized_pnl_pct": pct,
                    "price_source": sources.get(position.key, ""),
                }
            )
        )
    return result


def total_unrealized_pnl(positions: list[OpenPosition]) -> float | None:
    """Sum of unrealised P&L over priced positions, or None if none priced."""
    values = [p.unrealized_pnl for p in positions if p.unrealized_pnl is not None]
    return float(sum(values)) if values else None


def fetch_stock_price(symbol: str) -> float | None:
    """Best-effort current price for a stock/ETF via yfinance."""
    try:
        import yfinance as yf
    except ImportError:
        return None
    try:
        info = yf.Ticker(symbol).fast_info
        price = info.get("last_price") if hasattr(info, "get") else getattr(info, "last_price", None)
        if price:
            return float(price)
    except Exception as e:  # network / missing ticker
        print(f"[POSITIONS] fast_info {symbol} failed: {type(e).__name__}: {e}")
    try:
        hist = yf.Ticker(symbol).history(period="5d")
        if hist is not None and not hist.empty:
            return float(hist["Close"].iloc[-1])
    except Exception as e:
        print(f"[POSITIONS] history {symbol} failed: {type(e).__name__}: {e}")
    return None


def fetch_option_price(underlying: str, expiry: str, right: str, strike: float) -> float | None:
    """Best-effort option mark via the yfinance option chain.

    Expects ``expiry`` as ``YYYYMMDD``. Uses the bid/ask midpoint when both
    are quoted, else the last price. Returns None when unavailable.
    """
    if not (underlying and len(expiry) == 8 and right.upper() in {"C", "P"}):
        return None
    try:
        import yfinance as yf
    except ImportError:
        return None
    expiry_dash = f"{expiry[:4]}-{expiry[4:6]}-{expiry[6:8]}"
    try:
        chain = yf.Ticker(underlying).option_chain(expiry_dash)
    except Exception as e:
        print(f"[POSITIONS] option_chain {underlying} {expiry_dash} failed: {type(e).__name__}: {e}")
        return None
    frame = chain.calls if right.upper() == "C" else chain.puts
    if frame is None or frame.empty:
        return None
    match = frame[(frame["strike"] - strike).abs() < 1e-6]
    if match.empty:
        return None
    row = match.iloc[0]
    bid = float(row.get("bid") or 0.0)
    ask = float(row.get("ask") or 0.0)
    if bid > 0 and ask > 0:
        return (bid + ask) / 2.0
    last = float(row.get("lastPrice") or 0.0)
    return last or None


def fetch_market_prices(positions: list[OpenPosition]) -> tuple[dict[str, float], dict[str, str]]:
    """Fetch prices for all positions; returns (prices, sources) keyed by position key."""
    prices: dict[str, float] = {}
    sources: dict[str, str] = {}
    for position in positions:
        if position.sec_type.upper() == "OPT":
            price = fetch_option_price(position.symbol, position.expiry, position.right, position.strike)
            source = "yfinance option chain"
        else:
            price = fetch_stock_price(position.symbol)
            source = "yfinance"
        if price is not None:
            prices[position.key] = price
            sources[position.key] = source
    return prices, sources
