"""Modulo AI Provider per la selezione dinamica del modello Gemini e Ollama."""
from typing import Optional, List, Any, Union, Iterator
import os
import time
import random
import re
import ollama
import requests
from bs4 import BeautifulSoup

from google import genai
from google.genai import types
from google.api_core.exceptions import (
    ResourceExhausted, ServiceUnavailable, NotFound, InvalidArgument, InternalServerError
)

# Tentativo di importazione sicura per Ollama e PyMuPDF (fitz)
try:
    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False
    
try:
    import fitz  # PyMuPDF
    import io
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    fitz = None

class OllamaWrapper:
    """Wrapper per chiamate a modelli locali via Ollama."""
    def __init__(self, model_name: str, json_mode: bool = False):
        self.model_name = model_name
        self.json_mode = json_mode

    def _process_multimodal_input(self, prompt: Any) -> tuple[str, list]:
        """
        Estrae testo e immagini dal prompt multimodale.
        Converte PDF in testo usando PyMuPDF per maggiore robustezza.
        """
        final_text_parts = []
        images = []
        
        print(f"🤖 Ollama Pre-processing: Analizzando input per {self.model_name}...")
        
        if isinstance(prompt, list):
            for i, part in enumerate(prompt):
                if isinstance(part, str):
                    final_text_parts.append(part)
                elif isinstance(part, dict) and 'mime_type' in part and 'data' in part:
                    mime = part['mime_type']
                    data = part['data']
                    size_kb = len(data) / 1024
                    
                    print(f"   -> Part {i}: Rilevato {mime} ({size_kb:.1f} KB)")
                    
                    if mime == 'application/pdf':
                        # PDF Text Extraction Handling with PyMuPDF
                        if PYMUPDF_AVAILABLE:
                            try:
                                print("      -> Avvio estrazione PDF con PyMuPDF...")
                                doc = fitz.open(stream=data, filetype="pdf")
                                text_content = []
                                for page_num, page in enumerate(doc):
                                    page_text = page.get_text()
                                    if page_text.strip():
                                        text_content.append(page_text)
                                    print(f"         Pagina {page_num+1}: {len(page_text)} caratteri estratti.")
                                
                                extracted = "\n".join(text_content)
                                if extracted.strip():
                                    final_text_parts.append(f"\n--- INIZIO CONTENUTO PDF ---\n{extracted}\n--- FINE CONTENUTO PDF ---\n")
                                    print("      ✅ Estrazione completata con successo.")
                                else:
                                    print("      ⚠️ WARNING: Il PDF sembra vuoto o contiene solo immagini (no OCR).")
                            except Exception as e:
                                print(f"      ❌ Errore critico lettura PDF: {e}")
                        else:
                            print("      ❌ PyMuPDF non installato! Impossibile leggere PDF.")
                    elif mime.startswith('image/'):
                        images.append(data)
                        print("      -> Immagine aggiunta al payload.")
                    else:
                        print(f"      ⚠️ MIME type {mime} non supportato, ignorato.")
        else:
            final_text_parts.append(str(prompt))
            
        full_text = "\n".join(final_text_parts)
        print(f"📝 Prompt finale: {len(full_text)} caratteri, {len(images)} immagini.")
        return full_text, images

    def generate_content(self, prompt: Any):
        """Esegue la chiamata a Ollama."""
        try:
            prompt_text, images = self._process_multimodal_input(prompt)
            
            # Opzioni per forzare l'uso della GPU e Context Size adeguato
            options = {
                'num_gpu': 999,
                'num_ctx': 4096, # Ridotto per stabilità su GPU integrate
                'temperature': 0.0 # Bassa temperatura per estrazione dati
            }
            format_param = 'json' if self.json_mode else None
            
            # Parametri chiamata
            kwargs = {
                'model': self.model_name,
                'messages': [{'role': 'user', 'content': prompt_text}],
                'format': format_param,
                'options': options,
                'stream': True # Usiamo stream interna per debug
            }
            
            if images:
                # Aggiungi immagini al messaggio utente
                kwargs['messages'][0]['images'] = images

            print(f"⏳ Ollama: Invio richiesta a {self.model_name} (Ctx: 4096, Temp: 0)...")
            start_t = time.time()
            
            full_response = ""
            stream = ollama.chat(**kwargs)
            
            print("   Receiving: ", end="", flush=True)
            for chunk in stream:
                part = chunk.get('message', {}).get('content', '')
                full_response += part
                print(".", end="", flush=True) # Feedback visivo
            print(" Done.")
            
            duration = time.time() - start_t
            print(f"✅ Ollama: Risposta ricevuta in {duration:.2f}s. Lunghezza: {len(full_response)} chars.")
            
            class Response:
                """Response wrapper per uniformità."""
                text = full_response
            
            return Response()
            
        except Exception as e: # pylint: disable=broad-exception-caught
            print(f"❌ Errore Ollama ({self.model_name}): {e}")
            raise e

    def generate_stream(self, prompt: Any):
        """Esegue la chiamata a Ollama in streaming."""
        try:
            prompt_text, images = self._process_multimodal_input(prompt)
            options = {'num_gpu': 999}
            
            kwargs = {
                'model': self.model_name,
                'messages': [{'role': 'user', 'content': prompt_text}],
                'stream': True,
                'options': options
            }
            
            if images:
                kwargs['messages'][0]['images'] = images
            
            stream = ollama.chat(**kwargs)
            
            for chunk in stream:
                content = chunk.get('message', {}).get('content', '')
                if content:
                    yield content
                    
        except Exception as e:
            yield f"❌ Errore Ollama Stream: {e}"

