import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import traceback
import os
import subprocess
import shutil

from ibkr_connector import IBKRConnector
from technical_analysis import add_indicators, detect_patterns, get_holders_info, get_financial_info
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
    from agents.opencode_debate import OpencodeDebate
    from agents.opencode_agent import OpencodeAgent
    from agents import load_skills_knowledge
except ImportError:
    TraderAgent = None
    AIProvider = None
    load_skills_knowledge = None
    OpencodeDebate = None
    OpencodeAgent = None

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

    # Add holders info
    holders = st.session_state.get("market_holders", {})
    if holders.get("institutional_holders") or holders.get("etf_mutualfund_holders"):
        lines.append("")
        lines.append("── HOLDERS INFO (TOP 5) ──")
        if holders.get("institutional_holders"):
            lines.append("Institutions:")
            for h in holders["institutional_holders"]:
                lines.append(f"  - {h['Holder']}: {h['Shares']:,} shares ({h['pctHeld']*100:.2f}%)")
        if holders.get("etf_mutualfund_holders"):
            lines.append("ETFs/Mutual Funds:")
            for h in holders["etf_mutualfund_holders"]:
                lines.append(f"  - {h['Holder']}: {h['Shares']:,} shares ({h['pctHeld']*100:.2f}%)")

    # Add financial info
    financials = st.session_state.get("market_financials", {})
    if financials:
        lines.append("")
        lines.append("── FINANCIAL FUNDAMENTALS ──")
        for k, v in financials.items():
            if isinstance(v, float):
                # Formattiamo come percentuale se è un margine/ritorno o crescita
                if any(x in k.lower() for x in ['margin', 'yield', 'return', 'growth']):
                    lines.append(f"  {k}: {v*100:.2f}%")
                else:
                    lines.append(f"  {k}: {v:.2f}")
            else:
                lines.append(f"  {k}: {v}")

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

    # Initialize agent to extract appropriate knowledge based on security type
    agent = TraderAgent(provider_type=provider_type, model_name=model_name)
    sec_type = meta.get("sec_type", "STK")

    if sec_type == "OPT":
        skill_fw = load_skills_knowledge(["options-playbook", "options-course-workbook", "options-crash-course"]) if load_skills_knowledge else {}
        kb = "\n\n".join(skill_fw.values()) if skill_fw else getattr(agent, "knowledge", {}).get("options", "")
        kb_name = "Opencode Skills (Options)"
        kb_section = (
            f"\nCONOSCENZA TEORICA (Options Skill Frameworks):\n{kb}\n" if kb else ""
        )
        system_role = "Sei un Quantitative Options Analyst, esperto di strategie in opzioni e greche."
    else:
        skill_fw = load_skills_knowledge(["wyckoff-2-0", "volume-price-analysis", "volume-profile", "trades-about-to-happen", "trading-against-the-crowd"]) if load_skills_knowledge else {}
        volman_fw = load_skills_knowledge(["price-action-volman"]) if load_skills_knowledge else {}
        trading_kb = "\n\n".join(skill_fw.values()) if skill_fw else getattr(agent, "knowledge", {}).get("trading", "")
        scalping_kb = "\n\n".join(volman_fw.values()) if volman_fw else getattr(agent, "knowledge", {}).get("scalping_trading", "")
        kb_name = "Opencode Skills (Stocks)"
        kb_parts = []
        if trading_kb:
            kb_parts.append(
                f"\nCONOSCENZA ONDA MEDIA (Wyckoff, VPA, Volume Profile, Order Flow, Sentiment):\n{trading_kb}\n"
            )
        if scalping_kb:
            kb_parts.append(
                f"\nCONOSCENZA BREVE TERMINE (Volman Scalping):\n{scalping_kb}\n"
            )
        kb_section = "\n".join(kb_parts) if kb_parts else ""
        system_role = "Sei un trader esperto e analista quantitativo, specializzato in Wyckoff Method, Volume Price Analysis (VPA), Order Flow e Price Action."

    # Build conversation with context
    history_text = ""
    for msg in st.session_state.chat_history[-6:]:
        role = "User" if msg["role"] == "user" else "Analyst"
        history_text += f"\n{role}: {msg['content']}\n"

    import datetime

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    text_prompt = f"""{system_role}
Oggi è il {today_str}.
I tuoi principi chiave operativi sono basati su questa knowledge base:
{kb_section}

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
        actual_model = agent.ai.current_model_name
        print(f"🤖 Chat using: {provider_type} / {actual_model} | KB: {kb_name}")
        response = agent.ai.get_model().generate_content(prompt)

        # Build model badge — include LlamaCpp stats if available
        badge_parts = [
            f"*🤖 Model: `{provider_type}` / `{actual_model}`*",
            f"*📚 Knowledge: `{kb_name}`*",
        ]
        if hasattr(response, "tokens_per_sec") and response.tokens_per_sec > 0:
            badge_parts.append(f"*⚡ {response.tokens_per_sec:.1f} t/s*")
        if hasattr(response, "total_tokens") and response.total_tokens > 0:
            badge_parts.append(f"*🔢 {response.total_tokens} tokens*")
        if hasattr(response, "duration_sec") and response.duration_sec > 0:
            badge_parts.append(f"*⏱️ {response.duration_sec:.1f}s*")

        model_badge = "  |  ".join(badge_parts) + "\n\n---\n\n"
        return model_badge + response.text
    except Exception as e:
        return f"❌ AI Error ({provider_type}/{model_name}): {e}"


import yfinance as yf
import pandas as pd

def get_historical_data_with_fallback(connector, ticker, **kwargs):
    df = None
    data_source = "IBKR"
    
    sec_type = kwargs.get("sec_type", "STK")
    duration = kwargs.get("duration", "6 M")
    
    # Only attempt IBKR if the connector is actually connected
    if connector.connected:
        try:
            df = connector.get_historical_data(ticker, **kwargs)
        except Exception as e:
            print(f"IBKR fetch failed for {ticker}: {e}")
    else:
        print(f"IBKR not connected, skipping for {ticker}")

    if (df is None or df.empty) and sec_type == "STK":
        print(f"Attempting yfinance fallback for {ticker}")
        try:
            dur = duration.upper().replace(" ", "")
            period_map = {"1D": "5d", "1W": "5d", "1M": "1mo", "3M": "3mo", "6M": "6mo", "1Y": "1y", "2Y": "2y", "5Y": "5y"}
            p = period_map.get(dur, "6mo")
            
            # Map bar_size_setting to yfinance interval
            bar_size = kwargs.get("bar_size_setting", "1 day").lower()
            interval_map = {"1 min": "1m", "5 mins": "5m", "15 mins": "15m", "30 mins": "30m", "1 hour": "1h", "1 day": "1d", "1 week": "1wk", "1 month": "1mo"}
            interval = interval_map.get(bar_size, "1d")
            
            yf_df = yf.download(ticker, period=p, interval=interval, progress=False)
            if yf_df is not None and not yf_df.empty:
                if isinstance(yf_df.columns, pd.MultiIndex):
                    yf_df.columns = [col[0] for col in yf_df.columns]
                
                yf_df.columns = [c.lower() for c in yf_df.columns]
                if 'date' not in yf_df.columns and yf_df.index.name in ('Date', 'date'):
                    yf_df.index.name = 'date'
                
                df = yf_df
                data_source = "YFinance"
                print(f"✅ YFinance fallback successful for {ticker}")
        except Exception as e:
            print(f"yfinance fallback failed for {ticker}: {e}")
            
    return df, data_source

# ─── Sidebar ────────────────────────────────────────────────────────────────

# ── IBKR Gateway Launcher ──
st.sidebar.title("IBKR Gateway")

# Detect ib-gw binary
_IB_GW_PATH = shutil.which("ib-gw") or "/usr/bin/ib-gw"
_ib_gw_available = os.path.isfile(_IB_GW_PATH) and os.access(_IB_GW_PATH, os.X_OK)

# Trading mode selector — determines the port automatically
trading_mode = st.sidebar.radio(
    "Trading Mode",
    ["📄 Paper Trading", "💰 Normal Trading"],
    index=0,
    horizontal=True,
    help="Paper Trading uses port 7497, Normal Trading uses port 7496.",
)
_is_paper = trading_mode.startswith("📄")
_auto_port = 7497 if _is_paper else 7496

# Gateway process status helper
def _is_gw_running() -> bool:
    """Check if an IB Gateway (ibgateway.GWClient) process is currently running."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "ibgateway.GWClient"],
            capture_output=True, timeout=3,
        )
        return result.returncode == 0
    except Exception:
        return False

