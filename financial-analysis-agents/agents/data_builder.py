"""Modulo estrazione dati finanziari."""
import json
import os
from typing import Optional, Dict, Any
from .ai_provider import AIProvider

class DataBuilderAgent:
    """Estrae JSON dai dati grezzi."""
    def __init__(self, api_key: Optional[str] = None, provider: str = "gemini", model: Optional[str] = None):
        self.provider = AIProvider(api_key, provider, model)
        self.model = self.provider.get_model(json_mode=True)

    def build_from_text(self, raw_text: str) -> Optional[Dict[str, Any]]:
        """Estrae dati strutturati."""
        # PROMPT COMPRESSO: Solo istruzioni essenziali
        prompt = f"""
        ROLE: Financial Data Extractor.
        TASK: Extract JSON from the provided text data.
        OUTPUT SCHEMA:
        {{
            "total_assets": float, "current_assets": float, "current_liabilities": float,
            "inventory": float, "intangible_assets": float, "total_liabilities": float,
            "long_term_debt": float, "capital_lease_obligations": float,
            "preferred_stock": float, "common_stock": float, "surplus": float,
            "sales": float, "operating_income": float, "net_income": float,
            "interest_charges": float, "preferred_dividends": float,
            "shares_outstanding": float, "current_market_price": float,
            "eps_3y_avg": float, "earnings_growth_10y": bool, "dividend_history_20y": bool
        }}
        RULES:
        1. 'long_term_debt': ONLY FINANCIAL DEBT (Bonds, Notes, Bank Loans). EXCLUDE Leases (Operating/Finance) and Trade Payables.
        2. 'capital_lease_obligations': Extract Operating and Finance Lease Liabilities here. If missing, 0.0.
        3. 'interest_charges': Absolute value.
        3. Use provided TTM/MRQ values.
        4. If data missing, use 0.0 or best estimate.
        
        DATA:
        {raw_text}
        """
        try:
            resp = self.model.generate_content(prompt)
            return json.loads(resp.text)
        except Exception as e: # pylint: disable=broad-exception-caught
            print(f"❌ DataBuilder Error: {e}")
            return None
    
    def save_to_json(self, data, filename):
        """Salva su file."""
        os.makedirs("data", exist_ok=True)
        with open(f"data/{filename}", 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)