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
