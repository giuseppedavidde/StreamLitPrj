import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import traceback
import os

from ibkr_connector import IBKRConnector
from technical_analysis import add_indicators, detect_patterns
from option_utils import (
    compute_greeks_table,
    historical_volatility,
    vectorized_black_scholes,
    days_to_expiry,
)

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

    import datetime

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    text_prompt = f"""Sei un trader esperto e analista quantitativo.
Oggi è il {today_str}.
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
    if st.button("Connect", width="stretch"):
        try:
            st.session_state.connector.connect(host, port, client_id)
            st.session_state.pop("opt_cache_key", None)
            st.rerun()
        except Exception as e:
            print(f"[ERROR] Connection failed: {type(e).__name__}: {e}")
            traceback.print_exc()
            st.error(f"Connection Failed: {e}")
with col2:
    if st.button("Disconnect", width="stretch"):
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
    supported_providers = AIProvider.get_supported_providers()
    ai_provider = st.sidebar.selectbox(
        "Provider",
        supported_providers,
        format_func=lambda x: (
            "☁️ Gemini (Cloud)"
            if x.lower() == "gemini"
            else "🖥️ Ollama (Local)" if x.lower() == "ollama" else "⚡ Groq (LPU Cloud)"
        ),
    )
    # The application internally relies on lowercased provider strings.
    ai_provider = ai_provider.lower()
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
        # For Gemini, let the user select the model
        try:
            gemini_models = AIProvider.get_gemini_models()
        except Exception as e:
            st.sidebar.error(f"Debug Info: {e}")
            print(f"Error fetching Gemini models: {e}")
            gemini_models = AIProvider.FALLBACK_ORDER

        if not gemini_models:
            st.sidebar.error("❌ Could not fetch Gemini models.")
            st.session_state.ai_model_name = None
        else:
            st.session_state.ai_model_name = st.sidebar.selectbox(
                "Model", gemini_models
            )

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
                        width="stretch",
                    )

                if suggest_clicked:
                    provider_type = st.session_state.get("ai_provider", "gemini")
                    model_name = st.session_state.get("ai_model_name")

                    with st.spinner(
                        "📊 Fetching data, computing Black-Scholes Greeks, querying AI..."
                    ):
                        try:
                            # Fetch daily data for 1 Year specifically for accurate Historical Volatility (HV)
                            und_df = st.session_state.connector.get_historical_data(
                                ticker,
                                sec_type="STK",
                                duration="1 Y",
                                bar_size_setting="1 day",
                            )
                            if und_df is not None and not und_df.empty:
                                und_df = add_indicators(und_df)
                                und_analysis = detect_patterns(und_df)
                                price = und_analysis.get("current_price", 0)

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

                                # Filter expirations based on actual time difference from today
                                import datetime

                                today_date = datetime.date.today()

                                def get_days_to_exp(exp_str):
                                    try:
                                        exp_date = datetime.datetime.strptime(
                                            exp_str, "%Y%m%d"
                                        ).date()
                                        return (exp_date - today_date).days
                                    except:
                                        return 0

                                horizon_targets = {
                                    "weekly": 7,
                                    "monthly": 30,
                                    "quarterly": 90,
                                }
                                target_days = horizon_targets.get(time_horizon, 30)
                                sorted_exps = sorted(
                                    available_exps,
                                    key=lambda x: abs(get_days_to_exp(x) - target_days),
                                )
                                limited_exps = sorted(sorted_exps[:3])

                                # Identify closest ATM strike and target expiration for precise IV fetching
                                best_exp = limited_exps[0] if limited_exps else None
                                closest_strike = (
                                    min(nearby_strikes, key=lambda s: abs(s - price))
                                    if nearby_strikes
                                    else None
                                )

                                # Fetch Option Implied Volatility directly from IBKR
                                iv = st.session_state.connector.get_implied_volatility(
                                    ticker,
                                    exchange="SMART",
                                    currency="USD",
                                    expiry=best_exp,
                                    strike=closest_strike,
                                )
                                # Fallback to local historical volatility if IV is unavailable
                                if iv is None or iv <= 0:
                                    iv = und_analysis.get(
                                        "hist_volatility",
                                        historical_volatility(und_df),
                                    )
                                    print(f"⚠️ Falling back to local HV: {iv}")
                                else:
                                    print(f"📊 Native IBKR IV fetched: {iv}")

                                # Compute Black-Scholes Greeks for all strike x expiry combos
                                greeks_table = []
                                for exp in limited_exps:
                                    exp_greeks = compute_greeks_table(
                                        underlying_price=price,
                                        strikes=nearby_strikes,
                                        expiry_str=exp,
                                        hist_vol=iv,
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
                                    iv=iv,
                                )
                                for s in strategies:
                                    s["iv_used"] = iv
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
                            iv_str = f"{strat.get('iv_used', 0.30)*100:.1f}%"
                            st.markdown(
                                f"\n💰 **Max Profit:** {strat.get('max_profit', 'N/A')} · "
                                f"💸 **Max Loss:** {strat.get('max_loss', 'N/A')} · "
                                f"⚖️ **Breakeven:** {strat.get('breakeven', 'N/A')} · "
                                f"📊 **IV Assunta (IBKR IV):** {iv_str}"
                            )

                            # AI Rationale (should cite real indicator values)
                            rationale = strat.get("rationale", "")
                            if rationale:
                                st.info(f"💡 {rationale}")

                            # Explicit Mathematical Calculations
                            calc = strat.get("calculations", "")
                            if calc and calc != "N/A":
                                st.success(f"🧮 **Calcoli Matematici:**\n\n{calc}")

                            # Load strategy data button
                            if st.button(
                                f"📥 Load Strategy Data & Analyze ({strat['name']})",
                                key=f"btn_load_{i}",
                            ):
                                st.session_state["selected_strategy"] = strat
                                st.session_state["strategy_data_fetch"] = True
                                st.session_state.pop(
                                    "market_df", None
                                )  # Clear single option view

                    st.markdown("---")

                    # ── Fetch AI Strategy Data ──────────────────────────────
                    if st.session_state.get(
                        "strategy_data_fetch"
                    ) and st.session_state.get("selected_strategy"):
                        strat = st.session_state["selected_strategy"]
                        st.subheader(f"🔄 Fetching Data for: {strat['name']}")

                        leg_data = []  # Store df and meta for each leg
                        status_placeholder = st.empty()

                        try:
                            # 1. Fetch the underlying stock
                            status_placeholder.info(
                                f"📊 Fetching underlying stock {ticker}..."
                            )
                            und_df = st.session_state.connector.get_historical_data(
                                ticker,
                                sec_type="STK",
                                duration=duration,
                                bar_size_setting=timeframe,
                            )
                            if und_df is not None and not und_df.empty:
                                und_df = add_indicators(und_df)
                                st.session_state.underlying_df = und_df
                                st.session_state.underlying_analysis = detect_patterns(
                                    und_df
                                )

                            # 2. Fetch each option leg
                            for leg_idx, leg in enumerate(strat.get("legs", []), 1):
                                leg_name = f"{leg['right']} {leg['strike']} exp {leg['expiry']}"
                                status_placeholder.info(
                                    f"⏳ Fetching Leg {leg_idx}: {leg_name}..."
                                )

                                leg_df = st.session_state.connector.get_historical_data(
                                    ticker,
                                    sec_type="OPT",
                                    duration=duration,  # Use user's selected duration
                                    bar_size_setting=timeframe,  # Use user's selected timeframe
                                    strike=leg["strike"],
                                    expiry=leg["expiry"],
                                    right=leg["right"],
                                )

                                if leg_df is not None and not leg_df.empty:
                                    leg_df = add_indicators(leg_df)
                                    leg_meta = {
                                        "leg_id": leg_idx,
                                        "action": leg["action"],
                                        "quantity": leg.get("quantity", 1),
                                        "strike": leg["strike"],
                                        "expiry": leg["expiry"],
                                        "right": leg["right"],
                                        "name": leg_name,
                                        "greeks": leg.get("greeks", {}),
                                    }
                                    leg_data.append({"meta": leg_meta, "df": leg_df})
                                else:
                                    st.warning(
                                        f"⚠️ No data returned for Leg {leg_idx} ({leg_name})."
                                    )

                            st.session_state["strategy_legs_data"] = leg_data
                            st.session_state["strategy_data_fetch"] = (
                                False  # Reset flag
                            )
                            status_placeholder.success(
                                f"✅ Data loaded for {len(leg_data)} legs of {strat['name']}!"
                            )

                        except Exception as e:
                            status_placeholder.error(
                                f"❌ Error fetching strategy data: {e}"
                            )
                            print(f"[ERROR] Strategy Fetch: {type(e).__name__}: {e}")
                            traceback.print_exc()

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

if "strategy_legs_data" in st.session_state and st.session_state["strategy_legs_data"]:
    strat_meta = st.session_state.get("selected_strategy", {})
    leg_data_list = st.session_state["strategy_legs_data"]

    st.subheader(
        f"📊 Strategy Analysis: {strat_meta.get('name', 'Custom Option Strategy')}"
    )

    # Render individual leg metrics
    st.markdown("**Option Legs Technicals:**")
    cols = st.columns(len(leg_data_list))
    for i, leg_bundle in enumerate(leg_data_list):
        meta = leg_bundle["meta"]
        df_leg = leg_bundle["df"]
        with cols[i]:
            st.markdown(f"**{meta['name']}** ({meta['action']} {meta['quantity']}x)")
            if df_leg is not None and not df_leg.empty:
                latest = df_leg.iloc[-1]
                st.metric("Price", f"${latest['close']:.2f}")
                vwap_val = latest.get("VWAP")
                vwap_val = vwap_val if pd.notna(vwap_val) else 0.0
                rsi_val = latest.get("RSI_14")
                rsi_val = rsi_val if pd.notna(rsi_val) else 0.0
                vol_val = latest.get("volume")
                vol_val = vol_val if pd.notna(vol_val) else 0.0

                st.write(f"**VWAP:** ${vwap_val:.2f}")
                st.write(f"**RSI(14):** {rsi_val:.1f}")
                st.write(f"**Vol:** {vol_val:,.0f}")
            elif "greeks" in meta and "price" in meta["greeks"]:
                st.metric("Price", f"${meta['greeks']['price']:.2f}")
            else:
                st.warning("Data unavailable.")

            if "greeks" in meta and meta["greeks"]:
                st.caption(
                    f"Δ: {meta['greeks'].get('delta', 0):.2f} | Θ: {meta['greeks'].get('theta', 0):.3f}"
                )

    st.markdown("---")

    # Calculate and plot Net Payoff (P/L) Chart
    st.subheader("📈 Dynamic Payoff (P/L) Profile")

    und_price = 100.0
    if "underlying_df" in st.session_state and not st.session_state.underlying_df.empty:
        und_price = st.session_state.underlying_df.iloc[-1]["close"]

    import numpy as np

    # Generate price range +/- 25% from current underlying
    prices = np.linspace(und_price * 0.75, und_price * 1.25, 200)
    net_pl = np.zeros_like(prices)
    net_pl_t0 = np.zeros_like(prices)
    net_pl_thalf = np.zeros_like(prices)

    # Extraiamo l'IV dalla strategia (fallback 30%)
    iv = float(strat_meta.get("iv_used", strat_meta.get("hv_used", 0.30)))

    for leg_bundle in leg_data_list:
        meta = leg_bundle["meta"]
        strike = float(meta["strike"])
        qty = float(meta["quantity"])
        right = meta["right"].upper()
        is_buy = 1 if meta["action"].upper() == "BUY" else -1
        expiry_str = meta.get("expiry", "")
        dte = days_to_expiry(expiry_str) if expiry_str else 30

        # Use greeks price if available, else fallback to latest close from df
        entry_price = 0.0
        if "greeks" in meta and "price" in meta["greeks"]:
            entry_price = float(meta["greeks"]["price"])
        elif leg_bundle["df"] is not None and not leg_bundle["df"].empty:
            entry_price = leg_bundle["df"].iloc[-1]["close"]

        # Calculate intrinsic value at expiration
        if right == "C":
            payoff = np.maximum(prices - strike, 0)
        else:
            payoff = np.maximum(strike - prices, 0)

        # Net P/L for this leg at expiration
        leg_pl = (
            (payoff - entry_price) * is_buy * qty * 100
        )  # * 100 multiplier per contract
        net_pl += leg_pl

        # T+0 (Today) Dynamic Pricing
        leg_t0_price = vectorized_black_scholes(prices, strike, dte, 0.05, iv, right)
        leg_pl_t0 = (leg_t0_price - entry_price) * is_buy * qty * 100
        net_pl_t0 += leg_pl_t0

        # T+Half (Halfway to expiry) Dynamic Pricing
        leg_thalf_price = vectorized_black_scholes(
            prices, strike, dte / 2.0, 0.05, iv, right
        )
        leg_pl_thalf = (leg_thalf_price - entry_price) * is_buy * qty * 100
        net_pl_thalf += leg_pl_thalf

    fig_pl = go.Figure()

    # Dynamic T+0 Line (Today)
    fig_pl.add_trace(
        go.Scatter(
            x=prices,
            y=net_pl_t0,
            mode="lines",
            name="T+0 (Today)",
            line=dict(color="orange", width=2, dash="dash"),
        )
    )

    # Dynamic T+Half Line
    fig_pl.add_trace(
        go.Scatter(
            x=prices,
            y=net_pl_thalf,
            mode="lines",
            name="T+Half",
            line=dict(color="yellow", width=2, dash="dot"),
        )
    )

    # Expiration Line
    fig_pl.add_trace(
        go.Scatter(
            x=prices,
            y=net_pl,
            mode="lines",
            name="At Expiration",
            line=dict(color="#00ffcc", width=3),
        )
    )

    # Add horizontal zero line
    fig_pl.add_hline(y=0, line_dash="dash", line_color="gray")
    # Add vertical line for current underlying price
    fig_pl.add_vline(
        x=und_price,
        line_dash="dash",
        line_color="yellow",
        annotation_text="Current",
        annotation_position="top right",
    )

    # Fill colors for profit / loss
    fig_pl.add_trace(
        go.Scatter(
            x=prices,
            y=np.maximum(net_pl, 0),
            fill="tozeroy",
            fillcolor="rgba(0, 255, 0, 0.2)",
            line=dict(color="rgba(255,255,255,0)"),
            showlegend=False,
            name="Profit Zone",
        )
    )
    fig_pl.add_trace(
        go.Scatter(
            x=prices,
            y=np.minimum(net_pl, 0),
            fill="tozeroy",
            fillcolor="rgba(255, 0, 0, 0.2)",
            line=dict(color="rgba(255,255,255,0)"),
            showlegend=False,
            name="Loss Zone",
        )
    )

    fig_pl.update_layout(
        xaxis_title="Underlying Price at Expiration",
        yaxis_title="Net P/L ($)",
        height=500,
        margin=dict(l=20, r=20, t=30, b=20),
    )
    st.plotly_chart(fig_pl, width="stretch")

    # ─── Manual Strategy Builder ─────────────────────────────────────────────
    with st.expander("🛠️ Manual Strategy Builder (Tweak Current)", expanded=False):
        st.markdown(
            "Modify the loaded strategy legs. Click **Recalculate & Plot** to update the chart."
        )

        # We need a form or keys for each leg
        new_legs = []

        # Header row
        h1, h2, h3, h4, h5 = st.columns(5)
        h1.write("**Action**")
        h2.write("**Quantity**")
        h3.write("**Strike**")
        h4.write("**Right**")
        h5.write("**Expiry (YYYYMMDD)**")

        for i, leg_bundle in enumerate(leg_data_list):
            meta = leg_bundle["meta"]

            c1, c2, c3, c4, c5 = st.columns(5)
            with c1:
                action = st.selectbox(
                    f"Action_{i}",
                    ["BUY", "SELL"],
                    index=0 if meta["action"].upper() == "BUY" else 1,
                    label_visibility="collapsed",
                )
            with c2:
                qty = st.number_input(
                    f"Qty_{i}",
                    min_value=1,
                    value=int(meta["quantity"]),
                    label_visibility="collapsed",
                )
            with c3:
                strike = st.number_input(
                    f"Strike_{i}",
                    value=float(meta["strike"]),
                    step=0.5,
                    format="%.2f",
                    label_visibility="collapsed",
                )
            with c4:
                right = st.selectbox(
                    f"Right_{i}",
                    ["C", "P"],
                    index=0 if meta["right"].upper() == "C" else 1,
                    label_visibility="collapsed",
                )
            with c5:
                expiry = st.text_input(
                    f"Expiry_{i}",
                    value=meta.get("expiry", ""),
                    label_visibility="collapsed",
                )

            new_legs.append(
                {
                    "action": action,
                    "quantity": qty,
                    "strike": strike,
                    "right": right,
                    "expiry": expiry,
                }
            )

        if st.button("🔄 Recalculate & Plot", width="stretch"):
            from option_utils import compute_greeks_table

            # Recalculate the entire greeks table locally based on the tweaker
            # We assume we have the original underlying price and IV
            recalculated_strategy = dict(strat_meta)  # copy previous keys like iv_used
            recalculated_strategy["name"] = (
                f"Custom Tweaked: {strat_meta.get('name', '')}"
            )

            # Recompute greeks per leg using Black-Scholes function via compute_greeks_table
            # Need to create fresh 'strategy_legs_data' based on this
            new_leg_data_list = []
            for n_leg in new_legs:
                # We do a tiny greeks request just for this strike
                g_table = compute_greeks_table(
                    und_price, [n_leg["strike"]], n_leg["expiry"], iv, 0.05
                )
                if g_table:
                    # g_table[0] has 'call' and 'put'. Pick the correct one.
                    g_leg = (
                        g_table[0]["call"]
                        if n_leg["right"] == "C"
                        else g_table[0]["put"]
                    )
                    # Build dummy meta bundle
                    new_meta = {
                        "name": f"Leg {n_leg['strike']} {n_leg['right']}",
                        "action": n_leg["action"],
                        "quantity": n_leg["quantity"],
                        "strike": n_leg["strike"],
                        "right": n_leg["right"],
                        "expiry": n_leg["expiry"],
                        "greeks": g_leg,
                    }
                    new_leg_data_list.append(
                        {"meta": new_meta, "df": None}
                    )  # Can't reliably refetch df here synchronously

            st.session_state["selected_strategy"] = recalculated_strategy
            st.session_state["strategy_legs_data"] = new_leg_data_list
            st.rerun()

    # ─── Strategy AI Chat ────────────────────────────────────────────────────
    st.markdown("---")
    st.subheader("🤖 Strategy Chat Analyst")

    if "strategy_chat" not in st.session_state:
        st.session_state.strategy_chat = []

    if not TraderAgent:
        st.info("AI Agent not available (agents module not found).")
    else:
        # Calculate summary metrics to feed the AI
        max_profit = float(np.max(net_pl))
        max_loss = float(np.min(net_pl))

        # Determine Breakevens
        # Find points where net_pl crosses 0
        signs = np.sign(net_pl)
        signs[signs == 0] = -1
        crossings = np.where(np.diff(signs))[0]
        breakevens = [prices[idx] for idx in crossings]

        # Build Positions String gracefully
        pos_list = []
        if new_legs:
            pos_list = [
                f"{l['quantity']}x {l['action']} {l['strike']}{l['right']}"
                for l in new_legs
            ]
        else:
            pos_list = [
                f"{leg['meta'].get('quantity')}x {leg['meta'].get('action')} {leg['meta'].get('strike')}{leg['meta'].get('right')}"
                for leg in leg_data_list
            ]
        positions_str = ", ".join(pos_list)

        # Construct Hidden Context
        hidden_context = (
            f"STRATEGY CONTEXT TO ASSIST USER:\n"
            f"Underlying: {strat_meta.get('ticker','')} at ${und_price:.2f}\n"
            f"IV Assumed: {iv*100:.1f}%\n"
            f"Positions: {positions_str}\n"
            f"Calculated Max Profit at Expiration: ${max_profit:.2f}\n"
            f"Calculated Max Loss at Expiration: ${max_loss:.2f}\n"
            f"Breakeven Price(s): {[round(be, 2) for be in breakevens]}\n"
        )

        # Render chat history
        for msg in st.session_state.strategy_chat:
            if msg["role"] != "system":  # Don't show hidden contexts
                with st.chat_message(
                    msg["role"], avatar="🤖" if msg["role"] == "assistant" else "👤"
                ):
                    st.markdown(msg["content"])

        if strat_user_input := st.chat_input(
            "Ask about this P/L profile or how to adjust it..."
        ):
            st.session_state.strategy_chat.append(
                {"role": "user", "content": strat_user_input}
            )
            with st.chat_message("user", avatar="👤"):
                st.markdown(strat_user_input)

            with st.spinner("🤖 Analyzing the generated strategy..."):
                try:
                    # Provide system state and short user query to underlying _chat_with_ai or general AI
                    # Reusing the singleton TraderAgent to get raw text
                    agent = TraderAgent(
                        provider_type=st.session_state.get("ai_provider", "gemini"),
                        model_name=st.session_state.get("ai_model_name"),
                    )
                    prompt = f"Sei un Quantitative Options Analyst. Rispondi in italiano.\n\n{hidden_context}\n\nUser Question: {strat_user_input}"

                    response = agent.ai.get_model().generate_content(prompt)
                    ai_text = response.text

                    st.session_state.strategy_chat.append(
                        {"role": "assistant", "content": ai_text}
                    )
                    with st.chat_message("assistant", avatar="🤖"):
                        st.markdown(ai_text)
                except Exception as e:
                    st.error(f"Strategy AI Error: {e}")

elif "market_df" in st.session_state:
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
            st.plotly_chart(fig_und, width="stretch")

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
        st.plotly_chart(fig, width="stretch")

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