# Show gateway status
_gw_running = _is_gw_running()
if _gw_running:
    st.sidebar.markdown("**Gateway:** 🟢 Running")
else:
    st.sidebar.markdown("**Gateway:** ⚫ Not running")

# Launch / Stop buttons
_gw_col1, _gw_col2 = st.sidebar.columns(2)
with _gw_col1:
    if st.button("🚀 Launch GW", width="stretch", disabled=not _ib_gw_available or _gw_running):
        try:
            proc = subprocess.Popen(
                [_IB_GW_PATH],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,  # Detach from Streamlit process
            )
            st.session_state["_gw_pid"] = proc.pid
            st.toast(f"IB Gateway launched (PID {proc.pid}). Please enter your credentials in the Gateway window.", icon="🚀")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to launch IB Gateway: {e}")
with _gw_col2:
    if st.button("⏹️ Stop GW", width="stretch", disabled=not _gw_running):
        try:
            subprocess.run(["pkill", "-f", "ibgateway.GWClient"], timeout=5)
            st.session_state.pop("_gw_pid", None)
            st.toast("IB Gateway stopped.", icon="⏹️")
            st.rerun()
        except Exception as e:
            st.error(f"Failed to stop IB Gateway: {e}")

if not _ib_gw_available:
    st.sidebar.caption(f"⚠️ `ib-gw` not found at `{_IB_GW_PATH}`")

# ── API Auto-Connection (uses auto-port from trading mode) ──
if "manual_disconnect" not in st.session_state:
    st.session_state.manual_disconnect = False

if not st.session_state.connector.connected and not st.session_state.manual_disconnect:
    try:
        # Auto-connect silently with a short timeout.
        # Local connections are nearly instant if the gateway is listening.
        st.session_state.connector.connect("127.0.0.1", _auto_port, 1, timeout=1)
        if st.session_state.connector.connected:
            st.session_state.pop("opt_cache_key", None)
    except Exception:
        pass

if st.session_state.connector.connected:
    if st.sidebar.button("Disconnect", width="stretch"):
        st.session_state.connector.disconnect()
        st.session_state.manual_disconnect = True
        for k in ["opt_exps", "opt_strikes", "opt_cache_key"]:
            st.session_state.pop(k, None)
        st.rerun()
elif st.session_state.manual_disconnect:
    if st.sidebar.button("Reconnect", width="stretch"):
        st.session_state.manual_disconnect = False
        st.rerun()

is_connected = st.session_state.connector.connected
if is_connected:
    st.sidebar.markdown(f"**API:** 🟢 Connected · Port `{_auto_port}`")
else:
    st.sidebar.markdown(f"**API:** 🔴 Disconnected · Port `{_auto_port}`")
    st.sidebar.caption("📊 Stock data via YFinance (Options require IBKR)")
st.sidebar.markdown("---")

# Data Selection
st.sidebar.title("Data Selection")
ticker = st.sidebar.text_input("Ticker (for EU use YF format, e.g. IFX.DE)", "AAPL")
sec_type = st.sidebar.selectbox("Security Type", ["STK", "OPT"])
timeframe = st.sidebar.selectbox("Timeframe", ["1 hour", "5 mins", "1 day"])
duration = st.sidebar.selectbox("Duration", ["1 D", "1 W", "1 M", "3 M", "6 M", "1 Y"])

# ── Skill Selector per Opencode Debate ──
_SKILLS_MAP = {
    "stock": {
        "wyckoff-2-0": "Wyckoff 2.0 — Structures & Order Flow",
        "volume-price-analysis": "Volume Price Analysis (VPA)",
        "volume-profile": "Volume Profile — Insider's Guide",
        "trades-about-to-happen": "Trades About to Happen — Weis Wave",
        "trading-against-the-crowd": "Trading Against the Crowd — Sentiment",
        "price-action-volman": "Price Action (5min) — Bob Volman",
    },
    "options": {
        "options-playbook": "Options Playbook — Overby",
        "options-course-workbook": "Options Course Workbook — Fontanills",
        "options-crash-course": "Options Crash Course",
    },
    "crypto": {
        "crypto-technical-analysis": "Crypto Technical Analysis",
        "crypto-crash-course": "Crypto Crash Course",
    },
}
_SEC_DEFAULT = "stock" if sec_type == "STK" else "options"
_AVAILABLE_SKILLS = list(_SKILLS_MAP[_SEC_DEFAULT].keys()) if _SEC_DEFAULT in _SKILLS_MAP else []
_prev_skills = st.session_state.get("selected_skills", None)
default_skills = _prev_skills if _prev_skills else list(_AVAILABLE_SKILLS)

with st.sidebar.expander("📚 Skills Debate", expanded=True):
    selected_skills = st.multiselect(
        "Framework per dibattito",
        options=_AVAILABLE_SKILLS,
        default=default_skills,
        format_func=lambda s: _SKILLS_MAP.get(_SEC_DEFAULT, {}).get(s, s),
        key="skill_selector",
    )
    if selected_skills != _prev_skills:
        st.session_state.selected_skills = selected_skills

# ── Auto-clear stale data when ticker or sec_type changes ──
_prev_ticker = st.session_state.get("_prev_ticker")
_prev_sec_type = st.session_state.get("_prev_sec_type")

if "archived_sessions" not in st.session_state:
    st.session_state.archived_sessions = []

if _prev_ticker is not None and (_prev_ticker != ticker or _prev_sec_type != sec_type):
    # ── Archive current session before clearing ──
    import datetime as _dt
    _chat = st.session_state.get("chat_history", [])
    _opt_chat = st.session_state.get("opt_strategies_chat", [])
    _strategies = st.session_state.get("ai_strategies", [])
    _meta = st.session_state.get("market_meta", {})
    if _chat or _opt_chat or _strategies:
        st.session_state.archived_sessions.insert(0, {
            "ticker": _prev_ticker,
            "sec_type": _prev_sec_type,
            "timestamp": _dt.datetime.now().strftime("%H:%M:%S"),
            "chat_history": list(_chat),
            "opt_strategies_chat": list(_opt_chat),
            "ai_strategies": list(_strategies),
            "meta": dict(_meta),
        })
        # Keep only the last 10 sessions
        st.session_state.archived_sessions = st.session_state.archived_sessions[:10]

    # ── Clear ALL stale keys ──
    stale_keys = [
        "market_df", "market_analysis", "market_meta",
        "market_holders", "market_financials",
        "ai_strategies", "ai_metrics_matrix", "ai_strategies_model",
        "chat_history", "needs_initial_analysis",
        "underlying_df", "underlying_analysis",
        "strategy_legs_data", "selected_strategy", "strategy_data_fetch",
        "opt_cache_key", "opt_exps", "opt_strikes",
        "opt_strategies_chat",
        "opt_selected_expiry", "opt_selected_strike", "opt_selected_right",
        "opencode_session_id",
        "skill_selector", "selected_skills",
    ]
    for k in stale_keys:
        st.session_state.pop(k, None)
    print(f"[CACHE] Archived & cleared: {_prev_ticker}/{_prev_sec_type} → {ticker}/{sec_type}")
