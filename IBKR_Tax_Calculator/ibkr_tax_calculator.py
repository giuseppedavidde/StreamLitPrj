"""IBKR Tax Calculator — Streamlit Dashboard with AI Agent integration."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import io
import os
import datetime

from dotenv import load_dotenv
from ecb_fx import fetch_usdeur_range, fetch_usdeur_for_date

load_dotenv()

try:
    from agents import TraderAgent
    from agents.ai_provider import AIProvider
except ImportError:
    TraderAgent = None
    AIProvider = None

st.set_page_config(page_title="IBKR Tax Calculator", layout="wide", page_icon="📊")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "parsed_data" not in st.session_state:
    st.session_state.parsed_data = None
# Cache for ECB FX rates: maps date -> USD/EUR rate (USD per 1 EUR)
if "fx_cache" not in st.session_state:
    st.session_state.fx_cache = {}


# ─── ECB FX helpers ─────────────────────────────────────────────────────────

def _get_cached_rate(trade_date: datetime.date) -> float:
    """Return cached USD/EUR rate for a date, or 1.0 as fallback."""
    cache = st.session_state.fx_cache
    if trade_date in cache:
        return cache[trade_date]
    # Fallback: look for the most recent prior date in cache
    prior = [d for d in cache if d <= trade_date]
    if prior:
        return cache[max(prior)]
    return 1.0  # should not happen after enrich step


def enrich_trades_with_eur(data: dict) -> None:
    """Batch-fetch ECB USD/EUR rates for all unique trade dates and add EUR columns.

    Modifies `data['trades']` in-place, adding:
      - fx_rate        : USD/EUR rate used (USD per 1 EUR)
      - fx_rate_date   : actual ECB publication date for the rate
      - realized_pl_eur: realized_pl converted to EUR
      - commission_eur : commission converted to EUR
      - proceeds_eur   : proceeds converted to EUR
      - cost_basis_eur : cost_basis converted to EUR

    For trades already in EUR (currency != 'USD') the rate is set to 1.0.
    """
    trades = data.get("trades", [])
    if not trades:
        return

    # Collect all unique dates where currency is USD
    usd_dates = set()
    for t in trades:
        if t.get("currency", "USD") == "USD":
            try:
                dt = datetime.date.fromisoformat(str(t["datetime"])[:10])
                usd_dates.add(dt)
            except ValueError:
                pass

    # Single bulk API call for the full date range
    if usd_dates:
        min_date = min(usd_dates)
        max_date = max(usd_dates)
        # Extend window a bit to cover weekends/holidays at the edges
        min_date -= datetime.timedelta(days=10)
        rates_map = fetch_usdeur_range(min_date, max_date)
        # Sort dates so we can do forward-fill for non-trading days
        sorted_dates = sorted(rates_map.keys())
        date_to_rate = {}
        for d in sorted(usd_dates):
            # find nearest prior date in rates_map
            candidates = [rd for rd in sorted_dates if rd <= d]
            if candidates:
                chosen = max(candidates)
                date_to_rate[d] = (rates_map[chosen], chosen)
            else:
                date_to_rate[d] = (1.0, d)  # fallback
        # Persist into session cache
        for d, (rate, _) in date_to_rate.items():
            st.session_state.fx_cache[d] = rate
    else:
        date_to_rate = {}

    # Annotate each trade
    for t in trades:
        currency = t.get("currency", "USD")
        if currency != "USD":
            t["fx_rate"] = 1.0
            t["fx_rate_date"] = None
            t["realized_pl_eur"] = t["realized_pl"]
            t["commission_eur"] = t["commission"]
            t["proceeds_eur"] = t["proceeds"]
            t["cost_basis_eur"] = t["cost_basis"]
            continue
        try:
            dt = datetime.date.fromisoformat(str(t["datetime"])[:10])
        except ValueError:
            dt = None
        if dt and dt in date_to_rate:
            rate, rate_date = date_to_rate[dt]
        else:
            rate, rate_date = 1.0, None
        t["fx_rate"] = rate
        t["fx_rate_date"] = rate_date
        # Convert: USD_amount / (USD per EUR) = EUR_amount
        t["realized_pl_eur"] = t["realized_pl"] / rate if rate else t["realized_pl"]
        t["commission_eur"] = t["commission"] / rate if rate else t["commission"]
        t["proceeds_eur"] = t["proceeds"] / rate if rate else t["proceeds"]
        t["cost_basis_eur"] = t["cost_basis"] / rate if rate else t["cost_basis"]


# ─── CSV Parser ─────────────────────────────────────────────────────────────

def parse_ibkr_csv(file) -> dict:
    """Parse IBKR activity statement CSV into structured sections."""
    content = file.read().decode("utf-8") if hasattr(file, "read") else open(file, "r", encoding="utf-8").read()
    lines = content.strip().split("\n")

    data = {
        "account_info": {},
        "nav": [],
        "nav_change": {},
        "mtm_summary": [],
        "realized_unrealized": [],
        "trades": [],
        "open_positions": [],
        "deposits": [],
        "commissions": [],
        "forex_trades": [],
        "total_pl": None,
    }

    for line in lines:
        # Use csv reader for proper comma handling inside quotes
        import csv
        row = next(csv.reader(io.StringIO(line)))
        section = row[0].strip() if row else ""
        discriminator = row[1].strip() if len(row) > 1 else ""

        # Account Info
        if section == "Dati del conto" and discriminator == "Data":
            key = row[2].strip() if len(row) > 2 else ""
            val = row[3].strip() if len(row) > 3 else ""
            data["account_info"][key] = val

        # NAV
        elif section == "Valore patrimoniale netto" and discriminator == "Data":
            if len(row) >= 7:
                try:
                    data["nav"].append({
                        "asset_class": row[2].strip(),
                        "previous_total": _safe_float(row[3]),
                        "long_current": _safe_float(row[4]),
                        "short_current": _safe_float(row[5]),
                        "current_total": _safe_float(row[6]),
                        "change": _safe_float(row[7]) if len(row) > 7 else 0,
                    })
                except (ValueError, IndexError):
                    pass

        # NAV Change
        elif section == "Variazione del VPN" and discriminator == "Data":
            key = row[2].strip() if len(row) > 2 else ""
            val = row[3].strip() if len(row) > 3 else ""
            data["nav_change"][key] = _safe_float(val)

        # MTM P/L Summary
        elif section == "Sommario profitti e perdite Mark to market" and discriminator == "Data":
            if len(row) >= 13 and row[2].strip() not in ("Totale", "Totale (tutti i prodotti)",
                                                           "Interessi broker pagati e ricevuti",
                                                           "Altre commissioni"):
                if row[3].strip():  # has symbol
                    data["mtm_summary"].append({
                        "asset_type": row[2].strip(),
                        "symbol": row[3].strip(),
                        "prev_qty": _safe_float(row[4]),
                        "curr_qty": _safe_float(row[5]),
                        "mtm_position": _safe_float(row[8]),
                        "mtm_transaction": _safe_float(row[9]),
                        "mtm_commissions": _safe_float(row[10]),
                        "mtm_total": _safe_float(row[12]),
                    })

        # Realized / Unrealized P/L
        elif section == "Sommario profitti e perdite Realizzati e Non realizzati" and discriminator == "Data":
            if len(row) >= 16 and row[2].strip() not in ("Totale", "Totale (tutti i prodotti)"):
                if row[3].strip():
                    data["realized_unrealized"].append({
                        "asset_type": row[2].strip(),
                        "symbol": row[3].strip(),
                        "cost_adj": _safe_float(row[4]),
                        "realized_profit_st": _safe_float(row[5]),
                        "realized_loss_st": _safe_float(row[6]),
                        "realized_profit_lt": _safe_float(row[7]),
                        "realized_loss_lt": _safe_float(row[8]),
                        "realized_total": _safe_float(row[9]),
                        "unrealized_profit_st": _safe_float(row[10]),
                        "unrealized_loss_st": _safe_float(row[11]),
                        "unrealized_total": _safe_float(row[14]),
                        "total": _safe_float(row[15]),
                    })

        # Trade Details
        elif section == "Dettaglio eseguiti" and discriminator == "Data":
            if len(row) >= 15 and row[2].strip() == "Order":
                asset_type = row[3].strip()
                if asset_type == "Forex":
                    data["forex_trades"].append({
                        "symbol": row[5].strip(),
                        "datetime": row[6].strip(),
                        "quantity": _safe_float(row[7]),
                        "price": _safe_float(row[8]),
                        "proceeds": _safe_float(row[10]),
                        "commission": _safe_float(row[11]),
                    })
                else:
                    data["trades"].append({
                        "asset_type": asset_type,
                        "currency": row[4].strip(),
                        "symbol": row[5].strip(),
                        "datetime": row[6].strip(),
                        "quantity": _safe_float(row[7]),
                        "price": _safe_float(row[8]),
                        "close_price": _safe_float(row[9]),
                        "proceeds": _safe_float(row[10]),
                        "commission": _safe_float(row[11]),
                        "cost_basis": _safe_float(row[12]),
                        "realized_pl": _safe_float(row[13]),
                        "mtm_pl": _safe_float(row[14]),
                        "code": row[15].strip() if len(row) > 15 else "",
                    })

        # Open Positions
        elif section == "Posizioni aperte" and discriminator == "Data":
            if len(row) >= 13 and row[2].strip() == "Summary":
                data["open_positions"].append({
                    "asset_type": row[3].strip(),
                    "currency": row[4].strip(),
                    "symbol": row[5].strip(),
                    "quantity": _safe_float(row[6]),
                    "multiplier": _safe_float(row[7]),
                    "cost_price": _safe_float(row[8]),
                    "cost_basis": _safe_float(row[9]),
                    "close_price": _safe_float(row[10]),
                    "value": _safe_float(row[11]),
                    "unrealized_pl": _safe_float(row[12]),
                })

        # Deposits
        elif section == "Versamenti e prelievi" and discriminator == "Data":
            if len(row) >= 6 and row[2].strip() != "Totale":
                data["deposits"].append({
                    "currency": row[2].strip(),
                    "date": row[3].strip(),
                    "description": row[4].strip(),
                    "amount": _safe_float(row[5]),
                })

        # Total P/L
        elif section == "P/L totale per il periodo del rendiconto":
            if len(row) >= 13:
                data["total_pl"] = _safe_float(row[12])

    return data


def _safe_float(val) -> float:
    """Convert string to float, returning 0 for non-numeric values."""
    if isinstance(val, (int, float)):
        return float(val)
    try:
        cleaned = str(val).strip().replace(",", "").replace("%", "").replace("--", "0")
        return float(cleaned) if cleaned else 0.0
    except (ValueError, TypeError):
        return 0.0


# ─── AI Chat ────────────────────────────────────────────────────────────────

def _build_tax_context(data: dict) -> str:
    """Build a text summary of fiscal data for the AI."""
    lines = []
    # Account
    acc = data.get("account_info", {})
    lines.append(f"ACCOUNT: {acc.get('Nome', 'N/A')} | {acc.get('Conto', 'N/A')} | Base: {acc.get('Valuta di base', 'EUR')}")
    lines.append("")

    # NAV
    lines.append("═══ NET ASSET VALUE ═══")
    for item in data.get("nav", []):
        lines.append(f"  {item['asset_class']}: Previous={item['previous_total']:.2f} → Current={item['current_total']:.2f} (Δ {item['change']:+.2f})")

    # NAV Change
    nav_chg = data.get("nav_change", {})
    if nav_chg:
        lines.append("")
        lines.append("═══ NAV CHANGE BREAKDOWN ═══")
        for k, v in nav_chg.items():
            lines.append(f"  {k}: {v:+.2f}")

    # Total P/L
    if data.get("total_pl") is not None:
        lines.append(f"\n═══ TOTAL P/L FOR PERIOD: {data['total_pl']:+.2f} EUR ═══")

    # Realized/Unrealized
    rl = data.get("realized_unrealized", [])
    if rl:
        lines.append("\n═══ REALIZED & UNREALIZED P/L ═══")
        for r in rl:
            lines.append(f"  {r['asset_type']} | {r['symbol']}: Realized={r['realized_total']:+.2f} | Unrealized={r['unrealized_total']:+.2f} | Total={r['total']:+.2f}")

    # Trades — show both USD original and EUR converted values
    trades = data.get("trades", [])
    if trades:
        lines.append(f"\n═══ TRADES ({len(trades)} total) — P/L converted to EUR using ECB rates ═══")
        for t in trades:
            side = "BUY" if t["quantity"] > 0 else "SELL"
            pl_eur = t.get("realized_pl_eur", t["realized_pl"])
            fx = t.get("fx_rate", 1.0)
            comm_eur = t.get("commission_eur", t["commission"])
            lines.append(
                f"  {t['datetime']} | {side} {abs(t['quantity']):.4f} {t['symbol']} @ {t['price']:.4f} {t['currency']} | "
                f"P/L={t['realized_pl']:+.2f} {t['currency']} ({pl_eur:+.2f} EUR @ {fx:.4f}) | "
                f"Comm={t['commission']:.2f} {t['currency']} ({comm_eur:.2f} EUR) | Code={t['code']}"
            )

    # Open Positions
    op = data.get("open_positions", [])
    if op:
        lines.append(f"\n═══ OPEN POSITIONS ({len(op)}) ═══")
        for p in op:
            lines.append(
                f"  {p['symbol']}: Qty={p['quantity']:.4f} | Cost={p['cost_basis']:.2f} | Value={p['value']:.2f} | "
                f"Unrealized P/L={p['unrealized_pl']:+.2f} {p['currency']}"
            )

    # Deposits
    deps = data.get("deposits", [])
    if deps:
        total_dep = sum(d["amount"] for d in deps)
        lines.append(f"\n═══ DEPOSITS: {total_dep:,.2f} EUR ({len(deps)} transfers) ═══")

    return "\n".join(lines)


def _chat_with_ai(user_message: str, data: dict) -> str:
    """Send a message to the AI with full fiscal context."""
    if not TraderAgent:
        return "⚠️ AI Agent non disponibile (modulo `agents` non trovato). Installa `custom_agents`."

    context = _build_tax_context(data)
    provider_type = st.session_state.get("ai_provider", "gemini")
    model_name = st.session_state.get("ai_model_name")

    agent = TraderAgent(provider_type=provider_type, model_name=model_name)

    history_text = ""
    for msg in st.session_state.chat_history[-6:]:
        role = "User" if msg["role"] == "user" else "Analyst"
        history_text += f"\n{role}: {msg['content']}\n"

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    prompt = f"""Sei un consulente fiscale e analista finanziario esperto in tassazione austriaca (KESt 27.5%) e tassazione italiana (26% capital gains).
Oggi è il {today_str}.

