# 📈 IBKR Trading Intelligence Platform

A high-performance, asynchronous algorithmic trading and visualization dashboard integrating Interactive Brokers (IBKR) with AI-driven market analysis. 

Built for modern algorithmic traders, this platform bridges the gap between low-latency trade execution, advanced technical analysis, and Large Language Model (LLM) decision support.

---

## ✨ The "Juice" (Why this project exists)
Traditional trading dashboards are either clunky (TWS) or closed-source. We built this platform to provide a **transparent, highly extendable, and fast** UI using Streamlit, powered by the battle-tested `ib-async` library.

**Key Strengths:**
- ⚡ **True Asynchrony**: Built on `asyncio` and `ib-async`, preventing blocking calls during market data streaming or order execution.
- 🧠 **AI-Driven Support**: Integrated with LLM providers (Groq/OpenAI) to provide contextual analysis on technical indicators and earnings data.
- 📊 **Pro-Grade Viz**: Interactive, responsive charting using Plotly.
- 🧪 **Historical Verification**: Includes a dedicated earnings backtester engine to validate strategies before risking capital.

## 🏗 Architecture & Mental Model

The project is structured into distinct, decoupled modules to ensure maintainability:

### Core Components

- **`ibkr_trading.py` (Entry Point & UI Layer)**
  The main Streamlit application. Orchestrates the layout, user inputs, and delegates work to the underlying modules. Uses `nest-asyncio` to bridge Streamlit's sync execution with our async backend.

- **`ibkr_connector.py` (Broker Integration)**
  The gateway to Interactive Brokers. Manages connection state, handles reconnections, streams live ticker data, and dispatches orders.

- **`technical_analysis.py` (Quant Engine)**
  Processes OHLCV data using the `ta` library and `scipy`. Generates technical indicators (RSI, MACD, Bollinger Bands) independent of the UI state.

- **`earnings_backtester.py` (Simulation)**
  A dedicated engine for backtesting strategies specifically around earnings events, comparing historical estimates vs. actuals and simulating PnL.

- **`option_utils.py` (Derivatives)**
  Shared helper functions for pricing options, formatting strike chains, and calculating greeks.

### Data Flow Pattern
1. User interacts with Streamlit UI (`ibkr_trading.py`).
2. App requests async data fetch via `ibkr_connector.py`.
3. Raw data is pushed to `technical_analysis.py` for enrichment.
4. Enriched DataFrame is passed to Plotly for rendering back in the UI.

## ⚠️ Current Limitations & Roadmap

As a transparent engineering team, here are the current gaps we are tracking:

- **Error Handling Coverage**: While connection drops are handled, some core parsing modules need more robust `try/except` blocks to prevent dashboard crashes on malformed API responses.
- **Pending TODOs**: There are several `FIXME` and `TODO` tags in the codebase regarding edge-cases in option chain parsing.
- **State Management**: Streamlit's `st.session_state` can become bloated. A future refactor should introduce a more formal state management pattern for the IBKR connection object.

---
> [!IMPORTANT]
> **Ready to run the code?** 
> Head over to our [USAGE.md](USAGE.md) for a 2-minute quick start guide, including dependency setup and execution commands.