st.session_state["_prev_ticker"] = ticker
st.session_state["_prev_sec_type"] = sec_type

# ── Sidebar: Archived Sessions ──
if st.session_state.get("archived_sessions"):
    with st.sidebar.expander("📂 Archived Sessions", expanded=False):
        for idx, sess in enumerate(st.session_state.archived_sessions):
            label = f"{sess['ticker']} ({sess['sec_type']}) — {sess['timestamp']}"
            n_msgs = len(sess.get("chat_history", [])) + len(sess.get("opt_strategies_chat", []))
            n_strats = len(sess.get("ai_strategies", []))
            st.markdown(f"**{label}**")
            st.caption(f"💬 {n_msgs} messages · 📊 {n_strats} strategies")
            if st.button(f"🔍 View", key=f"view_arch_{idx}"):
                st.session_state[f"_show_archive_{idx}"] = not st.session_state.get(f"_show_archive_{idx}", False)
            if st.session_state.get(f"_show_archive_{idx}", False):
                for msg in sess.get("chat_history", []) + sess.get("opt_strategies_chat", []):
                    role_icon = "🤖" if msg["role"] == "assistant" else "👤"
                    content_preview = msg["content"][:200] + "..." if len(msg["content"]) > 200 else msg["content"]
                    st.markdown(f"{role_icon} {content_preview}")
                if sess.get("ai_strategies"):
                    for s in sess["ai_strategies"]:
                        st.markdown(f"📊 **{s.get('name', 'N/A')}** — {s.get('direction', '')}")
            st.markdown("---")

# Opencode Agent (must render first to check if active)
if OpencodeDebate:
    opencode_config = OpencodeDebate.render_streamlit_sidebar()
    st.session_state.opencode_config = opencode_config

# AI Model Selection — only when Opencode is NOT active
opencode_active = OpencodeDebate is not None and st.session_state.get("opencode_config") is not None
if opencode_active:
    st.sidebar.caption("🤖 Provider LLM disattivati — AI via Opencode Agent")
elif TraderAgent and AIProvider:
    provider, model = AIProvider.render_streamlit_sidebar()
    st.session_state.ai_provider = provider
    st.session_state.ai_model_name = model

# EMA Colors
if TraderAgent and AIProvider:
    with st.sidebar.expander("🎨 EMA Colors", expanded=False):
        ema20_color = st.color_picker("EMA 20", "#00BFFF", key="ema20_color")
        ema50_color = st.color_picker("EMA 50", "#FFD700", key="ema50_color")
        ema200_color = st.color_picker("EMA 200", "#FF1493", key="ema200_color")
else:
    ema20_color, ema50_color, ema200_color = "#00BFFF", "#FFD700", "#FF1493"

# Opencode Debate History
if OpencodeDebate:
    OpencodeDebate.render_debate_history_ui()

# ─── Navigation & Modes ─────────────────────────────────────────────────────
st.sidebar.markdown("---")
view_mode = st.sidebar.radio(
    "Navigation", ["🔍 Trading Dashboard", "🎡 Wheel Strategy Scanner", "📊 Earnings Backtester"]
)

if view_mode == "🎡 Wheel Strategy Scanner":
    st.title("🎡 AI Wheel Strategy Scanner")
    st.markdown(
        "Scan a list of tickers to find the absolute best candidates for Cash-Secured Puts (Wheel Strategy Phase 1)."
    )

    tickers_input = st.text_area(
        "Tickers to Scan (comma separated)", "AAPL, MSFT, SPY, QQQ, NVDA, TSLA, AMD"
    )

    time_horizon = st.radio(
        "⏱️ Investment Horizon (Days to Expiration)",
        ["weekly (1-2w)", "monthly (3-6w)", "quarterly (3-6m)"],
        index=1,
        horizontal=True,
    )

    if st.button("🚀 Run Wheel Scanner", type="primary"):
        with st.spinner(
            "Scanning market data and computing IV (this may take a minute)..."
        ):
            tickers = [
                t.strip().upper() for t in tickers_input.split(",") if t.strip()
            ]
            market_data = []

            for t in tickers:
                try:
                    # Fetch short-term data to get Price, RSI, Trend
                    df, _src = get_historical_data_with_fallback(
                        st.session_state.connector,
                        ticker=t,
                        sec_type="STK",
                        duration="6 M",
                        timeframe="1 day"
                    )
                    if _src == 'YFinance':
                        st.warning(f'⚠️ {t}: Using YFinance data (IBKR not connected).')
                    if df is not None and not df.empty:
                        from technical_analysis import (
                            add_indicators,
                            detect_patterns,
                        )

                        df = add_indicators(df)
                        analysis = detect_patterns(df)

                        price = analysis.get("current_price", df.iloc[-1]["close"])
                        rsi = analysis.get("rsi", "N/A")
                        trend = analysis.get("trend", "N/A")

                        # Get IV (only if IBKR is connected)
                        iv_val = None
                        if is_connected:
                            try:
                                iv_data = st.session_state.connector.get_implied_volatility(
                                    t
                                )
                                if isinstance(iv_data, dict):
                                    iv_val = iv_data.get("iv") or iv_data.get("avg")
                                else:
                                    iv_val = iv_data
                            except Exception:
                                pass

                        iv_str = f"{iv_val*100:.1f}%" if iv_val else "N/A"

                        market_data.append(
                            {
                                "ticker": t,
                                "price": (
                                    round(price, 2)
                                    if isinstance(price, (int, float))
                                    else price
                                ),
                                "iv": iv_str,
                                "bid_ask_spread": "N/A",  # Will be inferred tight for large caps
                                "trend": trend,
                                "rsi": (
                                    round(rsi, 2)
                                    if isinstance(rsi, (int, float))
                                    else rsi
                                ),
                            }
                        )
                except Exception as e:
                    st.warning(f"Could not fetch data for {t}: {e}")

            if market_data:
                st.info("Market data gathered. Running AI Candidate Analysis...")

                if not TraderAgent:
                    st.error(
                        "TraderAgent module not loaded. Check environment/imports."
                    )
                else:
                    agent = TraderAgent(
                        provider_type=st.session_state.get("ai_provider", "gemini"),
                        model_name=st.session_state.get("ai_model_name"),
                    )

                    try:
                        import json

                        res_json_str = agent.scan_put_selling_candidates(
                            market_data, time_horizon=time_horizon
                        )
                        res = json.loads(res_json_str)

                        st.success("✅ AI Analysis Complete")
                        overview = res.get("market_overview", "")
                        if overview:
                            st.markdown(f"**Overview:** {overview}")

                        st.subheader("🏆 Best Candidates")
                        best = res.get("best_candidates", [])
                        if best:
                            for c in best:
                                with st.expander(
                                    f"⭐ {c.get('ticker')} (Score: {c.get('score')}/10)",
                                    expanded=True,
                                ):
                                    st.write(
                                        f"**Suggested Delta:** {c.get('suggested_delta')}"
                                    )
                                    st.info(f"💡 {c.get('rationale')}")
                        else:
                            st.warning("No suitable candidates found in this list.")

                        st.subheader("❌ Rejected Candidates")
                        rejected = res.get("rejected_candidates", [])
                        if rejected:
                            for c in rejected:
                                st.error(
                                    f"**{c.get('ticker')}**: {c.get('reason')}"
                                )
                        else:
                            st.success("No candidates were explicitly rejected.")
                    except json.JSONDecodeError:
                        st.error("AI returned invalid JSON. Raw response:")
                        st.code(res_json_str)
                    except Exception as e:
                        st.error(f"Error executing AI analysis: {e}")
            else:
                st.error("No valid market data could be gathered.")

    st.stop()  # Stops execution here so the standard dashboard won't render below

