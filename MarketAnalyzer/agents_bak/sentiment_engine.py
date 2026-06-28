"""6-dimension sentiment engine. Pure Python, no AI dependency.

Dimensions:
  SI     — Short Interest (SI ratio, days-to-cover)
  Opt    — Options flow (put/call volume & OI ratios)
  Ins    — Insider transactions (purchases vs sales)
  Ret    — Retail sentiment (social volume, price action)
  Inst   — Institutional ownership & 13F changes
  Mom    — Relative momentum vs SPX
"""

import math
import numpy as np
import yfinance as yf
from datetime import datetime, date
from typing import Optional
from utils.cache_manager import CacheManager


class SentimentEngine:
    """Computes 6-dimension sentiment scores (0-100 each) for a ticker."""

    def __init__(self):
        self.cache = CacheManager()

    def score_all(self, ticker: str) -> dict:
        """Returns {dimension_name: {score, label, details}} for all 6 dims."""
        return {
            'Short Interest': self._score_short_interest(ticker),
            'Options Flow': self._score_options(ticker),
            'Insider Trading': self._score_insider(ticker),
            'Retail Sentiment': self._score_retail(ticker),
            'Institutional': self._score_institutional(ticker),
            'Momentum': self._score_momentum(ticker),
        }

    def aggregate(self, ticker: str) -> dict:
        """Confidence-weighted aggregate score."""
        dims = self.score_all(ticker)
        scores, weights = [], []
        for dim, data in dims.items():
            scores.append(data['score'])
            weights.append(data.get('weight', 1.0))
        total_w = sum(weights)
        if total_w == 0:
            return {'score': 50, 'dimensions': dims}
        agg = sum(s * w for s, w in zip(scores, weights)) / total_w
        return {'score': round(agg), 'dimensions': dims}

    # ── 1. Short Interest ─────────────────────────────────────
    def _score_short_interest(self, ticker: str) -> dict:
        details = {}
        weight = 1.0
        try:
            info = yf.Ticker(ticker).info
            si_pct = info.get('shortPercentOfFloat') or 0
            si_ratio = info.get('shortRatio') or 0
            si_pct_val = si_pct * 100 if si_pct < 1 else si_pct  # yfinance sometimes returns %
            details['short_float_pct'] = round(si_pct_val, 2)
            details['days_to_cover'] = round(si_ratio, 2)
            # Low SI = bullish (no overhang). Moderate-high = squeeze potential
            if si_pct_val < 3:
                score = 75
                details['note'] = 'Low short interest, no overhang'
            elif si_pct_val < 8:
                score = 60
                details['note'] = 'Moderate short interest'
            elif si_pct_val < 15:
                score = 45
                details['note'] = 'Elevated short interest, squeeze potential'
            else:
                score = 25
                details['note'] = 'Very high short interest -> bearish or squeeze setup'
                weight = 1.2
        except Exception:
            score, details = 50, {'note': 'No short interest data'}
        return {'score': score, 'label': f'{score}/100', 'weight': weight, 'details': details}

    # ── 2. Options Flow ───────────────────────────────────────
    def _score_options(self, ticker: str) -> dict:
        details = {}
        weight = 1.0
        try:
            t = yf.Ticker(ticker)
            exps = t.options
            if not exps:
                return {'score': 50, 'label': '50/100', 'weight': 0.5, 'details': {'note': 'No options data'}}
            # Use nearest monthly expiry
            chain = t.option_chain(exps[min(2, len(exps)-1)])
            calls, puts = chain.calls, chain.puts
            pc_vol = puts['volume'].sum() / max(calls['volume'].sum(), 1)
            pc_oi = puts['openInterest'].sum() / max(calls['openInterest'].sum(), 1)
            details['pc_volume_ratio'] = round(pc_vol, 2)
            details['pc_oi_ratio'] = round(pc_oi, 2)
            total_vol = int(calls['volume'].sum() + puts['volume'].sum())
            details['total_volume'] = total_vol
            if total_vol < 500:
                # Low liquidity: use OI ratio
                if pc_oi < 0.5:
                    score = 70; details['note'] = 'Low vol, OI bullish'
                elif pc_oi < 1.0:
                    score = 55; details['note'] = 'Low vol, OI neutral'
                else:
                    score = 35; details['note'] = 'Low vol, OI bearish'
            else:
                if pc_vol < 0.5:
                    score = 75; details['note'] = 'Call volume dominates'
                elif pc_vol < 1.0:
                    score = 60; details['note'] = 'Slightly bullish volume'
                elif pc_vol < 1.5:
                    score = 45; details['note'] = 'Neutral volume'
                else:
                    score = 30; details['note'] = 'Put volume dominates'
            weight = 0.8 if total_vol < 500 else 1.0
        except Exception:
            score, details = 50, {'note': 'Options data error'}
        return {'score': score, 'label': f'{score}/100', 'weight': weight, 'details': details}

    # ── 3. Insider Trading ────────────────────────────────────
    def _score_insider(self, ticker: str) -> dict:
        details = {}
        weight = 0.8
        try:
            t = yf.Ticker(ticker)
            # Try insider_purchases first
            insider = t.insider_purchases
            if insider is not None and not insider.empty:
                purchases = int(insider['Shares'].sum() if 'Shares' in insider.columns else 0)
                details['total_shares_purchased'] = purchases
                if purchases > 1_000_000:
                    score = 80; details['note'] = 'Strong insider buying'
                elif purchases > 100_000:
                    score = 65; details['note'] = 'Moderate insider buying'
                elif purchases > 0:
                    score = 55; details['note'] = 'Minor insider activity'
                else:
                    score = 45; details['note'] = 'No insider buying detected'
                    weight = 0.6
            else:
                score, details = 50, {'note': 'No insider data'}
                weight = 0.5
        except Exception:
            score, details = 50, {'note': 'Insider data error'}
            weight = 0.5
        return {'score': score, 'label': f'{score}/100', 'weight': weight, 'details': details}

    # ── 4. Retail Sentiment ───────────────────────────────────
    def _score_retail(self, ticker: str) -> dict:
        details = {}
        try:
            info = yf.Ticker(ticker).info
            price = info.get('regularMarketPrice') or 0
            ma50 = self._calc_ma(ticker, 50)
            ma200 = self._calc_ma(ticker, 200)
            rsi = self._calc_rsi(ticker)
            # Price vs MA as proxy for retail momentum
            above_ma50 = price > ma50 if ma50 else False
            above_ma200 = price > ma200 if ma200 else False
            details['above_ma50'] = above_ma50
            details['above_ma200'] = above_ma200
            details['rsi_14'] = round(rsi, 1)
            score = 50
            if above_ma200 and above_ma50:
                score = 65
                details['note'] = 'Price above both MAs, positive retail flow'
            elif above_ma50:
                score = 55
                details['note'] = 'Short-term retail positive'
            elif above_ma200:
                score = 45
                details['note'] = 'Above MA200 but short-term weak'
            else:
                score = 35
                details['note'] = 'Below both MAs, retail sentiment weak'
            if rsi > 70:
                score -= 10; details['note'] += ', overbought caution'
            elif rsi < 30:
                score += 5; details['note'] += ', oversold bounce opportunity'
        except Exception:
            score, details = 50, {'note': 'Retail data error'}
        return {'score': score, 'label': f'{score}/100', 'weight': 0.8, 'details': details}

    # ── 5. Institutional ──────────────────────────────────────
    def _score_institutional(self, ticker: str) -> dict:
        details = {}
        weight = 0.9
        try:
            info = yf.Ticker(ticker).info
            inst_pct = info.get('heldPercentInstitutions') or 0
            inst_val = inst_pct * 100 if inst_pct < 1 else inst_pct
            details['inst_ownership_pct'] = round(inst_val, 1)
            if inst_val > 80:
                score = 70; details['note'] = 'Very high institutional ownership'
            elif inst_val > 50:
                score = 65; details['note'] = 'Strong institutional interest'
            elif inst_val > 20:
                score = 55; details['note'] = 'Moderate institutional interest'
            elif inst_val > 5:
                score = 45; details['note'] = 'Low institutional ownership'
            else:
                score = 35; details['note'] = 'Very low institutional interest'
                weight = 0.6
        except Exception:
            score, details = 50, {'note': 'Institutional data error'}
            weight = 0.5
        return {'score': score, 'label': f'{score}/100', 'weight': weight, 'details': details}

    # ── 6. Relative Momentum ──────────────────────────────────
    def _score_momentum(self, ticker: str) -> dict:
        details = {}
        try:
            t = yf.Ticker(ticker)
            spx = yf.Ticker('^GSPC')
            hist_t = t.history(period='6mo')
            hist_s = spx.history(period='6mo')
            if hist_t.empty or hist_s.empty:
                return {'score': 50, 'label': '50/100', 'weight': 1.0, 'details': {'note': 'No momentum data'}}
            ret_t = hist_t['Close'].iloc[-1] / hist_t['Close'].iloc[0] - 1
            ret_s = hist_s['Close'].iloc[-1] / hist_s['Close'].iloc[0] - 1
            rel = ret_t - ret_s
            details['ticker_return_6m'] = round(float(ret_t * 100), 1)
            details['spx_return_6m'] = round(float(ret_s * 100), 1)
            details['relative_strength'] = round(float(rel * 100), 1)
            if rel > 0.15:
                score = 80; details['note'] = 'Strong relative outperformance'
            elif rel > 0.05:
                score = 65; details['note'] = 'Moderate outperformance'
            elif rel > -0.05:
                score = 50; details['note'] = 'In line with market'
            elif rel > -0.15:
                score = 35; details['note'] = 'Underperforming market'
            else:
                score = 20; details['note'] = 'Significant underperformance'
        except Exception:
            score, details = 50, {'note': 'Momentum data error'}
        return {'score': score, 'label': f'{score}/100', 'weight': 1.0, 'details': details}

    # ── Helpers ───────────────────────────────────────────────
    def _calc_ma(self, ticker: str, period: int) -> float:
        try:
            df = yf.Ticker(ticker).history(period='1y')
            if df.empty:
                return 0.0
            return float(df['Close'].rolling(period).mean().iloc[-1])
        except Exception:
            return 0.0

    def _calc_rsi(self, ticker: str, period: int = 14) -> float:
        try:
            df = yf.Ticker(ticker).history(period='6mo')
            if df.empty or len(df) < period + 1:
                return 50.0
            delta = df['Close'].diff()
            gain = delta.clip(lower=0).rolling(period).mean()
            loss = (-delta.clip(upper=0)).rolling(period).mean()
            rs = gain / loss.replace(0, np.nan)
            return float((100 - 100 / (1 + rs)).iloc[-1])
        except Exception:
            return 50.0
