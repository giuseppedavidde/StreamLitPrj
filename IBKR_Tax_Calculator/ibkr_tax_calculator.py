"""IBKR Tax Calculator — Streamlit Dashboard with AI Agent integration."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import io
import os
import datetime

from dotenv import load_dotenv

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

    # Trades
    trades = data.get("trades", [])
    if trades:
        lines.append(f"\n═══ TRADES ({len(trades)} total) ═══")
        for t in trades:
            side = "BUY" if t["quantity"] > 0 else "SELL"
            lines.append(
                f"  {t['datetime']} | {side} {abs(t['quantity']):.4f} {t['symbol']} @ {t['price']:.4f} {t['currency']} | "
                f"P/L Realized={t['realized_pl']:+.2f} | Comm={t['commission']:.2f} | Code={t['code']}"
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

        # Summary metrics
        total_realized = filtered["realized_pl"].sum()
        total_comm = filtered["commission"].sum()
        n_trades = len(filtered)
        winning = len(filtered[filtered["realized_pl"] > 0])
        losing = len(filtered[filtered["realized_pl"] < 0])

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Trade Totali", n_trades)
        c2.metric("P/L Realizzato", f"€{total_realized:+,.2f}")
        c3.metric("Commissioni", f"€{total_comm:,.2f}")
        c4.metric("Win/Loss", f"{winning}W / {losing}L")

        # Trade table
        display_df = filtered[["datetime", "asset_type", "symbol", "currency", "quantity", "price", "proceeds", "commission", "realized_pl", "mtm_pl", "code"]].copy()
        display_df.columns = ["Data/Ora", "Tipo", "Simbolo", "Val.", "Qtà", "Prezzo", "Ricavo", "Comm.", "P/L Real.", "P/L MTM", "Codice"]

        st.dataframe(
            display_df.style.format({
                "Qtà": "{:,.4f}",
                "Prezzo": "{:,.4f}",
                "Ricavo": "€{:,.2f}",
                "Comm.": "€{:,.2f}",
                "P/L Real.": "€{:+,.2f}",
                "P/L MTM": "€{:+,.2f}",
            }).map(
                lambda v: "color: #2ecc71; font-weight: bold" if isinstance(v, (int, float)) and v > 0 else "color: #e74c3c; font-weight: bold" if isinstance(v, (int, float)) and v < 0 else "",
                subset=["P/L Real."]
            ),
            use_container_width=True,
            hide_index=True,
            height=500,
        )

        # Timeline chart
        st.subheader("P/L Realizzato nel Tempo")
        realized_trades = filtered[filtered["realized_pl"] != 0].copy()
        if not realized_trades.empty:
            realized_trades["date"] = pd.to_datetime(realized_trades["datetime"].str[:10])
            daily_pl = realized_trades.groupby("date")["realized_pl"].sum().cumsum().reset_index()
            daily_pl.columns = ["Data", "P/L Cumulativo"]
            fig_timeline = go.Figure()
            fig_timeline.add_trace(go.Scatter(
                x=daily_pl["Data"],
                y=daily_pl["P/L Cumulativo"],
                mode="lines+markers",
                fill="tozeroy",
                line=dict(color="#3498db", width=2),
                fillcolor="rgba(52,152,219,0.1)",
            ))
            fig_timeline.update_layout(
                title="P/L Realizzato Cumulativo",
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

    rl = data.get("realized_unrealized", [])
    if rl:
        rl_df = pd.DataFrame(rl)

        # Separate by asset type
        total_realized = rl_df["realized_total"].sum()
        total_unrealized = rl_df["unrealized_total"].sum()
        total_realized_profit = rl_df["realized_profit_st"].sum() + rl_df["realized_profit_lt"].sum()
        total_realized_loss = rl_df["realized_loss_st"].sum() + rl_df["realized_loss_lt"].sum()

        st.markdown("### Riepilogo Generale")
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("✅ P/L Realizzato Totale", f"€{total_realized:+,.2f}")
        col2.metric("📈 Profitti Realizzati", f"€{total_realized_profit:,.2f}")
        col3.metric("📉 Perdite Realizzate", f"€{total_realized_loss:,.2f}")
        col4.metric("⏳ P/L Non Realizzato", f"€{total_unrealized:+,.2f}")

        # Tax calculations
        st.markdown("---")
        st.markdown("### Calcolo Imposte")

        # Austria KESt 27.5%
        kest_rate = 0.275
        # Italy 26%
        it_rate = 0.26

        # Net realized = profits + losses (losses offset profits)
        net_taxable = total_realized
        kest_due = max(net_taxable * kest_rate, 0) if net_taxable > 0 else 0
        it_tax_due = max(net_taxable * it_rate, 0) if net_taxable > 0 else 0

        commissions_total = abs(data["nav_change"].get("Commissioni", 0))
        other_fees = abs(data["nav_change"].get("Altre commissioni", 0))

        colA, colB = st.columns(2)
        with colA:
            st.markdown("#### 🇦🇹 Austria (KESt 27.5%)")
            st.markdown(f"""
            | Voce | Importo |
            |------|---------|
            | P/L Realizzato Netto | €{net_taxable:+,.2f} |
            | KESt dovuta (27.5%) | €{kest_due:,.2f} |
            | Commissioni (deducibili) | €{commissions_total:,.2f} |
            | Altre commissioni | €{other_fees:,.2f} |
            """)

        with colB:
            st.markdown("#### 🇮🇹 Italia (26%)")
            st.markdown(f"""
            | Voce | Importo |
            |------|---------|
            | P/L Realizzato Netto | €{net_taxable:+,.2f} |
            | Imposta dovuta (26%) | €{it_tax_due:,.2f} |
            | Commissioni (deducibili) | €{commissions_total:,.2f} |
            | Altre commissioni | €{other_fees:,.2f} |
            """)

        # Detailed P/L per symbol
        st.markdown("---")
        st.subheader("Dettaglio P/L per Simbolo (Realizzato + Non Realizzato)")

        display_rl = rl_df[["asset_type", "symbol", "realized_profit_st", "realized_loss_st", "realized_total", "unrealized_total", "total"]].copy()
        display_rl.columns = ["Tipo", "Simbolo", "Profitto S/T", "Perdita S/T", "Realizzato Tot.", "Non Real. Tot.", "Totale"]

        st.dataframe(
            display_rl.style.format({
                "Profitto S/T": "€{:,.2f}",
                "Perdita S/T": "€{:,.2f}",
                "Realizzato Tot.": "€{:+,.2f}",
                "Non Real. Tot.": "€{:+,.2f}",
                "Totale": "€{:+,.2f}",
            }).map(
                lambda v: "color: #2ecc71; font-weight: bold" if isinstance(v, (int, float)) and v > 0 else "color: #e74c3c; font-weight: bold" if isinstance(v, (int, float)) and v < 0 else "",
                subset=["Realizzato Tot.", "Non Real. Tot.", "Totale"]
            ),
            use_container_width=True,
            hide_index=True,
        )

        # Realized P/L waterfall by symbol
        realized_only = rl_df[rl_df["realized_total"] != 0].sort_values("realized_total", ascending=True)
        if not realized_only.empty:
            colors_rl = ["#2ecc71" if v >= 0 else "#e74c3c" for v in realized_only["realized_total"]]
            fig_rl = go.Figure(go.Bar(
                x=realized_only["realized_total"],
                y=realized_only["symbol"],
                orientation="h",
                marker_color=colors_rl,
                text=[f"€{v:+,.2f}" for v in realized_only["realized_total"]],
                textposition="auto",
            ))
            fig_rl.update_layout(
                title="P/L Realizzato per Simbolo",
                xaxis_title="EUR",
                height=max(400, len(realized_only) * 35),
                margin=dict(l=180),
            )
            st.plotly_chart(fig_rl, use_container_width=True)
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
