"""Crypto Portfolio DCA Dashboard

Questo dashboard permette di analizzare e visualizzare il tuo portafoglio Crypto Bitpanda con strategie DCA.
"""

import base64
import os
import io

from dotenv import load_dotenv

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Load environment variables
load_dotenv()

try:
    from agents.ai_provider import AIProvider
    from agents.trader_agent import TraderAgent
except ImportError as e:
    st.error(f"Modulo 'agents' non trovato o errore importazione: {e}")
    AIProvider = None
    TraderAgent = None

from agents.cloud_ui import render_cloud_ui
from modules.collect_data_utils import (
    collect_bitpanda_data,
    sort_data_by_asset,
    load_portfolio_snapshot,
)
from modules.portfolio_utils import aggregate_portfolio, filter_crypto_df
from modules.yahoo_utils import portfolio_history
from modules.price_utils import get_bitpanda_prices, calculate_gain_loss
from modules.crypto_ta_utils import get_crypto_ta

st.set_page_config(page_title="Crypto Portfolio DCA Dashboard", layout="wide")
st.title("Crypto Portfolio DCA Dashboard")
st.caption(
    "Analizza e visualizza il tuo portafoglio Crypto Bitpanda con strategie DCA."
)

# --- 0. SIDEBAR: AI CONFIGURATION ---
st.sidebar.header("🤖 Configurazione AI")
with st.sidebar.expander("Settings AI", expanded=False):
    supported_providers = (
        AIProvider.get_supported_providers() if AIProvider else ["Gemini", "Ollama"]
    )
    
    provider_type = st.selectbox(
        "Provider",
        supported_providers,
        format_func=lambda x: (
            "☁️ Gemini (Cloud)"
            if x.lower() == "gemini"
            else "🖥️ Ollama (Local)"
            if x.lower() == "ollama"
            else "⚡ Groq (LPU Cloud)"
            if x.lower() == "groq"
            else "🧠 Puter Free (Claude/Gemini)"
        ),
    )
    # Rendi minuscolo per standardizzare
    provider_type = provider_type.lower()

    api_key = None
    model_name = None

    if provider_type == "gemini":
        # Recupera API Key da Env o Input
        env_key = os.getenv("GOOGLE_API_KEY")
        api_key = st.text_input(
            "Gemini API Key",
            value=env_key if env_key else "",
            type="password",
            help="Se presente nel file .env verra' caricata automaticamente",
        )

        if AIProvider:
            try:
                gemini_models = AIProvider.get_gemini_models(api_key=api_key or env_key)
            except Exception as e:
                st.error(f"Errore recupero modelli Gemini: {e}")
                gemini_models = AIProvider.FALLBACK_ORDER
            if not gemini_models:
                gemini_models = AIProvider.FALLBACK_ORDER
        else:
            gemini_models = ["gemini-pro"]

        model_name = st.selectbox("Modello", gemini_models, index=0)
        
    elif provider_type == "groq":
        # Recupera API Key da Env o Input
        env_key = os.getenv("GROQ_API_KEY")
        api_key = st.text_input(
            "Groq API Key",
            value=env_key if env_key else "",
            type="password",
            help="Se presente nel file .env verra' caricata automaticamente",
        )

        if AIProvider:
            try:
                groq_models = AIProvider.get_groq_models(api_key=api_key or env_key)
            except Exception as e:
                st.error(f"Errore recupero modelli Groq: {e}")
                groq_models = []
            
            if groq_models:
                model_name = st.selectbox("Modello", groq_models, index=0)
            else:
                st.warning("Nessun modello trovato. Controlla la API Key.")
                
    elif provider_type == "puter":
        # Puter / Claude Free API
        puter_key = os.getenv("PUTER_API_KEY")
        api_key = st.text_input(
            "Puter Auth Token",
            value=puter_key if puter_key else "",
            type="password",
            help="Prendi il token da puter.com -> Settings.",
        )
        if api_key:
            os.environ["PUTER_API_KEY"] = api_key
            
        if AIProvider:
            try:
                puter_models = AIProvider.get_puter_models()
                if puter_models:
                    model_name = st.selectbox("Modello (Puter)", puter_models, index=0)
                else:
                    st.warning("Nessun modello trovato. Controlla il Token.")
            except Exception as e:
                st.error(f"Errore recupero modelli Puter: {e}")
                
    else:  # Assumiamo ollama
        if AIProvider:
            try:
                ollama_models = AIProvider.get_ollama_models()
                if ollama_models:
                    model_name = st.selectbox("Modello Locale", ollama_models, index=0)
                else:
                    st.warning("Nessun modello Ollama trovato o Ollama non in esecuzione.")
                    model_name = st.text_input("Nome Modello Manuale", value="llama3")
            except Exception as e:
                st.error(f"Errore connessione ad Ollama: {e}")
                model_name = st.text_input("Nome Modello Manuale", value="llama3")

    # Inizializza Provider nel Session State
    if st.button("Applica Configurazione AI"):
        if AIProvider:
            try:
                # Forza variabili d'ambiente per fallback interni
                if api_key:
                    os.environ["GOOGLE_API_KEY"] = api_key
                    os.environ["GROQ_API_KEY"] = api_key

                st.session_state["ai_provider"] = AIProvider(
                    api_key=api_key, provider_type=provider_type, model_name=model_name
                )
                
                if TraderAgent:
                    st.session_state["trader_agent"] = TraderAgent(
                        provider_type=provider_type, model_name=model_name
                    )
                    # Hack: passiamo direttamente l'istanza configurata all'agente per sicurezza
                    st.session_state["trader_agent"].ai = st.session_state["ai_provider"]

                st.toast(f"AI Attivata: {provider_type} ({model_name})", icon="🟢")
            except Exception as e:
                st.error(f"Errore Init AI: {e}")

