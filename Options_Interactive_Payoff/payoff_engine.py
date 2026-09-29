"""Local Black-Scholes payoff engine — no AI, no network.

Generalizes the verified "campaign" engine::

    P&L(S, tau) = realized
                  + sum_legs[ sign * qty * mult * BS(S, K, tau, IV_leg, kind) ]
                  - net_debit

where ``net_debit = sum_legs[ sign * qty * mult * entry_premium ]``.

All quantities are computed locally with Black-Scholes (scipy) and per-strike
implied volatilities solved from the observed market mid (skew).
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import Optional, Sequence

import numpy as np
from scipy.optimize import brentq
from scipy.stats import norm

from models import (
    Direction,
    Greeks,
    OptionKind,
    OptionLeg,
    PayoffConfig,
    PayoffResult,
    Position,
)

IV_LOWER_BOUND = 1e-4
IV_UPPER_BOUND = 5.0
MIN_TAU = 1e-9


def _d1_d2(
    spot: float, strike: float, tau: float, rate: float, sigma: float
) -> tuple[float, float]:
    """Black-Scholes d1, d2 terms."""
    vol_sqrt_t = sigma * math.sqrt(tau)
    d1 = (math.log(spot / strike) + (rate + 0.5 * sigma * sigma) * tau) / vol_sqrt_t
    return d1, d1 - vol_sqrt_t


def bs_price(
    spot: float,
    strike: float,
    tau: float,
    rate: float,
    sigma: float,
    kind: OptionKind,
) -> float:
    """Black-Scholes European option price per share (intrinsic when tau <= 0)."""
    if tau <= MIN_TAU or sigma <= 0 or spot <= 0 or strike <= 0:
        if kind is OptionKind.CALL:
            return max(spot - strike, 0.0)
        return max(strike - spot, 0.0)

    d1, d2 = _d1_d2(spot, strike, tau, rate, sigma)
    discount = math.exp(-rate * tau)
    if kind is OptionKind.CALL:
        return spot * norm.cdf(d1) - strike * discount * norm.cdf(d2)
    return strike * discount * norm.cdf(-d2) - spot * norm.cdf(-d1)


def bs_greeks(
    spot: float,
    strike: float,
    tau: float,
    rate: float,
    sigma: float,
    kind: OptionKind,
) -> Greeks:
    """Full Black-Scholes greeks per share (theta/vega/rho per 1 unit)."""
    if tau <= MIN_TAU or sigma <= 0 or spot <= 0 or strike <= 0:
        delta = 0.0
        if kind is OptionKind.CALL:
            delta = 1.0 if spot > strike else 0.0
        else:
            delta = -1.0 if spot < strike else 0.0
        return Greeks(delta=delta)

    d1, d2 = _d1_d2(spot, strike, tau, rate, sigma)
    pdf_d1 = norm.pdf(d1)
    sqrt_t = math.sqrt(tau)
    discount = math.exp(-rate * tau)
    price = bs_price(spot, strike, tau, rate, sigma, kind)
    gamma = pdf_d1 / (spot * sigma * sqrt_t)
    vega = spot * pdf_d1 * sqrt_t

    if kind is OptionKind.CALL:
        delta = norm.cdf(d1)
        theta = (-spot * pdf_d1 * sigma / (2 * sqrt_t) - rate * strike * discount * norm.cdf(d2))
        rho = strike * tau * discount * norm.cdf(d2)
    else:
        delta = -norm.cdf(-d1)
        theta = (-spot * pdf_d1 * sigma / (2 * sqrt_t) + rate * strike * discount * norm.cdf(-d2))
        rho = -strike * tau * discount * norm.cdf(-d2)

    return Greeks(
        price=price,
        delta=delta,
        gamma=gamma,
        theta=theta / 365.0,
        vega=vega / 100.0,
        rho=rho / 100.0,
    )


def implied_vol(
    price: float,
    spot: float,
    strike: float,
    tau: float,
    rate: float,
    kind: OptionKind,
) -> Optional[float]:
    """Solve implied volatility reproducing the observed price (None if impossible)."""
    if price <= 0 or tau <= MIN_TAU or spot <= 0 or strike <= 0:
        return None
    intrinsic = max(spot - strike, 0.0) if kind is OptionKind.CALL else max(strike - spot, 0.0)
    if price < intrinsic - 1e-6:
        return None

    def objective(sigma: float) -> float:
        return bs_price(spot, strike, tau, rate, sigma, kind) - price

    try:
        low = objective(IV_LOWER_BOUND)
        high = objective(IV_UPPER_BOUND)
        if low * high > 0:
            return None
        return float(brentq(objective, IV_LOWER_BOUND, IV_UPPER_BOUND, xtol=1e-6))
    except (ValueError, RuntimeError):
        return None


def position_value(
    spot: float,
    at_date: date,
    position: Position,
    default_iv: float,
) -> float:
    """Mark-to-market value of all legs (signed, contracted, multiplied)."""
    total = 0.0
    for leg in position.legs:
        sigma = leg.iv if leg.iv is not None else default_iv
        tau = leg.tau(at_date)
        value = bs_price(spot, leg.strike, tau, position.rate, sigma, leg.kind)
        total += leg.sign * value * position.multiplier
    return total


def campaign_pnl(
    spot: float,
    at_date: date,
    position: Position,
    default_iv: Optional[float] = None,
) -> float:
    """Campaign P&L at a given underlying price and date."""
    sigma = default_iv if default_iv is not None else position.required_iv
    return (
        position.realized_pnl
        + position_value(spot, at_date, position, sigma)
        - position.net_debit
    )


def net_greeks(position: Position, at_date: Optional[date] = None) -> Greeks:
    """Aggregate position greeks at a given date (defaults to today)."""
    at_date = at_date or date.today()
    total = Greeks()
    default_iv = position.required_iv
    for leg in position.legs:
        sigma = leg.iv if leg.iv is not None else default_iv
        tau = leg.tau(at_date)
        greeks = bs_greeks(
            position.underlying_price or leg.strike,
            leg.strike,
            tau,
            position.rate,
            sigma,
            leg.kind,
        )
        weight = leg.sign * position.multiplier
        total = Greeks(
            price=total.price + weight * greeks.price,
            delta=total.delta + weight * greeks.delta,
            gamma=total.gamma + weight * greeks.gamma,
            theta=total.theta + weight * greeks.theta,
            vega=total.vega + weight * greeks.vega,
            rho=total.rho + weight * greeks.rho,
        )
    return total


def _find_breakevens(prices: Sequence[float], pnls: Sequence[float]) -> list[float]:
    """Linear-interpolation breakevens where the expiry P&L crosses zero."""
    roots: list[float] = []
    for i in range(len(prices) - 1):
        y0, y1 = pnls[i], pnls[i + 1]
        if y0 == 0:
            roots.append(prices[i])
        elif y0 * y1 < 0:
            x0, x1 = prices[i], prices[i + 1]
            roots.append(x0 + (x1 - x0) * (-y0 / (y1 - y0)))
    return [round(r, 2) for r in roots]


def _slice_dates(today: date, expiry: date, n_slices: int) -> list[date]:
    """Evenly spaced slice dates from today to expiry (inclusive)."""
    days = max((expiry - today).days, 1)
    return [today + timedelta(days=round(i * days / (n_slices - 1))) for i in range(n_slices)]


def expiry_extremes(
    position: Position,
) -> tuple[Optional[float], Optional[float]]:
    """True max loss / max profit of the campaign *at expiry*, analytically.

    At expiry the P&L is piecewise linear in ``S``, so its extrema over the
    whole domain ``S in [0, +inf)`` are attained at the notable points::

        S = 0, every strike, and the S -> +inf asymptote

    This is independent of any user-chosen price grid (whose min/max only
    reflect the displayed range, not the real extremes).

    Returns ``(max_loss, max_profit)`` where ``None`` means the extreme is
    unbounded: ``None`` loss = ``-inf`` (net short calls dominate the right
    tail), ``None`` profit = ``+inf`` (net long calls dominate the right tail).
    """
    if not position.legs:
        raise ValueError("Position must contain at least one leg")
    expiry = position.max_expiry
    assert expiry is not None  # guaranteed by the legs check above

    candidates = sorted({0.0, *(leg.strike for leg in position.legs)})
    pnls = [campaign_pnl(spot, expiry, position) for spot in candidates]
    finite_min, finite_max = min(pnls), max(pnls)

    call_slope = position.multiplier * sum(
        leg.sign for leg in position.legs if leg.kind is OptionKind.CALL
    )
    if call_slope > 0:
        return finite_min, None
    if call_slope < 0:
        return None, finite_max
    return finite_min, finite_max


def compute_payoff(
    position: Position,
    config: PayoffConfig,
    today: Optional[date] = None,
) -> PayoffResult:
    """Compute the full payoff dataset (expiry, fan chart, surface, levels, greeks)."""
    if not position.legs:
        raise ValueError("Position must contain at least one leg")
    today = today or date.today()
    expiry = position.max_expiry
    assert expiry is not None  # guaranteed by the legs check above

    prices = np.linspace(config.price_min, config.price_max, config.n_points)
    price_list = [float(p) for p in prices]

    at_expiry = [campaign_pnl(float(p), expiry, position) for p in prices]

    dates = _slice_dates(today, expiry, config.n_slices)
    fan: dict[str, list[float]] = {}
    for slice_date in dates:
        fan[slice_date.isoformat()] = [
            round(campaign_pnl(float(p), slice_date, position), 2) for p in prices
        ]

    spot = position.underlying_price
    fan_dates = list(fan.keys())
    surface_z = [
        [fan[d][i] for d in fan_dates] for i in range(config.n_points)  # price-major
    ]

    max_loss, max_profit = expiry_extremes(position)
    grid_min, grid_max = min(at_expiry), max(at_expiry)
    spot_pnl = campaign_pnl(spot, today, position) if spot else None

    return PayoffResult(
        prices=[round(p, 2) for p in price_list],
        at_expiry=[round(v, 2) for v in at_expiry],
        slice_dates=fan_dates,
        fan=fan,
        surface_z=surface_z,
        max_loss=None if max_loss is None else round(max_loss, 2),
        max_profit=None if max_profit is None else round(max_profit, 2),
        grid_min=round(grid_min, 2),
        grid_max=round(grid_max, 2),
        breakevens=_find_breakevens(price_list, at_expiry),
        net_greeks=net_greeks(position, today),
        net_debit=round(position.net_debit, 2),
        spot=round(spot, 2) if spot else None,
        spot_pnl=None if spot_pnl is None else round(spot_pnl, 2),
    )


def build_bull_call_spread(
    ticker: str,
    long_strike: float,
    short_strike: float,
    expiry: date,
    long_premium: float,
    short_premium: float,
    spot: float,
    rate: float = 0.05,
    long_iv: Optional[float] = None,
    short_iv: Optional[float] = None,
) -> Position:
    """Convenience constructor for a long/short call spread (1 contract each)."""
    legs = [
        OptionLeg(
            kind=OptionKind.CALL,
            direction=Direction.LONG,
            strike=long_strike,
            expiry=expiry,
            quantity=1,
            entry_premium=long_premium,
            iv=long_iv,
        ),
        OptionLeg(
            kind=OptionKind.CALL,
            direction=Direction.SHORT,
            strike=short_strike,
            expiry=expiry,
            quantity=1,
            entry_premium=short_premium,
            iv=short_iv,
        ),
    ]
    return Position(
        ticker=ticker, legs=legs, underlying_price=spot, rate=rate
    )
