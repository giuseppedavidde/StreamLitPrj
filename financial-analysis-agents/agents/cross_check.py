"""Modulo verifica web."""
import json
import datetime
from typing import Dict, Any, List, Optional, Callable
from ddgs import DDGS # type: ignore
from .ai_provider import AIProvider
from .finviz import FinvizAgent

class CrossCheckAgent:
    """Verifica dati sospetti sul web."""
    def __init__(self, api_key: Optional[str] = None, provider: str = "gemini", model: Optional[str] = None):
        self.provider = AIProvider(api_key, provider, model)
        self.model = self.provider.get_model(json_mode=True)
        self.finviz = FinvizAgent()

    
    
    def cross_check_fields(self, ticker: str, original_data: Dict[str, Any], fields: List[str], callback: Optional[Callable[[str], None]] = None, external_finviz_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Verifica i campi sospetti usando Finviz + Web Search."""
        if not fields: return {}
        
        # 1. Recupero Dati Strutturati da Finviz (Usa esterno se fornito)
        finviz_data = external_finviz_data if external_finviz_data is not None else (self.finviz.get_fundamental_data(ticker) or {})
        
        if callback and finviz_data:
            callback(f"🌐 Finviz Data: {json.dumps(finviz_data, indent=2)}")
        
        # 2. Web Search di supporto (DDGS)
        q = f"{ticker} long term debt net income {datetime.date.today().year} financial results"
        web_context = ""
        try:
            web_res = list(DDGS().text(keywords=q, max_results=2)) # pyright: ignore
            web_context = "\n".join([r['body'] for r in web_res])
        except Exception: # pylint: disable=broad-exception-caught
            web_context = "Web search failed."

        prompt = f"""
        TASK: Verifying financial data for {ticker}.
        
        ORIGINAL EXTRACTED DATA:
        {json.dumps({k: original_data.get(k) for k in fields}, indent=2)}
        
        🏆 GOLDEN SOURCE (FINVIZ):
        {json.dumps(finviz_data, indent=2)}
        
        WEB SNIPPETS (Context):
        {web_context}
        
        INSTRUCTIONS:
        1. FINVIZ IS THE GOLDEN SOURCE. IT IS ALWAYS RIGHT.
        2. IF Finviz has a value for a requested field, YOU MUST OVERWRITE the specific original value with the Finviz value.
        3. MAPPING GUIDE:
           - 'sales' -> matches Finviz 'Sales'
           - 'net_income' -> matches Finviz 'Income'
           - 'shares_outstanding' -> matches Finviz 'Shs Outstand'
           - 'current_market_price' -> matches Finviz 'Price'
           - 'dividend_yield' -> matches Finviz 'Dividend %'
        4. If a field is NOT in Finviz, use Web Snippets to check validity.
        5. OUTPUT JSON MUST CONTAIN ONLY THE CORRECTED FIELDS.
        
        OUTPUT JSON: {{ "field_name": corrected_value_float }}
        """
        
        try:
            resp = self.model.generate_content(prompt)
            data = json.loads(resp.text)
            
            # Logging di debug per vedere cosa ha corretto
            if data:
                print(f"✅ Cross-Check ha corretto: {data.keys()}")
            
            return data
        except Exception as e: # pylint: disable=broad-exception-caught
            print(f"⚠️ Cross Check Error: {e}")
            return {}