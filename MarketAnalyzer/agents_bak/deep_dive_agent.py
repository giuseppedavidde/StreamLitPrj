"""5-dimension deep dive + TAATH + TATC → stock-crypto-analysis unified verdict.

Dimensions:
  1. Wyckoff Phase (A-E)
  2. Volume Profile (shape, VPOC, VA)
  3. Price Action (VPA, Volman, Weis patterns)
  4. Sentiment (6-dimension from sentiment_engine.py)
  5. Fundamentals (P/E, growth, margins, D/E)

TAATH: Springs, Upthrusts, Clusters, SOT, displacement
TATC:  Put/Call ratio, VIX, contrarian extremes
"""

from datetime import datetime
from agents.market_data_agent import MarketDataAgent
from agents.sentiment_engine import SentimentEngine


class DeepDiveAgent:
    """Produces the unified 5-dimension verdict for any ticker."""

    WEIGHTS = {'wyckoff': 0.25, 'volprof': 0.20, 'pa': 0.20, 'sentiment': 0.15, 'fundamentals': 0.20}

    def __init__(self):
        self.mda = MarketDataAgent()
        self.sentiment = SentimentEngine()

    def analyze(self, ticker: str, is_crypto: bool = False) -> dict:
        """Full deep dive returning structured verdict dict."""
        info = self.mda.get_info(ticker)
        hist = self.mda.get_history(ticker, '1y')
        if hist.empty:
            return {'ticker': ticker, 'error': 'No price data'}

        hist_w_ma = hist.copy()
        hist_w_ma['MA50'] = hist['Close'].rolling(50).mean()
        hist_w_ma['MA200'] = hist['Close'].rolling(200).mean()

        spx_hist = self.mda.get_history('^GSPC', '1y')

        wyckoff = self._wyckoff(hist_w_ma, info)
        volprof = self._volume_profile(hist)
        pa = self._price_action(hist)
        sent = self.sentiment.aggregate(ticker)
        fund = self._fundamentals(info)

        final, dims = self._aggregate(wyckoff['score'], volprof['score'], pa['score'], sent['score'], fund['score'])
        verdict, direction, action = self._verdict(final)

        return {
            'ticker': ticker.upper(),
            'name': self.mda.get_name(ticker),
            'price': round(self.mda.get_price(ticker), 2),
            'date': datetime.now().isoformat(),
            'wyckoff': wyckoff,
            'volume_profile': volprof,
            'price_action': pa,
            'sentiment': sent,
            'fundamentals': fund,
            'tatc': self._tatc(info),
            'final_score': round(final, 1),
            'verdict': verdict,
            'direction': direction,
            'action': action,
            'dimensions': dims,
        }

    # ── 1. Wyckoff ──────────────────────────────────────────────
    def _wyckoff(self, df: 'pd.DataFrame', info: dict) -> dict:
        c, hi, lo, v = df['Close'], df['High'], df['Low'], df['Volume']
        latest = df.iloc[-1]
        avg_60 = df.tail(60)
        r_lo, r_hi = avg_60['Low'].min(), avg_60['High'].max()
        r_pct = (latest['Close'] - r_lo) / (r_hi - r_lo) * 100 if r_hi > r_lo else 50

        last30 = df.tail(30)
        hh = last30['High'].diff().gt(0).sum() > 15
        hl = last30['Low'].diff().gt(0).sum() > 15
        lh = last30['High'].diff().lt(0).sum() > 15
        ll = last30['Low'].diff().lt(0).sum() > 15

        spring = False
        r_lo_f = float(r_lo)
        for i in range(-10, -1):
            if float(df.iloc[i]['Low']) < r_lo_f and float(df.iloc[i + 1]['Close']) > float(df.iloc[i]['Close']):
                spring = True; break

        upthrust = False
        r_hi_f = float(r_hi)
        for i in range(-10, -1):
            if float(df.iloc[i]['High']) > r_hi_f and float(df.iloc[i + 1]['Close']) < float(df.iloc[i]['Close']):
                upthrust = True; break

        vol_60 = float(v.tail(60).mean())
        vol_20 = float(v.tail(20).mean())
        contracting = vol_20 < vol_60 * 0.8 if vol_60 else False

        sos = sum(1 for i in range(-20, 0)
                  if float(v.iloc[i]) > float(v.tail(20).mean()) * 1.5 and float(df.iloc[i]['Close']) > float(df.iloc[i]['Open']))
        sow = sum(1 for i in range(-20, 0)
                  if float(v.iloc[i]) > float(v.tail(20).mean()) * 1.5 and float(df.iloc[i]['Close']) < float(df.iloc[i]['Open']))

        if spring and sos >= sow:
            phase, score = 'Phase C-D — Spring / Initial Effect', 82
        elif spring:
            phase, score = 'Phase C — Spring', 78
        elif hh and hl and r_pct > 80 and sos >= sow:
            phase, score = 'Phase D-E — Markup', 75
        elif upthrust:
            phase, score = 'Phase C — Upthrust (Bearish)', 25
        elif contracting and sos >= sow:
            phase, score = 'Phase B — Cause Building (Accumulation)', 60
        elif sos > sow:
            phase, score = 'Phase D — SOS Bias (Accumulation)', 65
        elif sow > sos:
            phase, score = 'Phase D — SOW Bias (Distribution)', 35
        elif hh and hl:
            phase, score = 'Phase D — Early Markup', 70
        else:
            phase, score = 'Phase A-B — Range / Cause Building', 50

        return {'phase': phase, 'score': score, 'range_pct': round(r_pct, 1),
                'spring': spring, 'upthrust': upthrust, 'sos': sos, 'sow': sow,
                'hh_hl': hh and hl, 'lh_ll': lh and ll,
                'vol_ratio_20v60': round(vol_20 / max(vol_60, 1) * 100, 1)}

    # ── 2. Volume Profile ──────────────────────────────────────
    def _volume_profile(self, hist: 'pd.DataFrame') -> dict:
        vp = hist.tail(63)
        if vp.empty:
            return {'shape': 'No Data', 'score': 50}

        pmin, pmax = float(vp['Low'].min()), float(vp['High'].max())
        bins, bw = 20, (pmax - pmin) / 20 if pmax > pmin else 1
        profile = {}
        for i in range(bins):
            lb, hb = pmin + i * bw, pmin + (i + 1) * bw
            mask = (vp['Close'] >= lb) & (vp['Close'] < hb)
            profile[i] = {'volume': float(vp.loc[mask, 'Volume'].sum()), 'count': int(mask.sum())}

        poc_bin_i = max(profile, key=lambda k: profile[k]['volume'])
        poc = pmin + (poc_bin_i + 0.5) * bw

        total_vol = float(vp['Volume'].sum())
        sorted_bins = sorted(profile.items(), key=lambda x: x[1]['volume'], reverse=True)
        cum, va_bins = 0, []
        for kk, vv in sorted_bins:
            cum += vv['volume']; va_bins.append(kk)
            if total_vol > 0 and cum / total_vol >= 0.7:
                break
        val = pmin + min(va_bins) * bw
        vah = pmin + (max(va_bins) + 1) * bw

        close_vp = float(vp['Close'].iloc[-1])
        curr_vol = float(vp['Volume'].iloc[-1])
        avg_vol = float(vp['Volume'].tail(20).mean())

        top_count = sorted_bins[0][1]['count']
        total_bars = len(vp)
        if top_count > total_bars * 0.25:
            shape, s_score = 'D-Profile (Balanced)', 30
        elif close_vp > poc and curr_vol > avg_vol * 1.2:
            shape, s_score = 'P-Profile (Bullish)', 50
        elif close_vp < poc and curr_vol > avg_vol * 1.2:
            shape, s_score = 'b-Profile (Bearish)', -30
        else:
            trend = 'up' if close_vp > float(vp['Close'].iloc[0]) else 'down'
            shape, s_score = f'Thin Profile (Trending {trend})', 20 if trend == 'up' else -20

        vpoc_score = 20 if close_vp > poc else (-20 if close_vp < poc else 0)
        va_score = -15 if close_vp > vah else (-15 if close_vp < val else 0)
        total_score = s_score + vpoc_score + va_score
        norm = max(0, min(100, 50 + total_score))

        return {'shape': shape, 'poc': round(poc, 2), 'val': round(val, 2), 'vah': round(vah, 2),
                'price_vs_poc': 'Bullish ▲' if close_vp > poc else 'Bearish ▼',
                'price_vs_va': f'Above VAH' if close_vp > vah else (f'Below VAL' if close_vp < val else 'Inside VA'),
                'score': norm}

    # ── 3. Price Action (VPA + Volman + Weis/TAATH) ────────────
    def _price_action(self, hist: 'pd.DataFrame') -> dict:
        v20 = hist.tail(20)
        c20, v20_vol = v20['Close'], v20['Volume']
        a20 = float(v20_vol.mean())
        a_range = (float(c20.max()) - float(c20.min())) / 20

        val_bull = sum(1 for i in range(-10, 0)
                       if float(hist.iloc[i]['Close']) > float(hist.iloc[i]['Open']) and float(hist.iloc[i]['Volume']) > a20 * 1.3)
        val_bear = sum(1 for i in range(-10, 0)
                       if float(hist.iloc[i]['Close']) < float(hist.iloc[i]['Open']) and float(hist.iloc[i]['Volume']) > a20 * 1.3)
        rev = sum(1 for i in range(-9, 0)
                  if (float(hist.iloc[i]['Close']) > float(hist.iloc[i - 1]['Close']) and float(hist.iloc[i - 1]['Close']) < float(hist.iloc[i - 1]['Open']))
                  or (float(hist.iloc[i]['Close']) < float(hist.iloc[i - 1]['Close']) and float(hist.iloc[i - 1]['Close']) > float(hist.iloc[i - 1]['Open'])))
        vpa = (val_bull - val_bear) * 5 + (rev * 10 if rev > 2 else 0)

        er = 0
        for i in range(-5, 0):
            br = float(hist.iloc[i]['High']) - float(hist.iloc[i]['Low'])
            wr = br > a_range * 1.2
            nr = br < a_range * 0.8
            hv = float(hist.iloc[i]['Volume']) > a20 * 1.3
            lv = float(hist.iloc[i]['Volume']) < a20 * 0.7
            er += 5 if (wr and hv) else (-5 if (nr and hv) else (-10 if (wr and lv) else 0))

        ema25 = c20.ewm(span=25).mean()
        ema_up = float(ema25.iloc[-1]) > float(ema25.iloc[-5])
        ema_s = 15 if ema_up else -15

        recent_r = float(v20['High'].max()) - float(v20['Low'].min())
        tight = float((v20['High'] - v20['Low']).tail(5).mean()) < recent_r * 0.15 if recent_r > 0 else False
        bld = 30 if tight else 0

        ws = 0
        for i in range(-15, -2):
            bar, nxt = hist.iloc[i], hist.iloc[i + 1]
            if float(bar['Low']) < float(hist.iloc[i - 1]['Low']) and float(nxt['Close']) > float(nxt['Open']):
                ws += 20; break

        pa_raw = (vpa + er + ema_s + bld + ws) / 4
        pa_norm = max(0, min(100, 50 + pa_raw))
        pa_v = 'Bullish' if pa_norm > 60 else ('Neutral' if pa_norm >= 40 else 'Bearish')

        return {'verdict': pa_v, 'score': pa_norm, 'vpa_bull': val_bull, 'vpa_bear': val_bear,
                'vpa_rev': rev, 'er': er, 'ema25_up': bool(ema_up), 'buildup': bool(tight), 'weis': ws}

    # ── 4. Fundamentals ────────────────────────────────────────
    def _fundamentals(self, info: dict) -> dict:
        score, reasons = 50, []
        pe = info.get('trailingPE')
        if pe is not None:
            if pe < 10: score += 30; reasons.append(f'P/E {pe:.1f} deep value')
            elif pe < 15: score += 20; reasons.append(f'P/E {pe:.1f} value')
            elif pe < 25: score += 10; reasons.append(f'P/E {pe:.1f} fair')
            elif pe > 40: score -= 20; reasons.append(f'P/E {pe:.1f} expensive')

        rev = info.get('revenueGrowth')
        if rev is not None:
            if rev > 0: score += 15; reasons.append(f'Revenue growth +{rev*100:.0f}%')
            else: score -= 15

        inst = info.get('heldPercentInstitutions')
        if inst is not None and inst > 0.5:
            score += 10

        margins = info.get('profitMargins')
        if margins is not None:
            if margins > 0.15: score += 15; reasons.append(f'Margins {margins*100:.0f}%')
            elif margins < 0: score -= 15

        dte = info.get('debtToEquity')
        if dte is not None:
            if dte > 300: score -= 10
            elif dte < 50: score += 10

        fcf = info.get('freeCashflow')
        if fcf is not None and fcf > 0:
            score += 10

        return {'score': max(0, min(100, score)), 'pe': pe, 'rev_growth': round(rev * 100, 1) if rev else None,
                'inst_own': round(inst * 100, 1) if inst else None,
                'margins': round(margins * 100, 1) if margins else None,
                'dte': dte, 'fcf': fcf, 'reasons': reasons}

    # ── TATC (Trading Against The Crowd) ───────────────────────
    def _tatc(self, info: dict) -> dict:
        score, signals = 0, []

        inst = info.get('heldPercentInstitutions')
        if inst is not None:
            if inst > 0.80:
                score += 20; signals.append('Extreme institutional ownership')
            elif inst < 0.20:
                score -= 10; signals.append('Low institutional interest')

        si = info.get('shortPercentOfFloat')
        if si is not None:
            if si > 0.15:
                score += 25; signals.append(f'High SI {si*100:.0f}% — contrarian squeeze potential')
            elif si < 0.03:
                score -= 10; signals.append('Low SI — no squeeze setup')

        beta = info.get('beta3Year') or info.get('beta')
        if beta is not None:
            if beta > 1.5:
                score += 10; signals.append('High beta — sentiment-driven')
            elif beta < 0.5:
                score -= 10; signals.append('Low beta — insulated from crowd')

        mcap = info.get('marketCap')
        if mcap is not None:
            if mcap < 2e9:
                score += 15; signals.append('Small cap — retail sentiment dominates')
            elif mcap > 100e9:
                score -= 5; signals.append('Mega cap — less sentiment amplification')

        direction = 'Contrarian Bullish' if score > 20 else ('Contrarian Bearish' if score < -10 else 'Neutral')
        return {'score': score, 'signals': signals, 'direction': direction}

    # ── Aggregation ────────────────────────────────────────────
    def _aggregate(self, w: float, vp: float, pa: float, s: float, f: float) -> tuple:
        dims = {'Wyckoff': (w, self.WEIGHTS['wyckoff']),
                'Volume Profile': (vp, self.WEIGHTS['volprof']),
                'Price Action': (pa, self.WEIGHTS['pa']),
                'Sentiment': (s, self.WEIGHTS['sentiment']),
                'Fundamentals': (f, self.WEIGHTS['fundamentals'])}
        final = w * self.WEIGHTS['wyckoff'] + vp * self.WEIGHTS['volprof'] + pa * self.WEIGHTS['pa'] + s * self.WEIGHTS['sentiment'] + f * self.WEIGHTS['fundamentals']
        return final, dims

    @staticmethod
    def _verdict(score: float) -> tuple:
        if score >= 70:
            return 'LONG-TERM INVESTMENT', 'Long', 'Entry DCA o singolo, PT 6-12 mesi'
        if score >= 50:
            return 'SHORT-TERM SPECULATION', 'Long', 'Entry tattico, PT 1-4 settimane, stop stretto'
        if score >= 30:
            return 'SHORT-TERM SPECULATION (Neutrale)', 'Neutrale', 'Solo setup perfetto'
        return 'AVOID / WAIT', 'N/A', 'Nessuna azione'