Hai accesso ai seguenti dati REALI del rendiconto IBKR annuale:
{context}

{'CONVERSAZIONE PRECEDENTE:' + history_text if history_text else ''}

DOMANDA:
{user_message}

ISTRUZIONI:
- Rispondi SOLO basandoti sui dati forniti. Non inventare numeri.
- Se viene chiesta un'analisi degli errori di trading, identifica i trade in perdita, spiega i pattern di errore e suggerisci miglioramenti.
- Per questioni fiscali, evidenzia: P/L realizzato vs non realizzato, commissioni deducibili, impatto cambi EUR/USD.
- Formatta con markdown (bold, tabelle, liste) per leggibilità.
- Rispondi nella lingua dell'utente.
"""

    try:
        actual_model = agent.ai.current_model_name
        response = agent.ai.get_model().generate_content(prompt)
        badge = f"*🤖 Model: `{provider_type}` / `{actual_model}`*\n\n---\n\n"
        return badge + response.text
    except Exception as e:
        return f"❌ AI Error ({provider_type}/{model_name}): {e}"


# ─── Sidebar ────────────────────────────────────────────────────────────────

st.sidebar.title("📊 IBKR Tax Calculator")
uploaded_file = st.sidebar.file_uploader("Carica rendiconto IBKR (CSV)", type=["csv"])

if uploaded_file:
    data = parse_ibkr_csv(uploaded_file)
    # Reset FX cache when a new file is loaded
    st.session_state.fx_cache = {}
    with st.sidebar:
        with st.spinner("🌐 Fetching ECB USD/EUR exchange rates…"):
            enrich_trades_with_eur(data)
    st.session_state.parsed_data = data

# AI Model Selection
if TraderAgent and AIProvider:
    st.sidebar.markdown("---")
    st.sidebar.title("🤖 AI Model")
    supported_providers = AIProvider.get_supported_providers()
    ai_provider = st.sidebar.selectbox(
        "Provider",
        supported_providers,
        format_func=lambda x: {
            "gemini": "☁️ Gemini (Cloud)",
            "ollama": "🖥️ Ollama (Local)",
            "groq": "⚡ Groq (LPU Cloud)",
            "puter": "🧠 Claude (Puter Free)",
        }.get(x.lower(), x),
    )
    ai_provider = ai_provider.lower()
    st.session_state.ai_provider = ai_provider

    if ai_provider == "ollama":
        ollama_models = AIProvider.get_ollama_models()
        if ollama_models:
            st.session_state.ai_model_name = st.sidebar.selectbox("Model", ollama_models)
        else:
            st.sidebar.warning("Nessun modello Ollama trovato.")
            st.session_state.ai_model_name = None
    elif ai_provider == "groq":
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            api_key = st.sidebar.text_input("Groq API Key", type="password")
            if api_key:
                os.environ["GROQ_API_KEY"] = api_key
        if not os.getenv("GROQ_API_KEY"):
            st.sidebar.warning("🔑 Groq API Key richiesta.")
            st.session_state.ai_model_name = None
        else:
            try:
                groq_models = AIProvider.get_groq_models(api_key=os.getenv("GROQ_API_KEY"))
            except Exception:
                groq_models = []
            if groq_models:
                st.session_state.ai_model_name = st.sidebar.selectbox("Model", groq_models)
            else:
                st.sidebar.error("❌ Impossibile caricare modelli Groq.")
                st.session_state.ai_model_name = None
    elif ai_provider == "puter":
        puter_key = os.getenv("PUTER_API_KEY")
        if not puter_key:
            puter_key = st.sidebar.text_input("Puter Auth Token", type="password")
            if puter_key:
                os.environ["PUTER_API_KEY"] = puter_key
        if not os.getenv("PUTER_API_KEY"):
            st.sidebar.warning("🔑 Puter Auth Token richiesto.")
            st.session_state.ai_model_name = None
        else:
            puter_models = AIProvider.get_puter_models()
            st.session_state.ai_model_name = st.sidebar.selectbox("Claude Model", puter_models)
    else:
        try:
            gemini_models = AIProvider.get_gemini_models()
        except Exception:
            gemini_models = AIProvider.FALLBACK_ORDER
        if gemini_models:
            st.session_state.ai_model_name = st.sidebar.selectbox("Model", gemini_models)
        else:
            st.sidebar.error("❌ Impossibile caricare modelli Gemini.")
            st.session_state.ai_model_name = None


# ─── Main Dashboard ─────────────────────────────────────────────────────────

data = st.session_state.parsed_data

if data is None:
    st.title("📊 IBKR Tax Calculator")
    st.info("⬅️ Carica un rendiconto IBKR (CSV) dalla sidebar per iniziare.")
    st.markdown("""
    ### Funzionalità
    - **Dashboard P/L**: Visualizzazione gain/loss per asset class con grafici interattivi
    - **Dettaglio Trade**: Ogni singola operazione con P/L realizzato
    - **Posizioni Aperte**: Stato attuale del portafoglio con P/L non realizzato
    - **Riepilogo Fiscale**: Dati rilevanti per la dichiarazione dei redditi
    - **AI Assistant**: Chatta con l'AI per analizzare errori di trading e ottimizzazione fiscale
    """)
    st.stop()

# Account header
acc = data["account_info"]
st.title(f"📊 {acc.get('Nome', 'N/A')} — {acc.get('Conto', 'N/A')}")
st.caption(f"Broker: {acc.get('Nome master', '')} | Tipo: {acc.get('Tipo di conto', '')} | Valuta base: {acc.get('Valuta di base', 'EUR')}")

# ─── TAB Navigation ─────────────────────────────────────────────────────────
tab_overview, tab_trades, tab_positions, tab_fiscal, tab_ai = st.tabs([
    "📈 Overview", "📋 Dettaglio Trade", "💼 Posizioni Aperte", "🏛️ Riepilogo Fiscale", "🤖 AI Assistant"
])

# ─── TAB 1: Overview ────────────────────────────────────────────────────────
with tab_overview:
    # KPIs
    nav_chg = data.get("nav_change", {})
    total_pl = data.get("total_pl", 0) or 0
    initial_val = nav_chg.get("Valore iniziale", 0)
    final_val = nav_chg.get("Valore finale", 0)
    deposits = nav_chg.get("Versamenti e prelievi", 0)
    commissions = nav_chg.get("Commissioni", 0)
    mtm_gain = nav_chg.get("Mark to market", 0)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("💰 Valore Finale", f"€{final_val:,.2f}", f"{total_pl:+,.2f} P/L")
    col2.metric("📥 Versamenti Totali", f"€{deposits:,.2f}")
    col3.metric("📊 Mark to Market", f"€{mtm_gain:+,.2f}")
    col4.metric("💸 Commissioni", f"€{commissions:,.2f}")

    st.markdown("---")

    # NAV Breakdown
    st.subheader("Asset Allocation")
    nav_items = [n for n in data.get("nav", []) if n["asset_class"] != "Totale"]
    if nav_items:
        col_chart, col_table = st.columns([1, 1])
        with col_chart:
            fig_nav = go.Figure(data=[go.Pie(
                labels=[n["asset_class"] for n in nav_items],
                values=[abs(n["current_total"]) for n in nav_items],
                hole=0.4,
                marker_colors=["#2ecc71", "#3498db", "#e74c3c", "#f39c12"],
                textinfo="label+percent+value",
                texttemplate="%{label}<br>€%{value:,.2f}<br>(%{percent})",
            )])
            fig_nav.update_layout(title="Composizione Portafoglio", height=400, showlegend=False)
            st.plotly_chart(fig_nav, use_container_width=True)

        with col_table:
            nav_df = pd.DataFrame(nav_items)
            nav_df.columns = ["Classe", "Precedente", "Long", "Short", "Totale", "Variazione"]
            st.dataframe(
                nav_df.style.format({
                    "Precedente": "€{:,.2f}",
                    "Long": "€{:,.2f}",
                    "Short": "€{:,.2f}",
                    "Totale": "€{:,.2f}",
                    "Variazione": "€{:+,.2f}",
                }).map(lambda v: "color: #2ecc71" if isinstance(v, (int, float)) and v > 0 else "color: #e74c3c" if isinstance(v, (int, float)) and v < 0 else "", subset=["Variazione"]),
                use_container_width=True,
                hide_index=True,
            )

    st.markdown("---")

    # P/L by Symbol (MTM)
    st.subheader("P/L Mark-to-Market per Simbolo")
    mtm = data.get("mtm_summary", [])
    if mtm:
        mtm_df = pd.DataFrame(mtm)
        # Waterfall chart
        mtm_df_sorted = mtm_df.sort_values("mtm_total", ascending=True)
        colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in mtm_df_sorted["mtm_total"]]
        fig_mtm = go.Figure(go.Bar(
            x=mtm_df_sorted["mtm_total"],
            y=mtm_df_sorted["symbol"],
            orientation="h",
            marker_color=colors,
            text=[f"€{v:+,.2f}" for v in mtm_df_sorted["mtm_total"]],
            textposition="auto",
        ))
        fig_mtm.update_layout(
            title="P/L MTM per Trade (EUR)",
            xaxis_title="P/L (EUR)",
            yaxis_title="",
            height=max(400, len(mtm_df_sorted) * 35),
            margin=dict(l=150),
        )
        st.plotly_chart(fig_mtm, use_container_width=True)

    # P/L by Asset Type
    st.subheader("P/L per Tipo di Attivo")
    if mtm:
        type_pl = mtm_df.groupby("asset_type")["mtm_total"].sum().reset_index()
        type_pl.columns = ["Tipo", "P/L Totale"]
        colors_type = ["#2ecc71" if v >= 0 else "#e74c3c" for v in type_pl["P/L Totale"]]
        fig_type = go.Figure(go.Bar(
            x=type_pl["Tipo"],
            y=type_pl["P/L Totale"],
            marker_color=colors_type,
            text=[f"€{v:+,.2f}" for v in type_pl["P/L Totale"]],
            textposition="auto",
        ))
        fig_type.update_layout(title="P/L per Asset Class", yaxis_title="EUR", height=400)
        st.plotly_chart(fig_type, use_container_width=True)


# ─── TAB 2: Trade Details ───────────────────────────────────────────────────
with tab_trades:
    trades = data.get("trades", [])
    if not trades:
        st.info("Nessun trade trovato nel rendiconto.")
    else:
        trades_df = pd.DataFrame(trades)
        # Ensure EUR columns exist (may be missing if enrich wasn't called yet)
        if "realized_pl_eur" not in trades_df.columns:
            trades_df["realized_pl_eur"] = trades_df["realized_pl"]
            trades_df["commission_eur"] = trades_df["commission"]
            trades_df["proceeds_eur"] = trades_df["proceeds"]
            trades_df["fx_rate"] = 1.0

        # Filters
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            asset_types = ["Tutti"] + sorted(trades_df["asset_type"].unique().tolist())
            filter_type = st.selectbox("Tipo Attivo", asset_types)
        with col_f2:
            symbols = ["Tutti"] + sorted(trades_df["symbol"].unique().tolist())
            filter_symbol = st.selectbox("Simbolo", symbols)
        with col_f3:
            filter_side = st.selectbox("Direzione", ["Tutti", "BUY", "SELL"])

        filtered = trades_df.copy()
        if filter_type != "Tutti":
            filtered = filtered[filtered["asset_type"] == filter_type]
        if filter_symbol != "Tutti":
            filtered = filtered[filtered["symbol"] == filter_symbol]
        if filter_side == "BUY":
            filtered = filtered[filtered["quantity"] > 0]
        elif filter_side == "SELL":
            filtered = filtered[filtered["quantity"] < 0]

        # Summary metrics — USE EUR converted values
        total_realized_eur = filtered["realized_pl_eur"].sum()
        total_realized_usd = filtered["realized_pl"].sum()
        total_comm_eur = filtered["commission_eur"].sum()
        n_trades = len(filtered)
        winning = len(filtered[filtered["realized_pl_eur"] > 0])
        losing = len(filtered[filtered["realized_pl_eur"] < 0])

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Trade Totali", n_trades)
        c2.metric("P/L Realizzato (EUR)", f"€{total_realized_eur:+,.2f}",
                  help=f"Convertito da {total_realized_usd:+,.2f} USD usando i tassi ECB del giorno del trade")
        c3.metric("Commissioni (EUR)", f"€{total_comm_eur:,.2f}")
        c4.metric("Win/Loss", f"{winning}W / {losing}L")

        # Trade table — show both USD original and EUR converted P/L
        display_cols = ["datetime", "asset_type", "symbol", "currency", "quantity",
                        "price", "proceeds_eur", "commission_eur", "realized_pl",
                        "realized_pl_eur", "fx_rate", "mtm_pl", "code"]
        display_df = filtered[display_cols].copy()
        display_df.columns = ["Data/Ora", "Tipo", "Simbolo", "Val.", "Qtà", "Prezzo",
                               "Ricavo (EUR)", "Comm. (EUR)", "P/L Real. (USD)",
                               "P/L Real. (EUR)", "Tasso ECB", "P/L MTM", "Codice"]

        st.dataframe(
            display_df.style.format({
                "Qtà": "{:,.4f}",
                "Prezzo": "{:,.4f}",
                "Ricavo (EUR)": "€{:,.2f}",
                "Comm. (EUR)": "€{:,.2f}",
                "P/L Real. (USD)": "{:+,.2f} $",
                "P/L Real. (EUR)": "€{:+,.2f}",
                "Tasso ECB": "{:.4f}",
                "P/L MTM": "{:+,.2f}",
            }).map(
                lambda v: "color: #2ecc71; font-weight: bold" if isinstance(v, (int, float)) and v > 0
                          else "color: #e74c3c; font-weight: bold" if isinstance(v, (int, float)) and v < 0
                          else "",
                subset=["P/L Real. (EUR)"]
            ),
            use_container_width=True,
            hide_index=True,
            height=500,
        )

        st.caption("💱 La colonna **Tasso ECB** riporta il tasso di cambio USD/EUR ufficiale BCE del giorno del trade (USD per 1 EUR). Il P/L in USD è diviso per questo tasso per ottenere il P/L in EUR.")

        # Timeline chart — cumulative EUR P/L
        st.subheader("P/L Realizzato nel Tempo (EUR)")
        realized_trades = filtered[filtered["realized_pl_eur"] != 0].copy()
        if not realized_trades.empty:
            realized_trades["date"] = pd.to_datetime(realized_trades["datetime"].str[:10])
            daily_pl = realized_trades.groupby("date")["realized_pl_eur"].sum().cumsum().reset_index()
            daily_pl.columns = ["Data", "P/L Cumulativo (EUR)"]
            fig_timeline = go.Figure()
            fig_timeline.add_trace(go.Scatter(
                x=daily_pl["Data"],
                y=daily_pl["P/L Cumulativo (EUR)"],
                mode="lines+markers",
                fill="tozeroy",
                line=dict(color="#3498db", width=2),
                fillcolor="rgba(52,152,219,0.1)",
            ))
            fig_timeline.update_layout(
                title="P/L Realizzato Cumulativo (EUR — tassi ECB giornalieri)",
                xaxis_title="Data",
                yaxis_title="EUR",
                height=400,
            )
            st.plotly_chart(fig_timeline, use_container_width=True)


# ─── TAB 3: Open Positions ──────────────────────────────────────────────────
with tab_positions:
    positions = data.get("open_positions", [])
    if not positions:
        st.info("Nessuna posizione aperta trovata.")
    else:
        pos_df = pd.DataFrame(positions)

        # KPIs
        total_value = pos_df["value"].sum()
        total_unreal = pos_df["unrealized_pl"].sum()
        total_cost = pos_df["cost_basis"].sum()

        c1, c2, c3 = st.columns(3)
        c1.metric("💰 Valore Totale", f"€{total_value:,.2f}")
        c2.metric("📊 P/L Non Realizzato", f"€{total_unreal:+,.2f}")
        c3.metric("💵 Costo Base", f"€{total_cost:,.2f}")

        # Position table
        display_pos = pos_df[["asset_type", "symbol", "currency", "quantity", "multiplier", "cost_price", "cost_basis", "close_price", "value", "unrealized_pl"]].copy()
        display_pos.columns = ["Tipo", "Simbolo", "Val.", "Qtà", "Molt.", "Prezzo Costo", "Base Costo", "Prezzo Close", "Valore", "P/L Non Real."]

        st.dataframe(
            display_pos.style.format({
                "Qtà": "{:,.4f}",
                "Molt.": "{:.0f}",
                "Prezzo Costo": "{:,.4f}",
                "Base Costo": "€{:,.2f}",
                "Prezzo Close": "{:,.4f}",
                "Valore": "€{:,.2f}",
                "P/L Non Real.": "€{:+,.2f}",
            }).map(
                lambda v: "color: #2ecc71; font-weight: bold" if isinstance(v, (int, float)) and v > 0 else "color: #e74c3c; font-weight: bold" if isinstance(v, (int, float)) and v < 0 else "",
                subset=["P/L Non Real."]
            ),
            use_container_width=True,
            hide_index=True,
        )

        # P/L chart per position
        colors_pos = ["#2ecc71" if v >= 0 else "#e74c3c" for v in pos_df["unrealized_pl"]]
        fig_pos = go.Figure(go.Bar(
            x=pos_df["symbol"],
            y=pos_df["unrealized_pl"],
            marker_color=colors_pos,
            text=[f"€{v:+,.2f}" for v in pos_df["unrealized_pl"]],
            textposition="auto",
        ))
        fig_pos.update_layout(title="P/L Non Realizzato per Posizione", yaxis_title="EUR", height=400)
        st.plotly_chart(fig_pos, use_container_width=True)


# ─── TAB 4: Tax Summary ─────────────────────────────────────────────────────
with tab_fiscal:
    st.subheader("🏛️ Riepilogo Fiscale Anno")

    # ── P/L totals from trades (USD → EUR via ECB daily rates) ───────────────
    trades_all = data.get("trades", [])
    trades_eur_df = pd.DataFrame(trades_all) if trades_all else pd.DataFrame()
    if not trades_eur_df.empty and "realized_pl_eur" in trades_eur_df.columns:
        total_realized_trades_eur = trades_eur_df["realized_pl_eur"].sum()
        total_comm_trades_eur = trades_eur_df["commission_eur"].sum()
        has_fx_conversion = True
    else:
        total_realized_trades_eur = None
        total_comm_trades_eur = None
        has_fx_conversion = False

    rl = data.get("realized_unrealized", [])
    if rl:
        rl_df = pd.DataFrame(rl)

        total_realized = rl_df["realized_total"].sum()      # from IBKR summary (may be USD)
        total_unrealized = rl_df["unrealized_total"].sum()
        total_realized_profit = rl_df["realized_profit_st"].sum() + rl_df["realized_profit_lt"].sum()
        total_realized_loss = rl_df["realized_loss_st"].sum() + rl_df["realized_loss_lt"].sum()

        st.markdown("### Riepilogo Generale")

        if has_fx_conversion:
            st.info(
                "💱 **Conversione USD → EUR attiva** (tassi BCE ufficiali giornalieri). "
                "Le imposte qui sotto sono calcolate sul **P/L convertito in EUR** usando "
                "il tasso BCE del giorno di ogni singola operazione."
            )
            net_taxable = total_realized_trades_eur
            net_taxable_label = "P/L Realizzato Netto (EUR, tassi ECB)"
        else:
            st.warning("⚠️ Dati FX non disponibili — i valori sono in valuta originale del trade.")
            net_taxable = total_realized
            net_taxable_label = "P/L Realizzato Netto (valuta originale)"

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("✅ P/L Realizzato EUR", f"€{net_taxable:+,.2f}",
                    help="Somma dei P/L realizzati di tutti i trade, convertiti in EUR al tasso ECB del giorno" if has_fx_conversion else None)
        col2.metric("📈 Profitti Lordi (IBKR)", f"€{total_realized_profit:,.2f}")
        col3.metric("📉 Perdite Lorde (IBKR)", f"€{total_realized_loss:,.2f}")
        col4.metric("⏳ P/L Non Realizzato", f"€{total_unrealized:+,.2f}")

        # ── Austrian KESt split by §27 Abs.3 vs §27 Abs.4 ──────────────────
        st.markdown("---")
        st.markdown("### 🇦🇹 Finanzonline — Modulo E1kv (KESt 27.5%)")
        st.info(
            "⚖️ La legge austriaca (§ 27 EStG) richiede che **profitti e perdite siano inseriti "
            "SEPARATAMENTE** (nicht saldiert) e che vengano distinti per categoria:\n\n"
            "- **§ 27 Abs. 3** → Azioni, ETF, Fondi → KZ **994** (Überschüsse) + KZ **892** (Verluste)\n"
            "- **§ 27 Abs. 4** → Derivati, Opzioni, Certificati → KZ **995** (Überschüsse) + KZ **896** (Verluste)"
        )

        if has_fx_conversion and not trades_eur_df.empty:

            # ── Classify trades by Austrian tax category ─────────────────────
            # IBKR asset_type strings (Italian UI): map to tax category
            DERIVATE_KEYWORDS = [
                "opzion", "option", "derivat", "future", "warrant",
                "certificat", "cfd", "swap",
            ]

            def _classify_at(asset_type: str) -> str:
                """Return 'derivate' or 'aktien' based on IBKR asset_type string."""
                at_lower = str(asset_type).lower()
                if any(k in at_lower for k in DERIVATE_KEYWORDS):
                    return "derivate"
                return "aktien"

            t_df = trades_eur_df.copy()
            t_df["at_category"] = t_df["asset_type"].apply(_classify_at)

            # Filter only closed trades (realized P/L ≠ 0)
            t_closed = t_df[t_df["realized_pl_eur"] != 0].copy()

            for cat, label_it, label_de, kz_profit, kz_loss, par in [
                ("aktien",  "📈 Azioni / ETF / Fondi",       "§ 27 Abs. 3 EStG",  994, 892, 3),
                ("derivate","⚡ Derivati / Opzioni / Futures","§ 27 Abs. 4 EStG",  995, 896, 4),
            ]:
                cat_df = t_closed[t_closed["at_category"] == cat]

                gross_profit = cat_df[cat_df["realized_pl_eur"] > 0]["realized_pl_eur"].sum()
                gross_loss   = cat_df[cat_df["realized_pl_eur"] < 0]["realized_pl_eur"].sum()  # negative
                net          = gross_profit + gross_loss
                kest_net     = max(net, 0) * 0.275   # KeSt on NET gain; 0 if net loss
                n            = len(cat_df)

                st.markdown(f"#### {label_it} — *{label_de}*")
                if n == 0:
                    st.caption(f"Nessun trade chiuso in questa categoria ({cat}).")
                    continue

                col_l, col_r = st.columns(2)
                with col_l:
                    st.markdown(f"""
