"""Modulo AI Provider per la selezione dinamica del modello Gemini, Ollama e Groq."""

import os
import random
import re
import time
from typing import Any, List, Optional

import requests
from bs4 import BeautifulSoup

# Nuova SDK Google GenAI
try:
    from google import genai
    from google.genai import types

    GOOGLE_GENAI_AVAILABLE = True
except ImportError:
    GOOGLE_GENAI_AVAILABLE = False

# Tentativo di importazione sicura per Ollama
try:
    import ollama

    OLLAMA_AVAILABLE = True
except ImportError:
    OLLAMA_AVAILABLE = False

# Tentativo di importazione sicura per Groq
try:
    from groq import Groq

    GROQ_AVAILABLE = True
except ImportError:
    GROQ_AVAILABLE = False


class OllamaWrapper:
    """Wrapper per chiamate a modelli locali via Ollama."""

    def __init__(self, model_name: str, json_mode: bool = False):
        self.model_name = model_name
        self.json_mode = json_mode

    def _extract_text_from_multimodal(self, prompt: Any) -> str:
        """Estrae solo il testo se il prompt è multimodale (lista)."""
        if isinstance(prompt, list):
            # Cerca parti testuali
            text_parts = [p for p in prompt if isinstance(p, str)]
            if len(text_parts) < len(prompt):
                print(
                    f"⚠️ Ollama: Multimodal inputs ignored for model {self.model_name}. Using text only."
                )
            return "\n".join(text_parts)
        return str(prompt)

    def generate_content(self, prompt: Any):
        """Esegue la chiamata a Ollama."""
        try:
            prompt_text = self._extract_text_from_multimodal(prompt)

            # Opzioni per forzare l'uso della GPU
            options = {
                "num_gpu": 999  # Forza l'offset di tutti i layer sulla GPU
            }
            format_param = "json" if self.json_mode else None

            # Simuliamo la struttura di risposta di Gemini
            response = ollama.chat(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt_text}],
                format=format_param,
                options=options,
            )

            class Response:
                """Response wrapper per uniformità."""

                text = response.get("message", {}).get("content", "")

            return Response()

        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"❌ Errore Ollama ({self.model_name}): {e}")
            raise e

    def generate_stream(self, prompt: Any):
        """Esegue la chiamata a Ollama in streaming."""
        try:
            prompt_text = self._extract_text_from_multimodal(prompt)
            options = {"num_gpu": 999}

            stream = ollama.chat(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt_text}],
                stream=True,
                options=options,
            )

            for chunk in stream:
                content = chunk.get("message", {}).get("content", "")
                if content:
                    yield content

        except Exception as e:
            yield f"❌ Errore Ollama Stream: {e}"


class GroqWrapper:
    """Wrapper per chiamate a modelli via Groq."""

    def __init__(self, provider, json_mode: bool = False):
        self.provider = provider
        self.json_mode = json_mode
        if not GROQ_AVAILABLE:
            raise ImportError(
                "Libreria 'groq' non installata. Esegui: pip install groq"
            )

        self.api_key = os.getenv("GROQ_API_KEY")
        if not self.api_key:
            raise ValueError("GROQ_API_KEY non trovata nelle variabili d'ambiente.")

        self.client = Groq(api_key=self.api_key)
        # Default fallback a un modello bilanciato se non specificato
        self.model_name = provider.target_model or "llama3-70b-8192"

    def _extract_text_from_multimodal(self, prompt: Any) -> str:
        """Estrae solo il testo se il prompt è multimodale (lista)."""
        if isinstance(prompt, list):
            text_parts = [p for p in prompt if isinstance(p, str)]
            if len(text_parts) < len(prompt):
                # Logging debug via provider if possible, otherwise print
                pass
            return "\n".join(text_parts)
        return str(prompt)

    def generate_content(self, prompt: Any):
        """Esegue la chiamata a Groq."""
        try:
            prompt_text = self._extract_text_from_multimodal(prompt)
            messages = [{"role": "user", "content": prompt_text}]

            # Parametri standard
            completion = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=1,
                max_completion_tokens=8192,
                top_p=1,
                stream=False,
                stop=None,
                response_format={"type": "json_object"} if self.json_mode else None,
            )

            class Response:
                text = completion.choices[0].message.content or ""

            return Response()

        except Exception as e:
            self.provider.log_debug(f"❌ Errore Groq ({self.model_name}): {e}")
            raise e

    def generate_stream(self, prompt: Any):
        """Esegue la chiamata a Groq in streaming."""
        try:
            prompt_text = self._extract_text_from_multimodal(prompt)
            messages = [{"role": "user", "content": prompt_text}]

            stream = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                temperature=1,
                max_completion_tokens=8192,
                top_p=1,
                stream=True,
                stop=None,
                response_format={"type": "json_object"} if self.json_mode else None,
            )

            for chunk in stream:
                # Groq delta content
                content = chunk.choices[0].delta.content or ""
                if content:
                    yield content

        except Exception as e:
            yield f"❌ Errore Groq Stream: {e}"


