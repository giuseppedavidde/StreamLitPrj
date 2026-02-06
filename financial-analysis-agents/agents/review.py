"""Modulo audit dati."""
import json
import dataclasses        
from typing import Tuple, List, Optional
from .ai_provider import AIProvider

class ReviewAgent:
    """Auditor dei dati estratti."""
    def __init__(self, api_key: Optional[str] = None, provider: str = "gemini", model: Optional[str] = None):
        self.provider = AIProvider(api_key, provider, model)
        self.model = self.provider.get_model(json_mode=True)

    def audit_data(self, ticker: str, data) -> Tuple[str, List[str]]:
        """Controlla anomalie nei dati estratti."""
        # Minificazione dati per prompt
        d = dataclasses.asdict(data)
        mini_data = {k: d[k] for k in ['long_term_debt', 'net_income', 'interest_charges', 'total_assets'] if k in d}
        
        prompt = f"""
        ROLE: Auditor.
        TASK: Check for anomalies in extracted data for {ticker}.
        RULES:
        1. If 'long_term_debt' > 0 but 'interest_charges' is 0 -> Flag 'interest_charges'.
        2. If 'long_term_debt' seems huge (> 50% assets) for a tech/retail firm -> Flag 'long_term_debt'.
        3. If 'net_income' mismatch with recent trends -> Flag 'net_income'.
        
        DATA: {json.dumps(mini_data)}
        
        OUTPUT JSON: {{ "report": "Short comment", "suspicious_fields": ["field1", ...] }}
        """
        try:
            resp = self.model.generate_content(prompt)
            res = json.loads(resp.text)
            return res.get("report", "OK"), res.get("suspicious_fields", [])
        except Exception: # pylint: disable=broad-exception-caught
            return "Errore Audit", []