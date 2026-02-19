import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import traceback
import os

from ibkr_connector import IBKRConnector
from technical_analysis import add_indicators, detect_patterns
from option_utils import compute_greeks_table, historical_volatility

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
        actual_model = agent.ai.current_model_name
        print(f"🤖 Chat using: {provider_type} / {actual_model}")
        response = agent.ai.get_model().generate_content(prompt)
        model_badge = f"*🤖 Model: `{provider_type}` / `{actual_model}`*\n\n---\n\n"
        return model_badge + response.text
    except Exception as e:
        return f"❌ AI Error ({provider_type}/{model_name}): {e}"


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
        ["gemini", "ollama", "groq"],
        format_func=lambda x: (
            "☁️ Gemini (Cloud)"
            if x == "gemini"
            else "🖥️ Ollama (Local)" if x == "ollama" else "⚡ Groq (LPU Cloud)"
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
    elif ai_provider == "groq":
        # Groq specific verification
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            api_key = st.sidebar.text_input("Groq API Key", type="password")
            if api_key:
                os.environ["GROQ_API_KEY"] = api_key

        if not os.getenv("GROQ_API_KEY"):
            st.sidebar.warning("🔑 Groq API Key required.")
            st.session_state.ai_model_name = None
        else:
            try:
                # Fetch models dynamically using the confirmed key
                groq_models = AIProvider.get_groq_models(
                    api_key=os.getenv("GROQ_API_KEY")
                )
            except Exception as e:
                st.sidebar.error(f"Debug Info: {e}")
                print(f"Error fetching Groq models: {e}")
                groq_models = []

            if not groq_models:
                st.sidebar.error("❌ Could not fetch Groq models. Check API Key.")
                st.session_state.ai_model_name = None
            else:
                st.session_state.ai_model_name = st.sidebar.selectbox(
                    "Model", groq_models
                )
    else:
        # For Gemini, let AIProvider auto-select the best model
        st.session_state.ai_model_name = None
        # Show which model is active
        try:
            _temp = AIProvider(provider_type="gemini")
            st.sidebar.caption(f"Auto: **{_temp.current_model_name}**")
        except Exception:
            st.sidebar.caption("Gemini (auto-select)")

# EMA Colors
if TraderAgent and AIProvider:
    with st.sidebar.expander("🎨 EMA Colors", expanded=False):
        ema20_color = st.color_picker("EMA 20", "#00BFFF", key="ema20_color")
        ema50_color = st.color_picker("EMA 50", "#FFD700", key="ema50_color")
        ema200_color = st.color_picker("EMA 200", "#FF1493", key="ema200_color")
else:
    ema20_color, ema50_color, ema200_color = "#00BFFF", "#FFD700", "#FF1493"

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

            available_exps = st.session_state["opt_exps"]
            available_strikes = st.session_state["opt_strikes"]

            # ── AI Strategy Suggestion ──────────────────────────────
            if TraderAgent and AIProvider:
                ai_col1, ai_col2 = st.columns([1, 3])
                with ai_col1:
                    time_horizon = st.radio(
                        "⏱️ Horizon",
                        ["weekly", "monthly", "quarterly"],
                        index=1,
                        format_func=lambda x: {
                            "weekly": "📅 Weekly",
                            "monthly": "📆 Monthly",
                            "quarterly": "📊 Quarterly",
                        }[x],
                        horizontal=True,
                    )
                with ai_col2:
                    suggest_clicked = st.button(
                        "🤖 AI Suggest Strategy",
                        use_container_width=True,
                    )

                if suggest_clicked:
                    provider_type = st.session_state.get("ai_provider", "gemini")
                    model_name = st.session_state.get("ai_model_name")

                    with st.spinner(
                        "📊 Fetching data, computing Black-Scholes Greeks, querying AI..."
                    ):
                        try:
                            und_df = st.session_state.connector.get_historical_data(
                                ticker,
                                sec_type="STK",
                                duration="1 M",
                                bar_size_setting="1 hour",
                            )
                            if und_df is not None and not und_df.empty:
                                und_df = add_indicators(und_df)
                                und_analysis = detect_patterns(und_df)
                                price = und_analysis.get("current_price", 0)

                                # Compute real historical volatility
                                hv = und_analysis.get(
                                    "hist_volatility",
                                    historical_volatility(und_df),
                                )

                                # Filter strikes near ATM for Greeks computation
                                atm_range = price * 0.10
                                nearby_strikes = sorted(
                                    [
                                        s
                                        for s in available_strikes
                                        if abs(s - price) <= atm_range
                                    ]
                                )
                                if len(nearby_strikes) < 4:
                                    nearby_strikes = sorted(available_strikes[:20])

                                # Filter expirations by horizon
                                horizon_map = {
                                    "weekly": 1,
                                    "monthly": 2,
                                    "quarterly": 4,
                                }
                                max_exps = horizon_map.get(time_horizon, 2)
                                limited_exps = available_exps[:max_exps]

                                # Compute Black-Scholes Greeks for all strike x expiry combos
                                greeks_table = []
                                for exp in limited_exps:
                                    exp_greeks = compute_greeks_table(
                                        underlying_price=price,
                                        strikes=nearby_strikes,
                                        expiry_str=exp,
                                        hist_vol=hv,
                                    )
                                    greeks_table.extend(exp_greeks)

                                agent = TraderAgent(
                                    provider_type=provider_type,
                                    model_name=model_name,
                                )
                                strategies = agent.suggest_option_strategy(
                                    ticker=ticker,
                                    analysis=und_analysis,
                                    expirations=available_exps,
                                    strikes=available_strikes,
                                    underlying_price=price,
                                    time_horizon=time_horizon,
                                    greeks_table=greeks_table,
                                )
                                st.session_state["ai_strategies"] = strategies
                                st.session_state["ai_strategies_model"] = (
                                    f"{provider_type}/{agent.ai.current_model_name}"
                                )
                            else:
                                st.warning(
                                    "Could not fetch underlying data for analysis."
                                )
                        except Exception as e:
                            st.error(f"❌ AI Strategy Error: {e}")
                            print(f"[ERROR] AI Strategy: {type(e).__name__}: {e}")
                            traceback.print_exc()

                # Display strategy cards if available
                if (
                    "ai_strategies" in st.session_state
                    and st.session_state["ai_strategies"]
                ):
                    strategies = st.session_state["ai_strategies"]
                    model_used = st.session_state.get("ai_strategies_model", "")
                    st.caption(f"*🤖 Suggested by `{model_used}`*")

                    for i, strat in enumerate(strategies):
                        prob = strat.get("probability", 50)
                        dir_icon = {
                            "BULLISH": "🟢",
                            "BEARISH": "🔴",
                            "NEUTRAL": "🟡",
                        }.get(strat.get("direction", "NEUTRAL"), "⚪")
                        prob_bar = "🟢" if prob >= 60 else "🟡" if prob >= 45 else "🔴"

                        with st.expander(
                            f"{dir_icon} **{strat['name']}** — {strat.get('direction', 'NEUTRAL')} — {prob_bar} {prob}%",
                            expanded=(i == 0),
                        ):
                            # Legs table with REAL Greeks
                            st.markdown("**📋 Operazioni da eseguire:**")
                            for j, leg in enumerate(strat.get("legs", []), 1):
                                action_icon = (
                                    "🟢 BUY" if leg["action"] == "BUY" else "🔴 SELL"
                                )
                                right_label = "Call" if leg["right"] == "C" else "Put"
                                qty = leg.get("quantity", 1)
                                strike_str = f"**{leg['strike']}**"
                                if leg.get("strike_corrected"):
                                    strike_str += " ⚠️"
                                exp_str = f"`{leg['expiry']}`"
                                if leg.get("expiry_corrected"):
                                    exp_str += " ⚠️"
                                leg_text = (
                                    f"**Leg {j}:** {action_icon} **{qty}x {right_label}** "
                                    f"Strike {strike_str} — Exp {exp_str}"
                                )
                                # Show real calculated Greeks if available
                                g = leg.get("greeks")
                                if g:
                                    leg_text += (
                                        f"  \n"
                                        f"  _Δ={g['delta']:+.3f}  "
                                        f"Γ={g['gamma']:.4f}  "
                                        f"Θ={g['theta']:+.4f}/day  "
                                        f"ν={g['vega']:.4f}  "
                                        f"Price=${g['price']:.2f}_"
                                    )
                                st.markdown(leg_text)

                            # P/L summary
                            st.markdown(
                                f"\n💰 **Max Profit:** {strat.get('max_profit', 'N/A')} · "
                                f"💸 **Max Loss:** {strat.get('max_loss', 'N/A')} · "
                                f"⚖️ **Breakeven:** {strat.get('breakeven', 'N/A')}"
                            )

                            # AI Rationale (should cite real indicator values)
                            rationale = strat.get("rationale", "")
                            if rationale:
                                st.info(f"💡 {rationale}")

                    st.markdown("---")

            # ── Manual Selectors (with AI pre-fill) ─────────────────
            # Determine default indices from AI selection or fallback
            default_exp_idx = 0
            default_strike_idx = 0
            default_right_idx = 0

            if "opt_selected_expiry" in st.session_state:
                sel_exp = st.session_state["opt_selected_expiry"]
                if sel_exp in available_exps:
                    default_exp_idx = available_exps.index(sel_exp)

            if "opt_selected_strike" in st.session_state:
                sel_strike = st.session_state["opt_selected_strike"]
                if sel_strike in available_strikes:
                    default_strike_idx = available_strikes.index(sel_strike)

            if "opt_selected_right" in st.session_state:
                default_right_idx = (
                    0 if st.session_state["opt_selected_right"] == "C" else 1
                )

            c1, c2, c3 = st.columns(3)
            with c1:
                expiry = st.selectbox(
                    "Expiry Date", available_exps, index=default_exp_idx
                )
            with c2:
                strike = st.selectbox(
                    "Strike Price", available_strikes, index=default_strike_idx
                )
            with c3:
                right = st.selectbox(
                    "Right",
                    ["C", "P"],
                    index=default_right_idx,
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
                        line=dict(color=ema20_color, width=2),
                    )
                )
            if "EMA_50" in und_df.columns:
                fig_und.add_trace(
                    go.Scatter(
                        x=und_df.index,
                        y=und_df["EMA_50"],
                        mode="lines",
                        name="EMA 50",
                        line=dict(color=ema50_color, width=2),
                    )
                )
            if "EMA_200" in und_df.columns:
                fig_und.add_trace(
                    go.Scatter(
                        x=und_df.index,
                        y=und_df["EMA_200"],
                        mode="lines",
                        name="EMA 200",
                        line=dict(color=ema200_color, width=2, dash="dash"),
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
                    line=dict(color=ema20_color, width=2),
                )
            )
        if "EMA_50" in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df["EMA_50"],
                    mode="lines",
                    name="EMA 50",
                    line=dict(color=ema50_color, width=2),
                )
            )
        if "EMA_200" in df.columns:
            fig.add_trace(
                go.Scatter(
                    x=df.index,
                    y=df["EMA_200"],
                    mode="lines",
                    name="EMA 200",
                    line=dict(color=ema200_color, width=2, dash="dash"),
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
