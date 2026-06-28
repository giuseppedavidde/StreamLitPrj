"""MarketAnalyzer v3 — Direct trading MCP integration, zero subprocess.

Auto-clones opencode-skills from GitHub on first run if not found.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dotenv import load_dotenv

_PROJECT_ROOT = Path(__file__).resolve().parent
load_dotenv(_PROJECT_ROOT / ".env")

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

_PROJECT_ROOT = Path(__file__).resolve().parent
_OCS_REPO = "https://github.com/anomalyco/opencode-skills.git"


def _find_or_setup_ocs() -> Path:
    ocs_home = Path(
        os.path.expanduser("~/.config/opencode/skills")
    ).parent.parent.resolve()
    ocs_sibling = (_PROJECT_ROOT.parent.parent / "opencode-skills").resolve()
    ocs_vendor = (_PROJECT_ROOT / "vendor" / "opencode-skills").resolve()
    env_root = os.environ.get("OPENSKILLS_ROOT")

    candidates: list[Path] = [ocs_vendor, ocs_sibling, ocs_home]
    if env_root:
        candidates.insert(0, Path(env_root).resolve())

    for candidate in candidates:
        mcp_pkg = candidate / "mcp" / "src" / "trading_mcp"
        if mcp_pkg.is_dir():
            return candidate.resolve()

    return _auto_clone_ocs(ocs_vendor)


def _auto_clone_ocs(target: Path) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    _log(f"opencode-skills not found — cloning from {_OCS_REPO} ...")
    _log(f"  target: {target}")

    result = subprocess.run(
        [
            "git", "clone", "--depth", "1",
            _OCS_REPO, str(target),
        ],
        capture_output=True, text=True,
        timeout=300,
    )

    if result.returncode != 0:
        stderr_tail = result.stderr.strip().split("\n")[-5:]
        raise RuntimeError(
            f"git clone failed (rc={result.returncode}).\n"
            + "\n".join(stderr_tail)
        )

    _log("  clone OK")

    python_exe = str(_PROJECT_ROOT / ".venv" / "bin" / "python3")
    if not Path(python_exe).exists():
        python_exe = sys.executable

    _log("  pip install -e ...")
    result = subprocess.run(
        [python_exe, "-m", "pip", "install", "-e",
         str(target / "mcp"), "-q"],
        capture_output=True, text=True,
        timeout=120,
    )

    if result.returncode != 0 and result.stderr.strip():
        _log(f"  pip warning (non-fatal): {result.stderr.strip()[:200]}")

    _log("  setup complete")
    return target


def _log(msg: str) -> None:
    print(f"[MarketAnalyzer] {msg}", flush=True)


_OCS_ROOT = _find_or_setup_ocs()

_MCP_SRC = str(_OCS_ROOT / "mcp" / "src")
_TICKERS_DIR = str(_OCS_ROOT / "skills" / "market-accumulation-scanner" / "data")
_SKILLS_DIR = str(_OCS_ROOT / "skills")

if _MCP_SRC not in sys.path:
    sys.path.insert(0, _MCP_SRC)

os.environ.setdefault("TRADING_SKILLS_DIR", _SKILLS_DIR)
os.environ.setdefault("TRADING_TICKERS_DIR", _TICKERS_DIR)

from trading_mcp.analysis.scanner import (  # noqa: E402
    apply_macro_regime,
    load_universe,
    process_ticker,
    set_fetch_news,
)
from trading_mcp.analysis.options_calc import analyze_options_position  # noqa: E402

UNIVERSES: dict[str, str] = {
    "us_large": "US Large Cap (~500)",
    "us_tech": "US Tech (~100)",
    "italy": "Italy - FTSE MIB (40)",
    "germany": "Germany - DAX 40 (40)",
    "france": "France - CAC 40 (40)",
    "uk": "UK - FTSE 100 (100)",
    "spain": "Spain - IBEX 35 (35)",
    "crypto": "Crypto Top (50)",
    "all": "All Markets (~900)",
}

REGIMES: list[str] = ["NORMAL", "FULL", "SELECTIVE", "DEFENSIVE"]

ETF_UNIVERSE: dict[str, str] = {
    "SPY": "S&P 500",
    "QQQ": "NASDAQ 100",
    "IGV": "Software ETF",
    "XLK": "Technology Sector",
    "XLV": "Healthcare Sector",
    "XLF": "Financial Sector",
    "XLE": "Energy Sector",
    "XLI": "Industrials Sector",
    "XLU": "Utilities Sector",
    "XLP": "Consumer Staples",
    "XLY": "Consumer Discretionary",
    "XLB": "Materials Sector",
    "XLRE": "Real Estate",
    "SMH": "Semiconductor ETF",
    "IWM": "Russell 2000",
    "VTI": "Total US Market",
    "EFA": "Developed ex-US",
    "VWO": "Emerging Markets",
    "TLT": "Long-Term Treasury",
}

DIMENSIONS: list[tuple[str, str]] = [
    ("Wyckoff Phase", "Wyckoff"),
    ("Volume Profile", "Vol Profile"),
    ("Price Action", "Price Action"),
    ("Sentiment", "Sentiment"),
    ("Fundamentals", "Fundamentals"),
]  # (name, label)

MODIFIERS_MAP: list[tuple[str, str]] = [
    ("multi_timeframe", "Multi-TF"),
    ("sot_weis_wave", "SOT/Weis"),
    ("clue6_test", "6-Clue Test"),
    ("squeeze_play", "Squeeze Play"),
    ("earnings_surprise", "Earnings Surprise"),
]

st.set_page_config(
    page_title="MarketAnalyzer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _score_color(score: float) -> str:
    if score >= 70:
        return "#198754"
    if score >= 50:
        return "#fd7e14"
    if score >= 30:
        return "#ffc107"
    return "#dc3545"


def _score_emoji(score: float) -> str:
    if score >= 70:
        return "🟢"
    if score >= 50:
        return "🟡"
    if score >= 30:
        return "🟠"
    return "🔴"


def _dimension_score(dimensions: list[dict], name: str) -> float:
    for d in dimensions:
        if d["name"] == name:
            return d["score"]
    return 0


def _dimension_detail(dimensions: list[dict], name: str) -> str:
    for d in dimensions:
        if d["name"] == name:
            return d.get("detail", "")
    return ""


def _modifier_score(modifiers: dict, key: str) -> float | None:
    m = modifiers.get(key)
    if isinstance(m, dict):
        return m.get("score")
    return m if isinstance(m, (int, float)) else None


def _modifier_detail(modifiers: dict, key: str) -> str:
    m = modifiers.get(key)
    if isinstance(m, dict):
        return m.get("detail", "")
    return ""


def _run_ticker_scan(t_dict: dict) -> dict | None:
    try:
        return process_ticker(t_dict)
    except Exception:
        return None


def _load_ticker_count(universe: str) -> int:
    try:
        ul = load_universe(universe, _TICKERS_DIR)
        return len(ul)
    except Exception:
        return 0


def _show_detail_card(result: dict) -> None:
    score = result.get("final_score", 0)
    symbol = result.get("symbol", "?")
    sector = result.get("sector", "")
    price = result.get("price", "")
    pattern = result.get("pattern", "")
    dimensions = result.get("dimensions", [])
    modifiers = result.get("modifiers", {})
    name = result.get("name", "")

    badge_color = _score_color(score)
    st.markdown(
        f"<span style='font-size:1.5em;color:{badge_color};font-weight:bold'>"
        f"{_score_emoji(score)} {symbol} — {score:.0f}/100</span>"
        f"<span style='margin-left:1em;color:#888'>"
        f"{'$'+str(price) if price else ''}"
        f"{' · ' + sector if sector else ''}"
        f"{' · ' + pattern if pattern else ''}</span>",
        unsafe_allow_html=True,
    )

    if name and name != symbol:
        st.caption(name)

    cols_dim = st.columns(len(DIMENSIONS))
    for i, (dim_name, label) in enumerate(DIMENSIONS):
        val = _dimension_score(dimensions, dim_name)
        with cols_dim[i]:
            st.metric(label, f"{val:.0f}")

    st.markdown("---")
    st.markdown("### Dimension Details")
    for dim_name, label in DIMENSIONS:
        detail = _dimension_detail(dimensions, dim_name)
        score_val = _dimension_score(dimensions, dim_name)
        if detail:
            with st.expander(f"{label}: {score_val:.0f}/100", expanded=False):
                st.caption(detail)

    active_mods = [
        (k, l) for k, l in MODIFIERS_MAP if _modifier_score(modifiers, k) is not None
    ]
    if active_mods:
        st.markdown("---")
        st.markdown("### Enhancement Modifiers")
        enh_cols = st.columns(len(active_mods))
        for i, (mod_key, mod_label) in enumerate(active_mods):
            with enh_cols[i]:
                st.metric(
                    mod_label,
                    f"{_modifier_score(modifiers, mod_key):.0f}",
                )
                det = _modifier_detail(modifiers, mod_key)
                if det:
                    with st.expander("Detail", expanded=False):
                        st.caption(det)

    sb = result.get("sentiment_breakdown")
    if sb:
        st.markdown("---")
        st.markdown("### Sentiment Breakdown")
        sub_keys = [
            ("short_interest", "Short Interest"),
            ("options_sentiment", "Options"),
            ("insider_trading", "Insider"),
            ("institutional", "Institutional"),
            ("web_news", "Web News"),
            ("social_media", "Social"),
            ("earnings_quality", "Earnings Quality"),
            ("retail_sentiment", "Retail"),
            ("momentum", "Momentum"),
        ]
        sub_cols = st.columns(len(sub_keys))
        for i, (sk, sl) in enumerate(sub_keys):
            val = sb.get(sk)
            with sub_cols[i]:
                st.metric(
                    sl,
                    f"{val:.0f}" if isinstance(val, (int, float)) else "N/A",
                )

    indicators = result.get("indicators", {})
    ind_keys = [
        ("candlestick", "Candlestick"),
        ("bollinger", "Bollinger"),
        ("fibonacci", "Fibonacci"),
        ("obv", "OBV"),
        ("ichimoku", "Ichimoku"),
        ("risk_reward", "Risk/Reward"),
    ]
    if any(k in indicators for k, _ in ind_keys):
        st.markdown("---")
        st.markdown("### Technical Indicators")
        ind_cols = st.columns(len(ind_keys))
        for i, (ik, il) in enumerate(ind_keys):
            v = indicators.get(ik)
            if v is not None:
                with ind_cols[i]:
                    st.metric(il, f"{v:.0f}" if isinstance(v, (int, float)) else str(v))


# ---------------------------------------------------------------------------
# sidebar
# ---------------------------------------------------------------------------
st.sidebar.title("📊 MarketAnalyzer")
st.sidebar.markdown("*Direct trading MCP engine*")
st.sidebar.markdown("---")

st.sidebar.markdown("### ⚙️ Global Settings")
fetch_news_global = st.sidebar.checkbox("Fetch news sentiment (slower)", value=False)
set_fetch_news(fetch_news_global)

st.sidebar.markdown("---")
st.sidebar.caption("Data: yfinance + CoinGecko")
st.sidebar.caption("Engine: trading-mcp-server")

if "scan_history" not in st.session_state:
    st.session_state.scan_history = []

# ---------------------------------------------------------------------------
# main tabs
# ---------------------------------------------------------------------------

st.title("📊 MarketAnalyzer")
st.markdown("Scanner + DeepDive + Chat — powered by trading MCP directly")

tab1, tab2, tab3 = st.tabs(["🔍 Scanner", "🎯 Deep Dive", "💬 Chat"])

# ===========================================================================
# TAB 1 — Scanner
# ===========================================================================
with tab1:
    col_mode, col_how = st.columns([2, 1])
    with col_mode:
        scan_mode = st.radio(
            "Mode",
            ["Ticker Singolo", "Scansione Mercato"],
            horizontal=True,
            key="scan_mode",
            help="Single ticker or full market scan",
        )
    with col_how:
        if scan_mode == "Scansione Mercato":
            asset_type = st.radio(
                "Asset type",
                ["Single Stock", "ETF"],
                horizontal=True,
                key="asset_type",
            )

    col1, col2, col3 = st.columns(3)
    top_n = 15
    asset_type_st = "Single Stock"

    if scan_mode == "Ticker Singolo":
        with col1:
            ticker_input = st.text_input(
                "Ticker", value="AAPL", key="single_ticker",
                help="Symbol (e.g. AAPL, ENI.MI, SAP.DE)",
            )
        with col2:
            min_score = st.slider("Min score", 0, 100, 0, 5, key="single_min_score")
        with col3:
            regime = st.selectbox("Regime", REGIMES, index=0, key="single_regime")
    elif asset_type_st == "ETF" or st.session_state.get("asset_type") == "ETF":
        asset_type_st = "ETF"
        with col1:
            selected_etf = st.selectbox(
                "ETF",
                list(ETF_UNIVERSE.keys()),
                format_func=lambda e: f"{e} — {ETF_UNIVERSE[e]}",
                key="scan_etf",
            )
        with col2:
            min_score = st.slider("Min score", 0, 100, 40, 5, key="etf_min_score")
        with col3:
            top_n = st.slider("Top N", 5, 50, 15, 5, key="etf_top_n")
            regime = st.selectbox("Regime", REGIMES, index=0, key="etf_regime")
    else:
        with col1:
            selected_universe = st.selectbox(
                "Universe",
                list(UNIVERSES.keys()),
                format_func=lambda u: UNIVERSES[u],
                key="scan_universe",
            )
            tc = _load_ticker_count(selected_universe)
            if tc:
                st.caption(f"{tc} tickers")
        with col2:
            min_score = st.slider("Min score", 0, 100, 50, 5, key="market_min_score")
        with col3:
            top_n = st.slider("Top N", 5, 50, 15, 5, key="market_top_n")
            regime = st.selectbox("Regime", REGIMES, index=0, key="market_regime")

    run_scan = st.button("🔍 Start Scan", type="primary", use_container_width=True)

    if run_scan:
        if scan_mode == "Ticker Singolo" and not st.session_state.single_ticker.strip():
            st.error("Enter a valid ticker.")
            st.stop()

        with st.spinner("Scanning... (may take a few minutes for large universes)"):
            t0 = time.time()
            results_raw: list[dict] = []
            failures = 0

            if scan_mode == "Ticker Singolo":
                ticker = st.session_state.single_ticker.strip().upper()
                t_dict = {"symbol": ticker, "name": ticker, "market": "US"}
                r = _run_ticker_scan(t_dict)
                if r:
                    results_raw = [r]
                    st.info(f"Scanned **{ticker}** in {time.time() - t0:.1f}s")
                else:
                    st.error(f"Could not process {ticker}")
                    st.stop()

            elif asset_type_st == "ETF" or st.session_state.get("asset_type") == "ETF":
                etf_ticker = st.session_state.scan_etf
                import yfinance as yf  # noqa: E402

                with st.spinner(f"Fetching holdings of {etf_ticker}..."):
                    etf = yf.Ticker(etf_ticker)
                    try:
                        holdings_df = etf.get_holdings()
                        holding_tickers = (
                            holdings_df.index.tolist()
                            if holdings_df is not None and not holdings_df.empty
                            else []
                        )
                    except Exception:
                        holding_tickers = []

                if not holding_tickers:
                    st.warning(f"No holdings for {etf_ticker}.")
                    st.stop()

                holding_tickers = holding_tickers[:50]
                universe_list = [
                    {"symbol": h, "name": h, "market": "US"}
                    for h in holding_tickers
                ]
                st.info(f"Scanning **{len(universe_list)} holdings** of {etf_ticker}...")
                batch_scan_info = (
                    f"ETF:{etf_ticker}",
                    universe_list,
                    t0,
                    regime,
                    min_score,
                    top_n,
                )

            else:
                universe_list = load_universe(selected_universe, _TICKERS_DIR)
                st.info(
                    f"Scanning **{UNIVERSES[selected_universe]}** "
                    f"({len(universe_list)} tickers)..."
                )
                batch_scan_info = (
                    selected_universe,
                    universe_list,
                    t0,
                    regime,
                    min_score,
                    top_n,
                )

            if scan_mode != "Ticker Singolo":
                max_workers = min(20, len(universe_list))
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    future_map = {
                        executor.submit(_run_ticker_scan, td): td["symbol"]
                        for td in universe_list
                    }
                    progress = st.progress(0)
                    total = len(universe_list)
                    completed = 0
                    for future in as_completed(future_map):
                        completed += 1
                        symbol = future_map[future]
                        try:
                            res = future.result(timeout=30)
                        except Exception:
                            res = None
                        if res:
                            results_raw.append(res)
                        else:
                            failures += 1
                        progress.progress(completed / total)
                    progress.empty()

                results_raw.sort(key=lambda r: r["final_score"], reverse=True)
                results_raw = apply_macro_regime(results_raw, regime)
                results_raw.sort(key=lambda r: r["final_score"], reverse=True)
                results_raw = [
                    r for r in results_raw if r["final_score"] >= min_score
                ]
                results_raw = results_raw[:top_n]

                elapsed = time.time() - t0
                st.success(
                    f"Done in {elapsed:.1f}s — {len(results_raw)} passed, "
                    f"{failures} failed (of {total})"
                )

            if not results_raw:
                st.warning("No results above threshold.")
                st.stop()

            st.session_state["scan_results"] = results_raw
            if scan_mode == "Ticker Singolo":
                ulabel = "CUSTOM"
            elif asset_type_st == "ETF":
                ulabel = f"ETF:{st.session_state.scan_etf}"
            else:
                ulabel = selected_universe
            st.session_state["scan_args"] = {
                "mode": scan_mode,
                "universe": ulabel,
                "at": time.strftime("%Y-%m-%d %H:%M"),
                "count": len(results_raw),
            }

    results = st.session_state.get("scan_results")
    scan_args = st.session_state.get("scan_args")
    if results:
        st.markdown("---")
        st.caption(
            f"**{scan_args['mode']}** · {scan_args['universe']}"
            f" · {scan_args['count']} results · {scan_args['at']}"
        )

        st.subheader("📋 Results")
        df_rows: list[dict] = []
        for r in results:
            dims = r.get("dimensions", [])
            df_rows.append(
                {
                    "Ticker": r.get("symbol", "?"),
                    "Score": r.get("final_score", 0),
                    "Wyckoff": _dimension_score(dims, "Wyckoff Phase"),
                    "VolProf": _dimension_score(dims, "Volume Profile"),
                    "PriceAct": _dimension_score(dims, "Price Action"),
                    "Sentiment": _dimension_score(dims, "Sentiment"),
                    "Fundament": _dimension_score(dims, "Fundamentals"),
                    "Pattern": r.get("pattern", "-"),
                    "Price": r.get("price", "-"),
                }
            )

        df = pd.DataFrame(df_rows).sort_values("Score", ascending=False)

        def _color_score(val):
            try:
                return f"color: {_score_color(float(val))}; font-weight: bold"
            except (ValueError, TypeError):
                return ""

        styled = df.style.map(_color_score, subset=["Score"])
        st.dataframe(
            styled,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Score": st.column_config.NumberColumn("Score", format="%.1f"),
                "Wyckoff": st.column_config.NumberColumn("Wyckoff", format="%.0f"),
                "VolProf": st.column_config.NumberColumn("Vol Prof", format="%.0f"),
                "PriceAct": st.column_config.NumberColumn("Price Act", format="%.0f"),
                "Sentiment": st.column_config.NumberColumn("Sentiment", format="%.0f"),
                "Fundament": st.column_config.NumberColumn("Fundament", format="%.0f"),
            },
        )

        if len(results) == 1:
            _show_detail_card(results[0])
        else:
            st.markdown("---")
            st.subheader("🔎 Top 3 Details")
            top3 = sorted(
                results, key=lambda x: x.get("final_score", 0), reverse=True
            )[:3]
            for i, r in enumerate(top3):
                with st.expander(
                    f"#{i + 1} **{r.get('symbol', '?')}**"
                    f" — Score {r.get('final_score', 0):.0f}/100"
                    f" — {r.get('pattern', '')}",
                    expanded=(i == 0),
                ):
                    _show_detail_card(r)

        st.download_button(
            "📥 Export CSV",
            df.to_csv(index=False).encode("utf-8"),
            file_name=f"scan_{time.strftime('%Y%m%d_%H%M')}.csv",
            mime="text/csv",
        )


# ===========================================================================
# TAB 2 — Deep Dive
# ===========================================================================
with tab2:
    st.markdown(
        "Deep single-ticker analysis using `process_ticker` from the MCP engine."
    )

    col_a, col_b = st.columns([2, 1])
    with col_a:
        dd_ticker = st.text_input(
            "Ticker", value="AAPL", key="dd_ticker",
            help="Single ticker for full deep dive",
        )
    with col_b:
        dd_options = st.checkbox(
            "Include options analysis", value=False, key="dd_options",
        )

    if dd_options:
        dd_expiry = st.text_input(
            "Options expiry (e.g. '2026-12-19')",
            value="", key="dd_expiry",
            help="Leave empty for default >=30 DTE",
        )

    if st.button("🎯 Start Deep Dive", type="primary", use_container_width=True):
        ticker = st.session_state.dd_ticker.strip().upper()
        if not ticker:
            st.error("Enter a ticker.")
            st.stop()

        with st.spinner(f"Analyzing {ticker}..."):
            t0 = time.time()
            t_dict = {"symbol": ticker, "name": ticker, "market": "US"}
            result = _run_ticker_scan(t_dict)

            if result is None:
                st.error(f"Could not analyze {ticker}.")
                st.stop()

            elapsed = time.time() - t0
            st.success(f"Analysis complete in {elapsed:.1f}s")
            st.session_state["dd_result"] = result

            if dd_options:
                try:
                    import yfinance as yf  # noqa: E402

                    expiry = st.session_state.get("dd_expiry", "").strip()
                    options_result = (
                        analyze_options_position(ticker, [])
                        if not expiry
                        else None
                    )
                    if options_result:
                        st.session_state["dd_options_result"] = options_result
                except Exception as exc:
                    st.warning(f"Options analysis skipped: {exc}")

    dd_result = st.session_state.get("dd_result")
    if dd_result:
        st.markdown("---")
        score = dd_result.get("final_score", 0)
        symbol = dd_result.get("symbol", "?")
        pattern = dd_result.get("pattern", "")
        verdict = "LONG-TERM INVESTMENT" if score >= 70 else (
            "SHORT-TERM SPECULATION" if score >= 50 else "AVOID / WAIT"
        )

        st.markdown(
            f"### {_score_emoji(score)} {symbol} — **{verdict}** "
            f"({score:.0f}/100) · {pattern}"
        )
        _show_detail_card(dd_result)


# ===========================================================================
# TAB 3 — Chat
# ===========================================================================
with tab3:
    st.markdown(
        "Free chat with **openCode**. Ask anything: "
        "analysis, scans, strategies, market questions."
    )
    st.info(
        "Note: This tab uses `opencode run` subprocess. "
        "Scanner and DeepDive use direct MCP calls (faster)."
    )

    if "chat_messages" not in st.session_state:
        st.session_state.chat_messages = []

    for msg in st.session_state.chat_messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    chat_input = st.chat_input("Message for openCode...")

    if chat_input:
        st.session_state.chat_messages.append({"role": "user", "content": chat_input})
        with st.chat_message("user"):
            st.markdown(chat_input)

        with st.chat_message("assistant"):
            with st.spinner("openCode thinking..."):
                try:
                    proc = subprocess.run(
                        ["opencode", "run", chat_input],
                        capture_output=True, text=True, timeout=600,
                    )
                    response = proc.stdout
                    st.markdown(response)
                    st.session_state.chat_messages.append(
                        {"role": "assistant", "content": response}
                    )
                except subprocess.TimeoutExpired:
                    err = "Timeout (>10 min). Try a simpler question."
                    st.error(err)
                    st.session_state.chat_messages.append(
                        {"role": "assistant", "content": err}
                    )
                except Exception as exc:
                    err = f"Error: {exc}"
                    st.error(err)
                    st.session_state.chat_messages.append(
                        {"role": "assistant", "content": err}
                    )

    if st.session_state.chat_messages:
        if st.button("🗑️ Clear chat", key="clear_chat"):
            st.session_state.chat_messages = []
            st.rerun()