| Campo Finanzonline | KZ | Importo EUR |
|---|---|---|
| Überschüsse 27,5% *(profitti lordi)* | **{kz_profit}** | **€ {gross_profit:,.2f}** |
| Verluste *(perdite lorde, con segno -)* | **{kz_loss}** | **€ {gross_loss:,.2f}** |
| Netto (solo informativo, NON da inserire) | — | € {net:+,.2f} |
| KeSt stimata sul netto (27.5%) | — | € {kest_net:,.2f} |
""")
                with col_r:
                    # Mini metric cards
                    st.metric(f"KZ {kz_profit} — Überschüsse", f"€ {gross_profit:,.2f}",
                              help=f"Inserire in Finanzonline → E1kv → KZ {kz_profit}")
                    st.metric(f"KZ {kz_loss} — Verluste", f"€ {gross_loss:,.2f}",
                              help=f"Inserire con segno NEGATIVO in Finanzonline → E1kv → KZ {kz_loss}")

                st.caption(
                    f"⚠️ **N.B.:** Inserire KZ {kz_profit} e KZ {kz_loss} **separatamente** (nicht saldiert). "
                    f"Non sommarli. Operazioni incluse: {n}."
                )
                st.markdown("")

        else:
            kest_rate = 0.275
            kest_due  = max(net_taxable * kest_rate, 0) if net_taxable > 0 else 0
            st.markdown(f"""