class GeminiWrapper:
    """Wrapper per Google Gemini con gestione retry e backoff (Google GenAI SDK v1)."""
    def __init__(self, provider, json_mode: bool):
        self.provider = provider
        self.json_mode = json_mode
        self.client = genai.Client(api_key=self.provider.api_key)

    def _prepare_contents(self, prompt: Any) -> list:
        """Prepara il contenuto per la nuova API."""
        contents = []
        if isinstance(prompt, str):
            contents.append(prompt)
        elif isinstance(prompt, list):
            for part in prompt:
                if isinstance(part, str):
                    contents.append(part)
                elif isinstance(part, dict) and 'mime_type' in part and 'data' in part:
                    # Handle raw bytes input (custom standard used in this project)
                    contents.append(types.Part.from_bytes(
                        data=part['data'],
                        mime_type=part['mime_type']
                    ))
                else:
                    # Fallback string
                    contents.append(str(part))
        return contents

    def generate_content(self, prompt):
        """Genera contenuto con Exponential Backoff."""
        max_retries = 5
        base_delay = 2
        last_error = None
        
        # Config
        config = types.GenerateContentConfig(
            response_mime_type="application/json" if self.json_mode else "text/plain"
        )
        
        contents = self._prepare_contents(prompt)

        for attempt in range(max_retries):
            try:
                start_time = time.time()
                
                response = self.client.models.generate_content(
                    model=self.provider.current_model_name,
                    contents=contents,
                    config=config
                )
                
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
                    pass # Retry with new model
            except (ServiceUnavailable, InternalServerError) as e:
                last_error = e
                time.sleep(5)
            except (NotFound, InvalidArgument) as e:
                last_error = e
                self.provider.log_debug(f"❌ Errore Modello {e}. Switching...")
                if self.provider.downgrade_model():
                    pass
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
            contents = self._prepare_contents(prompt)
            response = self.client.models.generate_content_stream(
                model=self.provider.current_model_name,
                contents=contents
            )
            for chunk in response:
                yield chunk.text
        except Exception as e:
            yield f"❌ Errore Gemini Stream: {e}"

class AIProvider:
    """Factory per modelli AI (Cloud/Local) con Caching."""
    
    DOCS_URL = "https://ai.google.dev/gemini-api/docs/models?hl=it"
    # Fallback solidi per Gemini: Rimosso 2.0-flash per instabilità (429 errors)
    FALLBACK_ORDER = ["gemini-3-pro-preview", "gemini-3-flash-preview", "gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro","gemini-2.0-flash-exp", "gemini-1.5-flash", "gemini-1.5-flash-8b", "gemini-1.5-pro"]
    
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
            
            # genai.configure NOT needed for Client
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
            # Simple regex to catch model names from text, fallback logic applies otherwise
            candidates = set(re.findall(r"(gemini-[a-zA-Z0-9\-\.]+)", text))
            valid = [m for m in candidates if "vision" not in m and "audio" not in m and "tts" not in m]
            # Prioritizza quelli con 'flash' o 'pro'
            return sorted(valid, reverse=True)
        except Exception: # pylint: disable=broad-exception-caught
            return []
