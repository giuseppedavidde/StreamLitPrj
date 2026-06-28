"""WallStreetBets pump detection via Reddit public JSON (no API key).

Scores hype on 5 dimensions, detects FOMO phase (Early/Mid/Late/Exit),
and feeds qualified candidates for full entry evaluation.
"""

import re
import time
from datetime import datetime, timezone
from typing import Optional

import requests

from agents.market_data_agent import MarketDataAgent


WSB_URLS = {
    'hot':   'https://www.reddit.com/r/wallstreetbets/hot.json?limit=100',
    'new':   'https://www.reddit.com/r/wallstreetbets/new.json?limit=100',
    'top':   'https://www.reddit.com/r/wallstreetbets/top.json?limit=100&t=day',
}

BLACKLIST = {'AUTO', 'YOLO', 'WSB', 'DD', 'MOON', 'HODL', 'FOMO', 'ROPE',
             'ETF', 'IPO', 'CEO', 'CFO', 'SEC', 'FDA', 'IRS', 'USA', 'UK',
             'AI', 'IT', 'OK', 'GO', 'NO', 'UP', 'DOWN', 'BIG', 'HOT', 'NEW',
             'BUY', 'SELL', 'HOLD', 'FREE', 'LOSS', 'GAIN', 'CASH', 'DEBT',
             'THE', 'AND', 'FOR', 'ARE', 'NOT', 'ALL', 'ANY', 'HOW', 'WHY',
             'ONE', 'TWO', 'NOW', 'LOL', 'WTF', 'FUK', 'ASS', 'GAY',
             'GME', 'AMC', 'BB', 'PLTR',  # historically known tickers — not excluded
             }

TICKER_PATTERN = re.compile(r'\$([A-Z]{1,5})(?:\b|(?=[^A-Za-z]))')
ALLCAPS_PATTERN = re.compile(r'\b([A-Z]{2,5})\b')

FOMO_THRESHOLDS = {
    'early': {'hype_max': 20, 'posts_max': 5},
    'mid':   {'hype_max': 60, 'posts_max': 20},
    'late':  {'hype_max': 85, 'posts_max': 50},
    'exit':  {'hype_min': 85},
}


