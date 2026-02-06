"""Modulo riassunto narrativo."""
from typing import Optional
from .ai_provider import AIProvider

class SummaryAgent:
    """Genera riassunti finanziari."""
    def __init__(self, api_key: Optional[str] = None, provider: str = "gemini", model: str = ""):    
        # Passiamo i parametri all'AIProvider
        self.provider = AIProvider(
            api_key=api_key, 
            provider_type=provider, 
            model_name=model
        )
        self.model = self.provider.get_model(json_mode=False)

    def summarize_dossier(self, raw_text: str) -> str:
        """Genera un riassunto narrativo dai dati finanziari."""
        # PROMPT COMPRESSO
        prompt = f"""
        TASK: Write a short financial summary (max 150 words) for this company.
        FOCUS:
        1. Recent trend (Revenue/Net Income TTM vs historical).
        2. Financial health (Debt load).
        3. Main business risks/opportunities.
        STYLE: Professional, concise, Italian language.
        
        DATA:
        {raw_text}
        """
        try:
            resp = self.model.generate_content(prompt)
            return resp.text
        except Exception: # pylint: disable=broad-exception-caught
            return "Riassunto non disponibile."