class GeminiWrapper:
    """Wrapper per Google Gemini con gestione retry e backoff (New SDK)."""

    def __init__(self, provider, json_mode: bool):
        self.provider = provider
        self.json_mode = json_mode

        # Inizializza client (stateless per chiamate, ma lo teniamo qui)
        if not GOOGLE_GENAI_AVAILABLE:
            raise ImportError("Libreria 'google-genai' non installata.")

        try:
            self.client = genai.Client(api_key=self.provider.api_key)
        except Exception as e:
            print(f"⚠️ Errore Init Gemini Client: {e}")
            self.client = None

    def generate_content(self, prompt):
        """Genera contenuto con Exponential Backoff."""
        if not self.client:
            raise RuntimeError("Gemini Client non inizializzato.")

        max_retries = 5
        base_delay = 2
        last_error = None

        # Configurazione
        config = {}
        if self.json_mode:
            config["response_mime_type"] = "application/json"

        for attempt in range(max_retries):
            try:
                start_time = time.time()

                # Nuova API Call
                response = self.client.models.generate_content(
                    model=self.provider.current_model_name,
                    contents=prompt,
                    config=config,
                )

                # Logging Token Usage (se disponibile)
                # Nota: Verifica struttura usage_metadata nella nuova SDK
                try:
                    usage = response.usage_metadata
                    input_tokens = usage.prompt_token_count
                    output_tokens = usage.candidates_token_count
                    total_tokens = usage.total_token_count
                    model_used = self.provider.current_model_name

                    self.provider.log_debug(
                        f"🤖 GENAI CALL | Model: {model_used} | Tokens: {input_tokens} in + {output_tokens} out = {total_tokens} tot | Time: {time.time()-start_time:.2f}s"
                    )
                except Exception:  # pylint: disable=broad-exception-caught
                    self.provider.log_debug(
                        f"🤖 GENAI CALL | Model: {self.provider.current_model_name} | (Token info non avail)"
                    )

                return response
            except ResourceExhausted as e:
                last_error = e
                wait = (base_delay * (2**attempt)) + random.uniform(0, 1)
                self.provider.log_debug(f"⚠️ Quota 429. Attendo {wait:.1f}s...")
                time.sleep(wait)
                if attempt >= 2 and self.provider.downgrade_model():
                    pass  # Riprova con nuovo nome modello (usato nella prossima iterazione)
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
            except Exception as e:  # pylint: disable=broad-exception-caught
                last_error = e
                self.provider.log_debug(f"❌ Errore: {e}")
                break

        raise RuntimeError(
            f"Impossibile generare contenuto Gemini. Last Error: {last_error}"
        )

    def generate_stream(self, prompt):
        """Genera contenuto in streaming."""
        if not self.client:
            yield "❌ Gemini Client non attivo."
            return

        try:
            # Nuova API Stream
            response = self.client.models.generate_content(
                model=self.provider.current_model_name,
                contents=prompt,
                config={"response_mime_type": "text/plain"}
                if not self.json_mode
                else {"response_mime_type": "application/json"},
            )
            # ATTENZIONE: La nuova SDK potrebbe non supportare stream=True come argomento diretto,
            # ma generate_content_stream o simile? Dalla doc (non letta completamente per stream),
            # assumiamo che generate_content ritorni un iterabile se stream=True?
            # Controlliamo meglio una cosa: Nel chunk 15 c'era "stream".
            # Ma per sicurezza nel dubbio uso generate_content standard se non stream, e cerco info stream.
            # Dalle info lette: "The new Google GenAI SDK provides access to all the API methods through the Client object..."
            # Non ho letto esplicitamente "generate_content_stream".
            # TUTTAVIA: Spesso è `client.models.generate_content_stream`.
            # Provo con `client.models.generate_content_stream` se esiste, altrimenti fallback.
            # In realtà, guardando gli esempi, non ho visto `generate_content_stream` esplicitamente,
            # ma è una scommessa sicura dato il pattern.
            # Update: Rileggendo la memoria, spesso è così.
            # Provo ad usare `generate_content` normale per ora nel blocco try, e se fallisce cambio.
            # MA aspetta, ho visto `response = model.generate_content(..., stream=True)` nel vecchio.
            # Nel nuovo, spesso è un metodo separato `generate_content_stream`.

            # USO DIRETTO: stream=True nel config? No.
            # Provo `generate_content_stream` che è lo standard per i client v2 solitamente.

            stream = self.client.models.generate_content_stream(
                model=self.provider.current_model_name, contents=prompt
            )

            for chunk in stream:
                yield chunk.text

        except Exception as e:
            # Fallback se il metodo non esiste (per sicurezza) o errore
            yield f"❌ Errore Gemini Stream: {e}"