st.sidebar.divider()

# --- SIDEBAR: ALTRE API ---
st.sidebar.header("🔑 Altre API")
with st.sidebar.expander("Impostazioni Dati", expanded=False):
    cg_env_key = os.getenv("COINGECKO_API_KEY")
    cg_api_key = st.text_input(
        "CoinGecko API Key",
        value=cg_env_key if cg_env_key else "",
        type="password",
        help="Chiave necessaria per recuperare i volumi storici Crypto senza rate-limit"
    )
    if cg_api_key:
        os.environ["COINGECKO_API_KEY"] = cg_api_key

st.sidebar.divider()

# --- File Upload Section ---
st.sidebar.header("Bitpanda CSV Upload")
uploaded_file = st.sidebar.file_uploader(
    "Carica il CSV Bitpanda delle transazioni",
    type=["csv"],
    help="Carica il file esportato da Bitpanda con le tue transazioni crypto.",
)

# --- Cloud Sync Section ---
# --- Cloud Sync Section ---
LOCAL_DATA_FILE = (
    "Crypto_Portfolio_csv.csv"  # Still referenced but maybe unused if in-memory
)
render_cloud_ui(is_sidebar=True)

crypto_df = None

if uploaded_file is not None:
    # Bitpanda Logic
    data_collected = collect_bitpanda_data(uploaded_file)
    data_collected = sort_data_by_asset(data_collected)
    df = pd.DataFrame(data_collected)
    # Conversione colonne numeriche
    df["amount_asset_collect"] = pd.to_numeric(
        df["amount_asset_collect"], errors="coerce"
    )
    df["amount_fiat_collect"] = pd.to_numeric(
        df["amount_fiat_collect"], errors="coerce"
    )
    df["asset_market_price_collect"] = pd.to_numeric(
        df["asset_market_price_collect"], errors="coerce"
    )
    # Filtri e aggregazione
    df = filter_crypto_df(df)
    grouped = aggregate_portfolio(df)
    crypto_df = grouped

elif "cloud_data" in st.session_state and st.session_state["cloud_data"]:
    st.sidebar.success("Uso dati da Cloud (In-Memory)")
    # Snapshot Logic - from buffer
    raw_data = st.session_state["cloud_data"]
    if isinstance(raw_data, bytes):
        raw_data = io.BytesIO(raw_data)
    else:
        raw_data = io.StringIO(raw_data)

    crypto_df = load_portfolio_snapshot(raw_data)

