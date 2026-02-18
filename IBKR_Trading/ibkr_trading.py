import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import traceback

from ibkr_connector import IBKRConnector
from technical_analysis import add_indicators, detect_patterns

# Load .env (GOOGLE_API_KEY etc.) before importing agents
from dotenv import load_dotenv

load_dotenv()

try:
    from agents import TraderAgent
    from agents.ai_provider import AIProvider
except ImportError:
    TraderAgent = None
    AIProvider = None

# Streamlit Config
st.set_page_config(page_title="IBKR AI Trader", layout="wide")

# Session State — single connector instance, reused across reruns
if "connector" not in st.session_state:
    st.session_state.connector = IBKRConnector()
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

# Sync displayed state with actual connection
conn = st.session_state.connector
if conn.connected:
    conn.is_ready()


# ─── Helpers ────────────────────────────────────────────────────────────────


def _build_market_context() -> str:
    """Build a rich text summary of market data for the AI context."""
    meta = st.session_state.get("market_meta", {})
    df = st.session_state.get("market_df")
    analysis = st.session_state.get("market_analysis", {})

    if df is None or df.empty:
        return ""

    ticker = meta.get("ticker", "N/A")
    timeframe = meta.get("timeframe", "N/A")
    duration = meta.get("duration", "N/A")
    sec_type = meta.get("sec_type", "STK")

    # Basic info
    lines = [
        f"ASSET: {ticker} ({sec_type})",
        f"TIMEFRAME: {timeframe}  |  DURATION: {duration}",
        f"BARS: {len(df)}  |  PERIOD: {df.index[0]} → {df.index[-1]}",
        "",
    ]

    # Latest bar
    latest = df.iloc[-1]
    lines.append("── LATEST BAR ──")
    lines.append(
        f"Open: {latest['open']:.2f}  |  High: {latest['high']:.2f}  |  "
        f"Low: {latest['low']:.2f}  |  Close: {latest['close']:.2f}"
    )
    if "volume" in df.columns and pd.notna(latest.get("volume")):
        lines.append(f"Volume: {latest['volume']:,.0f}")

    # Indicators on latest bar
    lines.append("")
    lines.append("── INDICATORS (latest) ──")
    for col in [
        "RSI_14",
        "VWAP",
        "EMA_20",
        "EMA_50",
        "EMA_200",
        "MACD_12_26_9",
        "MACDh_12_26_9",
        "MACDs_12_26_9",
        "BBL_20_2.0",
        "BBM_20_2.0",
        "BBU_20_2.0",
    ]:
        if col in df.columns and pd.notna(latest.get(col)):
            lines.append(f"  {col}: {latest[col]:.4f}")

    # Pattern analysis
    lines.append("")
    lines.append("── ANALYSIS ──")
    lines.append(f"Trend: {analysis.get('trend', 'N/A')}")
    lines.append(f"RSI: {analysis.get('rsi', 'N/A')}")
    lines.append(f"Patterns: {', '.join(analysis.get('patterns', [])) or 'None'}")
    lines.append(f"Volume Spike: {analysis.get('volume_spike', False)}")

    # Last 10 bars summary (OHLCV table)
    lines.append("")
    tail = df.tail(10)
    cols_to_show = ["open", "high", "low", "close"]
    if "volume" in df.columns:
        cols_to_show.append("volume")
    lines.append(f"── LAST {len(tail)} BARS (OHLCV) ──")
    lines.append(tail[cols_to_show].to_string())

    # Include underlying stock data if this is an options analysis
    und_df = st.session_state.get("underlying_df")
    und_analysis = st.session_state.get("underlying_analysis")
    if und_df is not None and not und_df.empty and und_analysis:
        lines.append("")
        lines.append("═══════════════════════════════")
        lines.append("UNDERLYING STOCK DATA")
        lines.append("═══════════════════════════════")
        und_latest = und_df.iloc[-1]
        lines.append(
            f"Stock Price: {und_latest['close']:.2f}  |  "
            f"High: {und_latest['high']:.2f}  |  Low: {und_latest['low']:.2f}"
        )
        for col in [
            "RSI_14",
            "VWAP",
            "EMA_20",
            "EMA_50",
            "EMA_200",
            "MACD_12_26_9",
            "MACDh_12_26_9",
            "MACDs_12_26_9",
            "BBL_20_2.0",
            "BBM_20_2.0",
            "BBU_20_2.0",
        ]:
            if col in und_df.columns and pd.notna(und_latest.get(col)):
                lines.append(f"  {col}: {und_latest[col]:.4f}")
        lines.append(f"Trend: {und_analysis.get('trend', 'N/A')}")
        lines.append(f"RSI: {und_analysis.get('rsi', 'N/A')}")
        lines.append(
            f"Patterns: {', '.join(und_analysis.get('patterns', [])) or 'None'}"
        )
        # Last 10 bars of underlying
        und_tail = und_df.tail(10)
        lines.append(f"── LAST {len(und_tail)} BARS (Underlying OHLCV) ──")
        lines.append(und_tail[["open", "high", "low", "close", "volume"]].to_string())

    return "\n".join(lines)


