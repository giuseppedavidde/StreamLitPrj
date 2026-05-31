"""Black-Scholes Greeks, payoff tables, and theta decay analysis.

Purely computational — no AI dependency. Uses scipy for norm cdf/pdf.
"""

import math
from datetime import datetime, date
from typing import Optional

import numpy as np
from scipy.stats import norm

from agents.market_data_agent import MarketDataAgent


class OptionsAgent:
    """Computes option prices, Greeks, and payoff scenarios."""

    def __init__(self):
        self.mda = MarketDataAgent()

    def get_chain(self, ticker: str, expiry: Optional[str] = None) -> dict:
        """Fetch option chain for given expiry (closest 60-90 DTE if None)."""
        ticker = ticker.upper()
        expirations = self.mda.get_option_expirations(ticker)
        if not expirations:
            return {'ticker': ticker, 'error': 'No options available'}

        if expiry is None:
            expiry = self.mda.find_closest_expiry(ticker, target_dte=75) or expirations[0]

        calls_df, puts_df = self.mda.get_option_chain(ticker, expiry)
        if calls_df.empty:
            return {'ticker': ticker, 'error': 'Empty option chain'}

        underlying = self.mda.get_price(ticker)
        dte = (datetime.strptime(expiry, '%Y-%m-%d').date() - date.today()).days
        iv_estimate = self._estimate_iv(calls_df, underlying, dte)

        calls = self._augment_chain(calls_df.reset_index(), underlying, dte, 'call')
        puts = self._augment_chain(puts_df.reset_index(), underlying, dte, 'put')

        return {
            'ticker': ticker,
            'underlying': underlying,
            'expiry': expiry,
            'dte': dte,
            'iv_estimate': round(iv_estimate * 100, 1),
            'calls': calls,
            'puts': puts,
        }

    def compute_greeks(self, S: float, K: float, T: float, r: float, sigma: float, option_type: str) -> dict:
        """Full Black-Scholes Greeks for a single option."""
        if T <= 0 or sigma <= 0:
            return {'delta': 0, 'gamma': 0, 'theta': 0, 'vega': 0, 'rho': 0, 'price': 0}

        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)

        if option_type == 'call':
            price = S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)
            delta = norm.cdf(d1)
            theta = (-S * norm.pdf(d1) * sigma / (2 * math.sqrt(T))
                     - r * K * math.exp(-r * T) * norm.cdf(d2)) / 365
            rho = K * T * math.exp(-r * T) * norm.cdf(d2) / 100
        else:
            price = K * math.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)
            delta = -norm.cdf(-d1)
            theta = (-S * norm.pdf(d1) * sigma / (2 * math.sqrt(T))
                     + r * K * math.exp(-r * T) * norm.cdf(-d2)) / 365
            rho = -K * T * math.exp(-r * T) * norm.cdf(-d2) / 100

        gamma = norm.pdf(d1) / (S * sigma * math.sqrt(T))
        vega = S * norm.pdf(d1) * math.sqrt(T) / 100

        return {
            'price': round(price, 2),
            'delta': round(delta, 3),
            'gamma': round(gamma, 4),
            'theta': round(theta, 3),
            'vega': round(vega, 3),
            'rho': round(rho, 3),
            'iv': round(sigma * 100, 1),
        }

    def payoff_scenarios(self, ticker: str, strategy_type: str, strikes: list[float],
                         premiums: list[float], sides: list[str],
                         expiry: str, n_scenarios: int = 20) -> dict:
        """Generate payoff table for a multi-leg position at expiry and mid-point."""
        underlying = self.mda.get_price(ticker)
        edate = datetime.strptime(expiry, '%Y-%m-%d').date()
        dte = (edate - date.today()).days
        half_dte = max(1, dte // 2)

        price_range = np.linspace(underlying * 0.5, underlying * 1.5, n_scenarios)
        at_expiry = []
        at_half = []

        theta = dte / 365
        half_theta = half_dte / 365

        for sp in price_range:
            pl_expiry = self._legs_pnl(sp, 0, strikes, premiums, sides)
            pl_half = self._legs_pnl(sp, half_theta / theta if theta > 0 else 0.5,
                                     strikes, premiums, sides)
            at_expiry.append(round(float(pl_expiry), 2))
            at_half.append(round(float(pl_half), 2))

        breakevens = self._find_breakevens(price_range, at_expiry)

        return {
            'strategy': strategy_type,
            'underlying': round(underlying, 2),
            'expiry': expiry,
            'dte': dte,
            'prices': [round(float(p), 2) for p in price_range],
            'at_expiry': at_expiry,
            'at_half': at_half,
            'breakevens': [round(b, 2) for b in breakevens],
            'max_profit': round(max(at_expiry), 2),
            'max_loss': round(min(at_expiry), 2),
            'net_premium': round(sum(p * (1 if 'buy' in s else -1) for p, s in zip(premiums, sides)), 2),
        }

    def theta_decay(self, ticker: str, strike: float, option_type: str,
                    days: int = 60) -> list[dict]:
        """Daily theta decay from today through expiry."""
        S = self.mda.get_price(ticker)
        sigma = 0.3
        r = 0.05
        result = []
        for dte in range(max(days, 5), 0, -1):
            T = dte / 365
            g = self.compute_greeks(S, strike, T, r, sigma, option_type)
            result.append({'dte': dte, 'price': g['price'], 'theta': g['theta'], 'delta': g['delta']})
        return result

    # ── Private helpers ──────────────────────────────────────

    def _augment_chain(self, df: 'pd.DataFrame', underlying: float, dte: int, opt_type: str) -> list[dict]:
        """Add computed Greeks to raw option chain rows."""
        T = max(dte, 1) / 365
        r = 0.05
        sigma = 0.3
        rows = []
        for _, row in df.iterrows():
            K = float(row.get('strike', 0))
            if K <= 0:
                continue
            greeks = self.compute_greeks(underlying, K, T, r, sigma, opt_type)
            rows.append({
                'strike': K,
                'bid': float(row.get('bid', 0)),
                'ask': float(row.get('ask', 0)),
                'last': float(row.get('lastPrice', 0)),
                'volume': int(row.get('volume', 0)),
                'oi': int(row.get('openInterest', 0)),
                'iv': float(row.get('impliedVolatility', greeks['iv'])),
                'delta': greeks['delta'],
                'gamma': greeks['gamma'],
                'theta': greeks['theta'],
                'vega': greeks['vega'],
            })
        return rows

    def _legs_pnl(self, S: float, time_remaining: float, strikes: list[float],
                  premiums: list[float], sides: list[str]) -> float:
        """Compute PnL for multi-leg position at price S."""
        total = 0.0
        for K, premium, side in zip(strikes, premiums, sides):
            is_call = 'call' in side.lower()
            is_buy = 'buy' in side.lower()
            intrinsic = max(S - K, 0) if is_call else max(K - S, 0)

            if is_buy:
                pl = intrinsic - premium * (1 - time_remaining)
            else:
                pl = -intrinsic + premium * (1 - time_remaining)
            total += pl

        return total

    def _find_breakevens(self, prices: np.ndarray, pnl: list) -> list:
        """Find price points where PnL crosses zero."""
        bps = []
        for i in range(1, len(pnl)):
            if pnl[i - 1] * pnl[i] < 0:
                w = abs(pnl[i - 1]) / (abs(pnl[i - 1]) + abs(pnl[i]))
                bp = prices[i - 1] + (prices[i] - prices[i - 1]) * w
                if bp > 0:
                    bps.append(bp)
            elif pnl[i] == 0:
                bps.append(prices[i])
        return bps

    @staticmethod
    def _estimate_iv(df: 'pd.DataFrame', S: float, dte: int) -> float:
        """Crude IV estimate from ATM option mid price."""
        T = max(dte, 1) / 365
        if T <= 0:
            return 0.3
        atm_row = df.iloc[(df['strike'] - S).abs().idxmin()] if 'strike' in df.columns else None
        if atm_row is None:
            return 0.3
        mid = (float(atm_row.get('bid', 0)) + float(atm_row.get('ask', 0))) / 2
        if mid <= 0:
            return 0.3
        try:
            from scipy.optimize import brentq
            def f(sig):
                d1 = (math.log(S / float(atm_row['strike'])) + (0.05 + 0.5 * sig ** 2) * T) / (sig * math.sqrt(T))
                d2 = d1 - sig * math.sqrt(T)
                bs_price = S * norm.cdf(d1) - float(atm_row['strike']) * math.exp(-0.05 * T) * norm.cdf(d2)
                return bs_price - mid
            return brentq(f, 0.001, 5.0)
        except (ValueError, RuntimeError):
            return 0.3