| Voce | Importo |
|------|---------|
| {net_taxable_label} | €{net_taxable:+,.2f} |
| KESt stimata (27.5%) | **€{kest_due:,.2f}** |
""")



        # ── Per-trade breakdown split by tax category ─────────────────────────
        if has_fx_conversion and not trades_eur_df.empty:
            st.markdown("---")
            st.subheader("Dettaglio P/L per Operazione (EUR, tassi ECB giornalieri)")

            # Prepare detail dataframe
            detail_df = trades_eur_df.copy()
            detail_df["data_operazione"] = detail_df["datetime"].str[:10]
            detail_df["data_tasso_ecb"] = detail_df["fx_rate_date"].apply(
                lambda d: str(d) if d is not None else ""
            )
            detail_df["tasso_leggibile"] = detail_df["fx_rate"].apply(
                lambda r: f"1 EUR = {r:.4f} USD" if r and r != 1.0 else "N/A"
            )
            detail_df["tasso_inverso"] = detail_df["fx_rate"].apply(
                lambda r: f"1 USD = {1/r:.4f} EUR" if r and r != 1.0 else "N/A"
            )

            # Reuse the same classification from the E1kv section above
            DERIVATE_KEYWORDS = [
                "opzion", "option", "derivat", "future", "warrant",
                "certificat", "cfd", "swap",
            ]
            def _classify(at: str) -> str:
                return "derivate" if any(k in str(at).lower() for k in DERIVATE_KEYWORDS) else "aktien"

            detail_df["at_category"] = detail_df["asset_type"].apply(_classify)

            # Only closed trades
            detail_closed = detail_df[detail_df["realized_pl_eur"] != 0].copy()

            _FMT = {
                "Qtà": "{:,.4f}",
                "Prezzo": "{:,.4f}",
                "P/L (USD)": "{:+,.2f} $",
                "P/L (EUR)": "€{:+,.2f}",
                "Comm. (EUR)": "€{:,.2f}",
            }

            for cat, emoji, label_it, label_de, kz_profit, kz_loss in [
                ("aktien",  "📈", "Azioni / ETF / Fondi",        "§ 27 Abs. 3 EStG", 994, 892),
                ("derivate","⚡", "Derivati / Opzioni / Futures", "§ 27 Abs. 4 EStG", 995, 896),
            ]:
                cat_rows = detail_closed[detail_closed["at_category"] == cat].sort_values(
                    ["data_operazione", "symbol"]
                )

                gross_profit = cat_rows[cat_rows["realized_pl_eur"] > 0]["realized_pl_eur"].sum()
                gross_loss   = cat_rows[cat_rows["realized_pl_eur"] < 0]["realized_pl_eur"].sum()
                net          = gross_profit + gross_loss

                st.markdown(f"#### {emoji} {label_it} — *{label_de}*")

                if cat_rows.empty:
                    st.caption("Nessuna operazione chiusa in questa categoria.")
                    continue

                # Build display dataframe
                disp = cat_rows[[
                    "data_operazione", "symbol", "asset_type", "currency",
                    "quantity", "price",
                    "realized_pl", "tasso_leggibile", "tasso_inverso", "data_tasso_ecb",
                    "realized_pl_eur", "commission_eur",
                ]].copy()
                disp.columns = [
                    "Giorno Operazione", "Simbolo", "Tipo", "Val.",
                    "Qtà", "Prezzo",
                    "P/L (USD)", "Cambio BCE (÷)", "Cambio BCE (×)", "Data Tasso ECB",
                    "P/L (EUR)", "Comm. (EUR)",
                ]

                st.dataframe(
                    disp.style.format(_FMT).map(
                        lambda v: "color: #2ecc71; font-weight: bold" if isinstance(v, (int, float)) and v > 0
                                  else "color: #e74c3c; font-weight: bold" if isinstance(v, (int, float)) and v < 0
                                  else "",
                        subset=["P/L (EUR)"]
                    ),
                    use_container_width=True,
                    hide_index=True,
                    height=min(500, max(150, len(disp) * 38)),
                )

                # Totals row — must match the KZ values in the E1kv section above
                c1, c2, c3, c4 = st.columns(4)
                c1.metric(
                    f"✅ KZ {kz_profit} Überschüsse",
                    f"€ {gross_profit:,.2f}",
                    help=f"Somma profitti lordi → inserire in Finanzonline KZ {kz_profit}",
                )
                c2.metric(
                    f"🔴 KZ {kz_loss} Verluste",
                    f"€ {gross_loss:,.2f}",
                    help=f"Somma perdite lorde (negativo) → inserire in Finanzonline KZ {kz_loss}",
                )
                c3.metric(
                    "Netto (info)",
                    f"€ {net:+,.2f}",
                    help="Solo informativo — non corrisponde a nessun campo Finanzonline",
                )
                c4.metric(
                    "KeSt stimata sul netto (27.5%)",
                    f"€ {max(net, 0) * 0.275:,.2f}",
                    help="KeSt = max(Netto, 0) × 27.5%  — se il netto è negativo la KeSt è 0",
                )
                st.markdown("")  # spacer between categories

            st.caption(
                "📐 **Formula:** P/L (EUR) = P/L (USD) ÷ tasso BCE  "
                "→ **Cambio BCE (÷)** = divisore (es. *1 EUR = 1.0850 USD*) | "
                "**Cambio BCE (×)** = reciproco (es. *1 USD = 0.9216 EUR*).  "
                "I totali KZ mostrati qui sotto ogni tabella corrispondono esattamente a quelli "
                "del riepilogo Finanzonline E1kv qui sopra."
            )

            # Bar chart aggregated by symbol (overview)
            sym_eur = (
                trades_eur_df[trades_eur_df["realized_pl_eur"] != 0]
                .groupby("symbol")
                .agg(pl_eur=("realized_pl_eur", "sum"))
                .reset_index()
                .sort_values("pl_eur", ascending=True)
            )
            colors_sym = ["#2ecc71" if v >= 0 else "#e74c3c" for v in sym_eur["pl_eur"]]
            fig_sym = go.Figure(go.Bar(
                x=sym_eur["pl_eur"],
                y=sym_eur["symbol"],
                orientation="h",
                marker_color=colors_sym,
                text=[f"€{v:+,.2f}" for v in sym_eur["pl_eur"]],
                textposition="auto",
            ))
            fig_sym.update_layout(
                title="P/L Realizzato per Simbolo (EUR — tassi ECB giornalieri)",
                xaxis_title="EUR",
                height=max(400, len(sym_eur) * 35),
                margin=dict(l=180),
            )
            st.plotly_chart(fig_sym, use_container_width=True)

        # ── IBKR Realized/Unrealized summary table ───────────────────────────
        st.markdown("---")
        st.subheader("Dettaglio P/L IBKR per Simbolo (Realizzato + Non Realizzato)")

        display_rl = rl_df[["asset_type", "symbol", "realized_profit_st", "realized_loss_st", "realized_total", "unrealized_total", "total"]].copy()
        display_rl.columns = ["Tipo", "Simbolo", "Profitto S/T", "Perdita S/T", "Realizzato Tot.", "Non Real. Tot.", "Totale"]

        st.dataframe(
            display_rl.style.format({
                "Profitto S/T": "{:,.2f}",
                "Perdita S/T": "{:,.2f}",
                "Realizzato Tot.": "{:+,.2f}",
                "Non Real. Tot.": "{:+,.2f}",
                "Totale": "{:+,.2f}",
            }).map(
                lambda v: "color: #2ecc71; font-weight: bold" if isinstance(v, (int, float)) and v > 0
                          else "color: #e74c3c; font-weight: bold" if isinstance(v, (int, float)) and v < 0
                          else "",
                subset=["Realizzato Tot.", "Non Real. Tot.", "Totale"]
            ),
            use_container_width=True,
            hide_index=True,
        )
        st.caption("⚠️ I valori in questa tabella provengono direttamente dal riepilogo IBKR e potrebbero essere in USD. Per i valori fiscalmente corretti in EUR usa la tabella sopra (tassi ECB giornalieri).")

    else:
        st.info("Nessun dato P/L realizzato/non realizzato trovato.")

    # Deposits section
    deps = data.get("deposits", [])
    if deps:
        st.markdown("---")
        st.subheader("📥 Versamenti")
        dep_df = pd.DataFrame(deps)
        dep_df.columns = ["Valuta", "Data", "Descrizione", "Importo"]
        st.dataframe(
            dep_df.style.format({"Importo": "€{:,.2f}"}),
            use_container_width=True,
            hide_index=True,
        )
        st.metric("Totale Versamenti", f"€{sum(d['amount'] for d in deps):,.2f}")


# ─── TAB 5: AI Assistant ────────────────────────────────────────────────────
with tab_ai:
    st.subheader("🤖 AI Tax & Trading Analyst")

    if not TraderAgent:
        st.warning(
            "AI Agent non disponibile. Installa il pacchetto `custom_agents`:\n\n"
            "```bash\npip install -e ../../../Custom_Agents\n```"
        )
    else:
        st.markdown("Chiedi all'AI di analizzare i tuoi errori di trading, ottimizzazione fiscale, o qualsiasi domanda sui dati.")

        # Quick action buttons
        st.markdown("**Domande rapide:**")
        qcol1, qcol2, qcol3 = st.columns(3)
        with qcol1:
            if st.button("📊 Analisi errori di trading", use_container_width=True):
                st.session_state.quick_prompt = "Analizza tutti i miei trade in perdita. Per ognuno, spiega cosa è andato storto, identifica pattern di errore comuni e suggerisci miglioramenti concreti."
        with qcol2:
            if st.button("🏛️ Riepilogo fiscale completo", use_container_width=True):
                st.session_state.quick_prompt = "Fornisci un riepilogo fiscale completo: P/L realizzato netto, tasse da pagare (Austria 27.5% e Italia 26%), commissioni deducibili, e impatto del cambio EUR/USD."
        with qcol3:
            if st.button("🎯 Migliori e peggiori trade", use_container_width=True):
                st.session_state.quick_prompt = "Elenca i 5 migliori e i 5 peggiori trade dell'anno con analisi dettagliata di cosa ha funzionato e cosa no."

        # Chat history
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"], avatar="🤖" if msg["role"] == "assistant" else "👤"):
                st.markdown(msg["content"])

        # Handle quick prompt
        quick = st.session_state.pop("quick_prompt", None)
        if quick:
            st.session_state.chat_history.append({"role": "user", "content": quick})
            with st.chat_message("user", avatar="👤"):
                st.markdown(quick)
            with st.chat_message("assistant", avatar="🤖"):
                with st.spinner("🤖 Analizzando..."):
                    response = _chat_with_ai(quick, data)
                    st.markdown(response)
            st.session_state.chat_history.append({"role": "assistant", "content": response})
            st.rerun()

        # Free chat input
        if user_input := st.chat_input("Chiedi all'AI analista..."):
            st.session_state.chat_history.append({"role": "user", "content": user_input})
            with st.chat_message("user", avatar="👤"):
                st.markdown(user_input)
            with st.chat_message("assistant", avatar="🤖"):
                with st.spinner("🤖 Analizzando..."):
                    response = _chat_with_ai(user_input, data)
                    st.markdown(response)
            st.session_state.chat_history.append({"role": "assistant", "content": response})
            st.rerun()
