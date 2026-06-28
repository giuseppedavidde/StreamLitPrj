"""Multi-book strategy selector — filters and ranks options strategies.

Sources: options-playbook, options-course-workbook, options-crash-course,
         options-strategy-suggestions.

Strategy selection matrix: verdict (long-term/short-term/avoid) × IV regime × DTE.
"""

import math
from typing import Optional
from datetime import datetime, date
from agents.options_agent import OptionsAgent
from agents.market_data_agent import MarketDataAgent


# ── Strategy catalogue with metadata from all 4 sources ──────────
STRATEGIES = {
    'Synthetic Long 2:1': {
        'outlook': 'Bullish (aggressive)', 'source': 'options-strategy-suggestions',
        'min_verdict_score': 70, 'max_risk': 'Substantial (2x downside below put strike)',
        'min_dte': 45, 'ideal_dte': '60-90', 'iv_bias': 'not_extreme_low',
        'description': 'Sell 2x Put @ Strike A (OTM), Buy 1x Call @ Strike B (OTM/ATM). Net credit or cheaper than single long call.',
        'delta_approx': '1.5-2.0', 'theta': 'Positive if ITM/ATM', 'vega': 'Negative',
    },
    'LEAPS Call': {
        'outlook': 'Bullish', 'source': 'options-playbook',
        'min_verdict_score': 70, 'max_risk': 'Limited (premium paid)',
        'min_dte': 365, 'ideal_dte': '500-700', 'iv_bias': 'low',
        'description': 'Long-term call for directional exposure with time premium.',
        'delta_approx': '0.6-0.8', 'theta': 'Negative (slow decay)', 'vega': 'High',
    },
    'Cash-Secured Put': {
        'outlook': 'Bullish', 'source': 'options-playbook',
        'min_verdict_score': 60, 'max_risk': 'Substantial (strike - premium)',
        'min_dte': 30, 'ideal_dte': '30-45', 'iv_bias': 'high',
        'description': 'Sell put at desired entry price, collect premium, get assigned if below strike.',
        'delta_approx': '0.3-0.4', 'theta': 'Positive', 'vega': 'Negative',
    },
    'Covered Call': {
        'outlook': 'Neutral-Bullish', 'source': 'options-playbook',
        'min_verdict_score': 50, 'max_risk': 'Stock loss (opportunity cost)',
        'min_dte': 30, 'ideal_dte': '30-60', 'iv_bias': 'high',
        'description': 'Hold 100 shares, sell 1 call against them. Income + slight downside protection.',
        'delta_approx': '0.3', 'theta': 'Positive', 'vega': 'Negative',
    },
    'Collar': {
        'outlook': 'Neutral-Bullish (protected)', 'source': 'options-course-workbook',
        'min_verdict_score': 60, 'max_risk': 'Limited (put strike downside)',
        'min_dte': 30, 'ideal_dte': '45-90', 'iv_bias': 'any',
        'description': 'Own stock + long put (protective) + short call (funds the put).',
        'delta_approx': '0.2-0.4', 'theta': 'Slightly positive', 'vega': 'Near zero',
    },
    'Bull Call Spread': {
        'outlook': 'Bullish', 'source': 'options-playbook',
        'min_verdict_score': 50, 'max_risk': 'Limited (debit paid)',
        'min_dte': 30, 'ideal_dte': '45-60', 'iv_bias': 'low',
        'description': 'Buy ATM call + sell OTM call. Lower cost, capped profit.',
        'delta_approx': '0.3-0.5', 'theta': 'Negative (debit spread)', 'vega': 'Low',
    },
    'Bull Put Spread': {
        'outlook': 'Bullish', 'source': 'options-playbook',
        'min_verdict_score': 50, 'max_risk': 'Limited (width - credit)',
        'min_dte': 30, 'ideal_dte': '45', 'iv_bias': 'high',
        'description': 'Sell OTM put + buy further OTM put. Credit received, bullish bias.',
        'delta_approx': '0.2-0.3', 'theta': 'Positive', 'vega': 'Negative',
    },
    'Long Call ATM': {
        'outlook': 'Bullish', 'source': 'options-crash-course',
        'min_verdict_score': 50, 'max_risk': 'Limited (premium paid)',
        'min_dte': 30, 'ideal_dte': '45-60', 'iv_bias': 'low',
        'description': 'Buy ATM call for pure directional exposure.',
        'delta_approx': '0.5', 'theta': 'Negative (fast decay)', 'vega': 'Positive',
    },
    'Bear Put Spread': {
        'outlook': 'Bearish', 'source': 'options-playbook',
        'min_verdict_score': 30, 'max_risk': 'Limited (debit paid)',
        'min_dte': 30, 'ideal_dte': '45-60', 'iv_bias': 'low',
        'description': 'Buy ATM put + sell OTM put. Bearish, capped upside.',
        'delta_approx': '-0.3 to -0.5', 'theta': 'Negative (debit)', 'vega': 'Low',
    },
    'Bear Call Spread': {
        'outlook': 'Bearish', 'source': 'options-playbook',
        'min_verdict_score': 30, 'max_risk': 'Limited (width - credit)',
        'min_dte': 30, 'ideal_dte': '45', 'iv_bias': 'high',
        'description': 'Sell OTM call + buy further OTM call. Credit received, bearish bias.',
        'delta_approx': '-0.2 to -0.3', 'theta': 'Positive', 'vega': 'Negative',
    },
    'Long Put ATM': {
        'outlook': 'Bearish', 'source': 'options-crash-course',
        'min_verdict_score': 30, 'max_risk': 'Limited (premium paid)',
        'min_dte': 30, 'ideal_dte': '45-60', 'iv_bias': 'low',
        'description': 'Buy ATM put for pure bearish exposure.',
        'delta_approx': '-0.5', 'theta': 'Negative (fast decay)', 'vega': 'Positive',
    },
    'Iron Condor': {
        'outlook': 'Neutral / Range-bound', 'source': 'options-playbook',
        'min_verdict_score': 40, 'max_risk': 'Limited (widest spread width - credit)',
        'min_dte': 30, 'ideal_dte': '45', 'iv_bias': 'high',
        'description': 'Sell OTM put spread + sell OTM call spread. Profit in range.',
        'delta_approx': 'Near zero', 'theta': 'Positive (high)', 'vega': 'Negative',
    },
    'Long Butterfly': {
        'outlook': 'Neutral', 'source': 'options-course-workbook',
        'min_verdict_score': 40, 'max_risk': 'Limited (width of wings - debit)',
        'min_dte': 30, 'ideal_dte': '45-60', 'iv_bias': 'low',
        'description': 'Buy 1 ITM + sell 2 ATM + buy 1 OTM. Profit at center strike.',
        'delta_approx': 'Near zero', 'theta': 'Varies near expiry', 'vega': 'Low',
    },
    'Calendar Spread': {
        'outlook': 'Neutral / Volatility play', 'source': 'options-course-workbook',
        'min_verdict_score': 40, 'max_risk': 'Limited (debit paid)',
        'min_dte': 30, 'ideal_dte': '45-60 (near) / 90+ (far)', 'iv_bias': 'low',
        'description': 'Sell short-term option + buy same-strike long-term option.',
        'delta_approx': 'Near zero', 'theta': 'Positive (time spread)', 'vega': 'Long vega',
    },
    'Short Strangle (hedged)': {
        'outlook': 'Neutral', 'source': 'options-crash-course',
        'min_verdict_score': 40, 'max_risk': 'Unlimited in theory',
        'min_dte': 30, 'ideal_dte': '45', 'iv_bias': 'high',
        'description': 'Sell OTM put + sell OTM call. Wide range profit. Hedge tail risk.',
        'delta_approx': 'Near zero', 'theta': 'Positive', 'vega': 'Negative',
    },
    'Long Straddle': {
        'outlook': 'Volatile (big move expected)', 'source': 'options-playbook',
        'min_verdict_score': 50, 'max_risk': 'Limited (total premium paid)',
        'min_dte': 30, 'ideal_dte': '60', 'iv_bias': 'low',
        'description': 'Buy ATM call + buy ATM put. Profit from large move either direction.',
        'delta_approx': '0', 'theta': 'Negative (double decay)', 'vega': 'High positive',
    },
    'Long Strangle': {
        'outlook': 'Volatile', 'source': 'options-playbook',
        'min_verdict_score': 50, 'max_risk': 'Limited (total premium paid)',
        'min_dte': 30, 'ideal_dte': '60', 'iv_bias': 'low',
        'description': 'Buy OTM call + buy OTM put. Wider breakeven, lower cost than straddle.',
        'delta_approx': '0', 'theta': 'Negative', 'vega': 'Positive',
    },
    'Synthetic Long 1:1': {
        'outlook': 'Bullish', 'source': 'options-strategy-suggestions',
        'min_verdict_score': 60, 'max_risk': 'Substantial (downside below put strike)',
        'min_dte': 45, 'ideal_dte': '60-90', 'iv_bias': 'any',
        'description': 'Buy ATM call + sell ATM put. Replicates stock position at lower cost.',
        'delta_approx': '1.0', 'theta': 'Near zero', 'vega': 'Low',
    },
    'Married Put': {
        'outlook': 'Bullish (protected)', 'source': 'options-crash-course',
        'min_verdict_score': 60, 'max_risk': 'Limited (stock price - put strike + put cost)',
        'min_dte': 30, 'ideal_dte': '60-90', 'iv_bias': 'any',
        'description': 'Buy stock + buy put. Limited downside, unlimited upside.',
        'delta_approx': '0.9+ (stock) - 0.5 (put) = ~0.4', 'theta': 'Negative (put decay)', 'vega': 'Positive (put)',
    },
    'Short Call (naked)': {
        'outlook': 'Bearish', 'source': 'options-playbook',
        'min_verdict_score': 30, 'max_risk': 'Unlimited',
        'min_dte': 15, 'ideal_dte': '15-30', 'iv_bias': 'high',
        'description': 'Sell naked call. Max profit = premium. Only for advanced traders.',
        'delta_approx': '-0.3 to -0.5', 'theta': 'Positive', 'vega': 'Negative',
    },
}