def _chat_with_ai(user_message: str, uploaded_files=None) -> str:
    """Send a message to the AI with full market context and optional documents."""
    if not TraderAgent:
        return "⚠️ AI Agent not available (agents module not found)."

    context = _build_market_context()
    meta = st.session_state.get("market_meta", {})
    ticker = meta.get("ticker", "N/A")
    timeframe = meta.get("timeframe", "N/A")

    # Get selected AI model from session state
    provider_type = st.session_state.get("ai_provider", "gemini")
    model_name = st.session_state.get("ai_model_name")

    # Build conversation with context
    history_text = ""
    for msg in st.session_state.chat_history[-6:]:
        role = "User" if msg["role"] == "user" else "Analyst"
        history_text += f"\n{role}: {msg['content']}\n"

    text_prompt = f"""Sei un trader esperto e analista quantitativo.
Hai accesso ai seguenti dati di mercato REALI per {ticker} ({timeframe}):

{context}

{'CONVERSAZIONE PRECEDENTE:' + history_text if history_text else ''}

DOMANDA DEL TRADER:
{user_message}

ISTRUZIONI:
- Rispondi SOLO basandoti sui dati forniti sopra. Non inventare numeri.
- Se ci sono documenti allegati, analizzali nel contesto del mercato.
- Se i dati sono insufficienti per una conclusione, dillo chiaramente.
- Usa un linguaggio professionale ma conciso.
- Formatta con markdown (bold, liste ecc.) per leggibilità.
"""

    # Build multimodal prompt if files are uploaded
    if uploaded_files:
        prompt = [text_prompt]
        for f in uploaded_files:
            prompt.append({"mime_type": f.type, "data": f.getvalue()})
    else:
        prompt = text_prompt

    try:
        agent = TraderAgent(provider_type=provider_type, model_name=model_name)
        response = agent.ai.get_model().generate_content(prompt)
        return response.text
    except Exception as e:
        return f"❌ AI Error: {e}"


# ─── Sidebar ────────────────────────────────────────────────────────────────

st.sidebar.title("IBKR Connection")
host = st.sidebar.text_input("Host", "127.0.0.1")
port = st.sidebar.number_input("Port", value=7497, step=1)
client_id = st.sidebar.number_input("Client ID", value=1, step=1)

col1, col2 = st.sidebar.columns(2)
with col1:
    if st.button("Connect", use_container_width=True):
        try:
            st.session_state.connector.connect(host, port, client_id)
            st.session_state.pop("opt_cache_key", None)
            st.rerun()
        except Exception as e:
            print(f"[ERROR] Connection failed: {type(e).__name__}: {e}")
            traceback.print_exc()
            st.error(f"Connection Failed: {e}")
with col2:
    if st.button("Disconnect", use_container_width=True):
        st.session_state.connector.disconnect()
        for k in ["opt_exps", "opt_strikes", "opt_cache_key"]:
            st.session_state.pop(k, None)
        st.rerun()

# Show connection status
is_connected = st.session_state.connector.connected
st.sidebar.markdown(
    f"**Status:** {'🟢 Connected' if is_connected else '🔴 Disconnected'}"
)