elif view_mode == "📊 Earnings Backtester":
    from earnings_backtester import (
        get_earnings_dates,
        backtest_earnings_strategies,
        summarize_results,
        build_detail_table,
        STRATEGY_CATALOG,
    )

    st.title("📊 Earnings Pattern Backtester")
    st.markdown(
        "Backtest options strategies across historical earnings events to identify "
        "profitable patterns. Uses **Black-Scholes theoretical pricing** for simulation."
    )

    # ── Parameters ────────────────────────────────────────────────────────
    col_p1, col_p2 = st.columns(2)
    with col_p1:
        bt_ticker = st.text_input("Ticker", value=ticker, key="bt_ticker")
        num_earnings = st.slider(
            "Number of past earnings to analyse",
            min_value=2,
            max_value=20,
            value=8,
            step=1,
            key="bt_num_earnings",
        )
    with col_p2:
        entry_days = st.number_input(
            "Entry days before earnings",
            min_value=1,
            max_value=10,
            value=1,
            step=1,
            key="bt_entry_days",
        )
        exit_days = st.number_input(
            "Exit days after earnings",
            min_value=1,
            max_value=10,
            value=1,
            step=1,
            key="bt_exit_days",
        )

    col_p3, col_p4 = st.columns(2)
    with col_p3:
        dte_assumption = st.number_input(
            "Assumed DTE at entry (days)",
            min_value=1,
            max_value=60,
            value=7,
            step=1,
            key="bt_dte",
            help="The number of days to expiration assumed for the option at entry. "
            "A weekly option would be ~7, monthly ~30.",
        )
    with col_p4:
        otm_pct = st.slider(
            "OTM distance (% of stock price)",
            min_value=1,
            max_value=20,
            value=5,
            step=1,
            key="bt_otm_pct",
            help="How far out-of-the-money the OTM strikes should be for strangles, spreads, etc.",
        )

    selected_strategies = st.multiselect(
        "Strategies to backtest",
        options=list(STRATEGY_CATALOG.keys()),
        default=["Long Straddle", "Long Strangle", "Iron Condor"],
        key="bt_strategies",
    )

    # Show strategy descriptions
    with st.expander("ℹ️ Strategy Descriptions", expanded=False):
        for sname, sdef in STRATEGY_CATALOG.items():
            icon = "✅" if sname in selected_strategies else "⬜"
            st.markdown(f"{icon} **{sname}**: {sdef['description']}")

    # ── Run Backtest ──────────────────────────────────────────────────────
    if st.button("🚀 Run Earnings Backtest", type="primary", use_container_width=True):
        if not selected_strategies:
            st.error("Please select at least one strategy.")
        else:
            # Step 1: Fetch earnings dates (no IBKR needed)
            with st.spinner(f"📅 Fetching earnings dates for {bt_ticker} from Yahoo Finance..."):
                try:
                    earnings_dates = get_earnings_dates(bt_ticker, count=num_earnings)
                except Exception as e:
                    st.error(f"❌ Failed to fetch earnings dates: {e}")
                    earnings_dates = []

            if not earnings_dates:
                st.warning(
                    f"No past earnings dates found for {bt_ticker}. "
                    "Check the ticker symbol or try a different stock."
                )
            else:
                st.info(
                    f"Found **{len(earnings_dates)}** past earnings events for "
                    f"**{bt_ticker}**: {', '.join(str(d) for d in earnings_dates)}"
                )

                # Step 2: Run backtest (needs IBKR)
                progress_text = st.empty()
                progress_bar = st.progress(0)
                completed = {"n": 0}

                def _bt_progress(msg):
                    completed["n"] += 1
                    pct = min(int(completed["n"] / (len(earnings_dates) + 1) * 100), 99)
                    progress_bar.progress(pct)
                    progress_text.text(msg)

                try:
                    results = backtest_earnings_strategies(
                        connector=st.session_state.connector,
                        ticker=bt_ticker,
                        earnings_dates=earnings_dates,
                        strategy_names=selected_strategies,
                        entry_days_before=entry_days,
                        exit_days_after=exit_days,
                        dte_assumption=dte_assumption,
                        otm_pct=otm_pct / 100.0,
                        progress_callback=_bt_progress,
                    )
                except Exception as e:
                    st.error(f"❌ Backtest failed: {e}")
                    import traceback
                    traceback.print_exc()
                    results = []

                progress_bar.progress(100)
                progress_text.text("✅ Backtest complete!")

                if not results:
                    st.warning("No valid results were generated. Is IBKR providing data for this ticker?")
                else:
                    st.session_state["bt_results"] = results
                    st.session_state["bt_strategies_used"] = selected_strategies
                    st.session_state["bt_ticker_used"] = bt_ticker

    # ── Display Results ───────────────────────────────────────────────────
    if "bt_results" in st.session_state and st.session_state["bt_results"]:
        results = st.session_state["bt_results"]
        strat_used = st.session_state["bt_strategies_used"]
        bt_tk = st.session_state["bt_ticker_used"]

        st.markdown("---")
        st.subheader(f"📈 Results for {bt_tk} — {len(results)} Earnings Events")

        # Summary Table
        summary_df = summarize_results(results, strat_used)
        st.markdown("### 🏆 Strategy Summary")

        # Highlight the best strategy
        if not summary_df.empty and summary_df["Trades"].sum() > 0:
            best_idx = summary_df["Total P/L ($)"].idxmax()
            best_strat = summary_df.loc[best_idx, "Strategy"]
            best_pnl = summary_df.loc[best_idx, "Total P/L ($)"]
            best_wr = summary_df.loc[best_idx, "Win Rate (%)"]

            if best_pnl > 0:
                st.success(
                    f"🏆 **Best Strategy: {best_strat}** — "
                    f"Total P/L: **${best_pnl:+,.2f}** per contract | "
                    f"Win Rate: **{best_wr:.1f}%**"
                )
            else:
                st.warning(
                    f"⚠️ No strategy was profitable overall. "
                    f"Best: {best_strat} (${best_pnl:+,.2f})"
                )

        st.dataframe(
            summary_df.style.format({
                "Win Rate (%)": "{:.1f}%",
                "Avg P/L ($)": "${:+,.2f}",
                "Total P/L ($)": "${:+,.2f}",
                "Max Win ($)": "${:+,.2f}",
                "Max Loss ($)": "${:+,.2f}",
            }).apply(
                lambda row: [
                    "background-color: rgba(0,255,0,0.15)" if row["Total P/L ($)"] > 0
                    else "background-color: rgba(255,0,0,0.15)" if row["Total P/L ($)"] < 0
                    else ""
                ] * len(row),
                axis=1,
            ),
            use_container_width=True,
            hide_index=True,
        )

        # P/L Bar Chart per Earnings Event
        st.markdown("### 📊 P/L per Earnings Event")
        detail_df = build_detail_table(results, strat_used)

        # Build grouped bar chart (go already imported at top of file)

        fig_pnl = go.Figure()
        colors = ["#00ccff", "#ff6b6b", "#ffd93d", "#6bcb77", "#c084fc", "#ff922b"]
        for i, strat_name in enumerate(strat_used):
            col_name = f"{strat_name} P/L ($)"
            if col_name in detail_df.columns:
                pnl_vals = detail_df[col_name].fillna(0)
                bar_colors = ["rgba(0,200,0,0.7)" if v >= 0 else "rgba(200,0,0,0.7)" for v in pnl_vals]
                fig_pnl.add_trace(
                    go.Bar(
                        x=[str(d) for d in detail_df["Earnings Date"]],
                        y=pnl_vals,
                        name=strat_name,
                        marker_color=colors[i % len(colors)],
                    )
                )

        fig_pnl.update_layout(
            barmode="group",
            xaxis_title="Earnings Date",
            yaxis_title="P/L per Contract ($)",
            height=450,
            margin=dict(l=20, r=20, t=30, b=20),
        )
        fig_pnl.add_hline(y=0, line_dash="dash", line_color="gray")
        st.plotly_chart(fig_pnl, use_container_width=True)

        # Stock Move Distribution
        st.markdown("### 📉 Stock Move Around Earnings")
        moves = [r["move_pct"] for r in results]
        abs_moves = [r["abs_move_pct"] for r in results]
        col_m1, col_m2, col_m3 = st.columns(3)
        with col_m1:
            st.metric("Avg Move", f"{sum(moves)/len(moves):+.2f}%")
        with col_m2:
            st.metric("Avg |Move|", f"{sum(abs_moves)/len(abs_moves):.2f}%")
        with col_m3:
            st.metric("Max |Move|", f"{max(abs_moves):.2f}%")

        # Detail Table
        with st.expander("📋 Detailed Per-Earnings Results", expanded=False):
            st.dataframe(detail_df, use_container_width=True, hide_index=True)

    st.stop()

