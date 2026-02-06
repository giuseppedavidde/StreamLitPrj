"""Modulo ricerca ETF."""
import json
from typing import List, Dict, Any, Optional
import yfinance as yf
from .ai_provider import AIProvider

class ETFFinderAgent:
    """Trova ETF che detengono il titolo."""
    def __init__(self, api_key: Optional[str] = None, provider: str = "gemini", model: Optional[str] = None):
        self.provider = AIProvider(api_key, provider, model)
        self.model = self.provider.get_model(json_mode=True)

    def find_etfs_holding_ticker(self, ticker: str, sector: str = "") -> List[Dict[str, Any]]:
        """Trova ETF statunitensi che probabilmente detengono il titolo specificato."""
        # PROMPT COMPRESSO
        prompt = f"""
        TASK: List 3 major US ETFs likely holding {ticker} ({sector}).
        OUTPUT JSON: [{{ "ticker": "SPY", "estimated_weight": "High/Med/Low" }}]
        """
        try:
            resp = self.model.generate_content(prompt)
            data = json.loads(resp.text)
            
            results = []
            for item in data[:3]: # Limitiamo a 3 per velocità
                t = item.get("ticker")
                if t:
                    try:
                        info = yf.Ticker(t).info
                        results.append({
                            "etf_ticker": t,
                            "etf_name": info.get("shortName", t),
                            "weight_percentage": item.get("estimated_weight")
                        })
                    except Exception: # pylint: disable=broad-exception-caught
                        continue
            return results
        except Exception: # pylint: disable=broad-exception-caught
            return []