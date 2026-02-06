"""
Modulo per l'estrazione diretta dei dati fondamentali da Finviz.
"""
from typing import Dict, Optional, Any
import requests
from bs4 import BeautifulSoup

class FinvizAgent:
    """
    Agente Scraper per Finviz.
    Scarica la tabella 'Snapshot' dei fondamentali per un dato ticker.
    """
    
    BASE_URL = "https://finviz.com/quote.ashx"
    
    # Header per sembrare un browser reale (Finviz blocca gli script senza User-Agent)
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    def get_fundamental_data(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Scarica e parsa i dati fondamentali di Finviz.
        Restituisce un dizionario pulito { 'P/E': 15.5, 'Market Cap': 20000000000, ... }
        """
        print(f"🌐 FinvizAgent: Scarico dati per {ticker}...")
        
        try:
            response = requests.get(
                f"{self.BASE_URL}?t={ticker}", 
                headers=self.HEADERS, 
                timeout=10
            )
            
            if response.status_code != 200:
                print(f"⚠️ Finviz irraggiungibile (Status {response.status_code})")
                return None

            soup = BeautifulSoup(response.content, 'html.parser')
            
            # La tabella dei dati su Finviz ha solitamente la classe 'snapshot-table2'
            snapshot_table = soup.find('table', class_='snapshot-table2')
            
            if not snapshot_table:
                print("⚠️ Tabella dati non trovata nella pagina Finviz.")
                return None

            data = {}
            # Itera sulle righe della tabella
            rows = snapshot_table.find_all('tr') # pyright: ignore[reportOptionalMemberAccess]
            
            for row in rows:
                cols = row.find_all('td')
                # La struttura è: Label | Value | Label | Value ...
                for i in range(0, len(cols), 2):
                    key = cols[i].text.strip()
                    val_text = cols[i+1].text.strip()
                    
                    # Pulizia e conversione del valore
                    clean_val = self._parse_finviz_value(val_text)
                    data[key] = clean_val
            
            # Calcolo Campi Derivati (Smart Logic)
            self._calculate_derived_fields(data)

            return data

        except Exception as e: # pylint: disable=broad-exception-caught
            print(f"❌ Errore scraping Finviz: {e}")
            return None

    def _parse_finviz_value(self, text: str):
        """Converte stringhe come '1.5B', '100M', '2.5%' in float/int."""
        if text == '-':
            return 0.0
        
        # Rimozione %
        if text.endswith('%'):
            try:
                return float(text.replace('%', ''))
            except ValueError:
                return text

        # Gestione B (Miliardi), M (Milioni), K (Migliaia)
        multiplier = 1.0
        clean_text = text
        
        if text.endswith('B'):
            multiplier = 1_000_000_000.0
            clean_text = text[:-1]
        elif text.endswith('M'):
            multiplier = 1_000_000.0
            clean_text = text[:-1]
        elif text.endswith('K'):
            multiplier = 1_000.0
            clean_text = text[:-1]
            
        try:
            # Rimuove virgole se presenti (es. 1,200.50)
            return float(clean_text.replace(',', '')) * multiplier
        except ValueError:
            # Se non è un numero, restituisci il testo originale
            return text

    def _calculate_derived_fields(self, data: Dict[str, Any]):
        """
        Calcola campi mancanti usando formule inverse sui ratio disponibili.
        Es. Long Term Debt da LT Debt/Eq e Total Equity.
        """
        # 1. Calcolo Total Equity (Patrimonio Netto)
        # Equity = Book Value per Share * Shares Outstanding
        book_sh = data.get('Book/sh')
        shs_out = data.get('Shs Outstand')
        
        if isinstance(book_sh, (int, float)) and isinstance(shs_out, (int, float)):
            total_equity = book_sh * shs_out
            data['Total Equity'] = total_equity # Utile averlo
            
            # 2. Calcolo Long Term Debt
            # LTD = LT Debt/Eq * Total Equity
            lt_debt_eq = data.get('LT Debt/Eq')
            if isinstance(lt_debt_eq, (int, float)):
                ltd = lt_debt_eq * total_equity
                data['Long Term Debt'] = ltd
                print(f"🧮 Smart Finviz: Calcolato Long Term Debt = {ltd:,.0f} (da Ratio {lt_debt_eq})")

            # 3. Calcolo Total Debt
            # Total Debt = Debt/Eq * Total Equity
            debt_eq = data.get('Debt/Eq')
            if isinstance(debt_eq, (int, float)):
                total_debt = debt_eq * total_equity
                data['Total Debt'] = total_debt