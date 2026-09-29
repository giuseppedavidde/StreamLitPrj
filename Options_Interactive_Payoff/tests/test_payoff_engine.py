"""Unit tests for the local payoff engine (offline, no network, no AI)."""

from __future__ import annotations

from datetime import date
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from models import Direction, OptionKind, OptionLeg, PayoffConfig, Position  # noqa: E402
from payoff_engine import (  # noqa: E402
    bs_greeks,
    bs_price,
    build_bull_call_spread,
    campaign_pnl,
    compute_payoff,
    expiry_extremes,
    implied_vol,
    net_greeks,
)

# DRAM Bull Call Spread 59/70, ETF DRAM, expiry 18 Dec 2026.
DRAM_EXPIRY = date(2026, 12, 18)
DRAM_LONG_STRIKE = 59.0
DRAM_SHORT_STRIKE = 70.0
DRAM_SPOT = 65.0
# Premiums chosen so net_debit = (6.96 - 10.00) * 100 = -304 (campaign credit),
# reproducing the verified campaign numbers: min +304, max +1404, 62 -> +604.
DRAM_LONG_PREMIUM = 6.96
DRAM_SHORT_PREMIUM = 10.00
TODAY = date(2026, 9, 29)


def _dram_position():
    return build_bull_call_spread(
        ticker="DRAM",
        long_strike=DRAM_LONG_STRIKE,
        short_strike=DRAM_SHORT_STRIKE,
        expiry=DRAM_EXPIRY,
        long_premium=DRAM_LONG_PREMIUM,
        short_premium=DRAM_SHORT_PREMIUM,
        spot=DRAM_SPOT,
        rate=0.05,
        long_iv=0.60,
        short_iv=0.55,
    )


# Short put 23 x2, credit 1.62/share, spot 23.33, expiry 15 Jan 2027.
SHORT_PUT_EXPIRY = date(2027, 1, 15)
SHORT_PUT_STRIKE = 23.0
SHORT_PUT_QTY = 2
SHORT_PUT_CREDIT = 1.62
SHORT_PUT_SPOT = 23.33
# Analytic max loss at S=0: -(23 - 0) * 2 * 100 + 1.62 * 2 * 100 = -4276.0.
# (The -4274 seen in the app was the grid artefact at price_min = 0.01, since
# PayoffConfig forbids price_min = 0; the true S=0 loss is -4276.)
SHORT_PUT_MAX_LOSS = -4276.0
SHORT_PUT_MAX_PROFIT = 324.0


def _short_put_position():
    return Position(
        ticker="TEST",
        legs=[
            OptionLeg(
                kind=OptionKind.PUT,
                direction=Direction.SHORT,
                strike=SHORT_PUT_STRIKE,
                expiry=SHORT_PUT_EXPIRY,
                quantity=SHORT_PUT_QTY,
                entry_premium=SHORT_PUT_CREDIT,
                iv=0.5,
            )
        ],
        underlying_price=SHORT_PUT_SPOT,
        rate=0.05,
    )


def _single_call(direction: Direction, premium: float) -> Position:
    return Position(
        ticker="TEST",
        legs=[
            OptionLeg(
                kind=OptionKind.CALL,
                direction=direction,
                strike=100.0,
                expiry=date(2027, 1, 15),
                quantity=1,
                entry_premium=premium,
                iv=0.4,
            )
        ],
        underlying_price=100.0,
        rate=0.05,
    )


def test_net_debit_is_campaign_credit():
    assert _dram_position().net_debit == pytest.approx(-304.0)


def test_dram_floor_is_304():
    config = PayoffConfig(price_min=40.0, price_max=90.0, n_points=101)
    result = compute_payoff(_dram_position(), config, today=TODAY)
    assert result.grid_min == pytest.approx(304.0, abs=0.5)


def test_dram_cap_is_1404():
    config = PayoffConfig(price_min=40.0, price_max=90.0, n_points=101)
    result = compute_payoff(_dram_position(), config, today=TODAY)
    assert result.grid_max == pytest.approx(1404.0, abs=0.5)


@pytest.mark.parametrize(
    "price_min, price_max",
    [(40.0, 90.0), (59.0, 70.0), (10.0, 200.0), (0.01, 500.0)],
)
def test_dram_real_extremes_are_grid_independent(price_min, price_max):
    """Real (analytic) max loss/profit must not depend on the displayed grid."""
    config = PayoffConfig(price_min=price_min, price_max=price_max, n_points=101)
    result = compute_payoff(_dram_position(), config, today=TODAY)
    # Net-credit 59/70 call spread: min P&L +304 (below 59), max +1404 (>= 70).
    assert result.max_loss == pytest.approx(304.0, abs=0.5)
    assert result.max_profit == pytest.approx(1404.0, abs=0.5)


@pytest.mark.parametrize(
    "price_min, price_max, n_points",
    [
        (0.01, 46.0, 121),
        (14.0, 32.66, 121),
        (20.0, 27.0, 61),
        (0.01, 500.0, 201),
    ],
)
def test_short_put_real_max_loss_is_grid_independent(price_min, price_max, n_points):
    """The real max loss of a short put happens at S=0, not at the grid edge."""
    config = PayoffConfig(price_min=price_min, price_max=price_max, n_points=n_points)
    result = compute_payoff(_short_put_position(), config, today=TODAY)
    assert result.max_loss == pytest.approx(SHORT_PUT_MAX_LOSS, abs=0.01)
    assert result.max_profit == pytest.approx(SHORT_PUT_MAX_PROFIT, abs=0.01)