# ─── Main Area ──────────────────────────────────────────────────────────────

st.title("📈 IBKR AI Trading Dashboard")

# Option Chain — auto-fetch when OPT is selected
expiry = None
strike = None
right = None

if sec_type == "OPT":
    if not is_connected:
        st.warning("⚠️ Connect to IBKR to load Option Chain data. Options are not available via YFinance.")
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
                import datetime

                today_date = datetime.date.today()

                def get_days_to_exp(exp_str):
                    try:
                        exp_date = datetime.datetime.strptime(exp_str, "%Y%m%d").date()
                        return (exp_date - today_date).days
                    except:
                        return 0

                ai_col1, ai_col2, ai_col3 = st.columns([1, 1, 2])
                with ai_col1:
                    time_horizon = st.radio(
                        "⏱️ Horizon",
                        ["weekly", "monthly", "quarterly", "leaps"],
                        index=1,
                        format_func=lambda x: {
                            "weekly": "📅 Weekly",
                            "monthly": "📆 Monthly",
                            "quarterly": "📊 Quarterly",
                            "leaps": "🚀 LEAPS",
                        }[x],
                        horizontal=False,
                    )

                # Filter Expirations based on Horizon
                filtered_exps = []
                for exp in available_exps:
                    days = get_days_to_exp(exp)
                    if time_horizon == "weekly" and days <= 14:
                        filtered_exps.append(exp)
                    elif time_horizon == "monthly" and 15 <= days <= 45:
                        filtered_exps.append(exp)
                    elif time_horizon == "quarterly" and 46 <= days <= 365:
                        filtered_exps.append(exp)
                    elif time_horizon == "leaps" and days > 365:
                        filtered_exps.append(exp)

                # Fallback if no dates fit the exact bucket
                if not filtered_exps:
                    filtered_exps = available_exps

                with ai_col2:
                    selected_exp = st.selectbox(
                        "🎯 Expiration Date",
                        options=sorted(filtered_exps),
                        format_func=lambda x: f"{datetime.datetime.strptime(x, '%Y%m%d').strftime('%b %d, %Y')} ({get_days_to_exp(x)}d)",
                    )

                    # Convert to list to preserve compatibility with existing logic
                    limited_exps = [selected_exp] if selected_exp else []

                with ai_col3:
                    st.write("")  # Spacer
                    st.write("")  # Spacer
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
                            und_df, _src = get_historical_data_with_fallback(
                                st.session_state.connector,
                                ticker,
                                sec_type="STK",
                                duration="1 Y",
                                bar_size_setting="1 day",
                            )
                            if _src == 'YFinance':
                                st.warning('⚠️ Using YFinance data (IBKR not connected).')
                            if und_df is not None and not und_df.empty:
                                und_df = add_indicators(und_df)
                                und_analysis = detect_patterns(und_df)
                                price = und_analysis.get("current_price", 0)

                                # Identify target expiration for precise IV pulling and exact valid strikes
                                best_exp = limited_exps[0] if limited_exps else None

                                # Fetch actual strikes for the specific expiration to avoid Hallucinated LEAP strikes
                                valid_source_strikes = available_strikes
                                if best_exp:
                                    st.write(
                                        f"🔍 Validating specific available strikes for {best_exp}..."
                                    )
                                    specific_strikes = st.session_state.connector.get_strikes_for_expiration(
                                        ticker, best_exp
                                    )
                                    if specific_strikes:
                                        valid_source_strikes = specific_strikes

                                # Filter strikes near ATM for Greeks computation
                                atm_range = price * 0.10
                                nearby_strikes = sorted(
                                    [
                                        s
                                        for s in valid_source_strikes
                                        if abs(s - price) <= atm_range
                                    ]
                                )
                                if len(nearby_strikes) < 4:
                                    # Fallback: take closest 10 strikes instead of just the first 20 globally
                                    nearby_strikes = sorted(
                                        valid_source_strikes,
                                        key=lambda s: abs(s - price),
                                    )[:10]
                                    nearby_strikes = sorted(nearby_strikes)

                                closest_strike = (
                                    min(nearby_strikes, key=lambda s: abs(s - price))
                                    if nearby_strikes
                                    else None
                                )

                                # Fetch the global 30-day Implied Volatility (IV) directly from IBKR for the underlying stock
                                iv_data = (
                                    st.session_state.connector.get_implied_volatility(
                                        ticker, exchange="SMART", currency="USD"
                                    )
                                )

                                # Handle session_state caching the old IBKRConnector which returned a float
                                if isinstance(iv_data, dict):
                                    iv = iv_data.get("avg") if iv_data else None
                                    raw_iv = iv_data.get("iv") if iv_data else None
                                    raw_hv = iv_data.get("hv") if iv_data else None
                                else:
                                    iv = iv_data
                                    iv_data = (
                                        {"avg": iv, "iv": iv, "hv": None}
                                        if iv is not None
                                        else None
                                    )
                                    raw_iv = iv
                                    raw_hv = None

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
                                last_exp_iv = iv
                                last_exp_iv_data = iv_data

                                for exp in limited_exps:
                                    # Fetch specific IV for the closest ATM strike of this expiration
                                    exp_iv_data = st.session_state.connector.get_implied_volatility(
                                        ticker,
                                        exchange="SMART",
                                        currency="USD",
                                        expiry=exp,
                                        strike=closest_strike,
                                    )

                                    exp_iv = iv  # Fallback to stock 30-day IV
                                    if exp_iv_data and isinstance(exp_iv_data, dict):
                                        # Prefer the raw option IV (106) if available, else average
                                        exp_iv_val = exp_iv_data.get(
                                            "iv"
                                        ) or exp_iv_data.get("avg")
                                        if exp_iv_val and exp_iv_val > 0:
                                            exp_iv = exp_iv_val
                                            last_exp_iv = exp_iv
                                            last_exp_iv_data = exp_iv_data

                                    exp_greeks = st.session_state.connector.get_real_greeks_table(
                                        ticker=ticker,
                                        expiry_str=exp,
                                        strikes=nearby_strikes,
                                        underlying_price=price,
                                        hist_vol=exp_iv,
                                    )
                                    greeks_table.extend(exp_greeks)

                                agent = TraderAgent(
                                    provider_type=provider_type,
                                    model_name=model_name,
                                )
                                
                                # Fetch holders & financials for OPT (always fresh)
                                m_holders = get_holders_info(ticker)
                                m_fin = get_financial_info(ticker)
                                st.session_state.market_holders = m_holders
                                st.session_state.market_financials = m_fin
                                
                                # Costruisci il fundamentals_context da passare al TraderAgent
                                f_ctx = "Nessun dato fondamentale/societario disponibile."
                                if m_holders or m_fin:
                                    f_ctx = "FUNDAMENTALS & HOLDERS:\n"
                                    if m_fin:
                                        f_ctx += "Dati Finanziari: " + ", ".join(f"{k}={v}" for k,v in m_fin.items()) + "\n"
                                    if m_holders.get("institutional_holders"):
                                        f_ctx += "Top Istituzioni: " + ", ".join(h['Holder'] for h in m_holders["institutional_holders"]) + "\n"
                                    if m_holders.get("etf_mutualfund_holders"):
                                        f_ctx += "Top ETF/Fondi: " + ", ".join(h['Holder'] for h in m_holders["etf_mutualfund_holders"]) + "\n"
                                        
                                strategies, metrics_matrix = agent.suggest_option_strategy(
                                    ticker=ticker,
                                    analysis=und_analysis,
                                    expirations=limited_exps,  # CRITICAL: Pass only the user-selected date
                                    strikes=nearby_strikes,  # CRITICAL: Pass only the valid strikes for that date
                                    underlying_price=price,
                                    time_horizon=time_horizon,
                                    greeks_table=greeks_table,
                                    iv=last_exp_iv,  # Give AI the latest Expiration IV we gathered
                                    geopolitics_context=st.session_state.get("geo_events_input"),
                                    fundamentals_context=f_ctx
                                )
                                for s in strategies:
                                    s["iv_used"] = last_exp_iv
                                    s["iv_data"] = last_exp_iv_data
                                st.session_state["ai_strategies"] = strategies
                                st.session_state["ai_metrics_matrix"] = metrics_matrix
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
                    metrics_matrix = st.session_state.get("ai_metrics_matrix", [])
                    model_used = st.session_state.get("ai_strategies_model", "")
                    st.caption(
                        f"*🤖 Suggested by `{model_used}`*  |  *📚 Knowledge: `Opencode Skills (Options)`*"
                    )

                    if metrics_matrix:
                        st.markdown("### 📊 Underlying Evaluation Matrix")
                        import pandas as pd
                        df_metrics = pd.DataFrame(metrics_matrix)
                        # Aggiungiamo un'icona alla colonna satisfied
                        if 'satisfied' in df_metrics.columns:
                            df_metrics['satisfied'] = df_metrics['satisfied'].apply(
                                lambda x: f"✅ {x}" if "yes" in str(x).lower() else f"❌ {x}"
                            )
                        st.table(df_metrics)

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
                            iv_used = strat.get("iv_used", 0.30)
                            strat_iv_data = strat.get("iv_data")

                            if (
                                strat_iv_data
                                and strat_iv_data.get("iv") is not None
                                and strat_iv_data.get("hv") is not None
                            ):
                                iv_str = f"Avg: {strat_iv_data.get('avg')*100:.1f}% (IV: {strat_iv_data.get('iv')*100:.1f}% | HV: {strat_iv_data.get('hv')*100:.1f}%)"
                            else:
                                iv_str = f"{iv_used*100:.1f}%"

                            st.markdown(
                                f"\n💰 **Max Profit:** {strat.get('max_profit', 'N/A')} · "
                                f"💸 **Max Loss:** {strat.get('max_loss', 'N/A')} · "
                                f"⚖️ **Breakeven:** {strat.get('breakeven', 'N/A')} · "
                                f"📊 **IV Assunta (IBKR):** {iv_str}"
                            )

                            # AI Rationale (should cite real indicator values)
                            rationale = strat.get("rationale", "")
                            if rationale:
                                st.info(f"💡 {rationale}")

                            # Explicit Mathematical Calculations
                            calc = strat.get("calculations", "")
                            if calc and calc != "N/A":
                                st.success(f"🧮 **Calcoli Matematici:**\n\n{calc}")

                            # ── Esecuzione Ordine IBKR ──────────────────────────
                            with st.expander(
                                "🚀 Esecuzione Ordine IBKR (Live)", expanded=False
                            ):
                                st.warning(
                                    "⚠️ L'invio dell'ordine è diretto al tuo account IBKR collegato. Controlla accuratamente i parametri prima di confermare."
                                )

                                # Calculate theoretical net price
                                net_price = 0.0
                                for leg in strat.get("legs", []):
                                    g = leg.get("greeks")
                                    if g and "price" in g:
                                        p = g["price"]
                                        leg_qty = leg.get("quantity", 1)
                                        if leg.get("action") == "BUY":
                                            net_price += p * leg_qty
                                        else:
                                            net_price -= p * leg_qty

                                col_o1, col_o2 = st.columns(2)
                                with col_o1:
                                    order_type = st.selectbox(
                                        "Tipo Ordine", ["LMT", "MKT"], key=f"ot_{i}"
                                    )
                                    order_qty = st.number_input(
                                        "Quantità (Moltiplicatore Combo)",
                                        min_value=1,
                                        value=1,
                                        step=1,
                                        key=f"qty_{i}",
                                    )
                                with col_o2:
                                    limit_price = st.number_input(
                                        "Prezzo Limite ($)",
                                        value=round(net_price, 2) if net_price else 0.0,
                                        step=0.05,
                                        format="%.2f",
                                        key=f"lmt_{i}",
                                        disabled=(order_type == "MKT"),
                                    )

                                st.markdown("---")
                                confirm_order = st.checkbox(
                                    f"Confermo di voler inviare l'ordine per **{strat['name']}**",
                                    key=f"conf_{i}",
                                )

                                if st.button(
                                    "🔥 INVIA ORDINE A IBKR",
                                    key=f"send_{i}",
                                    disabled=not confirm_order,
                                    use_container_width=True,
                                    type="primary",
                                ):
                                    with st.spinner(
                                        "Trasmissione ordine a IBKR in corso..."
                                    ):
                                        res = st.session_state.connector.submit_strategy_order(
                                            ticker=ticker,
                                            legs=strat.get("legs", []),
                                            order_type=order_type,
                                            limit_price=(
                                                limit_price
                                                if order_type == "LMT"
                                                else None
                                            ),
                                            total_quantity=order_qty,
                                        )
                                        if res.get("status") == "success":
                                            st.success(
                                                f"✅ Ordine inviato! ID: {res.get('order_id')}"
                                            )
                                            st.info(res.get("msg"))
                                            st.toast(
                                                f"✅ Ordine Inviato: {strat['name']}"
                                            )
                                        else:
                                            st.error(
                                                f"❌ Errore Invio: {res.get('msg')}"
                                            )

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

                    # ─── Options Strategies General Chat ────────────────────────
                    st.subheader("💬 Chat Analisi Strategie Proposte")
                    
                    if "opt_strategies_chat" not in st.session_state:
                        st.session_state.opt_strategies_chat = []
                        
                    # Calculate summary context string once
                    strats_context = ""
                    for strat in strategies:
                        strats_context += f"- **{strat['name']}** ({strat.get('direction', 'NEUTRAL')}): Max Profit {strat.get('max_profit', 'N/A')}, Max Loss {strat.get('max_loss', 'N/A')}, Breakeven {strat.get('breakeven', 'N/A')}\n"
                    
                    hidden_ctx = (
                        f"CONTESTO SULLE STRATEGIE APPENA PROPOSTE ALL'UTENTE:\n{strats_context}\n\n"
                        f"L'utente ti sta facendo domande su queste soluzioni per capire validità, rischi, o eventuali aspetti sfuggiti al calcolo iniziale."
                    )
                    
                    for msg in st.session_state.opt_strategies_chat:
                        with st.chat_message(msg["role"], avatar="🤖" if msg["role"] == "assistant" else "👤"):
                            st.markdown(msg["content"])
                            
                    if opt_chat_input := st.chat_input("Chiedi all'AI chiarimenti sulle strategie proposte sopra..."):
                        st.session_state.opt_strategies_chat.append({"role": "user", "content": opt_chat_input})
                        with st.chat_message("user", avatar="👤"):
                            st.markdown(opt_chat_input)
                            
                        with st.spinner("🤖 Analizzando le strategie proposte in base alla tua domanda..."):
                            try:
                                agent = TraderAgent(
                                    provider_type=st.session_state.get("ai_provider", "gemini"),
                                    model_name=st.session_state.get("ai_model_name"),
                                )
                                skill_fw = load_skills_knowledge(["options-playbook", "options-course-workbook", "options-crash-course"]) if load_skills_knowledge else {}
                                kb = "\n\n".join(skill_fw.values()) if skill_fw else getattr(agent, "knowledge", {}).get("options", "")
                                kb_section = f"\nCONOSCENZA TEORICA (Options Skill Frameworks):\n{kb}\n" if kb else ""
                                
                                history_text = ""
                                for m in st.session_state.opt_strategies_chat[:-1][-4:]:
                                    role = "User" if m["role"] == "user" else "Analyst"
                                    history_text += f"{role}: {m['content']}\n"
                                
                                prompt = (
                                    f"Sei un Quantitative Options Analyst. Rispondi in italiano in modo conciso e analitico.\n"
                                    f"I tuoi principi chiave operativi sono basati su questa knowledge base:\n{kb_section}\n\n"
                                    f"{hidden_ctx}\n\n"
                                    f"{'CONVERSAZIONE PRECEDENTE:' + history_text if history_text else ''}\n"
                                    f"DOMANDA DELL'UTENTE: {opt_chat_input}"
                                )
                                
                                response = agent.ai.get_model().generate_content(prompt)
                                ai_text = response.text
                                
                                actual_model = agent.ai.current_model_name
                                provider = st.session_state.get("ai_provider", "gemini")
                                model_badge = f"*🤖 Model: `{provider}` / `{actual_model}`*  |  *📚 Knowledge: `Opencode Skills (Options)`*\n\n---\n\n"
                                formatted_ai_text = model_badge + ai_text
                                
                                st.session_state.opt_strategies_chat.append({"role": "assistant", "content": formatted_ai_text})
                                with st.chat_message("assistant", avatar="🤖"):
                                    st.markdown(formatted_ai_text)
                            except Exception as e:
                                st.error(f"Errore Strategy Chat: {e}")

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
                            und_df, _src = get_historical_data_with_fallback(
                                st.session_state.connector,
                                ticker,
                                sec_type="STK",
                                duration=duration,
                                bar_size_setting=timeframe,
                            )
                            if _src == 'YFinance':
                                st.warning('⚠️ Using YFinance data (IBKR not connected).')
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

                                opt_duration = duration
                                opt_timeframe = timeframe

                                if (
                                    "day" in opt_timeframe
                                    or "week" in opt_timeframe
                                    or "month" in opt_timeframe
                                ):
                                    opt_timeframe = "1 hour"
                                    opt_duration = "1 W"
                                elif " Y" in opt_duration:
                                    opt_duration = "1 M"
                                elif (
                                    " M" in opt_duration
                                    and int(opt_duration.split(" ")[0]) > 1
                                ):
                                    opt_duration = "1 M"

                                leg_df, _src = get_historical_data_with_fallback(st.session_state.connector, 
                                    ticker,
                                    sec_type="OPT",
                                    duration=opt_duration,  # Safe duration for options
                                    bar_size_setting=opt_timeframe,  # Safe timeframe for options
                                    strike=leg["strike"],
                                    expiry=leg["expiry"],
                                    right=leg["right"],
                                )
                                if _src == 'YFinance':
                                    st.warning('⚠️ Using YFinance data (IBKR not connected).')

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

                                if leg_df is not None and not leg_df.empty:
                                    leg_df = add_indicators(leg_df)
                                    leg_data.append({"meta": leg_meta, "df": leg_df})
                                else:
                                    st.warning(
                                        f"⚠️ Nessun dato storico per {leg_name}. Uso le Greche teoriche IBKR per il grafico."
                                    )
                                    leg_data.append({"meta": leg_meta, "df": None})

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
# STK can always be fetched (YFinance fallback); OPT requires IBKR connection + selection
can_fetch = True
if sec_type == "OPT":
    if not is_connected or not expiry or not strike or not right:
        can_fetch = False

