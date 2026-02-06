from modules import general_utils
from modules.general_utils import glob, os, np, pd, dt, go, sp, yf
from modules import stock_utils

# from modules.llm_utils import ... (Removed)

import warnings
from datetime import datetime as dtm
import requests
import streamlit as st
from dotenv import load_dotenv

# Carica variabili d'ambiente
load_dotenv()

import sys

# Add submodule path to sys.path for Deployment (Streamlit Cloud)
try:
    sys.path.append(os.path.join(os.path.dirname(__file__), "custom_agents"))
except Exception:
    pass

# Import Agents
try:
    from agents.ai_provider import AIProvider
    from agents.cloud_manager import CloudManager
    from agents.cloud_ui import render_cloud_sync_ui
except ImportError as e:
    st.error(f"Modulo 'agents' non trovato o errore importazione: {e}")
    AIProvider = None
    CloudManager = None

    def render_cloud_sync_ui(DATA_FILE, is_sidebar=True):
        st.error("Funzione Cloud UI non disponibile")


st.set_page_config(page_title="ETF/Stock Evaluation Dashboard", layout="wide")
st.title("ETF/Stock Evaluation Dashboard 📈")
st.caption(
    "Analyze and visualize your ETF/Stock portfolio and DCA strategies interactively."
)

DATA_FILE = "My_Portfolio.csv"

# --- 1. SIDEBAR: AI CONFIGURATION ---
st.sidebar.header("🤖 Configurazione AI")
with st.sidebar.expander("Settings AI", expanded=False):
    provider_type = st.selectbox("Provider", ["Gemini", "Ollama"], index=0)

    api_key = None
    model_name = None

    if provider_type == "Gemini":
        # Recupera API Key da Env o Input
        env_key = os.getenv("GOOGLE_API_KEY")
        api_key = st.text_input(
            "Gemini API Key",
            value=env_key if env_key else "",
            type="password",
            help="Se presente nel file .env verra' caricata automaticamente",
        )

        # Recupera lista modelli da AIProvider
        gemini_models = AIProvider.FALLBACK_ORDER
        model_name = st.selectbox("Modello", gemini_models, index=0)
    else:
        # Ollama
        if AIProvider:
            ollama_models = AIProvider.get_ollama_models()
            if ollama_models:
                model_name = st.selectbox("Modello Locale", ollama_models, index=0)
            else:
                st.warning("Nessun modello Ollama trovato o Ollama non in esecuzione.")
                model_name = st.text_input("Nome Modello Manuale", value="llama3")

    # Inizializza Provider nel Session State
    if st.button("Applica Configurazione AI"):
        if AIProvider:
            try:
                st.session_state["ai_provider"] = AIProvider(
                    api_key=api_key, provider_type=provider_type, model_name=model_name
                )
                st.toast(f"AI Attivata: {provider_type} ({model_name})", icon="🟢")
            except Exception as e:
                st.error(f"Errore Init AI: {e}")

# --- 2. SIDEBAR: CLOUD SYNC ---
render_cloud_sync_ui(DATA_FILE, is_sidebar=True)

