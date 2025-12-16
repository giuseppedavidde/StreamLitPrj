"""Modulo AI Provider per la selezione dinamica del modello Gemini e Ollama."""
from typing import Optional, List, Any
import os
import time
import random
import re
import ollama
import requests
from bs4 import BeautifulSoup
import google.generativeai as genai
from google.api_core.exceptions import (
    ResourceExhausted, ServiceUnavailable, NotFound, InvalidArgument, InternalServerError
)

# Tentativo di importazione sicura per Ollama
try:
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

class OllamaWrapper:
    """Wrapper per chiamate a modelli locali via Ollama."""
    def __init__(self, model_name: str, json_mode: bool = False):
        self.model_name = model_name
        self.json_mode = json_mode

    def generate_content(self, prompt: str):
        """Esegue la chiamata a Ollama."""
        try:
            # Opzioni per forzare l'uso della GPU
            options = {
                'num_gpu': 999  # Forza l'offset di tutti i layer sulla GPU
            }
            format_param = 'json' if self.json_mode else None
            
            # Simuliamo la struttura di risposta di Gemini
            response = ollama.chat(
                model=self.model_name,
                messages=[{'role': 'user', 'content': prompt}],
                format=format_param,
                options=options
            )
            
            class Response:
                """Response wrapper per uniformità."""
                text = response.get('message', {}).get('content', '')
            
            return Response()
            
        except Exception as e: # pylint: disable=broad-exception-caught
            print(f"❌ Errore Ollama ({self.model_name}): {e}")
            raise e

    def generate_stream(self, prompt: str):
        """Esegue la chiamata a Ollama in streaming."""
        try:
            options = {'num_gpu': 999}
            
            stream = ollama.chat(
                model=self.model_name,
                messages=[{'role': 'user', 'content': prompt}],
                stream=True,
                options=options
            )
            
            for chunk in stream:
                content = chunk.get('message', {}).get('content', '')
                if content:
                    yield content
                    
        except Exception as e:
            yield f"❌ Errore Ollama Stream: {e}"

class GeminiWrapper:
    """Wrapper per Google Gemini con gestione retry e backoff."""
    def __init__(self, provider, json_mode: bool):
        self.provider = provider
        self.json_mode = json_mode
        self._refresh_model()

    def _refresh_model(self):
        config = None
        if self.json_mode:
            config = genai.types.GenerationConfig( # pyright: ignore[reportPrivateImportUsage]
                response_mime_type="application/json"
            )
        self.real_model = genai.GenerativeModel( # pyright: ignore[reportPrivateImportUsage]
            model_name=self.provider.current_model_name,
            generation_config=config
        )

    def generate_content(self, prompt):
        """Genera contenuto con Exponential Backoff."""
        max_retries = 5
        base_delay = 2
        last_error = None
        
        for attempt in range(max_retries):
            try:
                start_time = time.time()
                response = self.real_model.generate_content(prompt)
                
                # Logging Token Usage e Modello
                try:
                    usage = response.usage_metadata
                    input_tokens = usage.prompt_token_count
                    output_tokens = usage.candidates_token_count
                    total_tokens = usage.total_token_count
                    model_used = self.provider.current_model_name
                    
                    self.provider.log_debug(
                        f"🤖 GENAI CALL | Model: {model_used} | Tokens: {input_tokens} in + {output_tokens} out = {total_tokens} tot | Time: {time.time()-start_time:.2f}s"
                    )
                except Exception: # pylint: disable=broad-exception-caught
                    self.provider.log_debug(f"🤖 GENAI CALL | Model: {self.provider.current_model_name} | (Token info non avail)")

                return response
            except ResourceExhausted as e:
                last_error = e
                wait = (base_delay * (2 ** attempt)) + random.uniform(0, 1)
                self.provider.log_debug(f"⚠️ Quota 429. Attendo {wait:.1f}s...")
                time.sleep(wait)
                if attempt >= 2 and self.provider.downgrade_model():
                    self._refresh_model()
            except (ServiceUnavailable, InternalServerError) as e:
                last_error = e
                time.sleep(5)
            except (NotFound, InvalidArgument) as e:
                last_error = e
                self.provider.log_debug(f"❌ Errore Modello {e}. Switching...")
                if self.provider.downgrade_model():
                    self._refresh_model()
                else:
                    break
            except Exception as e: # pylint: disable=broad-exception-caught
                last_error = e
                self.provider.log_debug(f"❌ Errore: {e}")
                break

        raise RuntimeError(f"Impossibile generare contenuto Gemini. Last Error: {last_error}")

    def generate_stream(self, prompt):
        """Genera contenuto in streaming."""
        try:
            response = self.real_model.generate_content(prompt, stream=True)
            for chunk in response:
                yield chunk.text
        except Exception as e:
            yield f"❌ Errore Gemini Stream: {e}"

