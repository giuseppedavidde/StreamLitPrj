"""Aggregate statistics for the Trade History ledger.

Pure pandas/Pydantic helpers, independent from Streamlit, so they can be
unit-tested directly. The input is either the full ledger or the subset
filtered by the date range selected in the UI.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
from pydantic import BaseModel, Field

_EPS = 1e-9


class SymbolStats(BaseModel):
    """Per-symbol aggregation."""

    symbol: str = ""
    n_trades: int = 0
    realized_pnl: float = 0.0
    win_rate: float = 0.0


class PeriodStats(BaseModel):
    """Per-period (month or year) aggregation."""

    period: str = ""
    n_trades: int = 0
    realized_pnl: float = 0.0


class TradeStats(BaseModel):
    """Full statistics bundle for a set of executions."""

    n_trades: int = 0
    n_symbols: int = 0
    first_date: datetime | None = None
    last_date: datetime | None = None
    total_volume: float = 0.0
    total_commission: float = 0.0

    realized_pnl: float = 0.0
    net_pnl: float = 0.0
    best_trade: float = 0.0
    worst_trade: float = 0.0

    n_wins: int = 0
    n_losses: int = 0
    n_flat: int = 0
    win_rate: float = 0.0
    avg_profit: float = 0.0
    avg_loss: float = 0.0
    profit_factor: float | None = None
    avg_pnl: float = 0.0

    n_bot: int = 0
    n_sld: int = 0
    pnl_bot: float = 0.0
    pnl_sld: float = 0.0

    by_symbol: list[SymbolStats] = Field(default_factory=list)
    by_month: list[PeriodStats] = Field(default_factory=list)
    by_year: list[PeriodStats] = Field(default_factory=list)


def _num(series: pd.Series) -> pd.Series:
    """Coerce a column to float, mapping NaN/None to 0.0."""
    return pd.to_numeric(series, errors="coerce").fillna(0.0)


def _win_rate(pnl: pd.Series) -> float:
    """Win rate in percent, counting wins and losses only (ignores flat trades)."""
    wins = int((pnl > _EPS).sum())
    losses = int((pnl < -_EPS).sum())
    denominator = wins + losses
    return (wins / denominator * 100.0) if denominator else 0.0


def _period_rows(work: pd.DataFrame, keys: pd.Series) -> list[PeriodStats]:
    """Aggregate realised P&L by an arbitrary period key, sorted ascending."""
    rows: list[PeriodStats] = []
    for period, group in work.assign(_period=keys).groupby("_period"):
        rows.append(
            PeriodStats(
                period=str(period),
                n_trades=int(len(group)),
                realized_pnl=float(group["pnl"].sum()),
            )
        )
    rows.sort(key=lambda item: item.period)
    return rows


def compute_trade_stats(df: pd.DataFrame | None) -> TradeStats:
    """Compute the TradeStats bundle from a ledger DataFrame.

    Never raises on empty/malformed input: missing columns and invalid dates
    are coerced, and an empty result yields a zeroed ``TradeStats``.
    """
    if df is None or df.empty or "time" not in df.columns:
        return TradeStats()

    work = df.copy()
    work["time"] = pd.to_datetime(work["time"], errors="coerce", utc=True)
    work["time"] = work["time"].dt.tz_localize(None)
    work = work.dropna(subset=["time"])
    if work.empty:
        return TradeStats()

    for column in ("symbol", "side"):
        if column not in work.columns:
            work[column] = ""
    for column in ("shares", "price", "commission", "realized_pnl"):
        work[column] = _num(work[column]) if column in work.columns else 0.0

    work["shares_abs"] = work["shares"].abs()
    work["pnl"] = work["realized_pnl"]

    pnl = work["pnl"]
    wins = work.loc[pnl > _EPS, "pnl"]
    losses = work.loc[pnl < -_EPS, "pnl"]
    gross_profit = float(wins.sum())
    gross_loss = float(losses.sum())
    profit_factor = (gross_profit / abs(gross_loss)) if gross_loss < 0 else None

    symbol_rows: list[SymbolStats] = []
    for symbol, group in work.groupby("symbol"):
        symbol_rows.append(
            SymbolStats(
                symbol=str(symbol),
                n_trades=int(len(group)),
                realized_pnl=float(group["pnl"].sum()),
                win_rate=_win_rate(group["pnl"]),
            )
        )
    symbol_rows.sort(key=lambda item: item.realized_pnl, reverse=True)

    side_norm = work["side"].astype(str).str.upper()
    total_commission = float(work["commission"].sum())
    realized = float(pnl.sum())

    return TradeStats(
        n_trades=int(len(work)),
        n_symbols=int(work["symbol"].nunique()),
        first_date=work["time"].min().to_pydatetime(),
        last_date=work["time"].max().to_pydatetime(),
        total_volume=float((work["shares_abs"] * work["price"]).sum()),
        total_commission=total_commission,
        realized_pnl=realized,
        net_pnl=realized - total_commission,
        best_trade=float(pnl.max()),
        worst_trade=float(pnl.min()),
        n_wins=int(len(wins)),
        n_losses=int(len(losses)),
        n_flat=int((pnl.abs() <= _EPS).sum()),
        win_rate=_win_rate(pnl),
        avg_profit=float(wins.mean()) if not wins.empty else 0.0,
        avg_loss=float(losses.mean()) if not losses.empty else 0.0,
        profit_factor=profit_factor,
        avg_pnl=float(pnl.mean()),
        n_bot=int((side_norm == "BOT").sum()),
        n_sld=int((side_norm == "SLD").sum()),
        pnl_bot=float(work.loc[side_norm == "BOT", "pnl"].sum()),
        pnl_sld=float(work.loc[side_norm == "SLD", "pnl"].sum()),
        by_symbol=symbol_rows,
        by_month=_period_rows(work, work["time"].dt.strftime("%Y-%m")),
        by_year=_period_rows(work, work["time"].dt.strftime("%Y")),
    )