# Data Selection
st.sidebar.title("Data Selection")
ticker = st.sidebar.text_input("Ticker", "AAPL")
sec_type = st.sidebar.selectbox("Security Type", ["STK", "OPT"])
timeframe = st.sidebar.selectbox("Timeframe", ["1 hour", "5 mins", "1 day"])
duration = st.sidebar.selectbox("Duration", ["1 D", "1 W", "1 M", "3 M", "6 M", "1 Y"])

# AI Model Selection
if TraderAgent and AIProvider:
    st.sidebar.title("AI Model")
    ai_provider = st.sidebar.selectbox(
        "Provider",
        ["gemini", "ollama"],
        format_func=lambda x: (
            "☁️ Gemini (Cloud)" if x == "gemini" else "🖥️ Ollama (Local)"
        ),
    )
    st.session_state.ai_provider = ai_provider

    if ai_provider == "ollama":
        ollama_models = AIProvider.get_ollama_models()
        if ollama_models:
            ai_model = st.sidebar.selectbox("Model", ollama_models)
            st.session_state.ai_model_name = ai_model
        else:
            st.sidebar.warning("No Ollama models found. Is Ollama running?")
            st.session_state.ai_model_name = None
    else:
        # For Gemini, let AIProvider auto-select the best model
        st.session_state.ai_model_name = None
        # Show which model is active
        try:
            _temp = AIProvider(provider_type="gemini")
            st.sidebar.caption(f"Auto: **{_temp.current_model_name}**")
        except Exception:
            st.sidebar.caption("Gemini (auto-select)")

# ─── Main Area ──────────────────────────────────────────────────────────────

st.title("📈 IBKR AI Trading Dashboard")

# Option Chain — auto-fetch when OPT is selected
expiry = None
strike = None
right = None

if sec_type == "OPT":
    if not is_connected:
        st.warning("⚠️ Connect to IBKR first to load Option Chain data.")
    else:
        opt_cache_key = f"opt_{ticker}"
        if st.session_state.get("opt_cache_key") != opt_cache_key:
            progress = st.progress(0, text=f"Loading option chain for {ticker}...")
            step = {"n": 0, "total": 4}

            def _on_progress(msg):
                step["n"] += 1
                pct = min(int(step["n"] / step["total"] * 100), 95)
                progress.progress(pct, text=msg)

            try:
                _on_progress(f"🔗 Qualifying {ticker}...")
                exps, strikes = st.session_state.connector.get_option_chain(
                    ticker, progress_callback=_on_progress
                )
                st.session_state["opt_exps"] = exps
                st.session_state["opt_strikes"] = strikes
                st.session_state["opt_cache_key"] = opt_cache_key
                progress.progress(
                    100,
                    text=f"✅ {len(exps)} expirations, {len(strikes)} strikes loaded",
                )
            except Exception as e:
                print(f"[ERROR] Option chain fetch failed: {type(e).__name__}: {e}")
                traceback.print_exc()
                progress.progress(100, text="❌ Failed")
                st.error(str(e))
                if st.button("🔄 Retry"):
                    st.session_state.pop("opt_cache_key", None)
                    st.rerun()

        # Show option selectors if data is available
        if (
            st.session_state.get("opt_cache_key") == opt_cache_key
            and "opt_exps" in st.session_state
        ):
            st.subheader("📋 Option Contract")
            c1, c2, c3 = st.columns(3)
            with c1:
                expiry = st.selectbox("Expiry Date", st.session_state["opt_exps"])
            with c2:
                strike = st.selectbox("Strike Price", st.session_state["opt_strikes"])
            with c3:
                right = st.selectbox(
                    "Right",
                    ["C", "P"],
                    format_func=lambda x: "📈 Call" if x == "C" else "📉 Put",
                )

# Fetch Data & Analyze
can_fetch = is_connected
if sec_type == "OPT" and (not expiry or not strike or not right):
    can_fetch = False