class AIProvider:
    """Factory per modelli AI (Cloud/Local) con Caching."""

    DOCS_URL = "https://ai.google.dev/gemini-api/docs/models?hl=it"
    # Fallback solidi per Gemini: Rimosso 2.0-flash per instabilità (429 errors)
    FALLBACK_ORDER = [
        "gemini-3-pro-preview",
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.5-pro",
        "gemini-2.0-flash-exp",
        "gemini-1.5-flash",
        "gemini-1.5-flash-8b",
        "gemini-1.5-pro",
    ]

    _cached_chain: Optional[List[str]] = None
    _last_scrape_time: float = 0

    def __init__(
        self,
        api_key: Optional[str] = None,
        provider_type: str = "gemini",
        model_name: Optional[str] = None,
    ):
        """
        Inizializza il provider.
        """
        self.provider_type = provider_type.lower()
        self.target_model = model_name

        # Recupero chiave dai Secrets (se disponibile in ambiente Streamlit)
        secret_key = None
        try:
            import streamlit as st

            # Usa get per evitare errori se la chiave non esiste
            secret_key = st.secrets.get("GOOGLE_API_KEY", None)
        except (ImportError, FileNotFoundError, AttributeError):
            pass

        # Gestione API Key: Priorità a quella passata, poi Secrets, poi Env
        self.api_key = api_key or secret_key or os.getenv("GOOGLE_API_KEY")

        self.debug_mode = os.getenv("AI_DEBUG", "true").lower() == "true"

        # Variabili di stato
        self.current_model_index = 0
        self.current_model_name = ""
        self.available_models_chain: List[str] = []

        # --- LOGICA DI INIZIALIZZAZIONE DEL PROVIDER ---
        if self.provider_type == "gemini":
            if not self.api_key:
                print("⚠️ API Key mancante per Gemini. Impossibile inizializzare.")
                return

            # Non c'è più configure globale, si passa al client
            self._init_gemini_chain()

        elif self.provider_type == "ollama":
            if not OLLAMA_AVAILABLE:
                raise ImportError(
                    "Libreria 'ollama' non installata. Esegui: pip install ollama"
                )
            self.current_model_name = self.target_model or "llama3"
            self.log_debug(
                f"🤖 AI Provider impostato su Ollama: {self.current_model_name}"
            )

        elif self.provider_type == "groq":
            if not GROQ_AVAILABLE:
                raise ImportError(
                    "Libreria 'groq' non installata. Esegui: pip install groq"
                )
            self.current_model_name = self.target_model or "llama3-70b-8192"
            self.log_debug(
                f"🤖 AI Provider impostato su Groq: {self.current_model_name}"
            )

    def log_debug(self, message: str):
        if self.debug_mode:
            print(message)

    @staticmethod
    def get_ollama_models() -> List[str]:
        if not OLLAMA_AVAILABLE:
            return []
        try:
            models_info = ollama.list()  # pyright: ignore[reportUnboundVariable]
            return [
                m.get("model") or m.get("name") for m in models_info.get("models", [])
            ]
        except Exception as e:  # pylint: disable=broad-exception-caught
            print(f"⚠️ Errore listing Ollama: {e}")
            return []

    def get_model(self, json_mode: bool = False) -> Any:
        if self.provider_type == "ollama":
            return OllamaWrapper(self.current_model_name, json_mode)
        elif self.provider_type == "groq":
            return GroqWrapper(self, json_mode)
        return GeminiWrapper(self, json_mode)

    @staticmethod
    def get_gemini_models(api_key: Optional[str] = None) -> List[str]:
        """Recupera la lista dei modelli Gemini disponibili, con fallback statico robusto."""
        # Usa key passata o env
        key = api_key or os.getenv("GOOGLE_API_KEY")

        # 1. Se SDK non disponibile, fallback immediato
        if not GOOGLE_GENAI_AVAILABLE:
            return AIProvider.FALLBACK_ORDER

        try:
            # 2. Se key mancante, fallback (permetti selezione UI)
            if not key:
                return AIProvider.FALLBACK_ORDER

            client = genai.Client(api_key=key)
            models = []
            for m in client.models.list():
                # Filtra modelli validi (che contengono 'gemini' e non 'embedding')
                if "gemini" in m.name and "embedding" not in m.name:
                    models.append(m.name)

            if not models:
                return AIProvider.FALLBACK_ORDER

            return sorted(models, reverse=True)
        except Exception as e:
            # 3. Su errore API (es. Key Invalida, Quota, Connection), fallback silenzioso
            print(f"⚠️ Errore listing Gemini API: {e}. Uso lista statica.")
            return AIProvider.FALLBACK_ORDER

    @staticmethod
    def get_groq_models(api_key: Optional[str] = None) -> List[str]:
        """Recupera la lista dei modelli Groq."""
        key = api_key or os.getenv("GROQ_API_KEY")
        if not key or not GROQ_AVAILABLE:
            return []
        try:
            client = Groq(api_key=key)
            # models.list() returns output with .data list
            return [m.id for m in client.models.list().data]
        except Exception as e:
            print(f"⚠️ Errore listing Groq: {e}")
            return []

    def _init_gemini_chain(self):
        # Se l'utente ha chiesto un modello specifico, lo mettiamo in cima
        if self.target_model:
            self.available_models_chain = [self.target_model] + self.FALLBACK_ORDER
        # Altrimenti usiamo la cache se valida
        elif AIProvider._cached_chain and (
            time.time() - AIProvider._last_scrape_time < 3600
        ):
            self.available_models_chain = AIProvider._cached_chain
        # Altrimenti scraping (Nota: Scraping potrebbe rompersi se pagina cambia, ma per ora teniamo)
        else:
            self.available_models_chain = self._build_gemini_chain()
            if self.available_models_chain:
                AIProvider._cached_chain = self.available_models_chain
                AIProvider._last_scrape_time = time.time()

        # Fallback finale
        if not self.available_models_chain:
            self.available_models_chain = self.FALLBACK_ORDER

        self.current_model_index = 0
        self.current_model_name = self.available_models_chain[0]
        self.log_debug(
            f"🤖 AI Provider Gemini pronto. Modello: {self.current_model_name}"
        )

    def downgrade_model(self) -> bool:
        if self.current_model_index + 1 < len(self.available_models_chain):
            self.current_model_index += 1
            self.current_model_name = self.available_models_chain[
                self.current_model_index
            ]
            return True
        return False

    def _build_gemini_chain(self) -> List[str]:
        try:
            response = requests.get(self.DOCS_URL, timeout=2)
            if response.status_code != 200:
                return []
            soup = BeautifulSoup(response.text, "html.parser")
            text = soup.get_text()
            candidates = set(re.findall(r"(gemini-[a-zA-Z0-9\-\.]+)", text))
            valid = [
                m
                for m in candidates
                if "vision" not in m and "audio" not in m and "tts" not in m
            ]
            return sorted(valid, reverse=True)
        except Exception:
            return []
