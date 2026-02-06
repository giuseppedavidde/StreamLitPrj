"""
Modulo per la gestione della cache locale per risparmiare token AI.
"""
import json
import os
import time
from typing import Optional, Dict, Any

class CacheManager:
    """
    Gestisce il salvataggio e il recupero di dati costosi (AI responses) su file JSON.
    """
    
    CACHE_FILE = "data/cache_store.json"
    
    # Durata validità in secondi (es. 10 giorni = 86400 * 10)
    DEFAULT_EXPIRATION = 86400 * 10 

    def __init__(self):
        self._ensure_cache_file()

    def _ensure_cache_file(self):
        """Crea il file di cache se non esiste."""
        os.makedirs(os.path.dirname(self.CACHE_FILE), exist_ok=True)
        if not os.path.exists(self.CACHE_FILE):
            with open(self.CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump({}, f)

    def _load_cache(self) -> Dict[str, Any]:
        """Carica l'intero database di cache."""
        try:
            with open(self.CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

    def _save_cache(self, cache_data: Dict[str, Any]):
        """Salva il database su disco."""
        with open(self.CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache_data, f, indent=4, ensure_ascii=False)

    def get(self, key: str, max_age_seconds: int = DEFAULT_EXPIRATION) -> Optional[Any]:
        """
        Recupera un valore dalla cache se esiste e non è scaduto.
        
        Args:
            key: Identificativo unico (es. "AAPL_summary", "GME_graham_data")
            max_age_seconds: Tempo massimo di vita del dato (default 10 giorni)
        """
        cache = self._load_cache()
        entry = cache.get(key)
        
        if not entry:
            return None
            
        timestamp = entry.get('timestamp', 0)
        data = entry.get('data')
        
        # Controllo scadenza
        if (time.time() - timestamp) < max_age_seconds:
            print(f"📦 Cache HIT per '{key}' (Salvato il {time.ctime(timestamp)})")
            return data
        else:
            print(f"⌛ Cache SCADUTA per '{key}'.")
            return None

    def set(self, key: str, data: Any):
        """Salva un valore in cache con il timestamp attuale."""
        cache = self._load_cache()
        
        cache[key] = {
            'timestamp': time.time(),
            'data': data
        }
        
        self._save_cache(cache)
        print(f"💾 Dato salvato in Cache: '{key}'")
        
    def clear_key(self, key: str):
        """Rimuove una chiave specifica (utile per forzare l'aggiornamento)."""
        cache = self._load_cache()
        if key in cache:
            del cache[key]
            self._save_cache(cache)
            print(f"🗑️ Rimossa chiave cache: {key}")

    def get_all_keys(self) -> list[str]:
        """Restituisce tutte le chiavi in cache."""
        return list(self._load_cache().keys())

    def delete_keys(self, keys: list[str]):
        """Rimuove una lista di chiavi."""
        cache = self._load_cache()
        flushed = False
        for k in keys:
            if k in cache:
                del cache[k]
                flushed = True
        if flushed:
            self._save_cache(cache)