elif os.path.exists(LOCAL_DATA_FILE):
    # Fallback: if local file still exists (maybe from manual save), use it but warn?
    # Or just ignore it as per user request "NON deve essere scaricato".
    # User said "NON deve essere scaricato", but maybe it exists from previous runs.
    # We should prioritize cloud_data. If cloud_data is missing, we could try to load local if exists,
    # or just show nothing.
    # Let's support it for now but clearly mark it.
    st.sidebar.warning(f"File locale rilevato: {LOCAL_DATA_FILE}")
    crypto_df = load_portfolio_snapshot(LOCAL_DATA_FILE)

if crypto_df is not None and not crypto_df.empty:
    st.subheader("Crypto Portfolio Aggregato per Asset")
    # Configure column formats for high precision
    # Use %.8f to show up to 8 decimals as requested
    st.dataframe(
        crypto_df,
        column_config={
            "amount_asset_collect": st.column_config.NumberColumn(
                "Shares (Quantità)", format="%.8f"
            ),
            "median_price": st.column_config.NumberColumn(
                "DCA Price (Prezzo Medio)", format="%.8f"
            ),
            "amount_fiat_collect": st.column_config.NumberColumn(
                "Invested (EUR)", format="%.2f"
            ),
            "date_last_update_buy": st.column_config.TextColumn(
                "Last Update (Buy/Sell)"
            ),
            "date_last_update_staking": st.column_config.TextColumn(
                "Last Update (Staking)"
            ),
        },
        width="stretch",
    )
    st.markdown("---")
    st.markdown("### Visualizzazione Grafica")
    # Pie chart per asset
    fig = go.Figure(
        data=[
            go.Pie(
                labels=crypto_df["asset_collect"],
                values=crypto_df["amount_fiat_collect"],
                hole=0.3,
            )
        ]
    )
    fig.update_layout(title_text="Distribuzione Investimento per Asset")
    st.plotly_chart(fig, width="stretch")
    # Bar chart per prezzo medio
    fig2 = go.Figure(
        data=[go.Bar(x=crypto_df["asset_collect"], y=crypto_df["median_price"])]
    )
    fig2.update_layout(
        title_text="Prezzo Medio di Acquisto (DCA) per Asset",
        xaxis_title="Asset",
        yaxis_title="Prezzo Medio",
    )
    st.plotly_chart(fig2, width="stretch")
    # Tabella Gain/Loss
    prices_dict = get_bitpanda_prices()
    gain_df = calculate_gain_loss(crypto_df, prices_dict)
    st.subheader("Gain/Loss Portfolio")
    st.dataframe(gain_df)
    # Grafico storico portafoglio
    st.markdown("### Andamento Storico del Portafoglio")
    history_df = portfolio_history(crypto_df)
    if not history_df.empty:
        fig3 = go.Figure()
        fig3.add_trace(
            go.Scatter(
                x=history_df.index,
                y=history_df["total_value"],
                mode="lines",
                name="Valore Totale",
            )
        )
        fig3.update_layout(
            title="Valore del Portafoglio nel Tempo (EUR)",
            xaxis_title="Data",
            yaxis_title="Valore Totale (EUR)",
        )
        st.plotly_chart(fig3, width="stretch")
    else:
        st.info("Storico non disponibile per uno o più asset.")
    # Download CSV aggregato
    csv = crypto_df.to_csv(index=False)

    # Save context for AI
    st.session_state["crypto_analyzed_csv"] = csv

    b64 = base64.b64encode(csv.encode()).decode()
    st.download_button(
        label="Scarica CSV aggregato",
        data=csv,
        file_name="crypto_portfolio_aggregato.csv",
        mime="text/csv",
    )

    st.markdown("---")
    st.subheader("🤖 Crypto Smart DCA Allocator (AI)")
    st.markdown("Alloca il tuo budget usando il framework di Valutazione Asset, Cicli di Mercato e Smart DCA.")
    
    with st.expander("⚙️ Parametri Macro (Smart DCA)", expanded=False):
        st.write("Aggiusta le soglie per il calcolo del moltiplicatore DCA. I valori di default si basano su backtest storici consolidati.")
        dca_col1, dca_col2 = st.columns(2)
        with dca_col1:
            st.markdown("##### 🔶 Blue Chip (BTC/ETH)")
            btc_wma_prox = st.number_input("Prossimità 200WMA (%)", min_value=1.0, max_value=2.0, value=1.05, step=0.01, help="1.05 = 5% sopra la media a 200 Settimane", key="btc_wma")
            btc_mayer_low = st.number_input("Mayer Multiple (Sottovalutato)", min_value=0.1, max_value=1.5, value=0.8, step=0.1, key="btc_ml")
            btc_mayer_high = st.number_input("Mayer Multiple (Bolla)", min_value=1.5, max_value=5.0, value=2.4, step=0.1, key="btc_mh")
            btc_rsi_low = st.number_input("Weekly RSI (Oversold)", min_value=10, max_value=50, value=40, step=1, key="btc_rl")
            btc_rsi_high = st.number_input("Weekly RSI (Overbought)", min_value=60, max_value=90, value=75, step=1, key="btc_rh")
            
        with dca_col2:
            st.markdown("##### 🚀 Altcoins (SOL, ecc..)")
            alt_mayer_low = st.number_input("Mayer Multiple (Sottovalutato)", min_value=0.1, max_value=1.5, value=0.8, step=0.1, key="alt_ml")
            alt_mayer_high = st.number_input("Mayer Multiple (Bolla)", min_value=1.5, max_value=5.0, value=2.0, step=0.1, key="alt_mh")
            alt_rsi_ext = st.number_input("Weekly RSI (Estremo Oversold)", min_value=10, max_value=40, value=30, step=1, key="alt_re")
            alt_rsi_low = st.number_input("Weekly RSI (Oversold)", min_value=10, max_value=50, value=40, step=1, key="alt_rl")
            alt_rsi_high = st.number_input("Weekly RSI (Overbought)", min_value=60, max_value=90, value=70, step=1, key="alt_rh")
            
        dca_params = {
            "btc_wma_prox": btc_wma_prox,
            "btc_mayer_low": btc_mayer_low,
            "btc_mayer_high": btc_mayer_high,
            "btc_rsi_low": btc_rsi_low,
            "btc_rsi_high": btc_rsi_high,
            "alt_rsi_ext": alt_rsi_ext,
            "alt_rsi_low": alt_rsi_low,
            "alt_rsi_high": alt_rsi_high,
            "alt_mayer_low": alt_mayer_low,
            "alt_mayer_high": alt_mayer_high,
        }

    col_dca_1, col_dca_2, col_dca_3 = st.columns([2, 1, 1])
    with col_dca_1:
        # Preseleziona i primi 3 o tutti se meno di 3
        default_tokens = list(crypto_df["asset_collect"].unique()[:3]) if len(crypto_df["asset_collect"].unique()) >= 3 else list(crypto_df["asset_collect"].unique())
        selected_tokens = st.multiselect("Token per la ripartizione Budget", crypto_df["asset_collect"].unique(), default=default_tokens)
        
    with col_dca_2:
        budget_fiat = st.number_input("Budget Mensile/Unico (EUR)", min_value=10.0, value=500.0, step=50.0)
        
    with col_dca_3:
        st.write("") # spacing
        st.write("")
        if st.button("Genera Allocazione Smart DCA", use_container_width=True):
            if "trader_agent" not in st.session_state or not st.session_state.get("ai_provider"):
                st.error("⚠️ Configura prima l'AI nella sidebar.")
            elif not selected_tokens:
                st.warning("⚠️ Seleziona almeno un Token dalla lista.")
            else:
                with st.spinner(f"Calcolo Analisi Tecnica e DCA per {len(selected_tokens)} token..."):
                    all_ta_data = {}
                    for t in selected_tokens:
                        all_ta_data[t] = get_crypto_ta(t, timeframe="1d", period="5y", dca_params=dca_params)
                        
                with st.spinner(f"Elaborazione Allocazione Budget AI in corso..."):
                    try:
                        # 1. Carica Knowledge Base
                        kb_path = os.path.join(os.path.dirname(__file__), "..", "..", "Custom_Agents", "agents", "knowledge", "crypto_asset_knowledge.md")
                        kb_content = ""
                        if os.path.exists(kb_path):
                            with open(kb_path, "r", encoding="utf-8") as f:
                                kb_content = f.read()
                        else:
                            kb_content = "Documento 'crypto_asset_knowledge.md' non trovato. Utilizza regole generali di prudenza."
                            
                        # 2. Crea il Prompt
                        sys_prompt_text = f"Sei un Crypto Asset Allocator specializzato. La tua conoscenza base è la seguente:\n\n{kb_content}\n\nREGOLE AGGIUNTIVE:\n- Ignora il PE Ratio (NVT) se non disponibile on-chain.\n- Decidi importi precisi in EUR per ogni token in base al budget totale, usando le formule (Volatilità, SMA50/200, Volume Trend, Moltiplicatori Smart DCA) spiegate nel testo.\n- REGOLA PRIORITARIA: Se il prezzo attuale di un token è SOTTO il prezzo medio di carico dell'investitore, quel token rappresenta un'opportunità di 'averaging down'. PREDILIGI l'allocazione verso i token dove lo sconto rispetto al prezzo di carico è maggiore, perché l'obiettivo è abbassare il più possibile il prezzo medio di carico nel breve termine.\n- Calcola e mostra sempre il NUOVO prezzo medio di carico stimato dopo l'allocazione suggerita."
                        
                        ta_summary = ""
                        for t, data in all_ta_data.items():
                            ta_summary += f"\n\n--- ASSET: {t} ---\n"
                            ta_summary += f"Prezzo Attuale: {data.get('current_price', 'N/A')}\n"
                            ta_summary += f"SMA50: {data.get('ema_50', 'N/A')} | SMA200: {data.get('sma_200', 'N/A')}\n"
                            ta_summary += f"Volume Trend [HIGH/LOW]: {data.get('volume_trend', 'N/A')} | Volatilità Daily: {data.get('daily_volatility', 'N/A')}\n"
                            
                            dca_info = data.get('smart_dca', {})
                            ta_summary += f"Smart DCA Multiplier Consigliato: {dca_info.get('multiplier', 1.0)}x\n"
                            ta_summary += f"Segnali Macro Innescati: {', '.join(dca_info.get('signals', []))}\n"
                            
                            # --- PORTFOLIO-AWARE: Prezzo medio di carico e simulazione ---
                            row = crypto_df[crypto_df["asset_collect"] == t]
                            if not row.empty:
                                avg_cost = row.iloc[0].get("median_price", None)
                                qty_held = row.iloc[0].get("amount_asset_collect", 0)
                                total_invested = row.iloc[0].get("amount_fiat_collect", 0)
                                current_p = data.get("current_price", 0)
                                
                                if avg_cost and current_p and avg_cost > 0 and current_p != "N/A":
                                    current_p = float(current_p)
                                    avg_cost = float(avg_cost)
                                    qty_held = float(qty_held)
                                    total_invested = float(total_invested)
                                    
                                    # Sconto/Premio rispetto al prezzo di carico
                                    discount_pct = ((current_p - avg_cost) / avg_cost) * 100
                                    
                                    # Simulazione: se investissi TUTTO il budget su questo token
                                    new_qty = qty_held + (budget_fiat / current_p) if current_p > 0 else qty_held
                                    new_total = total_invested + budget_fiat
                                    new_avg = new_total / new_qty if new_qty > 0 else avg_cost
                                    avg_drop_pct = ((new_avg - avg_cost) / avg_cost) * 100
                                    
                                    ta_summary += f"📌 PORTAFOGLIO ATTUALE: Quantità detenuta: {qty_held:.6f} | Investito: {total_invested:.2f} EUR | Prezzo Medio di Carico: {avg_cost:.4f} EUR\n"
                                    ta_summary += f"📊 Sconto/Premio vs Carico: {discount_pct:+.2f}%\n"
                                    ta_summary += f"🔮 Simulazione (se tutto il budget fosse qui): Nuovo PM Carico = {new_avg:.4f} EUR (variazione {avg_drop_pct:+.2f}%)\n"
                                else:
                                    ta_summary += f"📌 PORTAFOGLIO: Dati di carico non disponibili per {t}\n"
                            else:
                                ta_summary += f"📌 PORTAFOGLIO: Token {t} non presente nel portafoglio attuale.\n"
                            
                        user_msg_text = f"Ho un BUDGET totale di {budget_fiat} EUR.\nI token candidati e le loro metriche sono i seguenti:\n{ta_summary}\n\nAnalizza tutti i token secondo i criteri della knowledge. OBIETTIVO PRIMARIO: Abbassare il più possibile il prezzo medio di carico complessivo del portafoglio nel breve termine. Fornisci un portafoglio di ripartizione con importi EUR precisi, spiegando il ragionamento per ognuno e mostrando il NUOVO prezzo medio di carico stimato dopo l'acquisto."
                        
                        # 3. Richiesta AI
                        agent = st.session_state["trader_agent"]
                        final_prompt = f"SYSTEM: {sys_prompt_text}\n\nUSER_REQUEST: {user_msg_text}"
                        
                        # Use provider wrapper generically
                        try:
                            # AIProvider -> generate_content string
                            if hasattr(st.session_state["ai_provider"], 'get_model'):
                                resp = st.session_state["ai_provider"].get_model().generate_content([final_prompt])
                                ai_response = resp.text if hasattr(resp, 'text') else str(resp)
                            else:
                                # Fallback se l'API non ha .get_model()
                                ai_response = "Errore: Incompatibilità libreria AIProvider. Verifica logs."
                        except Exception as ai_ex:
                             # Se usiamo il pattern standard di TraderAgent:
                             ai_response = f"Errore AI Provider: {ai_ex}. \nAssicurati che Claude o Gemini non abbiano blocchi sulle query corpose."
                        
                        # 4. Salva risultato in session_state per render inline
                        st.session_state["smart_dca_report"] = ai_response
                        st.session_state["smart_dca_tokens"] = ', '.join(selected_tokens)
                        st.session_state["smart_dca_budget"] = budget_fiat
                        
                    except Exception as e:
                        st.error(f"Errore critico durante l'elaborazione AI: {e}")
    
    # Render del report inline (sotto il pulsante, nella pagina principale)
    if "smart_dca_report" in st.session_state and st.session_state["smart_dca_report"]:
        st.markdown("---")
        st.markdown(f"### 📊 Smart DCA Allocation Report")
        st.caption(f"Token: {st.session_state.get('smart_dca_tokens', '')} | Budget: {st.session_state.get('smart_dca_budget', '')} EUR")
        st.markdown(st.session_state["smart_dca_report"])
        
        # --- Follow-up Chat inline ---
        st.markdown("---")
        st.markdown("#### 💬 Domande sul Report")
        
        if "dca_chat_history" not in st.session_state:
            st.session_state["dca_chat_history"] = []
        
        # Mostra la cronologia dei follow-up
        for msg in st.session_state["dca_chat_history"]:
            with st.chat_message(msg["role"]):
                st.markdown(msg["content"])
        
        if followup := st.chat_input("Chiedi approfondimenti sul report...", key="dca_followup_input"):
            st.session_state["dca_chat_history"].append({"role": "user", "content": followup})
            with st.chat_message("user"):
                st.markdown(followup)
            
            with st.chat_message("assistant"):
                with st.spinner("Elaboro..."):
                    try:
                        # Costruisci contesto: report + cronologia
                        context = f"Sei un Crypto Asset Allocator. Hai appena generato questo report:\n\n{st.session_state['smart_dca_report']}\n\n"
                        for prev in st.session_state["dca_chat_history"][:-1]:
                            context += f"{prev['role'].upper()}: {prev['content']}\n"
                        context += f"\nNuova domanda dell'utente: {followup}\n\nRispondi in modo preciso e conciso, in italiano."
                        
                        resp = st.session_state["ai_provider"].get_model().generate_content([context])
                        answer = resp.text if hasattr(resp, 'text') else str(resp)
                        
                        st.markdown(answer)
                        st.session_state["dca_chat_history"].append({"role": "assistant", "content": answer})
                    except Exception as e:
                        err_msg = f"Errore: {e}"
                        st.error(err_msg)
                        st.session_state["dca_chat_history"].append({"role": "assistant", "content": err_msg})
