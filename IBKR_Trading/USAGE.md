# 🚀 Quick Start: IBKR Trading Dashboard

Welcome to the **IBKR Trading Dashboard**. This guide will get your environment up and running in under 2 minutes. 

We use **Streamlit** for the frontend and **ib-async** for a robust, asynchronous connection to Interactive Brokers.

---

## 🛠 1. Installation & Environment Setup

We recommend using a virtual environment (`venv` or `conda`) to avoid dependency conflicts.

```bash
# 1. Navigate to the project directory
cd StreamLitPrj/IBKR_Trading

# 2. Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows use: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt
```

> [!NOTE]  
> Key dependencies include `streamlit`, `ib-async`, `ta` (for technical analysis), `plotly` (for visualization), and `groq` (for AI-driven insights). We use `nest-asyncio2` to safely run the asyncio event loop within Streamlit.

## ⚙️ 2. Configuration & Secrets

Before launching, ensure you have the required configuration. We rely on environment variables for sensitive data.

Create a `.env` file in the project root:
```bash
touch .env
```

Add your environment-specific configurations (e.g., API keys if using LLMs like Groq/OpenAI, or flags like `LOCAL_DEVELOPMENT`).
```env
# Example .env configuration
LOCAL_DEVELOPMENT=True
GROQ_API_KEY=your_groq_api_key_here
```

*Note: Streamlit also supports `.streamlit/secrets.toml` if you prefer that approach.*

## 🏃 3. Execution

Once your IBKR Gateway or TWS is running locally (usually on port `7496` for live or `7497` for paper trading), launch the dashboard:

```bash
streamlit run ibkr_trading.py
```

### What to expect:
- **Browser Automatically Opens**: The dashboard will launch at `http://localhost:8501`.
- **Interactive UI**: 
  - **Sidebar**: Manage IBKR connection settings, port selection, and navigation controls.
  - **Main Page**: Interactive Plotly charts, data entry fields for strategy parameters, and AI-driven insights.

## 💡 Troubleshooting (Gotchas)
- **Connection Refused**: Ensure Interactive Brokers Gateway or TWS is open, you are logged in, and API access is enabled (Settings > API > Settings > Enable ActiveX and Socket Clients).
- **Event Loop Errors**: If you encounter `asyncio` errors, ensure `nest_asyncio.apply()` is not being bypassed. It's critical for Streamlit's synchronous thread model interacting with `ib-async`.

## 📜 Trade History — Posizioni aperte e Statistiche
La pagina **Trade History** ricostruisce le posizioni ancora aperte dal ledger
(`trade_history.csv`) tramite netting delle quantità (+BOT / −SLD) e ne calcola
valore di mercato e P&L non realizzato.

- **Azioni/ETF**: prezzo corrente via `yfinance` (pulsante **🔄 Aggiorna prezzi**).
- **Opzioni**: prezzo in best-effort dal option chain di Yahoo; se non
  disponibile viene mostrato `n/d`. Un prezzo opzione *live* affidabile richiede
  la connessione a IBKR/market data.
- **IBKR (opzionale)**: se il gateway è connesso, i prezzi delle posizioni
  vengono sovrascritti con quelli reali letti da IBKR.

## 🤖 Trading Coach — configurazione
La pagina **Trading Coach** è una chat che raccoglie il tuo stile di trading e lo
salva in `trading_profile.md` (storico in `coach_history.json`, entrambi locali).

Usa un endpoint **OpenAI-compatibile**. **Default: `opencode-go`** (OpenCode
Zen Go) — basta `OPENCODE_GO_API_KEY` già presente in `.env`. Se assente, la
chiave viene scelta automaticamente nell'ordine `opencode-go` → `groq` →
`openrouter` → `google`.

Override esplicito (facoltativo):

```
TRADING_COACH_PROVIDER=opencode-go  # opencode-go | groq | openrouter | google | custom
TRADING_COACH_MODEL=deepseek-v4.1-flash
TRADING_COACH_API_KEY=...
TRADING_COACH_BASE_URL=https://opencode.ai/zen/go/v1
```

Provider predefiniti: `opencode-go` (OpenCode Zen Go, base
`https://opencode.ai/zen/go/v1`, modello `deepseek-v4.1-flash`),
`groq`, `openrouter`, `google` (Gemini, endpoint OpenAI-compatibile).
Nessun segreto è hardcoded: tutto letto da env.

### Derivazione automatica del profilo dallo storico
Nella pagina è presente il pulsante **🔎 Analizza il mio storico**: legge il
ledger `trade_history.csv`, calcola un riassunto statistico (`trade_stats.py` +
posizioni aperte da `positions.py`: win rate, profit factor, P&L per simbolo,
long/short, distribuzione mensile, holding period stimato, sizing, frequenza,
mix azioni/opzioni, campione di trade rappresentativi) e chiede all'LLM di
inferire il profilo, distinguendo **✅ Dedotto dai dati** da **❓ Da confermare
con l'utente**. Il risultato viene salvato in `trading_profile.md`. Se il
profilo non esiste, l'app propone la derivazione (nessuna chiamata LLM senza
consenso).

Il profilo salvato è riutilizzabile nel codice con `get_trading_profile()`
(da `trading_coach.py`).
