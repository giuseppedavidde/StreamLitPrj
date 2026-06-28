"""Crypto-specific analysis — on-chain metrics, tokenomics, hype detection.

Uses CoinGecko free API for crypto data, yfinance for price history fallback.
"""

import math
from datetime import datetime, timedelta
from typing import Optional

import requests

from agents.market_data_agent import MarketDataAgent
from agents.deep_dive_agent import DeepDiveAgent


COINGECKO_BASE = 'https://api.coingecko.com/api/v3'


class CryptoAgent:
    """Crypto-focused analysis layer — on-chain, tokenomics, hype."""

    def __init__(self):
        self.mda = MarketDataAgent()
        self.dda = DeepDiveAgent()

    def analyze(self, coin_id: str, vs_currency: str = 'usd') -> dict:
        """Full crypto analysis. coin_id = CoinGecko ID (e.g. 'bitcoin')."""
        cg = self._coingecko_data(coin_id, vs_currency)
        if not cg:
            return {'coin': coin_id, 'error': 'No CoinGecko data'}

        ticker = cg.get('symbol', coin_id).upper()
        ticker_yf = f'{ticker}-USD' if ticker != 'BTC' else 'BTC-USD'

        price = cg.get('current_price', 0)
        hist = self.mda.get_history(ticker_yf, '1y')
        info = self.mda.get_info(ticker_yf)

        onchain = self._onchain_score(cg)
        tokenomics = self._tokenomics_score(cg)
        hype = self._hype_score(cg)
        fundamentals = self._fundamentals_score(cg)

        stock_analysis = {}
        if not hist.empty:
            stock_analysis = self.dda.analyze(ticker_yf, is_crypto=True)

        crypto_score = int(onchain['score'] * 0.35 + tokenomics['score'] * 0.35 + hype['score'] * 0.15 + fundamentals['score'] * 0.15)

        return {
            'coin': coin_id,
            'name': cg.get('name', coin_id),
            'symbol': ticker,
            'price': price,
            'market_cap_rank': cg.get('market_cap_rank'),
            'market_cap': cg.get('market_cap'),
            'total_volume': cg.get('total_volume'),
            'high_24h': cg.get('high_24h'),
            'low_24h': cg.get('low_24h'),
            'price_change_24h': cg.get('price_change_percentage_24h'),
            'price_change_7d': cg.get('price_change_percentage_7d'),
            'price_change_30d': cg.get('price_change_percentage_30d'),
            'onchain': onchain,
            'tokenomics': tokenomics,
            'hype': hype,
            'fundamentals': fundamentals,
            'crypto_score': crypto_score,
            'stock_analysis': stock_analysis,
        }

    # ── Dimension scores (0-100 each) ────────────────────────

    def _onchain_score(self, cg: dict) -> dict:
        score = 50
        details = []

        active_addrs = cg.get('active_addresses', cg.get('coingecko_rank'))
        if active_addrs:
            score += 20; details.append('Active addresses available (+20)')

        vol_mcap = 0
        if cg.get('total_volume') and cg.get('market_cap'):
            vol_mcap = cg['total_volume'] / cg['market_cap']
        if 0.02 < vol_mcap < 0.3:
            score += 15; details.append(f'Volume/MCap ratio {vol_mcap:.2%} healthy (+15)')
        elif vol_mcap > 0.5:
            score += 5; details.append('High volume liquidity (+5)')
        else:
            details.append('Low volume relative to mcap')

        return {'score': min(100, score), 'details': ' | '.join(details) if details else 'Limited on-chain data', 'vol_mcap_ratio': round(vol_mcap, 4) if vol_mcap else None}

    def _tokenomics_score(self, cg: dict) -> dict:
        score = 50
        details = []

        max_supply = cg.get('max_supply')
        circ_supply = cg.get('circulating_supply')
        total_supply = cg.get('total_supply')

        if max_supply and circ_supply:
            pct_circulated = circ_supply / max_supply * 100
            details.append(f'Circulated: {pct_circulated:.1f}% of max')

            if max_supply > 0 and abs(circ_supply - max_supply) / max_supply < 0.05:
                score += 20; details.append('Near max supply — deflationary potential (+20)')
            elif pct_circulated < 50:
                score += 5; details.append('Early in issuance schedule (+5)')
            elif pct_circulated > 90:
                score += 15; details.append('High circulation — less dilution risk (+15)')

            score += 10; details.append('Max supply defined — supply cap (+10)')
        else:
            details.append('No max supply — potential inflation risk')

        if cg.get('ath') and cg.get('current_price'):
            pct_from_ath = (cg['current_price'] / cg['ath']) * 100
            details.append(f'{pct_from_ath:.1f}% from ATH')
            if pct_from_ath < 10:
                score += 20; details.append('Deep value from ATH (+20)')
            elif pct_from_ath < 30:
                score += 10; details.append('Discount from ATH (+10)')

        return {'score': min(100, score), 'details': ' | '.join(details) if details else 'Limited tokenomics data',
                'max_supply': max_supply, 'circ_supply': circ_supply, 'total_supply': total_supply}

    def _hype_score(self, cg: dict) -> dict:
        score = 50
        details = []

        pc24 = cg.get('price_change_percentage_24h')
        pc7 = cg.get('price_change_percentage_7d')

        if pc24 is not None and abs(pc24) > 15:
            if pc24 > 0:
                score += 20; details.append(f'24h pump {pc24:.1f}% (+20)')
            else:
                score += 10; details.append(f'24h dump {pc24:.1f}% — potential bounce (+10)')

        if pc7 is not None and abs(pc7) > 50:
            if pc7 > 0:
                score -= 20; details.append('7d pump > 50% — hype risk (-20)')
            else:
                score += 10; details.append('7d dump > 50% — oversold (+10)')

        if cg.get('market_cap_rank') and cg['market_cap_rank'] <= 10:
            score += 10; details.append(f'Top 10 coin — mainstream adoption (+10)')
        elif cg.get('coingecko_score'):
            cg_score = cg.get('coingecko_score')
            details.append(f'CG score: {cg_score}')

        return {'score': max(0, min(100, score)), 'details': ' | '.join(details) if details else 'No hype signals detected'}

    def _fundamentals_score(self, cg: dict) -> dict:
        score = 50
        details = []

        mcap = cg.get('market_cap')
        if mcap:
            if mcap > 10e9:
                score += 20; details.append(f'MCap ${mcap/1e9:.1f}B — institutional grade (+20)')
            elif mcap > 1e9:
                score += 10; details.append(f'MCap ${mcap/1e9:.1f}B — established (+10)')
            elif mcap > 100e6:
                details.append(f'MCap ${mcap/1e6:.1f}M — small cap')

        rank = cg.get('market_cap_rank')
        if rank and rank <= 20:
            score += 15; details.append(f'Rank #{rank} — top 20 (+15)')
        elif rank and rank <= 50:
            score += 5; details.append(f'Rank #{rank} — top 50 (+5)')

        return {'score': min(100, score), 'details': ' | '.join(details) if details else 'Limited fundamental data',
                'mcap': mcap, 'rank': rank}

    # ── CoinGecko API ─────────────────────────────────────────

    @staticmethod
    def _coingecko_data(coin_id: str, vs_currency: str = 'usd',
                        max_age_minutes: int = 15) -> Optional[dict]:
        """Fetch coin data from CoinGecko with simple in-memory cache."""
        try:
            r = requests.get(
                f'{COINGECKO_BASE}/coins/{coin_id}',
                params={
                    'localization': 'false',
                    'tickers': 'false',
                    'community_data': 'false',
                    'developer_data': 'false',
                    'sparkline': 'false',
                },
                timeout=10,
            )
            if r.status_code != 200:
                return None
            data = r.json()
            md = data.get('market_data', {})
            return {
                'name': data.get('name', coin_id),
                'symbol': data.get('symbol', '').upper(),
                'current_price': md.get('current_price', {}).get(vs_currency),
                'market_cap': md.get('market_cap', {}).get(vs_currency),
                'market_cap_rank': data.get('market_cap_rank'),
                'total_volume': md.get('total_volume', {}).get(vs_currency),
                'high_24h': md.get('high_24h', {}).get(vs_currency),
                'low_24h': md.get('low_24h', {}).get(vs_currency),
                'price_change_percentage_24h': md.get('price_change_percentage_24h'),
                'price_change_percentage_7d': md.get('price_change_percentage_7d_in_currency', {}).get(vs_currency),
                'price_change_percentage_30d': md.get('price_change_percentage_30d_in_currency', {}).get(vs_currency),
                'ath': md.get('ath', {}).get(vs_currency),
                'ath_date': md.get('ath_date', {}).get(vs_currency),
                'max_supply': md.get('max_supply'),
                'circulating_supply': md.get('circulating_supply'),
                'total_supply': md.get('total_supply'),
            }
        except (requests.RequestException, ValueError, KeyError):
            return None

    @staticmethod
    def search_coin(query: str) -> list[dict]:
        """Search for coins by name/symbol."""
        try:
            r = requests.get(f'{COINGECKO_BASE}/search', params={'query': query}, timeout=10)
            if r.status_code != 200:
                return []
            coins = r.json().get('coins', [])
            return [{'id': c['id'], 'name': c['name'], 'symbol': c['symbol'].upper(),
                     'market_cap_rank': c.get('market_cap_rank'),
                     'thumb': c.get('thumb', '')} for c in coins[:10]]
        except (requests.RequestException, ValueError):
            return []

    @staticmethod
    def list_top_coins(limit: int = 50) -> list[dict]:
        """List top coins by market cap."""
        try:
            r = requests.get(
                f'{COINGECKO_BASE}/coins/markets',
                params={'vs_currency': 'usd', 'order': 'market_cap_desc',
                        'per_page': min(limit, 250), 'page': 1,
                        'sparkline': 'false'},
                timeout=15,
            )
            if r.status_code != 200:
                return []
            return [{'id': c['id'], 'name': c['name'], 'symbol': c['symbol'].upper(),
                     'current_price': c['current_price'],
                     'market_cap_rank': c['market_cap_rank'],
                     'price_change_percentage_24h': c.get('price_change_percentage_24h'),
                     'total_volume': c.get('total_volume')} for c in r.json()]
        except (requests.RequestException, ValueError):
            return []
