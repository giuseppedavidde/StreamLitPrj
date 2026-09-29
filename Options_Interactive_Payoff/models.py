"""Pydantic data models for the Options Interactive Payoff app.

Pure data modelling — no market access, no AI, no side effects.
"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

DEFAULT_MULTIPLIER = 100


class OptionKind(str, Enum):
    """Option right."""

    CALL = "call"
    PUT = "put"


class Direction(str, Enum):
    """Position side."""

    LONG = "long"
    SHORT = "short"

    @property
    def sign(self) -> int:
        """+1 for long, -1 for short."""
        return 1 if self is Direction.LONG else -1


class OptionLeg(BaseModel):
    """A single option leg of a multi-leg position."""

    model_config = ConfigDict(use_enum_values=False)

    kind: OptionKind = OptionKind.CALL
    direction: Direction = Direction.LONG
    strike: float = Field(gt=0, description="Strike price")
    expiry: date = Field(description="Expiration date")
    quantity: int = Field(default=1, ge=1, description="Number of contracts")
    entry_premium: float = Field(
        default=0.0, description="Load / entry premium per share (user input)"
    )
    iv: Optional[float] = Field(
        default=None, gt=0, description="Annualized implied vol as a decimal"
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sign(self) -> int:
        """Signed contract multiplier (+q for long, -q for short)."""
        return self.direction.sign * self.quantity

    def tau(self, at_date: date) -> float:
        """Time to this leg's expiry in years, clamped at zero."""
        days = (self.expiry - at_date).days
        return max(days, 0) / 365.0

    def intrinsic(self, spot: float) -> float:
        """Intrinsic value per share at expiry."""
        if self.kind is OptionKind.CALL:
            return max(spot - self.strike, 0.0)
        return max(self.strike - spot, 0.0)


class Position(BaseModel):
    """A multi-leg option position campaign."""

    ticker: str = Field(min_length=1)
    legs: list[OptionLeg] = Field(default_factory=list)
    underlying_price: Optional[float] = Field(default=None, gt=0)
    realized_pnl: float = Field(
        default=0.0, description="Already realized P&L of the campaign"
    )
    multiplier: int = Field(default=DEFAULT_MULTIPLIER, gt=0)
    rate: float = Field(default=0.05, description="Risk-free rate as a decimal")

    @property
    def net_debit(self) -> float:
        """Net entry cost (positive = debit paid, negative = credit received)."""
        return sum(
            leg.sign * leg.entry_premium * self.multiplier for leg in self.legs
        )

    @property
    def max_expiry(self) -> Optional[date]:
        """Latest expiry across all legs."""
        if not self.legs:
            return None
        return max(leg.expiry for leg in self.legs)

    @property
    def required_iv(self) -> float:
        """Fallback implied volatility when a leg has none set."""
        return 0.30


class PayoffConfig(BaseModel):
    """Grid and slice configuration for the payoff computation."""

    price_min: float = Field(gt=0)
    price_max: float = Field(gt=0)
    n_points: int = Field(default=121, ge=5, le=2000)
    n_slices: int = Field(default=12, ge=2, le=60)

    @model_validator(mode="after")
    def _check_range(self) -> "PayoffConfig":
        """Ensure the price range is strictly increasing."""
        if self.price_max <= self.price_min:
            raise ValueError("price_max must be greater than price_min")
        return self


class Greeks(BaseModel):
    """Black-Scholes greeks for a single option (per share)."""

    price: float = 0.0
    delta: float = 0.0
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    rho: float = 0.0


class PayoffResult(BaseModel):
    """Full payoff computation output.

    ``max_loss``/``max_profit`` are the *analytic* extremes at expiry over
    ``S in [0, +inf)``; ``None`` means unbounded (``-inf`` / ``+inf``).
    ``grid_min``/``grid_max`` are the extremes on the displayed price grid only.
    """

    prices: list[float]
    at_expiry: list[float]
    slice_dates: list[str]
    fan: dict[str, list[float]]
    surface_z: list[list[float]]
    max_loss: Optional[float] = None
    max_profit: Optional[float] = None
    grid_min: float = 0.0
    grid_max: float = 0.0
    breakevens: list[float]
    net_greeks: Greeks
    net_debit: float
    spot: Optional[float] = None
    spot_pnl: Optional[float] = None


class OptionQuote(BaseModel):
    """A single option chain row (bid/ask/last/iv)."""

    strike: float
    bid: Optional[float] = None
    ask: Optional[float] = None
    last: Optional[float] = None
    implied_vol: Optional[float] = None
    open_interest: Optional[float] = None
    volume: Optional[float] = None

    @property
    def mid(self) -> Optional[float]:
        """Mid price from bid/ask, falling back to last."""
        if self.bid is not None and self.ask is not None and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        if self.last is not None and self.last > 0:
            return self.last
        return None


class ExpiryChain(BaseModel):
    """Option chain snapshot for a single expiry."""

    ticker: str
    expiry: date
    spot: float
    rate: float
    calls: list[OptionQuote] = Field(default_factory=list)
    puts: list[OptionQuote] = Field(default_factory=list)

    def quotes(self, kind: OptionKind) -> list[OptionQuote]:
        """Quotes for the requested option kind."""
        return self.calls if kind is OptionKind.CALL else self.puts

    def mid_for(self, kind: OptionKind, strike: float) -> Optional[float]:
        """Nearest-strike mid price for prefill purposes."""
        rows = self.quotes(kind)
        if not rows:
            return None
        nearest = min(rows, key=lambda q: abs(q.strike - strike))
        return nearest.mid