class AIProvider:
    """Factory per modelli AI (Cloud/Local) con Caching."""
    
    DOCS_URL = "https://ai.google.dev/gemini-api/docs/models?hl=it"
    # Fallback solidi per Gemini: Rimosso 2.0-flash per instabilità (429 errors)
    FALLBACK_ORDER = ["gemini-3-pro-preview", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro","gemini-2.0-flash-exp", "gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-1.5-pro"]
    
    _cached_chain: Optional[List[str]] = None
    _last_scrape_time: float = 0
    
    def __init__(self, api_key: Optional[str] = None, provider_type: str = "gemini", model_name: Optional[str] = None):
        """
        Inizializza il provider.
        IMPORTANTE: Configura immediatamente la catena o il modello in base al provider_type.
        """
        self.provider_type = provider_type.lower()
        self.target_model = model_name
        
        # Gestione API Key: Priorità a quella passata, poi Env
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        
        self.debug_mode = os.getenv("AI_DEBUG", "true").lower() == "true"
        
        # Variabili di stato
        self.current_model_index = 0
        self.current_model_name = ""
        self.available_models_chain: List[str] = []

        # --- LOGICA DI INIZIALIZZAZIONE DEL PROVIDER ---
        if self.provider_type == "gemini":
            if not self.api_key:
                # Non raisiamo errore subito per non bloccare UI se manca key
                print("⚠️ API Key mancante per Gemini. Impossibile inizializzare.")
                return 
            
            genai.configure(api_key=self.api_key) # pyright: ignore[reportPrivateImportUsage]
            self._init_gemini_chain()
        
        elif self.provider_type == "ollama":
            if not OLLAMA_AVAILABLE:
                raise ImportError("Libreria 'ollama' non installata. Esegui: pip install ollama")
            # Per Ollama non c'è una catena complessa, usiamo il modello target
            self.current_model_name = self.target_model or "llama3"
            self.log_debug(f"🤖 AI Provider impostato su Ollama: {self.current_model_name}")

    @staticmethod
    def get_ollama_models() -> List[str]:
        """Recupera la lista dei modelli locali installati su Ollama."""
        if not OLLAMA_AVAILABLE:
            return []
        try:
            # ollama.list() ritorna un dict con 'models'
            models_info = ollama.list() # pyright: ignore[reportUnboundVariable]
            return [m.get('model') or m.get('name') for m in models_info.get('models', [])]
        except Exception as e: # pylint: disable=broad-exception-caught
            print(f"⚠️ Errore listing Ollama: {e}")
            return []

    def log_debug(self, message: str):
        """Log di debug se abilitato."""
        if self.debug_mode: 
            print(message)

    def get_model(self, json_mode: bool = False) -> Any:
        """Restituisce l'istanza del modello AI richiesto."""
        if self.provider_type == "ollama":
            return OllamaWrapper(self.current_model_name, json_mode)
        return GeminiWrapper(self, json_mode)

    def _init_gemini_chain(self):
        """Inizializza la catena Gemini con priorità al modello richiesto."""
        # Se l'utente ha chiesto un modello specifico, lo mettiamo in cima
        if self.target_model:
            self.available_models_chain = [self.target_model] + self.FALLBACK_ORDER
        # Altrimenti usiamo la cache se valida
        elif AIProvider._cached_chain and (time.time() - AIProvider._last_scrape_time < 3600):
            self.available_models_chain = AIProvider._cached_chain
        # Altrimenti scraping
        else:
            self.available_models_chain = self._build_gemini_chain()
            if self.available_models_chain:
                AIProvider._cached_chain = self.available_models_chain
                AIProvider._last_scrape_time = time.time()
        
        # Fallback finale se tutto fallisce
        if not self.available_models_chain:
            self.available_models_chain = self.FALLBACK_ORDER
        
        self.current_model_index = 0
        self.current_model_name = self.available_models_chain[0]
        self.log_debug(f"🤖 AI Provider Gemini pronto. Modello: {self.current_model_name}")

    def downgrade_model(self) -> bool:
        """Passa al modello successivo nella catena di fallback."""
        if self.current_model_index + 1 < len(self.available_models_chain):
            self.current_model_index += 1
            self.current_model_name = self.available_models_chain[self.current_model_index]
            return True
        return False

    def _build_gemini_chain(self) -> List[str]:
        """Costruisce lista modelli via scraping."""
        try:
            response = requests.get(self.DOCS_URL, timeout=2)
            if response.status_code != 200: return []
            soup = BeautifulSoup(response.text, 'html.parser')
            text = soup.get_text()
            candidates = set(re.findall(r"(gemini-[a-zA-Z0-9\-\.]+)", text))
            valid = [m for m in candidates if "vision" not in m and "audio" not in m and "tts" not in m]
            # Prioritizza quelli con 'flash' o 'pro'
            return sorted(valid, reverse=True)
        except Exception: # pylint: disable=broad-exception-caught
            return []
