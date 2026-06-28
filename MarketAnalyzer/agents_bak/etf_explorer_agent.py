"""ETF Explorer — two modes:

Mode 1: Given an ETF ticker, find undervalued holdings inside it.
Mode 2: Scan the ETF universe for the best opportunity across ETFs.
"""

import pandas as pd
from agents.market_data_agent import MarketDataAgent
from agents.scanner_agent import ScannerAgent


ETF_UNIVERSE = {
    'SPY': 'S&P 500',
    'QQQ': 'NASDAQ 100',
    'IGV': 'Software ETF',
    'XLK': 'Technology Sector',
    'XLV': 'Healthcare Sector',
    'XLF': 'Financial Sector',
    'XLE': 'Energy Sector',
    'XLI': 'Industrials Sector',
    'XLU': 'Utilities Sector',
    'XLP': 'Consumer Staples',
    'XLY': 'Consumer Discretionary',
    'XLB': 'Materials Sector',
    'XLRE': 'Real Estate',
    'SMH': 'Semiconductor ETF',
    'ARKK': 'ARK Innovation',
    'VTI': 'Total US Market',
    'VWO': 'Emerging Markets',
    'EFA': 'Developed ex-US',
    'IWM': 'Russell 2000',
    'TLT': 'Long-Term Treasury',
}


class ETFExplorerAgent:
    """Dual-mode ETF analysis."""

    def __init__(self):
        self.mda = MarketDataAgent()
        self.scanner = ScannerAgent()

    def mode1_find_undervalued(self, etf_ticker: str, top_n: int = 10, min_weight: float = 0.5) -> list[dict]:
        """Mode 1: ETF → scan holdings → rank by scanner score."""
        holdings = self.mda.get_top_holdings(etf_ticker, 50)
        if holdings.empty:
            return []

        holdings = holdings[holdings['Weight'] >= min_weight]
        results = []
        for _, row in holdings.iterrows():
            sym = row['Symbol']
            if not sym or len(sym) > 5:
                continue
            scan = self.scanner.scan(sym)
            if 'error' not in scan:
                scan['etf_weight'] = round(row['Weight'], 2)
                results.append(scan)

        results.sort(key=lambda r: r['final_score'], reverse=True)
        return results[:top_n]

    def mode2_scan_universe(self, top_n: int = 5, min_weight: float = 0.5,
                            min_holdings_score: float = 50) -> list[dict]:
        """Mode 2: Scan entire ETF universe → rank by avg score of top holdings."""
        etf_results = []
        for etf_ticker, etf_name in ETF_UNIVERSE.items():
            try:
                holdings = self.mda.get_top_holdings(etf_ticker, 20)
                if holdings.empty:
                    continue
                holdings = holdings[holdings['Weight'] >= min_weight]
                if holdings.empty:
                    continue

                scores = []
                for _, row in holdings.head(10).iterrows():
                    sym = row['Symbol']
                    if not sym or len(sym) > 5:
                        continue
                    scan = self.scanner.scan(sym)
                    if 'error' not in scan:
                        scores.append(scan['final_score'])

                if not scores:
                    continue
                avg_score = sum(scores) / len(scores)
                if avg_score >= min_holdings_score:
                    etf_results.append({
                        'etf_ticker': etf_ticker,
                        'etf_name': etf_name,
                        'avg_score': round(avg_score, 1),
                        'holdings_scanned': len(scores),
                        'top_holdings_scores': scores[:5],
                    })
            except Exception:
                continue

        etf_results.sort(key=lambda r: r['avg_score'], reverse=True)
        return etf_results[:top_n]

    def get_etf_sector_exposure(self, etf_ticker: str) -> dict:
        """Returns sector weightings for an ETF for visualisation."""
        return self.mda.get_sector_weightings(etf_ticker)

    def get_etf_holdings_table(self, etf_ticker: str, n: int = 15) -> pd.DataFrame:
        """Returns DataFrame of top holdings."""
        return self.mda.get_top_holdings(etf_ticker, n)

    def list_universe(self) -> dict:
        """Returns {ticker: name} for all known ETFs."""
        return dict(ETF_UNIVERSE)