else:
    st.info("Carica un file CSV per iniziare l'analisi del portafoglio crypto.")

# --- SIDEBAR: CHAT ASSISTANT ---
st.sidebar.divider()
st.sidebar.header("💬 Chat Assistant")

if "ai_provider" in st.session_state and st.session_state["ai_provider"]:
    # Init chat history
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    # Show chat
    with st.sidebar.expander("Conversazione", expanded=True):
        if st.button("🗑️ Pulisci Chat"):
            st.session_state.chat_history = []
            st.rerun()

        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])

        # Files Uploader
        uploaded_files = st.sidebar.file_uploader(
            "Allega file (Immagini/PDF)",
            type=["png", "jpg", "jpeg", "pdf"],
            accept_multiple_files=True,
            key="chat_file_uploader_crypto",
        )

        if user_prompt := st.chat_input(
            "Chiedi al Crypto Advisor...", key="sidebar_chat_input_crypto"
        ):
            # Prepare message content
            display_msg = user_prompt
            if uploaded_files:
                display_msg += f"\n\n📎 *{len(uploaded_files)} file allegati*"

            st.session_state.chat_history.append(
                {"role": "user", "content": display_msg}
            )
            with st.chat_message("user"):
                st.write(display_msg)

            with st.chat_message("assistant"):
                with st.spinner("Thinking..."):
                    try:
                        # --- CONTEXT PREPARATION ---
                        system_msg = "Sei un esperto di criptovalute e investimenti."

                        KEY_ANALYZED = "crypto_analyzed_csv"

                        data_context_str = ""

                        if (
                            KEY_ANALYZED in st.session_state
                            and st.session_state[KEY_ANALYZED]
                        ):
                            data_context_str = st.session_state[KEY_ANALYZED]
                            system_msg += "\n\nAnalizza il seguente portafoglio Crypto aggregato:\n"

                        if data_context_str:
                            system_msg += f"""
                             {data_context_str}
                             
                             Rispondi alle domande dell'utente basandoti su questi dati.
                             Sii preciso e conciso. Rispondi in italiano.
                             """
                        else:
                            system_msg += " Non hai accesso ai dati del portafoglio al momento. Rispondi genericamente."

                        final_prompt_text = (
                            f"{system_msg}\n\nDOMANDA UTENTE: {user_prompt}"
                        )

                        # Construct Prompt (List if files present)
                        final_prompt = [final_prompt_text]

                        if uploaded_files:
                            for uploaded_file in uploaded_files:
                                bytes_data = uploaded_file.getvalue()
                                mime_type = uploaded_file.type
                                final_prompt.append(
                                    {"mime_type": mime_type, "data": bytes_data}
                                )

                        # If only text, pass string (cleaner debug)
                        if len(final_prompt) == 1:
                            final_prompt = final_prompt[0]

                        stream = (
                            st.session_state["ai_provider"]
                            .get_model()
                            .generate_stream(final_prompt)
                        )
                        response = st.write_stream(stream)
                        st.session_state.chat_history.append(
                            {"role": "assistant", "content": response}
                        )
                    except Exception as e:
                        st.error(f"Errore: {e}")
else:
    st.sidebar.info("Configura l'AI sopra per attivare la chat.")

st.caption("Dashboard informativa. Fai sempre le tue ricerche prima di investire.")