# --- 3. SIDEBAR: CHAT ---
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
        uploaded_files = st.file_uploader(
            "Allega file (Immagini/PDF)",
            type=["png", "jpg", "jpeg", "pdf"],
            accept_multiple_files=True,
            key="chat_file_uploader",
        )

        if user_prompt := st.chat_input(
            "Chiedi al Portfolio Advisor...", key="sidebar_chat_input"
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
                        system_msg = "Sei un consulente finanziario esperto."

                        # Data from Session State
                        # Priority: 1. Analyzed Table (df_invested_capital as CSV) 2. Raw File (Cloud Sync)

                        KEY_ANALYZED = "portfolio_analyzed_csv"
                        KEY_RAW = "portfolio_cloud_data"

                        data_context_str = ""

                        if (
                            KEY_ANALYZED in st.session_state
                            and st.session_state[KEY_ANALYZED]
                        ):
                            data_context_str = st.session_state[KEY_ANALYZED]
                            system_msg += "\n\nAnalizza la seguente tabella riassuntiva del portafoglio (DCA and Gain Analysis):\n"
                        elif KEY_RAW in st.session_state and st.session_state[KEY_RAW]:
                            data_context_str = st.session_state[KEY_RAW]
                            if isinstance(data_context_str, bytes):
                                data_context_str = data_context_str.decode("utf-8")
                            system_msg += "\n\nHai accesso ai dati grezzi del portafoglio (CSV):\n"

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


# --- 4. MAIN: DATA LOADING ---
df_portfolio = None
import io

# Logic:
# 1. Check Cloud Data (Session State)
# 2. Check local DATA_FILE (Fallback)
# 3. Allow upload or default

KEY_DATA = "portfolio_cloud_data"

if KEY_DATA in st.session_state and st.session_state[KEY_DATA]:
    try:
        raw_data = st.session_state[KEY_DATA]
        if isinstance(raw_data, bytes):
            raw_data = io.BytesIO(raw_data)
        else:
            raw_data = io.StringIO(raw_data)

        df_portfolio = pd.read_csv(raw_data, sep=";")
        st.info("Using Cloud Data (In-Memory)")
    except Exception as e:
        st.error(f"Errore lettura dati cloud: {e}")

if df_portfolio is None and os.path.exists(DATA_FILE):
    # Only load local if no cloud data
    try:
        df_portfolio = pd.read_csv(
            DATA_FILE, sep=";"
        )  # Assuming semicolon for this portfolio file
        st.warning(f"Using Local File: {DATA_FILE} (Cloud data not loaded)")
    except Exception as e:
        st.error(f"Errore lettura file locale {DATA_FILE}: {e}")

if df_portfolio is None:
    st.info(
        "Nessun portfolio trovato. Scaricalo da GitHub (menu a sinistra) o caricane uno."
    )
    uploaded_file = st.file_uploader("Carica Portfolio CSV (sep=;)", type=["csv"])
    if uploaded_file:
        df_portfolio = pd.read_csv(uploaded_file, sep=";")
        # If uploaded manually, maybe we treat as cloud data "draft"?
        # For now, stick to old behavior or just put in memory?
        # Let's put in memory so Push works
        csv_buffer = io.StringIO()
        df_portfolio.to_csv(csv_buffer, sep=";", index=False)
        st.session_state[KEY_DATA] = csv_buffer.getvalue()
        st.rerun()


# --- 5. DATA EDITING & MANAGEMENT ---
if df_portfolio is not None:
    st.sidebar.divider()
    st.sidebar.header("🛠️ Gestione Portfolio")

    with st.sidebar.expander("➕ Aggiungi Transazione", expanded=True):
        with st.container():  # Form removed to allow interactive UI (Currency Label)
            # Get Tickers for suggestions
            ticker_col_name = (
                "Symbol"
                if "Symbol" in df_portfolio.columns
                else df_portfolio.columns[0]
            )
            existing_tickers = sorted(
                df_portfolio[ticker_col_name].astype(str).unique().tolist()
            )

            # Selectbox for Ticker
            selected_ticker_opt = st.selectbox(
                "Seleziona Ticker",
                ["-- Seleziona --"] + existing_tickers + ["➕ NUOVO TICKER"],
            )

            new_ticker = ""
            if selected_ticker_opt == "➕ NUOVO TICKER":
                new_ticker = (
                    st.text_input("Inserisci Nuovo Ticker (es. VWCE.DE)")
                    .strip()
                    .upper()
                )
            elif selected_ticker_opt != "-- Seleziona --":
                new_ticker = selected_ticker_opt

            c1, c2 = st.columns(2)
            with c1:
                broker = st.selectbox(
                    "Broker", ["Trade Republic", "Flatex", "Others"], index=0
                )
            with c2:
                currency = st.radio(
                    "Valuta Transazione", ["EUR", "USD"], horizontal=True
                )

            txn_type = st.selectbox("Tipo", ["Buy", "Sell"], index=0)

            c3, c4 = st.columns(2)
            with c3:
                shares = st.number_input(
                    "Quote (Shares)",
                    min_value=0.0,
                    value=0.0,
                    step=0.000001,
                    format="%.6f",
                )
            with c4:
                price_label = f"Prezzo per Quota ({currency})"
                price_per_share = st.number_input(
                    price_label, min_value=0.0, value=0.0, step=0.01, format="%.2f"
                )

            txn_date = st.date_input("Data Transazione", value=pd.Timestamp.today())

            submitted = st.button("Aggiungi / Aggiorna")

            if submitted:
                if not new_ticker:
                    st.error("Seleziona o inserisci un Ticker valido.")
                elif shares <= 0:
                    st.error("Inserisci una quantità di quote valida (> 0).")
                elif price_per_share < 0:
                    st.error("Il prezzo non può essere negativo.")
                else:
                    # --- UPDATE LOGIC ---
                    try:
                        df = df_portfolio.copy()

                        # 1. Check if Ticker exists
                        if new_ticker in df[ticker_col_name].values:
                            idx = df.index[df[ticker_col_name] == new_ticker].tolist()[
                                0
                            ]
                        else:
                            # Append new row
                            new_row = {col: np.nan for col in df.columns}
                            new_row[ticker_col_name] = new_ticker
                            new_row["Category"] = "Stock"  # Default
                            df = pd.concat(
                                [df, pd.DataFrame([new_row])], ignore_index=True
                            )
                            idx = df.index[-1]
                            st.info(f"Nuovo Ticker {new_ticker} creato.")

                        # 2. Broker specific updates (EUR ONLY)
                        def get_val(r, c):
                            try:
                                return float(r[c]) if pd.notna(r[c]) else 0.0
                            except:
                                return 0.0

                        if broker == "Trade Republic":
                            col_invest = "TR Investment"
                            col_shares = "TR Shares "
                            col_avg = "TR  Average Cost"
                        elif broker == "Flatex":
                            col_invest = "Flatex Investment "
                            col_shares = "Flatex Shares"
                            col_avg = "Flatex Average Cost"
                        else:
                            col_invest = f"{broker} Investment"
                            col_shares = f"{broker} Shares"
                            col_avg = f"{broker} Average Cost"
                            for c in [col_invest, col_shares, col_avg]:
                                if c not in df.columns:
                                    df[c] = np.nan

                        def find_col(exact):
                            if exact in df.columns:
                                return exact
                            for c in df.columns:
                                if c.strip() == exact.strip():
                                    return c
                            return exact

                        col_invest = find_col(col_invest)
                        col_shares = find_col(col_shares)
                        col_avg = find_col(col_avg)

                        # --- STRICT SEGREGATED LOGIC (User Formula) ---

                        # Helper for Case-Insensitive Column Lookup
                        def find_col_ci(df, prompt_name):
                            for c in df.columns:
                                if c.strip().lower() == prompt_name.strip().lower():
                                    return c
                            return prompt_name  # Return prompt if not found (will be created)

                        # Identify Columns (Robust to Casing)
                        col_invest_eur = find_col_ci(df, "Invested (EUR)")
                        col_cost_eur = find_col_ci(df, "Share cost (EUR)")

                        col_invest_usd = find_col_ci(df, "Invested (USD)")
                        col_cost_usd = find_col_ci(df, "Share Cost (USD)")

                        # 1. Derive Current State (Bucket Model)
                        # Read existing values
                        cur_invest_eur = get_val(df.loc[idx], col_invest_eur)
                        cur_cost_eur = get_val(df.loc[idx], col_cost_eur)

                        cur_invest_usd = get_val(df.loc[idx], col_invest_usd)
                        cur_cost_usd = get_val(df.loc[idx], col_cost_usd)

                        # Read Broker Specific Values (Restored)
                        cur_shares_broker = get_val(df.loc[idx], col_shares)
                        cur_invest_broker = get_val(df.loc[idx], col_invest)

                        # Derive Currency-Specific Shares (User Formula: Invested / Cost)
                        cur_shares_eur_bucket = (
                            cur_invest_eur / cur_cost_eur
                            if cur_cost_eur and cur_invest_eur
                            else 0.0
                        )
                        cur_shares_usd_bucket = (
                            cur_invest_usd / cur_cost_usd
                            if cur_cost_usd and cur_invest_usd
                            else 0.0
                        )

                        # 2. Calculate Transaction Impacts
                        # Quote (Shares) from Input
                        txn_shares = shares
                        # Price from Input (in selected currency)
                        txn_price = price_per_share

                        # Deltas
                        # Shares: Sell (-), Buy (+)
                        delta_shares = txn_shares if txn_type == "Buy" else -txn_shares
                        # Invested (Cash Flow): Buy (+), Sell (-) -> shares * price
                        # Note: User specified: New_Invested = Old - (Shares * Price) for Sell.
                        # Matches: delta_Value = Shares * Price. Buy adds it, Sell subtracts it.
                        delta_value = (
                            (txn_shares * txn_price)
                            if txn_type == "Buy"
                            else -(txn_shares * txn_price)
                        )

                        # 3. Apply to Active Bucket ONLY
                        if currency == "EUR":
                            # Update EUR
                            new_invest_eur = cur_invest_eur + delta_value
                            new_shares_eur_bucket = max(
                                0, cur_shares_eur_bucket + delta_shares
                            )

                            # Recalc EUR Cost
                            if new_shares_eur_bucket > 0:
                                new_cost_eur = new_invest_eur / new_shares_eur_bucket
                            else:
                                new_cost_eur = 0.0

                            # Write changes to DataFrame (EUR)
                            df.at[idx, col_invest_eur] = new_invest_eur
                            df.at[idx, col_cost_eur] = new_cost_eur

                            # Update Broker (EUR)
                            new_invest_broker = cur_invest_broker + delta_value
                            df.at[idx, col_invest] = new_invest_broker

                        else:  # USD
                            # Update USD
                            new_invest_usd = cur_invest_usd + delta_value
                            new_shares_usd_bucket = max(
                                0, cur_shares_usd_bucket + delta_shares
                            )

                            # Recalc USD Cost
                            if new_shares_usd_bucket > 0:
                                new_cost_usd = new_invest_usd / new_shares_usd_bucket
                            else:
                                new_cost_usd = 0.0

                            # Write changes to DataFrame (USD)
                            df.at[idx, col_invest_usd] = new_invest_usd
                            df.at[idx, col_cost_usd] = new_cost_usd

                            # Broker (EUR) UNCHANGED
                            # We do NOT touch col_invest (EUR) for this broker if dealing in USD

                        # 4. Global & Broker Shares Updates (Always)
                        new_shares_broker = max(0, cur_shares_broker + delta_shares)
                        df.at[idx, col_shares] = new_shares_broker

                        cur_total_shares = get_val(df.loc[idx], "Shares")
                        new_total_shares = max(0, cur_total_shares + delta_shares)
                        df.at[idx, "Shares"] = new_total_shares

                        # 5. Broker Average Cost (Legacy - update if we changed broker shares/invest)
                        # If EUR txn, we updated Invest and Shares.
                        # If USD txn, we updated Shares, but NOT Invest (EUR).
                        # So Broker Avg Cost (EUR) changes in both cases?
                        # If USD txn: Broker Invest (EUR) static, Shares changed. Avg Cost (EUR) changes.
                        current_invest_broker_final = get_val(
                            df.loc[idx], col_invest
                        )  # Might be new or old
                        if new_shares_broker > 0:
                            df.at[idx, col_avg] = (
                                current_invest_broker_final / new_shares_broker
                            )
                        else:
                            df.at[idx, col_avg] = 0

                        df.at[idx, "Last Purchase (YY-MM-DD)"] = txn_date.strftime(
                            "%Y-%m-%d"
                        )

                        # Save
                        df_portfolio = df
                        csv_buffer = io.StringIO()
                        df_portfolio.to_csv(csv_buffer, sep=";", index=False)
                        st.session_state[KEY_DATA] = csv_buffer.getvalue()

                        st.success(
                            f"Aggiornato {new_ticker} ({currency})! Logic: {txn_type} {txn_shares} shares."
                        )
                        st.rerun()

                    except Exception as e:
                        st.error(f"Errore aggiornamento: {e}")

# --- 6. ANALYSIS LOGIC (Original Preserved) ---
if df_portfolio is not None:
    # --- User Inputs ---
    st.sidebar.divider()
    st.sidebar.header("Analysis Options")
    portfolio_mode = st.sidebar.radio(
        "Analysis Mode:", ["Single Stock", "Portfolio"], index=1
    )

    # Date selection
    today_ts = pd.Timestamp.today()

    # Fix: Ensure logic works. 'df_portfolio' (loaded) is our stock_under_test for Portfolio mode.
    # Note: df_portfolio might be all strings due to editor. Convert back numericals if needed?
    # The original code loaded it, then used existing types.
    # If loaded from CSV, it's inferred. If passed through astype(str) for editor, it is string.
    # We MUST reload or convert back for analysis.

    # Helper to convert back
    def safe_convert(df):
        df_new = df.copy()
        if "Formula Result" in df_new.columns:
            df_new = df_new.drop(columns=["Formula Result"])
        for col in df_new.columns:
            try:
                df_new[col] = pd.to_numeric(df_new[col])
            except:
                pass
        return df_new

    df_analysis = df_portfolio
    # Fallback to df_portfolio (loaded from disk/upload) if edited_df not yet defined (e.g. not expanded)
    # Actually edited_df is defined inside expander. If expander closed, it might NOT be in locals if st.data_editor not run?
    # st.data_editor runs even if not visible? No, if inside expander it runs.
    # If we are outside expander, use df_portfolio but need to convert types if we did astype(str).
    # Actually, let's just use the loaded df_portfolio and convert it.

    # Reload from disk to be safe for types? Or just cast.
    # Let's assume df_portfolio is raw loaded (good types) UNTIL we edit it.
    # But we did `df_portfolio = df_portfolio.astype(str)` BEFORE editor.
    # So we need to re-read or convert.

    # Better approach:
    # 1. Load `df_raw` from CSV (good types).
    # 2. `df_str` = `df_raw.astype(str)` for editor.
    # 3. `edited_str` = st.data_editor(df_str).
    # 4. If using for analysis, try to parse `edited_str` back to numbers.

    # Re-conversion for analysis
    stock_under_test = df_analysis  # Rename for compatibility

    if portfolio_mode == "Portfolio":
        start_date = st.sidebar.date_input(
            "Start Date", value=today_ts.replace(year=today_ts.year - 3)
        )
    else:
        stock_symbol = st.sidebar.text_input("Enter Stock Ticker Symbol", value="AAPL")
        category = st.sidebar.selectbox(
            "Category", ["ETF", "Crypto", "Stock"], key="sidebar_category"
        )
        start_date = st.sidebar.date_input(
            "Start Date", value=today_ts.replace(year=today_ts.year - 3)
        )
        stock_under_test = stock_symbol

    end_date = st.sidebar.date_input("End Date", value=today_ts)
    end_date_str = end_date.strftime("%Y-%m-%d")

    # --- Data Collection ---
    if isinstance(stock_under_test, pd.DataFrame):
        stock_data_object = {}
        # Ensure Symbol column exists
        if "Symbol" in stock_under_test.columns:
            for symbol in stock_under_test["Symbol"]:
                if pd.notna(symbol) and str(symbol).strip() != "":
                    stock_data_object[symbol] = stock_utils.get_stock_data(str(symbol))
    else:
        stock_data_object = stock_utils.get_stock_data(stock_under_test)

    # --- Main Analysis Logic ---
    if isinstance(stock_under_test, pd.DataFrame):
        st.subheader("Portfolio Overview")
        st.dataframe(stock_under_test)

        # --- DCA and Gain Calculations ---
        st.markdown("### Portfolio DCA and Gain Analysis")
        # USDEUR DailyRate Change
        forex_data = None
        if (
            isinstance(stock_data_object, dict)
            and "USDEUR=X" in stock_data_object
            and stock_data_object["USDEUR=X"] is not None
        ):
            try:
                forex_data = stock_data_object["USDEUR=X"].history(period="1d")
            except Exception:
                forex_data = None
        latest_rate = forex_data["Close"].iloc[-1] if forex_data is not None else 1.0

        # Dictionaries for calculations
        invested_capital_usd_dict = {}
        invested_capital_eur_dict = {}
        invested_capital_eur_dict_today = {}
        shares_dict = {}
        shares_cost_dict = {}
        shares_cost_usd_dict = {}
        shares_value_dict = {}
        shares_value_usd_dict = {}
        gain_shares_absolute_value_dict = {}
        gain_shares_percentage_dict = {}

        # Ensure 'Category' column
        if "Category" not in stock_under_test.columns:
            st.error("Column 'Category' missing in portfolio.")
            st.stop()

        capital_by_category = {
            cat: 0.0 for cat in stock_under_test["Category"].unique()
        }
        capital_by_category_today = {
            cat: 0.0 for cat in stock_under_test["Category"].unique()
        }
        weight_by_symbol = {}
        weight_by_symbol_today = {}
        total_gain = 0.0

        end_date_dca = end_date_str

        for symbol in stock_under_test["Symbol"]:
            if symbol != "USDEUR=X" and pd.notna(symbol) and str(symbol).strip() != "":
                # Find row index
                row = stock_under_test[stock_under_test["Symbol"] == symbol].iloc[0]

                category = row["Category"]
                shares = float(row.get("Shares", 0))
                invested_capital_usd = float(row.get("Invested (USD)", 0))
                invested_capital_eur = float(row.get("Invested (EUR)", 0))

                invested_capital_usd_dict[symbol] = invested_capital_usd
                shares_dict[symbol] = shares

                shares_info = None
                if (
                    isinstance(stock_data_object, dict)
                    and symbol in stock_data_object
                    and stock_data_object[symbol] is not None
                ):
                    try:
                        shares_info = stock_data_object[symbol].history(period="1d")
                    except Exception:
                        shares_info = None

                if shares_info is not None and not shares_info.empty:
                    close_price = shares_info["Close"].iloc[-1]
                    # Logic for USD/EUR conversion if needed
                    # Original logic was bit custom for specific symbols or heuristic
                    if invested_capital_usd_dict[symbol] > 0.0:
                        shares_value_dict[symbol] = close_price * latest_rate
                        shares_value_usd_dict[symbol] = close_price
                    elif symbol in ["IE00BK5BQT80", "IE00BFMXXD54"]:  # EUR ETFs
                        shares_value_dict[symbol] = close_price * latest_rate
                        shares_value_usd_dict[symbol] = close_price
                    else:
                        shares_value_dict[symbol] = close_price
                        shares_value_usd_dict[symbol] = (
                            close_price / latest_rate if latest_rate else 0.0
                        )
                else:
                    shares_value_dict[symbol] = 0.0
                    shares_value_usd_dict[symbol] = 0.0

                invested_capital_eur_dict[symbol] = (
                    (
                        invested_capital_usd_dict[symbol] * latest_rate
                        + invested_capital_eur
                    )
                    if invested_capital_usd_dict[symbol] > 0.0
                    else invested_capital_eur
                )

                invested_capital_eur_dict_today[symbol] = (
                    shares * shares_value_dict[symbol]
                )

                shares_cost_dict[symbol] = (
                    invested_capital_eur_dict[symbol] / shares_dict[symbol]
                    if shares_dict[symbol] > 0.0
                    else 0.0
                )

                shares_cost_usd_dict[symbol] = (
                    shares_cost_dict[symbol] / latest_rate
                    if latest_rate and shares_cost_dict[symbol] > 0.0
                    else 0.0
                )

                gain_shares_absolute_value_dict[symbol] = (
                    shares_value_dict[symbol] * shares_dict[symbol]
                ) - invested_capital_eur_dict[symbol]

                gain_shares_percentage_dict[symbol] = (
                    (
                        gain_shares_absolute_value_dict[symbol]
                        / invested_capital_eur_dict[symbol]
                    )
                    * 100
                    if invested_capital_eur_dict[symbol]
                    else 0.0
                )
                total_gain += gain_shares_absolute_value_dict[symbol]

                if category not in capital_by_category:
                    capital_by_category[category] = 0.0
                capital_by_category[category] += invested_capital_eur_dict[symbol]

                if category not in capital_by_category_today:
                    capital_by_category_today[category] = 0.0
                capital_by_category_today[category] += invested_capital_eur_dict_today[
                    symbol
                ]

                weight_by_symbol[symbol] = {
                    "invested": invested_capital_eur_dict[symbol],
                    "category": category,
                }
                weight_by_symbol_today[symbol] = {
                    "invested": invested_capital_eur_dict_today[symbol],
                    "category": category,
                }

        # Calculate weights logic (Original)
        for symbol, data in weight_by_symbol.items():
            category_total = capital_by_category[data["category"]]
            if category_total > 0.0:
                weight_by_symbol[symbol]["weight"] = (
                    data["invested"] / category_total * 100
                )
            else:
                weight_by_symbol[symbol]["weight"] = 0.0
        for symbol, data in weight_by_symbol_today.items():
            category_total_today = capital_by_category_today[data["category"]]
            if category_total_today > 0.0:
                weight_by_symbol_today[symbol]["weight"] = (
                    data["invested"] / category_total_today * 100
                )
            else:
                weight_by_symbol_today[symbol]["weight"] = 0.0

        # DataFrame for invested capital
        # Ensure lists are aligned
        symbols_list = list(invested_capital_eur_dict.keys())

        df_invested_capital = pd.DataFrame(
            {
                "Symbol": symbols_list,
                "BEGINNING: Invested Capital (EUR)": [
                    invested_capital_eur_dict.get(s, 0.0) for s in symbols_list
                ],
                "TODAY: Invested Capital (EUR)": [
                    invested_capital_eur_dict_today.get(s, 0.0) for s in symbols_list
                ],
                "Shares": [shares_dict.get(s, 0.0) for s in symbols_list],
                "Share Value (USD)": [
                    shares_value_usd_dict.get(s, 0.0) for s in symbols_list
                ],
                "Share Value (EUR)": [
                    shares_value_dict.get(s, 0.0) for s in symbols_list
                ],
                "Share Cost (USD)": [
                    shares_cost_usd_dict.get(s, 0.0) for s in symbols_list
                ],
                "Share Cost (EUR)": [
                    shares_cost_dict.get(s, 0.0) for s in symbols_list
                ],
                "Gain (EUR)": [
                    gain_shares_absolute_value_dict.get(s, 0.0) for s in symbols_list
                ],
                "Gain %": [
                    gain_shares_percentage_dict.get(s, 0.0) for s in symbols_list
                ],
            }
        )
        st.dataframe(df_invested_capital, use_container_width=True)

        # --- Update Session State for AI Context ---
        try:
            # Save this dataframe as CSV string to session state for the Chat Assistant
            import io

            buf = io.StringIO()
            df_invested_capital.to_csv(buf, index=False)
            st.session_state["portfolio_analyzed_csv"] = buf.getvalue()
        except Exception as e:
            print(f"Error caching portfolio for AI: {e}")

        # Totals
        eur_total = (
            stock_under_test["Total Invested (EUR)"].astype(float).sum()
            if "Total Invested (EUR)" in stock_under_test.columns
            else 0
        )  # Careful with Total columns sum vs single row
        # In original, it seemed to take iloc[0]. Let's try to be smart.
        # Actually in original CSV, 'Total Invested (EUR)' might be a formula or manually put value same for all?
        # Let's rely on computed values? Or fallback to reading column if needed.
        # Computed:
        invested_capital_invested = sum(invested_capital_eur_dict.values())

        st.metric("Total Invested (EUR)", f"{invested_capital_invested:,.2f}")
        st.metric("Total Return (EUR)", f"{total_gain:,.2f}")
        percentage_return = (
            (total_gain / invested_capital_invested) * 100
            if invested_capital_invested
            else 0
        )
        st.metric("Total Return %", f"{percentage_return:.2f}%")

        # Pie Charts Logic (Helper)
        def safe_create_pie_chart(labels, values, title_text):
            if not labels or not values or sum(values) == 0:
                st.info(f"No data to display for: {title_text}")
                return None
            fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=0.3)])
            fig.update_layout(title_text=title_text)
            return fig

        with st.expander("Show Invested Capital by Category Pie Charts"):
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("#### BEGINNING")
                fig1 = safe_create_pie_chart(
                    list(capital_by_category.keys()),
                    list(capital_by_category.values()),
                    "Invested Capital per Category",
                )
                if fig1:
                    st.plotly_chart(fig1, use_container_width=True)

            with c2:
                st.markdown("#### TODAY")
                fig2 = safe_create_pie_chart(
                    list(capital_by_category_today.keys()),
                    list(capital_by_category_today.values()),
                    "Value per Category",
                )
                if fig2:
                    st.plotly_chart(fig2, use_container_width=True)

        with st.expander("Show Weights by Symbol in Each Category Pie Charts"):
            for category in capital_by_category.keys():
                if category == "Forex":
                    continue

                # Logic to filter
                cat_syms = [
                    s for s, d in weight_by_symbol.items() if d["category"] == category
                ]
                cat_ws = [
                    d["weight"]
                    for s, d in weight_by_symbol.items()
                    if d["category"] == category
                ]

                cat_ws_today = [
                    d["weight"]
                    for s, d in weight_by_symbol_today.items()
                    if d["category"] == category
                ]

                if cat_syms and sum(cat_ws) > 0:
                    st.markdown(f"**{category}**")
                    col_a, col_b = st.columns(2)
                    with col_a:
                        f3 = safe_create_pie_chart(
                            cat_syms, cat_ws, f"BEGINNING: {category}"
                        )
                        if f3:
                            st.plotly_chart(f3, use_container_width=True)
                    with col_b:
                        f4 = safe_create_pie_chart(
                            cat_syms, cat_ws_today, f"TODAY: {category}"
                        )
                        if f4:
                            st.plotly_chart(f4, use_container_width=True)

    else:
        # SINGLE STOCK MODE
        st.subheader(f"Stock Overview: {stock_under_test}")
        st.markdown("### Single Stock DCA and Gain Analysis")

        invested_capital_invested = st.number_input(
            "Insert how much you want to invest in EUR",
            min_value=0.0,
            value=1000.0,
            step=100.0,
        )
        start_date_dca = st.date_input(
            "Enter the start date for DCA Strategy", value=start_date
        )
        end_date_dca = st.date_input(
            "Enter the end date for DCA Strategy", value=end_date
        )

        # Adjust End Date Logic
        today_dt = pd.Timestamp.today().normalize().date()
        if end_date_dca >= today_dt:
            temp_ticker = stock_utils.get_stock_data(stock_under_test)
            if temp_ticker is not None:
                hist = temp_ticker.history(period="5d")
                if not hist.empty:
                    last_trading_day = hist.index[-1].to_pydatetime().date()
                    if last_trading_day < end_date_dca:
                        st.warning(
                            f"End date adjusted to last trading day: {last_trading_day}"
                        )
                        end_date_dca = last_trading_day

        start_date_dca_str = start_date_dca.strftime("%Y-%m-%d")
        end_date_dca_str = end_date_dca.strftime("%Y-%m-%d")

        ma_period = st.number_input(
            "Moving Average Period (MA)", min_value=1, value=200, step=1
        )

        if category is None:
            category = st.sidebar.selectbox(
                "Category",
                ["ETF", "Crypto", "Stock"],
                key="single_stock_category_fallback",
            )

        # Get Data
        stock_data_dca_values = stock_utils.get_stock_with_date_index_data(
            stock_data=stock_data_object,
            category=category,
            start_date=start_date_dca_str,
            end_date=end_date_dca_str,
            ma_period=ma_period,
        )
        st.dataframe(stock_data_dca_values)

        if (
            stock_data_dca_values["stock_price"].isna().all()
            or stock_data_dca_values["MA200"].isna().all()
            or "error" in stock_data_dca_values.columns
        ):
            st.error("No valid data found.")
        else:
            stock_data_dca_values = stock_data_dca_values.copy()
            if not isinstance(stock_data_dca_values.index, pd.DatetimeIndex):
                stock_data_dca_values.index = pd.to_datetime(
                    stock_data_dca_values.index
                )
            stock_data_dca_values = stock_data_dca_values.sort_index()

            # Recalc MA200
            stock_data_dca_values["MA200"] = (
                stock_data_dca_values["stock_price"].rolling(window=ma_period).mean()
            )

            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=stock_data_dca_values.index,
                    y=stock_data_dca_values["stock_price"],
                    mode="lines",
                    name="Price",
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=stock_data_dca_values.index,
                    y=stock_data_dca_values["MA200"],
                    mode="lines",
                    name=f"MA{ma_period}",
                )
            )
            fig.update_layout(
                title=f"{stock_under_test} Analysis", hovermode="x unified"
            )
            st.plotly_chart(fig, use_container_width=True)

# --- Footer ---
st.caption("Auto-generated Dashboard powered by Streamlit & Agents")
