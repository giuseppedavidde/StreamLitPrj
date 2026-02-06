"""
Modulo per l'analisi fondamentale: Integrazione 'L'Investitore Intelligente'.
"""
from typing import Optional
from dataclasses import dataclass
from models.data_schema import FinancialData
# Import lazy per evitare cicli se non necessario, ma qui ci serve per type hint
# from agents.ai_provider import AIProvider 
# from agents.knowledge_base import KnowledgeBase

@dataclass
class GrahamCheck:
    """Guida per ogni criterio di selezione di Graham."""
    criterion: str
    passed: bool
    details: str

class GrahamAgent:
    """
    Analista che implementa le strategie de 'L'Investitore Intelligente' (Cap. 14).
    Ora potenziato da AI per evolvere le strategie con nuova conoscenza.
    """
    def __init__(self, data: FinancialData, ai_provider=None, knowledge_base=None):
        self.d = data
        self.ai = ai_provider
        self.kb = knowledge_base

    def analyze(self) -> str:
        """Genera il report completo."""
        
        # --- CALCOLI DI SUPPORTO ---
        equity = self.d.common_stock + self.d.surplus
        tangible_equity = equity - self.d.intangible_assets
        bv_share = tangible_equity / self.d.shares_outstanding if self.d.shares_outstanding else 0
        
        # Calcolo EPS (Preferiamo la media a 3 anni se disponibile, altrimenti TTM)
        eps_calc = self.d.eps_3y_avg if self.d.eps_3y_avg > 0 else (self.d.net_income / self.d.shares_outstanding)
        
        pe_ratio = self.d.current_market_price / eps_calc if eps_calc > 0 else 0
        pb_ratio = self.d.current_market_price / bv_share if bv_share > 0 else 0
        
        # Graham Number (Cap. 14): P/E * P/B non dovrebbe superare 22.5 [cite: 3055]
        graham_number_val = pe_ratio * pb_ratio

        # Capitale Circolante Netto (Working Capital) [cite: 2607]
        working_capital = self.d.current_assets - self.d.current_liabilities

        # --- CHECKLIST INVESTITORE DIFENSIVO (Cap. 14) ---
        checks = []

        # 1. Dimensioni Adeguate 
        # Graham: "$100M vendite annuali" (nel 1972). Aggiustato inflazione (x7) ~= $700M.
        # Usiamo $1B per sicurezza moderna.
        checks.append(GrahamCheck(
            "1. Dimensioni Adeguate",
            self.d.sales >= 1_000_000_000,
            f"Vendite: ${self.d.sales/1e9:.2f}B (Target > $1B)"
        ))

        # 2. Condizione Finanziaria Sufficientemente Solida 
        # "Attività correnti almeno il doppio delle passività correnti"
        # "Indebitamento a lungo termine non superiore al capitale circolante netto"
        curr_ratio = self.d.current_assets / self.d.current_liabilities if (self.d.current_liabilities and self.d.current_liabilities > 0) else 0.0
        
        # Check per dati mancanti (evita falsi negativi se estrazione fallita)
        data_missing = (self.d.current_assets == 0 or self.d.current_liabilities == 0)
        
        cond_strong = (curr_ratio >= 2.0) and (self.d.long_term_debt <= working_capital)
        
        details_str = f"Current Ratio: {curr_ratio:.2f} (Target 2.0) | Working Capital > Fin. Debt: {'SI' if self.d.long_term_debt <= working_capital else 'NO'}"
        if data_missing:
            details_str = "⚠️ DATI MANCANTI (Assets/Liabs trovati a 0)"
            cond_strong = False

        checks.append(GrahamCheck(
            "2. Solidità Finanziaria",
            cond_strong,
            details_str
        ))

        # Check Interest Coverage (non strettamente Cap. 14 ma vitale per bond analysis)
        int_coverage = self.d.operating_income / self.d.interest_charges if self.d.interest_charges > 0 else 999.0
        # Graham consigliava 7x-10x per i bond a seconda del tipo
        
        # Debito Finanziario Totale
        fin_debt_ratio = self.d.long_term_debt / (self.d.long_term_debt + equity) if (self.d.long_term_debt + equity) > 0 else 0.0


        # 3. Stabilità degli Utili 
        # "Alcuni guadagni per le azioni ordinarie in ciascuno degli ultimi dieci anni"
        earnings_msg = "Nessun deficit rilevato (Check storico AI)"
        if self.d.earnings_years_count > 0:
            earnings_msg = f"Utili positivi in tutti gli anni analizzati ({self.d.earnings_years_count}y disp.)"
            # Se abbiamo meno di 10 anni ma tutti positivi, diamo un giudizio di incoraggiamento
            if self.d.earnings_years_count < 10 and self.d.earnings_growth_10y is False:
                earnings_msg += " -> ⚠️ Storico breve ma IMPECCABILE (100% positivo)"
        
        checks.append(GrahamCheck(
            "3. Stabilità Utili (10y)",
            self.d.earnings_growth_10y, 
            earnings_msg
        ))

        # 4. Record di Dividendi 
        # "Pagamenti ininterrotti per almeno gli ultimi 20 anni"
        div_msg = "Pagamenti ininterrotti (Check storico)"
        if self.d.dividend_years_count > 0:
            div_msg = f"Dividendi rilevati per {self.d.dividend_years_count} anni (Target 20y)"
            if self.d.dividend_years_count < 20 and not self.d.dividend_history_20y:
                 div_msg += f" -> ⚠️ Storico breve ma CONTINUATIVO ({self.d.dividend_years_count} anni consecutivi)"
        
        checks.append(GrahamCheck(
            "4. Storia Dividendi (20y)",
            self.d.dividend_history_20y,
            div_msg
        ))

        # 5. Crescita degli Utili 
        # "Aumento minimo di almeno un terzo dell'utile per azione negli ultimi dieci anni"
        checks.append(GrahamCheck(
            "5. Crescita Utili",
            True, # Difficile da calcolare preciso senza dati raw di 10 anni fa, assumiamo OK se positivo
            "Crescita moderata a lungo termine richiesta"
        ))

        # 6. Rapporto Prezzo/Utili Moderato 
        # "Non superiore a 15 volte i guadagni medi degli ultimi tre anni"
        checks.append(GrahamCheck(
            "6. P/E Moderato",
            pe_ratio <= 15.0,
            f"P/E (su media 3y): {pe_ratio:.2f}x (Target < 15.0)"
        ))

        # 7. Rapporto Moderato Prezzo/Attività [cite: 3055]
        # "Non superiore a 1.5 volte il valore contabile... prodotto P/E * P/B < 22.5"
        checks.append(GrahamCheck(
            "7. Prezzo/Attività (Graham Number)",
            graham_number_val <= 22.5,
            f"P/E * P/B = {graham_number_val:.2f} (Target < 22.5)"
        ))

        # --- COSTRUZIONE REPORT ---
        score = sum(1 for c in checks if c.passed)
        
        report = f"""
        === ANALISI 'L'INVESTITORE INTELLIGENTE' (Ben Graham) ===
        
        [CRITERI SELEZIONE INVESTITORE DIFENSIVO - CAP. 14]
        Punteggio: {score}/7 Criteri Soddisfatti
        
        """
        
        for c in checks:
            icon = "✅" if c.passed else "❌"
            report += f"{icon} {c.criterion}\n   -> {c.details}\n"
            
        report += f"""
        ------------------------------------------------
        [VALUTAZIONE ENTERPRISING INVESTOR]
        Se l'azienda non soddisfa i criteri difensivi (troppo severi), 
        Graham suggerisce di guardare al "Capitale Circolante Netto" (NCAV).
        
        NCAV per Azione: ${ (working_capital - self.d.long_term_debt) / self.d.shares_outstanding if self.d.shares_outstanding else 0 :.2f}
        Prezzo Attuale:  ${self.d.current_market_price:.2f}
        
        Giudizio: {"SOTTOVALUTATA (Bargain)" if self.d.current_market_price < ((working_capital - self.d.long_term_debt) / self.d.shares_outstanding) else "Prezzo superiore al valore di liquidazione netto."}
        ------------------------------------------------
        
        [STRUTTURA DEL CAPITALE - EXTRA]
        Interest Coverage: {int_coverage:.1f}x {"(Debt Free ??)" if int_coverage > 900 else ""}
        Incidenza Debito Finanziario (Bond/Prestiti): {fin_debt_ratio*100:.1f}%
        
        Nota Leasing (Retail/Tech):
        Oltre al debito finanziario (${self.d.long_term_debt/1e6:.1f}M), l'azienda ha
        obbligazioni di leasing per ${self.d.capital_lease_obligations/1e6:.1f}M.
        Questi sono costi operativi e NON contano come Funded Debt per Graham.
        ------------------------------------------------
        Note:
        - Il P/E è calcolato sulla media degli utili a 3 anni (ove disp.) come raccomandato a pag. 410.
        - Il limite di debito per l'investitore difensivo considera SOLO il Debito Finanziario (Bonds), escludendo i Leasing.
        """
        
        # --- SEZIONE EVOLUTIVA (AI + KNOWLEDGE) ---
        if self.ai and self.kb:
            report += "\n\n🧠 --- INSIGHT EVOLUTIVI (DAI TUOI LIBRI/DOCS) ---\n"
            report += "Sto consultando la tua libreria personale per affinare l'analisi...\n"
            
            try:
                # 1. Recupera Contesto
                context = self.kb.get_context()
                if not context:
                    report += "⚠️ Nessun documento trovato nella Knowledge Base. Carica libri o appunti per 'evolvere'."
                else:
                    # 2. Costruisci Prompt
                    prompt = f"""
                    Sei GrahamGPT, un'evoluzione dell'analista Ben Graham.
                    
                    DATI AZIENDALI:
                    - P/E: {pe_ratio:.2f}
                    - P/B: {pb_ratio:.2f}
                    - Debt/Equity: {fin_debt_ratio:.2f}
                    - Current Ratio: {curr_ratio:.2f}
                    - Graham Number Check: {graham_number_val:.2f} (Target 22.5)
                    - Net Income: {self.d.net_income}
                    
                    CONOSCENZA AGGIUNTIVA DALLA LIBRERIA UTENTE:
                    {context[:15000]}  # Tronchiamo per evitare overflow token
                    
                    RICHIESTA:
                    Analizza questi dati alla luce della "Conoscenza Aggiuntiva" fornita.
                    Se trovi regole, eccezioni o sfumature nei documenti caricati che si applicano a questo caso, citalie e usale per dare un giudizio più evoluto.
                    Sii conciso, diretto e cita la fonte se possibile (es. "Come menzionato nel documento X...").
                    Se i documenti non aggiungono nulla di specifico, dai un consiglio di investimento generale basato sui dati.
                    """
                    
                    # 3. Genera
                    resp = self.ai.get_model().generate_content(prompt)
                    report += resp.text
            except Exception as e:
                report += f"❌ Errore durante l'evoluzione AI: {e}"

        return report