class OptionsStrategistAgent:
    """Multi-book strategy selector — filters and ranks by verdict + IV + DTE."""

    def __init__(self):
        self.mda = MarketDataAgent()
        self.oa = OptionsAgent()

    def suggest(self, ticker: str, verdict_score: float, direction: str,
                in_position: bool = False, target_dte: int = 45,
                preferred_books: Optional[list[str]] = None) -> list[dict]:
        """Rank strategies for this ticker based on unified analysis verdict."""
        info = self.mda.get_info(ticker)
        iv_regime = self._assess_iv_regime(ticker)
        price = self.mda.get_price(ticker)
        exps = self.mda.get_option_expirations(ticker)
        has_options = bool(exps)

        candidates = []
        for name, strat in STRATEGIES.items():
            if preferred_books and strat['source'] not in preferred_books:
                continue
            if self._skip_strategy(name, verdict_score, direction, in_position, iv_regime, target_dte, strat):
                continue

            fit = self._fit_score(name, verdict_score, direction, in_position, iv_regime, target_dte, strat)
            expiry = self._pick_expiry(exps, name, target_dte)

            candidates.append({
                'strategy': name,
                'source': strat['source'],
                'outlook': strat['outlook'],
                'fit_score': fit,
                'max_risk': strat['max_risk'],
                'description': strat['description'],
                'suggested_expiry': expiry,
                'suggested_dte': self._dte_from_expiry(expiry),
                'delta_approx': strat.get('delta_approx', ''),
                'theta_profile': strat.get('theta', ''),
                'vega_profile': strat.get('vega', ''),
                'iv_regime': iv_regime,
            })

        candidates.sort(key=lambda r: r['fit_score'], reverse=True)
        return {'ticker': ticker.upper(), 'price': price, 'iv_regime': iv_regime,
                'has_options': has_options, 'strategies': candidates}

    # ── Strategy selection matrix logic ──────────────────────

    def _skip_strategy(self, name: str, verdict_score: float, direction: str,
                       in_position: bool, iv_regime: str, target_dte: int, strat: dict) -> bool:
        """Return True if this strategy should be excluded."""
        if verdict_score < strat['min_verdict_score']:
            return True
        if target_dte < strat['min_dte']:
            return True

        iv = iv_regime
        iv_bias = strat['iv_bias']
        if iv_bias == 'low' and iv != 'low':
            return True
        if iv_bias == 'high' and iv != 'high':
            return True
        if iv_bias == 'not_extreme_low' and iv == 'low':
            return True

        if name == 'Covered Call' and not in_position:
            return True
        if name == 'Collar' and not in_position:
            return True
        if name == 'Married Put' and not in_position:
            return True

        if direction == 'Bearish' and 'Bullish' in strat.get('outlook', '') and 'protected' not in strat.get('outlook', ''):
            return True
        if direction == 'Bullish' and 'Bearish' in strat.get('outlook', '') and 'protected' not in strat.get('outlook', ''):
            return True

        return False

    def _fit_score(self, name: str, verdict_score: float, direction: str,
                   in_position: bool, iv_regime: str, target_dte: int, strat: dict) -> float:
        """Compute fit score 0-100 — higher = better match."""
        score = 50.0

        if verdict_score >= 70 and strat['min_verdict_score'] >= 60:
            score += 20
        elif verdict_score >= 50 and strat['min_verdict_score'] >= 40:
            score += 10
        elif verdict_score < 40 and strat['min_verdict_score'] >= 50:
            score -= 20

        iv = iv_regime
        if iv == strat['iv_bias']:
            score += 15
        elif strat['iv_bias'] == 'any':
            score += 5

        dte_match = target_dte >= strat['min_dte']
        if dte_match:
            score += 10
        if hasattr(self, '_') and 45 <= target_dte <= 60:
            score += 5

        if in_position and name in ('Covered Call', 'Collar', 'Married Put'):
            score += 15
        elif not in_position and name in ('LEAPS Call', 'Synthetic Long 2:1', 'Cash-Secured Put'):
            score += 10

        if strat['source'] == 'options-strategy-suggestions':
            score += 5

        return min(100, max(0, score))

    def _assess_iv_regime(self, ticker: str) -> str:
        """Assess IV regime: low / normal / high."""
        try:
            from scipy.stats import percentileofscore
            hist = self.mda.get_history(ticker, '1y')
            if hist.empty:
                return 'normal'
            returns = hist['Close'].pct_change().dropna()
            hv = float(returns.std() * math.sqrt(252))

            exps = self.mda.get_option_expirations(ticker)
            if not exps:
                return 'normal'
            chain = self.mda.get_option_chain(ticker, exps[min(2, len(exps) - 1)])
            if chain[0].empty:
                return 'normal'
            atm_iv = chain[0]['impliedVolatility'].median() or 0.3
            atm_iv = float(atm_iv)

            ratio = atm_iv / max(hv, 0.01)
            if ratio > 1.3:
                return 'high'
            if ratio < 0.7:
                return 'low'
            return 'normal'
        except Exception:
            return 'normal'

    def _pick_expiry(self, exps: list[str], strategy: str, target_dte: int) -> Optional[str]:
        if not exps:
            return None
        if 'LEAPS' in strategy:
            return exps[-1]  # farthest out
        return self._find_closest(exps, target_dte)

    @staticmethod
    def _find_closest(exps: list[str], target: int) -> Optional[str]:
        today = date.today()
        best, best_dte = None, 999
        for e in exps:
            ed = datetime.strptime(e, '%Y-%m-%d').date()
            dte = (ed - today).days
            if abs(dte - target) < abs(best_dte - target):
                best, best_dte = e, dte
        return best

    @staticmethod
    def _dte_from_expiry(expiry: Optional[str]) -> Optional[int]:
        if not expiry:
            return None
        return (datetime.strptime(expiry, '%Y-%m-%d').date() - date.today()).days

    def synthetic_long_2x_quote(self, ticker: str, target_dte: int = 75) -> Optional[dict]:
        """Quote a Synthetic Long 2:1 structure."""
        info = self.mda.get_info(ticker)
        price = self.mda.get_price(ticker)
        exps = self.mda.get_option_expirations(ticker)
        if not exps:
            return None

        expiry = self._find_closest(exps, target_dte)
        if not expiry:
            return None

        calls_df, puts_df = self.mda.get_option_chain(ticker, expiry)
        if calls_df.empty or puts_df.empty:
            return None

        dte = (datetime.strptime(expiry, '%Y-%m-%d').date() - date.today()).days
        sigma = 0.3

        put_strike = round(price * 0.92, 1)
        call_strike = round(price * 1.0, 1)

        call_strikes = [k for k in calls_df.index if k >= call_strike]
        put_strikes = [k for k in puts_df.index if k <= put_strike]

        if not call_strikes or not put_strikes:
            return None

        best_call_strike = min(call_strikes)
        best_put_strike = max(put_strikes)

        call_row = calls_df.loc[best_call_strike]
        put_row = puts_df.loc[best_put_strike]

        call_premium = (float(call_row['ask']) + float(call_row['bid'])) / 2
        put_premium = (float(put_row['ask']) + float(put_row['bid'])) / 2

        net = call_premium - 2 * put_premium
        max_loss = (best_put_strike * 2 - best_call_strike) * -1 if net < 0 else 0

        return {
            'ticker': ticker.upper(),
            'expiry': expiry,
            'dte': dte,
            'underlying': round(price, 2),
            'structure': {
                'leg1': f'Buy 1x {ticker} {best_call_strike} Call @ ${call_premium:.2f}',
                'leg2': f'Sell 2x {ticker} {best_put_strike} Put @ ${put_premium:.2f} each',
            },
            'net_premium': round(net, 2),
            'net_label': f'${abs(net):.2f} CREDIT' if net < 0 else f'${abs(net):.2f} DEBIT',
            'max_loss': round(max_loss, 2),
            'upside_profile': f'Unlimited above ${best_call_strike:.2f} (less net premium)',
            'downside_risk': f'2:1 exposure below ${best_put_strike:.2f}',
        }