if st.button("Fetch Data & Analyze", disabled=not can_fetch):
    with st.spinner("Fetching historical data..."):
        try:
            # Clear previous underlying data
            st.session_state.pop("underlying_df", None)
            st.session_state.pop("underlying_analysis", None)

            opt_kwargs = {}
            if sec_type == "OPT":
                # 1. Fetch the UNDERLYING stock first (user's duration/timeframe)
                with st.spinner(f"📊 Fetching {ticker} underlying stock data..."):
                    und_df = st.session_state.connector.get_historical_data(
                        ticker,
                        sec_type="STK",
                        duration=duration,
                        bar_size_setting=timeframe,
                    )
                    if und_df is not None and not und_df.empty:
                        und_df = add_indicators(und_df)
                        st.session_state.underlying_df = und_df
                        st.session_state.underlying_analysis = detect_patterns(und_df)

                # 2. Then fetch the option data (safe defaults)
                opt_kwargs = {"expiry": expiry, "strike": strike, "right": right}
                fetch_duration = "1 M"
                fetch_timeframe = "1 hour"
            else:
                fetch_duration = duration
                fetch_timeframe = timeframe

            df = st.session_state.connector.get_historical_data(
                ticker,
                sec_type=sec_type,
                duration=fetch_duration,
                bar_size_setting=fetch_timeframe,
                **opt_kwargs,
            )

            if df is not None and not df.empty:
                df = add_indicators(df)
                analysis = detect_patterns(df)

                # Store in session state for chart + chat
                st.session_state.market_df = df
                st.session_state.market_analysis = analysis
                st.session_state.market_meta = {
                    "ticker": ticker,
                    "timeframe": timeframe,
                    "duration": duration,
                    "sec_type": sec_type,
                }
                # Reset chat and trigger initial analysis
                st.session_state.chat_history = []
                st.session_state.needs_initial_analysis = True
            else:
                st.warning("No data returned. Check market hours or contract details.")

        except Exception as e:
            print(f"[ERROR] Fetch failed: {type(e).__name__}: {e}")
            traceback.print_exc()
            st.error(f"Error ({type(e).__name__}): {e}")


# ─── Chart & Stats (persistent after fetch) ─────────────────────────────────

