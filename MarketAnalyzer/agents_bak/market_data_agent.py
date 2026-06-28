"""Unified yfinance wrapper with caching, error handling, and consistent formatting."""

import math
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import datetime, date, timedelta
from typing import Optional, Any
from utils.cache_manager import CacheManager


class MarketDataAgent:
    """Single entry point for all yfinance data across the app."""

    def __init__(self):
        self.cache = CacheManager()

    # ── Ticker info ──────────────────────────────────────────
    def get_info(self, ticker: str) -> dict:
        """Fetch ticker info dict with cache (1h TTL)."""
        cached = self.cache.get(f'{ticker}_info', max_age=3600)
        if cached:
            return cached
        try:
            info = yf.Ticker(ticker).info or {}
            self.cache.set(f'{ticker}_info', info)
            return info
        except Exception:
            return {}

    def get_price(self, ticker: str) -> float:
        return self.get_info(ticker).get('regularMarketPrice') or \
               self.get_info(ticker).get('currentPrice') or 0.0

    def get_name(self, ticker: str) -> str:
        return self.get_info(ticker).get('longName') or \
               self.get_info(ticker).get('shortName') or ticker

    # ── Price history ────────────────────────────────────────
    def get_history(self, ticker: str, period: str = '2y') -> pd.DataFrame:
        """OHLCV history with cache (1h TTL)."""
        cached = self.cache.get(f'{ticker}_hist_{period}', max_age=3600)
        if cached is not None:
            df = pd.DataFrame(cached['data'], columns=cached['columns'], index=cached['index'])
            df.index = pd.to_datetime(df.index, utc=True)
            df.index = df.index.tz_convert(None)
            return df
        try:
            df = yf.Ticker(ticker).history(period=period)
            if df.empty:
                return pd.DataFrame()
            cached = {
                'data': df.values.tolist(),
                'columns': list(df.columns),
                'index': [str(i) for i in df.index],
            }
            self.cache.set(f'{ticker}_hist_{period}', cached)
            return df
        except Exception:
            return pd.DataFrame()

    def get_history_dates(self, ticker: str, start: str, end: str) -> pd.DataFrame:
        cached = self.cache.get(f'{ticker}_hist_{start}_{end}', max_age=3600)
        if cached is not None:
            df = pd.DataFrame(cached['data'], columns=cached['columns'], index=cached['index'])
            df.index = pd.to_datetime(df.index, utc=True)
            df.index = df.index.tz_convert(None)
            return df
        try:
            df = yf.Ticker(ticker).history(start=start, end=end)
            if not df.empty:
                cached = {
                    'data': df.values.tolist(),
                    'columns': list(df.columns),
                    'index': [str(i) for i in df.index],
                }
                self.cache.set(f'{ticker}_hist_{start}_{end}', cached)
            return df
        except Exception:
            return pd.DataFrame()

    # ── Technical helpers ────────────────────────────────────
    def compute_ma(self, ticker: str, period: int = 50) -> float:
        df = self.get_history(ticker, '1y')
        if df.empty:
            return 0.0
        return float(df['Close'].rolling(period).mean().iloc[-1])

    def compute_rsi(self, ticker: str, period: int = 14) -> float:
        df = self.get_history(ticker, '6mo')
        if df.empty or len(df) < period + 1:
            return 50.0
        delta = df['Close'].diff()
        gain = delta.clip(lower=0).rolling(period).mean()
        loss = (-delta.clip(upper=0)).rolling(period).mean()
        rs = gain / loss.replace(0, np.nan)
        return float((100 - 100 / (1 + rs)).iloc[-1])

    def get_range_position(self, ticker: str) -> float:
        df = self.get_history(ticker, '1y')
        if df.empty:
            return 50.0
        lo, hi = df['Close'].min(), df['Close'].max()
        price = df['Close'].iloc[-1]
        if hi == lo:
            return 50.0
        return float((price - lo) / (hi - lo) * 100)

    def get_max_drawdown(self, ticker: str, period: str = '3mo') -> float:
        df = self.get_history(ticker, period)
        if df.empty:
            return 0.0
        dd = (df['Close'] / df['Close'].cummax() - 1).min()
        return float(dd * 100)

    def get_volatility(self, ticker: str, period: str = '6mo') -> float:
        df = self.get_history(ticker, period)
        if df.empty:
            return 0.0
        return float(df['Close'].pct_change().std() * math.sqrt(252) * 100)

    # ── Options ───────────────────────────────────────────────
    def get_option_expirations(self, ticker: str) -> list[str]:
        cached = self.cache.get(f'{ticker}_exps', max_age=3600)
        if cached:
            return cached
        try:
            exps = yf.Ticker(ticker).options or []
            self.cache.set(f'{ticker}_exps', exps)
            return list(exps)
        except Exception:
            return []

    def get_option_chain(self, ticker: str, expiry: str) -> tuple:
        """Returns (calls_df, puts_df) for given expiry, each with strike as index."""
        try:
            chain = yf.Ticker(ticker).option_chain(expiry)
            calls = chain.calls.set_index('strike')
            puts = chain.puts.set_index('strike')
            return calls, puts
        except Exception:
            return pd.DataFrame(), pd.DataFrame()

    def find_closest_expiry(self, ticker: str, target_dte: int = 200) -> Optional[str]:
        """Find the option expiry closest to target_dte days out."""
        exps = self.get_option_expirations(ticker)
        if not exps:
            return None
        today_d = date.today()
        best, best_dte = None, 9999
        for e in exps:
            ed = datetime.strptime(e, '%Y-%m-%d').date()
            dte = (ed - today_d).days
            if abs(dte - target_dte) < abs(best_dte - target_dte):
                best, best_dte = e, dte
        return best

    # ── ETF holdings ──────────────────────────────────────────
    def get_top_holdings(self, etf_ticker: str, n: int = 15) -> pd.DataFrame:
        """Returns top-N holdings as DataFrame with columns: Symbol, Name, Weight."""
        cached = self.cache.get(f'{etf_ticker}_holdings_{n}', max_age=86400)
        if cached is not None:
            return pd.DataFrame(cached)
        try:
            t = yf.Ticker(etf_ticker)
            holdings = t.funds_data.top_holdings
            if holdings is None or holdings.empty:
                return pd.DataFrame(columns=['Symbol', 'Name', 'Weight'])
            holdings = holdings.head(n)
            results = []
            for idx, row in holdings.iterrows():
                sym = str(idx) if not isinstance(idx, str) else idx
                name = row.get('Name', sym)
                wt_col = row.get('Holding Percent', 0)
                if wt_col == 0 and 'holding_percent' in holdings.columns:
                    wt_col = row.get('holding_percent', 0)
                wt = float(wt_col) * 100
                results.append({'Symbol': sym, 'Name': name, 'Weight': wt})
            df = pd.DataFrame(results)
            self.cache.set(f'{etf_ticker}_holdings_{n}', df.to_dict())
            return df
        except Exception:
            return pd.DataFrame(columns=['Symbol', 'Name', 'Weight'])

    def get_sector_weightings(self, etf_ticker: str) -> dict:
        cached = self.cache.get(f'{etf_ticker}_sector', max_age=86400)
        if cached:
            return cached
        try:
            sw = yf.Ticker(etf_ticker).funds_data.sector_weightings
            if sw:
                result = {k: v * 100 for k, v in sw.items() if v > 0.005}
                self.cache.set(f'{etf_ticker}_sector', result)
                return result
            return {}
        except Exception:
            return {}

    # ── Summary dict (for reports) ────────────────────────────
    def get_summary(self, ticker: str) -> dict:
        """Returns a flat dict of key data points for analysis."""
        info = self.get_info(ticker)
        price = self.get_price(ticker)
        ma50 = self.compute_ma(ticker, 50)
        ma200 = self.compute_ma(ticker, 200)
        hist = self.get_history(ticker, '1y')
        lo52 = float(hist['Close'].min()) if not hist.empty else 0
        hi52 = float(hist['Close'].max()) if not hist.empty else 0
        return {
            'ticker': ticker.upper(),
            'name': self.get_name(ticker),
            'price': price,
            'ma50': ma50,
            'ma200': ma200,
            'rsi14': self.compute_rsi(ticker),
            'range_pct': self.get_range_position(ticker),
            'vol_ann': self.get_volatility(ticker),
            'maxdd_3m': self.get_max_drawdown(ticker),
            'lo52': lo52,
            'hi52': hi52,
            'sector': info.get('sector', ''),
            'industry': info.get('industry', ''),
            'mkt_cap': info.get('marketCap', 0),
            'pe': info.get('trailingPE') or info.get('forwardPE') or 0,
            'beta': info.get('beta3Year') or info.get('beta') or 0,
            'div_yield': (info.get('dividendYield') or 0) * 100 if (info.get('dividendYield') or 0) < 1 else (info.get('dividendYield') or 0),
        }