if st.button("Fetch Data & Analyze", disabled=not can_fetch):
    with st.spinner("Fetching historical data..."):
        try:
            # Check if we are analyzing a new ticker and clear chat history if so
            current_meta = st.session_state.get("market_meta", {})
            if current_meta.get("ticker") != ticker:
                st.session_state.chat_history = []
                st.session_state.needs_initial_analysis = True

            # Clear previous underlying data
            st.session_state.pop("underlying_df", None)
            st.session_state.pop("underlying_analysis", None)

            opt_kwargs = {}
            if sec_type == "OPT":
                # 1. Fetch the UNDERLYING stock first (user's duration/timeframe)
                with st.spinner(f"📊 Fetching {ticker} underlying stock data..."):
                    und_df, _src = get_historical_data_with_fallback(st.session_state.connector, 
                        ticker,
                        sec_type="STK",
                        duration=duration,
                        bar_size_setting=timeframe,
                    )
                    if _src == 'YFinance':
                        st.warning('⚠️ Using YFinance data (IBKR not connected).')
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

            df, _src = get_historical_data_with_fallback(st.session_state.connector, 
                ticker,
                sec_type=sec_type,
                duration=fetch_duration,
                bar_size_setting=fetch_timeframe,
                **opt_kwargs,
            )
            if _src == 'YFinance':
                st.warning('⚠️ Using YFinance data (IBKR not connected).')

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
                
                # Fetch holders info
                st.session_state.market_holders = get_holders_info(ticker)
                
                # Fetch financial info
                st.session_state.market_financials = get_financial_info(ticker)
                
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

        # Use the REAL market close price if available, else fallback to theoretical greeks
        entry_price = 0.0
        if leg_bundle["df"] is not None and not leg_bundle["df"].empty:
            entry_price = leg_bundle["df"].iloc[-1]["close"]
        elif "greeks" in meta and "price" in meta["greeks"]:
            entry_price = float(meta["greeks"]["price"])

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
                    skill_fw = load_skills_knowledge(["options-playbook", "options-course-workbook", "options-crash-course"]) if load_skills_knowledge else {}
                    kb = "\n\n".join(skill_fw.values()) if skill_fw else getattr(agent, "knowledge", {}).get("options", "")
                    kb_section = (
                        f"\nCONOSCENZA TEORICA (Options Skill Frameworks):\n{kb}\n"
                        if kb
                        else ""
                    )

                    prompt = f"Sei un Quantitative Options Analyst. Rispondi in italiano.\nI tuoi principi chiave operativi sono basati su questa knowledge base:\n{kb_section}\n\n{hidden_context}\n\nUser Question: {strat_user_input}"

                    response = agent.ai.get_model().generate_content(prompt)
                    ai_text = response.text

                    # Add model and knowledge badge to Strategy Chat Analyst
                    actual_model = agent.ai.current_model_name
                    provider = st.session_state.get("ai_provider", "gemini")
                    model_badge = f"*🤖 Model: `{provider}` / `{actual_model}`*  |  *📚 Knowledge: `Opencode Skills (Options)`*\n\n---\n\n"
                    ai_text = model_badge + ai_text

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
        # 🌍 Geopolitics Section
        # Auto-fill news context via Opencode (once per ticker)
        _oc_cfg = st.session_state.get("opencode_config")
        _auto_key = "geo_events_filled_for"
        _prev_filled = st.session_state.get(_auto_key)
        _current_ticker = meta.get("ticker", "")
        if OpencodeDebate and _oc_cfg and _current_ticker and _current_ticker != _prev_filled:
            st.session_state[_auto_key] = _current_ticker
            with st.spinner(f"🔍 Opencode: cerca news geopolitiche per {_current_ticker}..."):
                try:
                    _oc_agent = OpencodeAgent(_oc_cfg)
                    _oc_prompt = (
                        f"Cerca sul web le notizie e gli eventi geopolitici degli ultimi 3 mesi "
                        f"relativi al ticker {_current_ticker} e al suo settore di appartenenza. "
                        f"Fornisci un riassunto di massimo 5 bullet points degli eventi chiave "
                        f"che potrebbero influenzare il prezzo del titolo. "
                        f"Includi: rischi geopolitici, cambi normativi, tensioni commerciali, "
                        f"problemi di supply chain, fattori macroeconomici."
                    )
                    _news_text = ""
                    for _chunk in _oc_agent.stream_prompt(_oc_prompt):
                        _news_text += _chunk
                    st.session_state["geo_events_input"] = _news_text
                except Exception:  # pylint: disable=broad-exception-caught
                    pass

        with st.expander("🌍 Geopolitical Risk Analysis", expanded=False):
            st.write("Analyze the macro-geopolitical risk for this asset using institutional frameworks.")
            col_geo1, col_geo2 = st.columns([2, 1])
            with col_geo1:
                geo_events = st.text_area("Recent News/Events (optional):", height=68, key="geo_events_input")
            with col_geo2:
                geo_framework = st.selectbox(
                    "Framework:",
                    ["Grand Chessboard (Brzezinski)", "Prisoners of Geography (Tim Marshall)", "World Order (Kissinger)"],
                    key="geo_framework_sel"
                )
            
            if st.button("Run Geopolitical Analysis", type="primary", key="btn_run_geo"):
                with st.spinner(f"Analyzing {meta['ticker']} through {geo_framework}..."):
                    geo_agent = TraderAgent(
                        provider_type=st.session_state.get("ai_provider", "gemini"),
                        model_name=st.session_state.get("ai_model_name"),
                    )
                    geo_response = geo_agent.analyze_geopolitical_risk(
                        asset=meta['ticker'],
                        current_events=geo_events if geo_events else "Nessun evento o notizia specifica fornita. Analizza il contesto geografico e strutturale generale.",
                        framework=geo_framework
                    )
                    st.markdown(geo_response)

        # Auto-generate initial analysis on first fetch
        if st.session_state.get("needs_initial_analysis"):
            st.session_state.needs_initial_analysis = False
            meta = st.session_state.get("market_meta", {})
            analysis = st.session_state.get("market_analysis", {})

            opencode_config = st.session_state.get("opencode_config")
            if OpencodeDebate and opencode_config is not None:
                # ── Opencode Multi-Skill Debate (auto-start) ──
                holders = st.session_state.get("market_holders", {})
                financials = st.session_state.get("market_financials", {})
                holders_text = ""
                if holders:
                    holders_text = (
                        f"Top istituzionali: {holders.get('top_institutional', 'N/A')}\n"
                        f"Top ETF: {holders.get('top_etf', 'N/A')}"
                    )
                financials_text = ""
                if financials:
                    financials_text = "\n".join(
                        f"{k}: {v}" for k, v in financials.items() if v is not None
                    )
                patterns_list = analysis.get("patterns", [])
                if isinstance(patterns_list, str):
                    patterns_list = [patterns_list]

                skill_slugs = st.session_state.get("selected_skills", [])
                n_skills = len(skill_slugs)
                total_rounds = max(1 + n_skills + 1, 3)  # R1 + Rskills + Rfinal

                progress_bar = st.progress(0, text="🧪 Avvio Opencode Multi-Skill Debate...")

                with st.chat_message("assistant", avatar="🤖"):
                    st.caption(f"🧪 **Opencode Multi-Skill Debate** ({n_skills} skills)...")
                    output_area = st.empty()

                    debate = OpencodeDebate(opencode_config)
                    stream = debate.debate_multi_skill(
                        ticker=meta.get("ticker", "N/A"),
                        price=analysis.get("current_price", 0.0),
                        change=analysis.get("change_pct"),
                        trend=analysis.get("trend", "Unknown"),
                        adx=analysis.get("adx"),
                        rsi=analysis.get("rsi"),
                        stoch_k=analysis.get("stoch_k"),
                        stoch_d=analysis.get("stoch_d"),
                        williams_r=analysis.get("williams_r"),
                        macd=analysis.get("macd"),
                        macd_signal=analysis.get("macd_signal"),
                        macd_histogram=analysis.get("macd_histogram"),
                        bb_position=analysis.get("bb_position", "N/A"),
                        bb_width=analysis.get("bb_width"),
                        volume_ratio=analysis.get("volume_ratio"),
                        volume_signal=analysis.get("volume_info", "N/A"),
                        patterns=patterns_list,
                        holders_text=holders_text if holders_text else None,
                        financials_text=financials_text if financials_text else None,
                        skill_slugs=skill_slugs if skill_slugs else None,
                    )

                    full_text = ""
                    # Dynamic progress tracking: parse round headers from stream
                    current_round = 0
                    round_targets = [3000] + [2500] * n_skills + [2000]

                    for chunk in stream:
                        for r in range(1, total_rounds + 1):
                            marker = f"Round {r}/{total_rounds}"
                            if marker in chunk:
                                current_round = r - 1
                                pct = int((current_round / total_rounds) * 100)
                                labels = ["Analisi Base"] + [s.replace("-"," ").title() for s in skill_slugs] + ["Sintesi Finale"]
                                lbl = labels[current_round] if current_round < len(labels) else f"Round {r}"
                                progress_bar.progress(max(pct, 3), text=f"📊 {lbl}...")
                                break

                        full_text += chunk
                        output_area.markdown(full_text)

                progress_bar.progress(100, text="✅ Debate completato!")
                st.session_state.chat_history.append(
                    {"role": "assistant", "content": f"## 🧪 Opencode Multi-Skill Debate\n\n{full_text}"}
                )

            else:
                # ── Traditional AI Analysis (via AIProvider) ──
                with st.spinner("🤖 AI analyzing market data..."):
                    if meta.get("sec_type") == "OPT":
                        initial_prompt = (
                            f"Analizza la situazione di mercato per l'OPZIONE su {meta['ticker']} "
                            f"sul timeframe {meta['timeframe']}. "
                            "Usa i framework teorici (Options Playbook, Options Course, Crash Course) per valutare le Greche e la Volatilità. "
                            "Fornisci: 1) Analisi Sintetica delle Greche e del Pricing, 2) Opportunità Strategica (Sì/No/Forse), "
                            "3) Direzione Implicita, 4) Livelli Chiave (strutture consigliate), "
                            "5) Probabilità di successo."
                        )
                    else:
                        initial_prompt = (
                            f"Analizza la situazione di mercato per {meta['ticker']} "
                            f"sul timeframe {meta['timeframe']}. "
                            "Usa i principi di Volume Price Analysis (VPA) e Price Action. "
                            "Fornisci: 1) Analisi VPA (Anomalie prezzo-volume), 2) Setup Volman (se applicabile), "
                            "3) Direzione (Long/Short/Wait), 4) Livelli Chiave (S/L a 10 pip e T/P a 20 pip), "
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

            # Get AI response
            with st.chat_message("assistant", avatar="🤖"):
                with st.spinner("Analyzing..."):
                    _oc_cfg = st.session_state.get("opencode_config")
                    if OpencodeDebate and _oc_cfg is not None:
                        # Opencode session-based chat
                        _oc_agent = OpencodeAgent(_oc_cfg)
                        _sid = st.session_state.get("opencode_session_id")
                        if _sid is None:
                            _sid = _oc_agent.create_session()
                            st.session_state.opencode_session_id = _sid
                        _response_chunks = []
                        try:
                            for _chunk in _oc_agent.stream_chat(user_input, _sid):
                                _response_chunks.append(_chunk)
                        except Exception as _e:
                            ai_response = f"❌ Opencode Error: {_e}"
                        else:
                            ai_response = "".join(_response_chunks)
                    else:
                        # Traditional AI (via AIProvider)
                        ai_response = _chat_with_ai(
                            user_input, uploaded_files=uploaded_files or None
                        )
                    st.markdown(ai_response)
            st.session_state.chat_history.append(
                {"role": "assistant", "content": ai_response}
            )