class WSBAgent:
    """WSB pump detection — fetch Reddit posts, extract tickers, score hype."""

    def __init__(self):
        self.mda = MarketDataAgent()
        self._user_agent = 'MarketAnalyzer/1.0'

    def scan(self, limit: int = 15) -> list[dict]:
        """Full WSB scan: fetch → extract → score → rank."""
        posts = self._fetch_posts()
        raw = self._extract_tickers(posts)
        scored = [self._score_ticker(t, posts) for t in raw]
        scored = [s for s in scored if s is not None]
        scored.sort(key=lambda r: r['hype_score'], reverse=True)
        return scored[:limit]

    def analyze_ticker(self, ticker: str, posts: Optional[list[dict]] = None) -> Optional[dict]:
        """Score a specific ticker's WSB presence."""
        if posts is None:
            posts = self._fetch_posts()
        raw_posts = self._extract_ticker_posts(ticker, posts)
        if not raw_posts:
            return None
        return self._score_single(ticker.upper(), raw_posts, posts)

    # ── Private ──────────────────────────────────────────────

    def _fetch_posts(self) -> list[dict]:
        posts = []
        for label, url in WSB_URLS.items():
            try:
                r = requests.get(url, headers={'User-Agent': self._user_agent}, timeout=15)
                if r.status_code == 200:
                    data = r.json()
                    for child in data.get('data', {}).get('children', []):
                        c = child.get('data', {})
                        posts.append({
                            'id': c.get('id'),
                            'title': c.get('title', ''),
                            'selftext': (c.get('selftext') or '')[:500],
                            'score': c.get('score', 0),
                            'upvote_ratio': c.get('upvote_ratio', 0.5),
                            'num_comments': c.get('num_comments', 0),
                            'flair': c.get('link_flair_text', ''),
                            'created_utc': c.get('created_utc', 0),
                            'author': c.get('author', ''),
                            'permalink': c.get('permalink', ''),
                            'source': label,
                        })
                time.sleep(0.3)
            except (requests.RequestException, ValueError, KeyError):
                continue
        return posts

    def _extract_tickers(self, posts: list[dict]) -> dict:
        ticker_posts = {}
        for post in posts:
            text = f"{post['title']} {post['selftext']}"
            candidates = set()
            for m in TICKER_PATTERN.finditer(text):
                candidates.add(m.group(1))
            for m in ALLCAPS_PATTERN.finditer(text):
                word = m.group(1)
                if word not in BLACKLIST:
                    candidates.add(word)
            for ticker in candidates:
                raw_posts = ticker_posts.setdefault(ticker, [])
                raw_posts.append(post)
        return ticker_posts

    def _extract_ticker_posts(self, ticker: str, posts: list[dict]) -> list[dict]:
        target = ticker.upper()
        matching = []
        for post in posts:
            text = f"{post['title']} {post['selftext']}"
            if target in text.upper():
                matching.append(post)
        return matching

    def _score_ticker(self, ticker: str, all_posts: list[dict]) -> Optional[dict]:
        ticker_posts = self._extract_ticker_posts(ticker, all_posts)
        if not ticker_posts:
            return None
        return self._score_single(ticker, ticker_posts, all_posts)

    def _score_single(self, ticker: str, ticker_posts: list[dict], all_posts: list[dict]) -> dict:
        info = {}
        try:
            info = self.mda.get_info(ticker)
        except Exception:
            pass

        n_posts = len(ticker_posts)
        total_comments = sum(p['num_comments'] for p in ticker_posts)
        total_score = sum(p['score'] for p in ticker_posts)
        avg_upr = sum(p['upvote_ratio'] for p in ticker_posts) / max(n_posts, 1)

        # Dimension 1: Mention Volume (25%)
        mention_vol = min(n_posts * 10 + total_comments / 20, 100)

        # Dimension 2: Engagement (20%)
        engagement = avg_upr * 80 + min(total_score / max(n_posts, 1) / 10, 20)

        # Dimension 3: Sentiment Polarity (15%)
        bullish_count = sum(1 for p in ticker_posts
                            if any(w in p['title'].lower() for w in
                                   ['🚀', 'moon', 'tendies', 'calls', 'yolo', 'rip', 'squeeze', 'rocket', 'breakout']))
        bearish_count = sum(1 for p in ticker_posts
                            if any(w in p['title'].lower() for w in
                                   ['rug', 'dump', 'baghold', 'short', 'dead', 'rugpull', 'exit']))
        total_sent = bullish_count + bearish_count
        if total_sent > 0:
            sentiment = (bullish_count / total_sent) * 100
        else:
            sentiment = 50

        # Dimension 4: Post Authority (15%)
        dd_count = sum(1 for p in ticker_posts if p.get('flair', '') in ('DD', 'Technical Analysis'))
        meme_count = sum(1 for p in ticker_posts if p.get('flair', '') in ('Meme', 'Shitpost'))
        dd_ratio = dd_count / max(n_posts, 1)
        meme_ratio = meme_count / max(n_posts, 1)
        post_authority = dd_ratio * 60 + (1 - meme_ratio) * 40

        # Dimension 5: Squeeze Setup (25%)
        si = info.get('shortPercentOfFloat', 0) or 0
        borrow = info.get('shortRatio', 0) or 0
        squeeze = min(si * 200, 50) + min(borrow * 10, 30) + min((info.get('shortRatio', 0) or 0) * 5, 20)

        # Aggregate
        hype_score = (
            mention_vol * 0.25 + engagement * 0.20 +
            sentiment * 0.15 + post_authority * 0.15 + squeeze * 0.25
        )

        fomo_phase = self._detect_fomo(hype_score, n_posts)

        price = self.mda.get_price(ticker)
        hist = self.mda.get_history(ticker, '1mo')
        price_change_7d = 0
        price_change_30d = 0
        if not hist.empty:
            if len(hist) >= 7:
                price_change_7d = (float(hist['Close'].iloc[-1]) / float(hist['Close'].iloc[-7]) - 1) * 100
            if len(hist) >= 30:
                price_change_30d = (float(hist['Close'].iloc[-1]) / float(hist['Close'].iloc[0]) - 1) * 100

        return {
            'ticker': ticker,
            'name': info.get('longName', info.get('shortName', ticker)),
            'price': price,
            'hype_score': round(hype_score, 1),
            'dimensions': {
                'mention_volume': round(mention_vol, 1),
                'engagement': round(engagement, 1),
                'sentiment': round(sentiment, 1),
                'post_authority': round(post_authority, 1),
                'squeeze_setup': round(squeeze, 1),
            },
            'fomo_phase': fomo_phase,
            'posts_24h': n_posts,
            'avg_score': round(total_score / max(n_posts, 1), 1),
            'avg_upvote': round(avg_upr * 100, 1),
            'price_change_7d': round(price_change_7d, 1),
            'price_change_30d': round(price_change_30d, 1),
            'short_interest': round(si * 100, 1) if si else None,
            'days_to_cover': round(borrow, 2) if borrow else None,
        }

    @staticmethod
    def _detect_fomo(hype_score: float, n_posts: int) -> str:
        if hype_score >= FOMO_THRESHOLDS['exit']['hype_min']:
            return 'Exit'
        if hype_score >= FOMO_THRESHOLDS['late']['hype_max'] or n_posts >= FOMO_THRESHOLDS['late']['posts_max']:
            return 'Late'
        if hype_score >= FOMO_THRESHOLDS['mid']['hype_max'] or n_posts >= FOMO_THRESHOLDS['mid']['posts_max']:
            return 'Mid'
        return 'Early'
