"""MarketAnalyzer — Streamlit entry point."""

import streamlit as st

st.set_page_config(
    page_title='MarketAnalyzer',
    page_icon='📊',
    layout='wide',
    initial_sidebar_state='expanded',
)

st.title('📊 MarketAnalyzer')
st.markdown('---')

st.markdown("""
### Unified Market Analysis Platform

Integrates **11 analysis agents** powered by 40+ opencode skills:

| Funzione | Descrizione |
|----------|-------------|
| 🔍 **Scanner** | Wyckoff + VP + PA scanning su US/EU mercati |
| 🎯 **Deep Dive** | Verdetto unificato 5-dimensioni + TAATH + TATC |
| 📈 **ETF Explorer** | Trova sottovalutati dentro ETF o scansiona l'universo ETF |
| 🎲 **Options Strategist** | Selezione strategie multi-libro per verdetto + IV + DTE |
| 📚 **Knowledge Base** | Accesso live a tutti gli skill opencode |

**Features chiave:**
- Zero AI dependency per analisi quantitative (puro Python + numpy/scipy)
- AI narrativa opzionale via `Custom_Agents`
- Report PDF con fpdf2 (stesso formato HPQ/IGV)
- Dati gratuiti via yfinance + CoinGecko

---
Seleziona una pagina dal menu a sinistra per iniziare.
""")
