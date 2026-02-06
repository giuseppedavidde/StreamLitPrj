"""Modulo per il caricamento dei dati finanziari da file JSON."""
import json
from typing import Optional
from models.data_schema import FinancialData

def load_company_data(filepath: str) -> Optional[FinancialData]:
    """Carica un file JSON e restituisce un oggetto FinancialData."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # Scompatta il dizionario nella dataclass
        return FinancialData(**data)
    except FileNotFoundError:
        print(f"Errore: File {filepath} non trovato.")
        return None
    except json.JSONDecodeError as e:
        print(f"Errore nel parsing JSON del file: {e}")
        return None
    except TypeError as e:
        # Raised when the dict cannot be unpacked into FinancialData (wrong/missing fields)
        print(f"Errore di tipo durante la conversione in FinancialData: {e}")
        return None