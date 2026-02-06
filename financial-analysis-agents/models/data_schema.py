"""Modello dati per l'analisi finanziaria con metriche storiche di 'L'Invest"""
from dataclasses import dataclass


@dataclass
class FinancialData:
    """
    Struttura dati aggiornata per includere metriche storiche di 'L'Investitore Intelligente'.
    """
    # Stato Patrimoniale
    total_assets: float
    current_assets: float
    current_liabilities: float
    inventory: float
    intangible_assets: float
    total_liabilities: float
    long_term_debt: float 

    
    # Capitale
    preferred_stock: float
    common_stock: float
    surplus: float
    
    # Conto Economico
    sales: float
    operating_income: float
    net_income: float
    interest_charges: float
    preferred_dividends: float
    
    # --- NUOVI CAMPI PER 'L'INVESTITORE INTELLIGENTE' ---
    eps_3y_avg: float    # Utile per azione medio ultimi 3 anni 
    earnings_growth_10y: bool # Ha mostrato crescita negli ultimi 10 anni? 
    dividend_history_20y: bool # Ha pagato dividendi per 20 anni? 
    
    # Mercato
    shares_outstanding: float
    current_market_price: float
    
    # Metadati aggiuntivi per reportistica (con default alla fine)
    dividend_years_count: int = 0
    earnings_years_count: int = 0
    
    capital_lease_obligations: float = 0.0 # Valore predefinito se non estratto 

    def __post_init__(self):
        # Fix segni e valori
        self.interest_charges = abs(self.interest_charges)
        self.intangible_assets = abs(self.intangible_assets)
        self.current_market_price = abs(self.current_market_price)
        self.shares_outstanding = abs(self.shares_outstanding)
        self.long_term_debt = abs(self.long_term_debt)
        self.capital_lease_obligations = abs(self.capital_lease_obligations)