if "market_df" in st.session_state:
    df = st.session_state.market_df
    analysis = st.session_state.market_analysis
    meta = st.session_state.market_meta

    # Show underlying stock chart first if available (for OPT mode)
    if "underlying_df" in st.session_state and meta.get("sec_type") == "OPT":
        und_df = st.session_state.underlying_df
        und_analysis = st.session_state.underlying_analysis

        st.subheader(f"📊 {meta['ticker']} — Underlying Stock")
        col_und_chart, col_und_stats = st.columns([3, 1])

        with col_und_chart:
            fig_und = go.Figure(
                data=[
                    go.Candlestick(
                        x=und_df.index,
                        open=und_df["open"],
                        high=und_df["high"],
                        low=und_df["low"],
                        close=und_df["close"],
                        name=meta["ticker"],
                    )
                ]
            )
            if "EMA_20" in und_df.columns:
                fig_und.add_trace(
                    go.Scatter(
                        x=und_df.index,
                        y=und_df["EMA_20"],
                        mode="lines",
                        name="EMA 20",
                        line=dict(color="blue", width=1),
                    )
                )
            if "EMA_50" in und_df.columns:
                fig_und.add_trace(
                    go.Scatter(
                        x=und_df.index,
                        y=und_df["EMA_50"],
                        mode="lines",
                        name="EMA 50",
                        line=dict(color="orange", width=1),
                    )
                )
            fig_und.update_layout(
                title=f"{meta['ticker']} Underlying ({meta['timeframe']})", height=500
            )
            st.plotly_chart(fig_und, use_container_width=True)

        with col_und_stats:
            st.markdown("**Underlying Stats**")
            st.metric("Stock Price", f"{und_analysis.get('current_price', 0):.2f}")
            und_rsi = und_analysis.get("rsi")
            st.metric("RSI (14)", f"{und_rsi:.2f}" if und_rsi is not None else "N/A")
            st.write(f"**Trend:** {und_analysis.get('trend', 'N/A')}")
            st.write(
                f"**Patterns:** {', '.join(und_analysis.get('patterns', [])) or 'None'}"
            )

        st.markdown("---")

    # Main chart (STK or OPT)
    chart_label = (
        f"📈 {meta['ticker']} — Option"
        if meta.get("sec_type") == "OPT"
        else f"📈 {meta['ticker']}"
    )
    st.subheader(chart_label)

    col_chart, col_stats = st.columns([3, 1])

    with col_chart:
        fig = go.Figure(
            data=[
                go.Candlestick(
                    x=df.index,
                    open=df["open"],
                    high=df["high"],
                    low=df["low"],
                    close=df["close"],
                    name=meta["ticker"],
                )
            ]
        )
        if "EMA_20" in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df["EMA_20"],
                    mode="lines",
                    name="EMA 20",
                    line=dict(color="blue", width=1),
                )
            )
        if "EMA_50" in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df["EMA_50"],
                    mode="lines",
                    name="EMA 50",
                    line=dict(color="orange", width=1),
                )
            )
        fig.update_layout(
            title=f"{meta['ticker']} Price Chart ({meta['timeframe']})", height=600
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_stats:
        st.subheader("Technical Stats")
        st.metric("Current Price", f"{analysis.get('current_price', 0):.2f}")
        rsi_val = analysis.get("rsi")
        st.metric("RSI (14)", f"{rsi_val:.2f}" if rsi_val is not None else "N/A")
        st.write(f"**Trend:** {analysis.get('trend', 'N/A')}")
        st.write(f"**Patterns:** {', '.join(analysis.get('patterns', [])) or 'None'}")

    # ─── AI Chat ─────────────────────────────────────────────────────────────

    st.markdown("---")
    st.subheader("🤖 AI Trading Analyst")

    if not TraderAgent:
        st.info("AI Agent not available (agents module not found).")
    else:
        # Auto-generate initial analysis on first fetch
        if st.session_state.get("needs_initial_analysis"):
            st.session_state.needs_initial_analysis = False
            with st.spinner("🤖 AI analyzing market data..."):
                initial_prompt = (
                    f"Analizza la situazione di mercato per {meta['ticker']} "
                    f"sul timeframe {meta['timeframe']}. "
                    "Fornisci: 1) Analisi Sintetica, 2) Setup (Sì/No/Forse), "
                    "3) Direzione (Long/Short/Wait), 4) Livelli Chiave (S/L e T/P), "
                    "5) Probabilità di successo."
                )
                ai_response = _chat_with_ai(initial_prompt)
                st.session_state.chat_history.append(
                    {"role": "assistant", "content": ai_response}
                )

        # Render chat history
        for msg in st.session_state.chat_history:
            with st.chat_message(
                msg["role"], avatar="🤖" if msg["role"] == "assistant" else "👤"
            ):
                # Show attached file names if any
                if msg.get("files"):
                    st.caption(f"📎 {', '.join(msg['files'])}")
                st.markdown(msg["content"])

        # Document upload
        uploaded_files = st.file_uploader(
            "📎 Attach documents for context (PDF, images)",
            type=["pdf", "png", "jpg", "jpeg", "webp"],
            accept_multiple_files=True,
            key="chat_files",
        )

        # Chat input
        if user_input := st.chat_input("Ask the AI analyst about the chart data..."):
            # Track file names for display
            file_names = [f.name for f in uploaded_files] if uploaded_files else []

            # Add user message
            st.session_state.chat_history.append(
                {"role": "user", "content": user_input, "files": file_names}
            )
            with st.chat_message("user", avatar="👤"):
                if file_names:
                    st.caption(f"📎 {', '.join(file_names)}")
                st.markdown(user_input)

            # Get AI response (with uploaded files if any)
            with st.chat_message("assistant", avatar="🤖"):
                with st.spinner("Analyzing..."):
                    ai_response = _chat_with_ai(
                        user_input, uploaded_files=uploaded_files or None
                    )
                    st.markdown(ai_response)
            st.session_state.chat_history.append(
                {"role": "assistant", "content": ai_response}
            )
