"""Wyckoff phase + Volume Profile + Price Action scoring for market scanning."""

import numpy as np
import pandas as pd
from agents.market_data_agent import MarketDataAgent


class ScannerAgent:
    """Computes Wyckoff/VP/PA scores for one ticker — replicating scanner.py logic."""

    def __init__(self):
        self.mda = MarketDataAgent()

    def scan(self, ticker: str) -> dict:
        """Full 5-dimension scan returning {wyckoff, volprof, pa, fundamentals, pattern, final_score}."""
        info = self.mda.get_info(ticker)
        hist = self.mda.get_history(ticker, '1y')
        if hist.empty:
            return {'ticker': ticker, 'error': 'No data'}

        wyckoff_score, wyckoff_detail = self._wyckoff(hist, info)
        volprof_score, volprof_detail = self._volume_profile(hist)
        pa_score, pa_detail = self._price_action(hist)
        fund_score, fund_detail = self._fundamentals(info)

        hist_s = hist.tail(60)
        spx_hist = self.mda.get_history('^GSPC', '1y')
        sentiment_data = self._sentiment(info, hist_s, spx_hist)

        final = (
            wyckoff_score * 0.25 + volprof_score * 0.20 +
            pa_score * 0.20 + sentiment_data['score'] * 0.15 +
            fund_score * 0.20
        )

        pattern = self._identify_pattern(
            wyckoff_score, volprof_score, pa_score,
            sentiment_data['score'], fund_score, info, wyckoff_detail
        )

        return {
            'ticker': ticker.upper(),
            'price': round(self.mda.get_price(ticker), 2),
            'final_score': round(final, 1),
            'wyckoff': wyckoff_score,
            'volprof': volprof_score,
            'pa': pa_score,
            'sentiment': sentiment_data['score'],
            'fundamentals': fund_score,
            'pattern': pattern,
            'details': {
                'wyckoff': wyckoff_detail,
                'volprof': volprof_detail,
                'pa': pa_detail,
                'sentiment': sentiment_data.get('detail', ''),
                'fundamentals': fund_detail,
            },
            'sub_scores': sentiment_data.get('subs', {}),
        }

    def _wyckoff(self, hist: pd.DataFrame, info: dict) -> tuple:
        score, details = 20, []
        if hist.empty or len(hist) < 50:
            return 20, 'Insufficient data'

        price = float(hist['Close'].iloc[-1])
        hi1y, lo1y = hist['High'].max(), hist['Low'].min()
        pos = ((price - lo1y) / (hi1y - lo1y)) * 100 if (hi1y - lo1y) > 0 else 50

        if pos < 30:
            score += 15; details.append('Bottom 30% of 1Y range (+15)')
        elif pos < 60:
            score += 30; details.append('Accumulation zone 30-60% (+30)')

        recent = hist.tail(60)
        if len(recent) >= 20:
            highs, lows = recent['High'].values, recent['Low'].values
            half = len(highs) // 2
            if highs[-1] > highs[half] and lows[-1] > lows[half]:
                score += 40; details.append('HH/HL pattern Markup (+40)')
            elif highs[-1] < highs[half] and lows[-1] < lows[half]:
                score -= 20; details.append('LH/LL pattern Markdown (-20)')

        if len(hist) >= 50:
            ma50 = float(hist['Close'].rolling(50).mean().iloc[-1])
            if len(hist) >= 200:
                ma200 = float(hist['Close'].rolling(200).mean().iloc[-1])
                if ma50 > ma200:
                    score += 15; details.append(f'MA50 > MA200 (+15)')

        if len(hist) >= 30:
            r30 = hist.tail(30)
            low_30, low_idx = r30['Low'].min(), r30['Low'].idxmin()
            if low_idx and low_idx < hist.index[-5] and price > low_30 * 1.05:
                score += 30; details.append('Spring detected (+30)')

        if len(hist) >= 90:
            vol_older = hist.tail(90).head(60)['Volume'].mean()
            vol_recent = hist.tail(30)['Volume'].mean()
            if vol_recent < vol_older * 0.8:
                score += 15; details.append('Volume decreasing absorption (+15)')

        return min(score, 100), ' | '.join(details)

    def _volume_profile(self, hist: pd.DataFrame) -> tuple:
        if hist.empty or len(hist) < 20:
            return 10, 'Insufficient data'

        score, details = 10, []
        price = float(hist['Close'].iloc[-1])
        hist_r = hist['High'].max() - hist['Low'].min()
        n_bins = 20
        bin_w = hist_r / n_bins if hist_r > 0 else 1

        h = hist.copy()
        h['bin'] = ((h['Close'] - hist['Low'].min()) / bin_w).astype(int).clip(0, n_bins - 1)
        vol_by_bin = h.groupby('bin')['Volume'].sum()
        poc_bin = vol_by_bin.idxmax()
        poc_price = hist['Low'].min() + (poc_bin + 0.5) * bin_w
        total_vol = vol_by_bin.sum()
        cum, va_bins = 0, []
        for b, v in vol_by_bin.sort_values(ascending=False).items():
            cum += v; va_bins.append(b)
            if cum / total_vol >= 0.7:
                break
        val = hist['Low'].min() + min(va_bins) * bin_w
        vah = hist['Low'].min() + (max(va_bins) + 1) * bin_w

        if val <= price <= vah:
            score += 20; details.append(f'Price inside VA ({val:.2f}-{vah:.2f}) (+20)')
        elif price < val:
            score += 25; details.append(f'Price below VAL ({val:.2f}) (+25)')
        else:
            score += 15; details.append(f'Price above VAH ({vah:.2f}) (+15)')

        if abs(price - poc_price) / max(poc_price, 0.01) < 0.05:
            score += 10; details.append(f'Near VPOC ${poc_price:.2f} (+10)')

        if len(hist) >= 21:
            vr = float(hist['Volume'].iloc[-1]) / max(float(hist['Volume'].iloc[-21:].mean()), 0.01)
            if vr > 2.0:
                score += 15; details.append(f'Volume ratio {vr:.1f}x (+15)')
            elif vr > 1.0:
                score += 10; details.append(f'Volume ratio {vr:.1f}x (+10)')

        pos = ((price - hist['Low'].min()) / max(hist_r, 0.01)) * 100
        if 40 < pos < 60:
            score += 15; details.append('D-Profile shape balanced (+15)')

        return min(score, 100), ' | '.join(details)

    def _price_action(self, hist: pd.DataFrame) -> tuple:
        if hist.empty or len(hist) < 20:
            return 10, 'Insufficient data'

        score, details = 10, []

        if len(hist) >= 15:
            delta = hist['Close'].diff()
            up = delta.clip(lower=0)
            down = -delta.clip(upper=0)
            ma_up = up.ewm(com=13).mean()
            ma_down = down.ewm(com=13).mean()
            rsi = 100 - (100 / (1 + ma_up / ma_down.fillna(0.001)))
            rsi_val = float(rsi.iloc[-1])
            if 40 <= rsi_val <= 60:
                score += 10; details.append(f'RSI {rsi_val:.0f} neutral (+10)')
            elif 30 <= rsi_val < 40:
                score += 20; details.append(f'RSI {rsi_val:.0f} oversold zone (+20)')
            elif rsi_val < 30:
                score += 10; details.append(f'RSI {rsi_val:.0f} extreme (+10)')
            else:
                details.append(f'RSI {rsi_val:.0f} (+0)')

        h = hist.copy()
        h['ema25'] = h['Close'].ewm(span=25).mean()
        if len(hist) >= 30:
            slope = (h['ema25'].iloc[-1] - h['ema25'].iloc[-5]) / max(h['ema25'].iloc[-5], 0.01)
            if slope > 0:
                score += 15; details.append('25ema rising (+15)')

        last20 = hist.tail(20)
        vpa_net = 0
        for i in range(1, len(last20)):
            bar, prev = last20.iloc[i], last20.iloc[i - 1]
            vol, avg = float(bar['Volume']), float(last20['Volume'].mean())
            vr = vol / max(avg, 1)
            up = float(bar['Close']) > float(prev['Close'])
            wide = (float(bar['High']) - float(bar['Low'])) > (float(prev['High']) - float(prev['Low'])) * 1.2
            high_vol = vr > 1.5
            if up and high_vol:
                vpa_net += 1
            elif not up and high_vol:
                vpa_net -= 1
            if up and vr < 0.6 and wide:
                vpa_net -= 1
            elif not up and vr < 0.6 and wide:
                vpa_net += 1

        if vpa_net > 2:
            score += 20; details.append(f'VPA bullish ({vpa_net}) (+20)')
        elif vpa_net > 0:
            details.append(f'VPA mildly bullish ({vpa_net}) (+0)')

        return min(score, 100), ' | '.join(details)

    def _sentiment(self, info: dict, hist: pd.DataFrame, spx_hist: pd.DataFrame) -> dict:
        score, subs = 25, {}
        detail_parts = []

        si = info.get('shortPercentOfFloat')
        if si is not None:
            subs['si'] = round(si * 100, 1)
            if si > 0.20:
                score += 35; detail_parts.append(f'SI {si*100:.1f}% > 20% (+35)')
            elif si > 0.10:
                score += 20; detail_parts.append(f'SI {si*100:.1f}% 10-20% (+20)')
        else:
            detail_parts.append('SI N/A (+0)')

        inst = info.get('heldPercentInstitutions')
        if inst is not None and inst > 0.50:
            score += 15; detail_parts.append(f'Inst {inst*100:.0f}% > 50% (+15)')

        dtc = info.get('shortRatio')
        if dtc is not None:
            subs['dtc'] = round(dtc, 1)
            if dtc > 7:
                score += 25; detail_parts.append(f'DTC {dtc:.1f} > 7 (+25)')
            elif dtc > 3:
                score += 15; detail_parts.append(f'DTC {dtc:.1f} > 3 (+15)')

        return {'score': min(score, 100), 'detail': ' | '.join(detail_parts), 'subs': subs}

    def _fundamentals(self, info: dict) -> tuple:
        score, details = 10, []
        pe = info.get('trailingPE')
        if pe and pe > 0:
            if pe < 15:
                score += 30; details.append(f'P/E {pe:.1f} < 15 (+30)')
            elif pe < 25:
                score += 15; details.append(f'P/E {pe:.1f} < 25 (+15)')
            else:
                details.append(f'P/E {pe:.1f} (+0)')
        else:
            details.append('P/E N/A (+0)')

        rev = info.get('revenueGrowth')
        if rev and rev > 0:
            score += 20; details.append(f'Rev growth {rev*100:.1f}% (+20)')
        elif rev:
            details.append(f'Rev growth {rev*100:.1f}% (+0)')

        margins = info.get('profitMargins')
        if margins and margins > 0:
            score += 20; details.append(f'Margins {margins*100:.1f}% (+20)')

        de = info.get('debtToEquity')
        if de is not None:
            if de < 0.5:
                score += 25; details.append(f'D/E {de:.2f} < 0.5 (+25)')
            elif de < 1.0:
                score += 15; details.append(f'D/E {de:.2f} < 1.0 (+15)')

        mcap = info.get('marketCap')
        if mcap and mcap > 10e9:
            score += 10; details.append(f'MCap ${mcap/1e9:.1f}B > $10B (+10)')

        return min(score, 100), ' | '.join(details)

    def _identify_pattern(self, wyckoff: int, volprof: int, pa: int, sent: int, fund: int, info: dict, wyckoff_d: str) -> str:
        si = info.get('shortPercentOfFloat', 0) or 0
        if wyckoff >= 70 and 'Spring' in wyckoff_d:
            return 'Accumulation Spring'
        if volprof >= 70 and fund >= 60:
            return 'D-Profile Value Zone'
        if pa >= 70 and sent >= 50:
            return 'P-Profile Breakout'
        if sent >= 70 and si > 0.20:
            return 'Squeeze Setup'
        if wyckoff >= 65 and fund >= 60:
            return 'Golden Cross Accumulation'
        if volprof < 30:
            return 'b-Profile Trap'
        return 'Mixed / No dominant pattern'
