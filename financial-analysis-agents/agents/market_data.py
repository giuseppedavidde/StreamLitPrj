"""Agente Facade ottimizzato per risparmio token."""
from typing import Optional, Dict, Any, Callable    
from dataclasses import asdict
import pandas as pd
import yfinance as yf
from models.data_schema import FinancialData
from utils.cache_manager import CacheManager
from .data_builder import DataBuilderAgent
from .summary import SummaryAgent
from .review import ReviewAgent
from .etf_finder import ETFFinderAgent
from .cross_check import CrossCheckAgent



class MarketDataAgent:
    """Orchestratore con logiche di risparmio token."""
    
    def __init__(self, api_key: Optional[str] = None, provider: str = "gemini", model: str = ""):
        self.cache = CacheManager()
        
        # --- MODEL TIERING (Strategia di Risparmio) ---
        # Se usiamo Gemini, usiamo modelli "Flash" (veloci/economici) per task meccanici
        # e modelli "Pro" (o user choice) per task complessi (Summary).
        builder_model = model
        cross_check_model = model
        
        if provider == "gemini":
            # Se l'utente non ha forzato un modello specifico, usiamo i default ottimizzati
            if not model:
                builder_model = "gemini-1.5-flash"  # Estrazione dati: Flash è perfetto
                cross_check_model = "gemini-1.5-flash" # Ragionamento semplice: Flash ok
                model = "gemini-1.5-pro" # Summary/Reasoning: Pro preferibile
            else:
                # Se l'utente ha scelto un modello (es. 2.0-flash), usiamo quello ovunque
                builder_model = model
                cross_check_model = model

        # Inizializzazione Agenti con modelli specifici
        self.builder = DataBuilderAgent(api_key, provider, model)
        self.summarizer = SummaryAgent(api_key, provider, model)
        self.reviewer = ReviewAgent(api_key, provider, model)
        self.etf_finder = ETFFinderAgent(api_key, provider, model)
        self.cross_checker = CrossCheckAgent(api_key, provider, model)

    def _minify_dataframe(self, df: pd.DataFrame, max_cols: int = 4, max_rows: int = 12) -> str:
        """Minifica un DataFrame in CSV tabulare per risparmiare token."""
        if df.empty: return "N/A"
        # Prendi solo le colonne più recenti (sx)
        df_reduced = df.iloc[:, :max_cols]
        # Se troppe righe, taglia (per bilanci annuali ok, per trimestrali lunghi taglia)
        if len(df_reduced) > max_rows:
            df_reduced = df_reduced.head(max_rows)
        return df_reduced.to_csv(sep="\t", index=True, float_format="%.2f")

    def fetch_from_ticker(self, ticker_symbol: str, audit_mode: str = "quick", callback: Optional[Callable[[str], None]] = None) -> Optional[Dict[str, Any]]:
        """
        Recupera dati finanziari e summary.
        audit_mode: 'quick' (solo errori ovvi) | 'full' (controllo esteso)
        """
        print(f"📈 Analisi Ottimizzata per {ticker_symbol} (Mode: {audit_mode})...")
        
        print(f"📈 Analisi Ottimizzata per {ticker_symbol} (Mode: {audit_mode})...")
        
        # CHECK CACHE
        cache_fin = self.cache.get(f"{ticker_symbol}_financials", 86400*7)
        # Summary 30gg, Finviz 24h (dati giornalieri)
        cache_sum = self.cache.get(f"{ticker_symbol}_summary", 86400*30)
        cache_fv = self.cache.get(f"{ticker_symbol}_finviz", 86400)
        
        # Se abbiamo cache financials e summary e siamo in quick, usiamo cache.
        # Se siamo in full, magari vogliamo rinfrescare finviz? Per ora usiamo caché se valida (24h).
        if cache_fin and cache_sum and audit_mode == "quick":
            print("🚀 HIT Cache! Zero token usati.")
            # Se abbiamo finviz in cache bene, sennò pace (in quick mode non è critico se non per display)
            return {"financials": cache_fin, "summary": cache_sum, "finviz": cache_fv}

        # FETCH YFINANCE
        try:
            # ... (Codice YFinance esistente invariato, omettiamo per brevità diff se non cambia)
            tk = yf.Ticker(ticker_symbol)
            q_inc = tk.quarterly_financials
            if q_inc.empty: return None
            
            # Calcoli TTM (Python side = 0 token)
            cols = q_inc.columns[:4]
            ttm_inc = q_inc[cols].sum(axis=1).to_frame("TTM")
            ttm_cf = tk.quarterly_cashflow[cols].sum(axis=1).to_frame("TTM")
            mrq_bs = tk.quarterly_balance_sheet.iloc[:, 0:1]
            
            # DATA PRUNING & PAYLOAD
            raw_text = f"""
            DATA: {ticker_symbol} Price:{tk.info.get('currentPrice')}
            [INCOME TTM]
            {self._minify_dataframe(ttm_inc, max_rows=30)}
            [BALANCE MRQ]
            {self._minify_dataframe(mrq_bs, max_rows=60)}
            [CASH FLOW TTM]
            {self._minify_dataframe(ttm_cf, max_rows=30)}
            """

            # SUMMARY GENERATION
            final_summary = cache_sum
            if not final_summary:
                print("📜 Generazione Summary...")
                # Per il summary serve un po' più di contesto storico
                summary_payload = raw_text + f"\nDesc: {tk.info.get('longBusinessSummary','')[:1000]}"
                final_summary = self.summarizer.summarize_dossier(summary_payload)
                self.cache.set(f"{ticker_symbol}_summary", final_summary)
            
            # FINVIZ PRE-FETCH (Gestione Cache)
            finviz_data = cache_fv
            if not finviz_data:
                # Se non è in cache, scarichiamo ora
                finviz_data = self.cross_checker.finviz.get_fundamental_data(ticker_symbol)
                if finviz_data:
                    self.cache.set(f"{ticker_symbol}_finviz", finviz_data)

            # FINANCIALS EXTRACTION
            if cache_fin and audit_mode == "quick":
                final_fin = cache_fin
            else:
                print("🧠 Estrazione Dati...")
                
                data_dict = None
                if cache_fin:
                    print("♻️ Uso dati in cache come base per Full Audit...")
                    data_dict = cache_fin
                else:
                    data_dict = self.builder.build_from_text(raw_text)
                
                if not data_dict: return None
                
                # --- ARRICCHIMENTO DATI STORICI (Hard Calculations) ---
                # Calcoliamo qui la storia dividendi e utili da YF, sovrascrivendo l'LLM se necessario
                div_years = 0
                earn_years = 0
                try:
                    # Storia Dividendi
                    divs = tk.dividends
                    if not divs.empty:
                        # Conta anni unici in cui c'è stato un dividendo
                        div_years = len(divs.index.year.unique())
                    
                    # Storia Utili (Annuali disponibili su YF, solitamente 4)
                    inc_stmt = tk.financials
                    if not inc_stmt.empty and "Net Income" in inc_stmt.index:
                        # Conta quanti anni hanno Net Income > 0
                        net_income_row = inc_stmt.loc["Net Income"]
                        earn_years = (net_income_row > 0).sum()
                    
                    # Aggiorna il dizionario
                    data_dict['dividend_years_count'] = int(div_years)
                    data_dict['earnings_years_count'] = int(earn_years)
                    
                    # Logica Fallback/Override dei Booleani (L'LLM spesso allucina su 20y se non li vede)
                    # Se YF ci dà info, usiamo quelle.
                    # Nota: YF di solito non dà 20 anni di financials, ma dividendi si.
                    if div_years >= 20: 
                        data_dict['dividend_history_20y'] = True
                    elif div_years > 0 and div_years < 20:
                        # Se ne abbiamo trovati alcuni ma non 20, l'LLM diceva False? 
                        # Lasciamo l'LLM decidere se ha visto testo aggiuntivo, 
                        # MA se l'LLM ha detto False e noi abbiamo >20, abbiamo corretto sopra.
                        pass
                    
                except Exception as e:
                    print(f"⚠️ Errore calcolo storico: {e}")
                
                fin_obj = FinancialData(**data_dict)
                
                # LAZY EXECUTION: Audit Logic
                print(f"🧐 Audit {audit_mode.title()}...")
                _, suspicious = self.reviewer.audit_data(ticker_symbol, fin_obj)
                
                # Definizione Criticità
                if audit_mode == "full":
                    # In Full mode forziamo il controllo su TUTTI i campi principali
                    real_issues = [
                        'long_term_debt', 'net_income', 'shares_outstanding', 'sales', 
                        'operating_income', 'total_assets', 'current_assets', 'total_liabilities',
                        'inventory', 'intangible_assets', 'current_market_price', 
                        'preferred_dividends', 'eps_3y_avg', 'interest_charges'
                    ]
                    print(f"🛡️ Start Full Audit su {len(real_issues)} campi...")
                else:
                    # In Quick mode filtro solo errori critici sospetti
                    critical = ['long_term_debt', 'net_income', 'shares_outstanding']
                    real_issues = [f for f in suspicious if f in critical]
                
                if real_issues:
                    print(f"⚠️ Verifica Web ({len(real_issues)} campi)...")
                    if callback: callback(f"⚠️ Verifica Web estesa su: {real_issues}")
                    # Passiamo finviz_data cachato per evitare doppio download
                    fixes = self.cross_checker.cross_check_fields(
                        ticker_symbol, 
                        asdict(fin_obj), 
                        real_issues, 
                        callback=callback, 
                        external_finviz_data=finviz_data
                    )
                    if fixes: data_dict.update(fixes)
                
                final_fin = asdict(FinancialData(**data_dict))
                self.cache.set(f"{ticker_symbol}_financials", final_fin)

            return {"financials": final_fin, "summary": final_summary, "finviz": finviz_data}

        except Exception as e: # pylint: disable=broad-exception-caught
            print(f"❌ Errore: {e}")
            return None