def test_short_put_expiry_extremes_direct():
    """Analytic extremes bypass the grid entirely."""
    max_loss, max_profit = expiry_extremes(_short_put_position())
    assert max_loss == pytest.approx(SHORT_PUT_MAX_LOSS, abs=0.01)
    assert max_profit == pytest.approx(SHORT_PUT_MAX_PROFIT, abs=0.01)


def test_short_put_grid_min_changes_but_real_loss_does_not():
    """Displayed grid extremes move with the range; the real loss does not."""
    narrow = compute_payoff(
        _short_put_position(), PayoffConfig(price_min=20.0, price_max=27.0), today=TODAY
    )
    wide = compute_payoff(
        _short_put_position(), PayoffConfig(price_min=0.01, price_max=46.0), today=TODAY
    )
    assert narrow.grid_min != wide.grid_min
    assert narrow.max_loss == wide.max_loss == pytest.approx(SHORT_PUT_MAX_LOSS, abs=0.01)


def test_long_call_max_profit_is_unbounded():
    max_loss, max_profit = expiry_extremes(_single_call(Direction.LONG, 5.0))
    assert max_profit is None
    assert max_loss == pytest.approx(-500.0, abs=0.01)


def test_short_call_max_loss_is_unbounded():
    max_loss, max_profit = expiry_extremes(_single_call(Direction.SHORT, 5.0))
    assert max_loss is None
    assert max_profit == pytest.approx(500.0, abs=0.01)


def test_unbounded_extremes_survive_compute_payoff():
    config = PayoffConfig(price_min=50.0, price_max=150.0, n_points=101)
    result = compute_payoff(_single_call(Direction.LONG, 5.0), config, today=TODAY)
    assert result.max_profit is None
    assert result.max_loss == pytest.approx(-500.0, abs=0.01)


def test_dram_point_62_is_604():
    position = _dram_position()
    pnl = campaign_pnl(62.0, DRAM_EXPIRY, position)
    assert pnl == pytest.approx(604.0, abs=0.5)


def test_dram_no_breakeven_since_always_positive():
    config = PayoffConfig(price_min=40.0, price_max=90.0, n_points=101)
    result = compute_payoff(_dram_position(), config, today=TODAY)
    assert result.breakevens == []


def test_expiry_curve_matches_intrinsic():
    config = PayoffConfig(price_min=40.0, price_max=90.0, n_points=101)
    result = compute_payoff(_dram_position(), config, today=TODAY)
    for price, pnl in zip(result.prices, result.at_expiry):
        expected = max(price - DRAM_LONG_STRIKE, 0.0) * 100
        expected -= max(price - DRAM_SHORT_STRIKE, 0.0) * 100
        expected -= -304.0
        assert pnl == pytest.approx(expected, abs=0.5)


def test_bs_call_put_parity():
    spot, strike, tau, rate, sigma = 100.0, 100.0, 1.0, 0.05, 0.2
    call = bs_price(spot, strike, tau, rate, sigma, OptionKind.CALL)
    put = bs_price(spot, strike, tau, rate, sigma, OptionKind.PUT)
    import math

    expected = spot - strike * math.exp(-rate * tau)
    assert call - put == pytest.approx(expected, abs=1e-6)


def test_implied_vol_round_trip():
    spot, strike, tau, rate, sigma = 100.0, 105.0, 0.5, 0.04, 0.35
    price = bs_price(spot, strike, tau, rate, sigma, OptionKind.CALL)
    solved = implied_vol(price, spot, strike, tau, rate, OptionKind.CALL)
    assert solved is not None
    assert solved == pytest.approx(sigma, abs=1e-4)


def test_implied_vol_none_below_intrinsic():
    assert implied_vol(0.5, 100.0, 90.0, 0.5, 0.04, OptionKind.CALL) is None


def test_bs_price_at_expiry_is_intrinsic():
    assert bs_price(120.0, 100.0, 0.0, 0.05, 0.3, OptionKind.CALL) == pytest.approx(20.0)
    assert bs_price(120.0, 100.0, 0.0, 0.05, 0.3, OptionKind.PUT) == pytest.approx(0.0)


def test_net_greeks_of_spread_are_bounded():
    greeks = net_greeks(_dram_position(), TODAY)
    # bull call spread delta must lie in (0, 100) contracts * 100 shares
    assert 0 < greeks.delta <= 100.0


def test_fan_and_surface_shapes():
    config = PayoffConfig(price_min=40.0, price_max=90.0, n_points=61, n_slices=8)
    result = compute_payoff(_dram_position(), config, today=TODAY)
    assert len(result.fan) == 8
    assert all(len(series) == 61 for series in result.fan.values())
    assert len(result.surface_z) == 61
    assert all(len(row) == 8 for row in result.surface_z)
    # first slice is today, last is expiry
    assert result.slice_dates[0] == TODAY.isoformat()
    assert result.slice_dates[-1] == DRAM_EXPIRY.isoformat()


def test_empty_position_raises():
    from models import Position

    with pytest.raises(ValueError):
        compute_payoff(Position(ticker="X"), PayoffConfig(price_min=1, price_max=2))
