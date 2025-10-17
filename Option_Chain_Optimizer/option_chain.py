import streamlit as st
import asyncio
import pandas as pd
import requests
import json

st.set_page_config(page_title="Option Chain Optimizer", layout="wide")

st.title("Option Chain Optimizer Dashboard")
st.sidebar.header("Options Analysis Controls")

uploaded_file = st.sidebar.file_uploader("Upload Option Chain CSV", type=["csv"])

if uploaded_file is not None:
    df = pd.read_csv(uploaded_file)
    st.subheader("Uploaded Option Chain Data")
    st.dataframe(df.head())
    # ...placeholder for further analysis and visualization...
else:
    st.info("Please upload an option chain CSV file to begin analysis.")


# --- IBKR API Connection ---

# --- IBKR API Connection ---
st.sidebar.markdown("---")
st.sidebar.header("IBKR API Connection")
if "ibkr_connected" not in st.session_state:
    st.session_state.ibkr_connected = False
if "ibkr_status" not in st.session_state:
    st.session_state.ibkr_status = "Not connected"


# Store last used port/client_id for reconnection
if "ibkr_last_port" not in st.session_state:
    st.session_state.ibkr_last_port = 7497
if "ibkr_last_client_id" not in st.session_state:
    st.session_state.ibkr_last_client_id = 1

ibkr_port = st.sidebar.selectbox(
    "API Port",
    options=[7497, 7496],
    index=0,
    help="7496 for TWS Real Trading, 7497 for Paper Trading",
    key="ibkr_port_selectbox",
)
ibkr_client_id = st.sidebar.number_input(
    "Client ID", min_value=1, max_value=999, value=1, key="ibkr_client_id_input"
)


# On rerun, try to reconnect if TWS is active but session state is missing IBKR reference
if "ibkr_ib" not in st.session_state or st.session_state.ibkr_ib is None:
    try:
        import asyncio

        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())
        from ib_insync import IB

        # Close any existing connection first
        old_ib = st.session_state.get("ibkr_ib")
        if (
            old_ib is not None
            and hasattr(old_ib, "isConnected")
            and old_ib.isConnected()
        ):
            try:
                old_ib.disconnect()
                old_ib.shutdown()
            except Exception:
                pass
            st.session_state.ibkr_ib = None
            st.session_state.ibkr_connected = False
            st.session_state.ibkr_status = "Previous IBKR connection closed."
        ib = IB()
        ib.connect(
            "127.0.0.1",
            int(st.session_state.ibkr_last_port),
            clientId=int(st.session_state.ibkr_last_client_id),
            timeout=5,
        )
        if ib.isConnected():
            st.session_state.ibkr_ib = ib
            st.session_state.ibkr_connected = True
            st.session_state.ibkr_status = f"Reconnected to IBKR API on port {st.session_state.ibkr_last_port} (Client ID {st.session_state.ibkr_last_client_id})"
    except Exception:
        pass


def connect_ibkr_api(port, client_id):
    import asyncio

    old_ib = st.session_state.get("ibkr_ib")
    if old_ib is not None and hasattr(old_ib, "isConnected") and old_ib.isConnected():
        try:
            old_ib.disconnect()
            old_ib.shutdown()
        except Exception:
            pass
        st.session_state.ibkr_ib = None
        st.session_state.ibkr_connected = False
        st.session_state.ibkr_status = "Previous IBKR connection closed."

    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())

    from ib_insync import IB

    ib = IB()
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            ib.connect("127.0.0.1", int(port), clientId=int(client_id), timeout=5)
            if ib.isConnected():
                st.session_state.ibkr_ib = ib
                return (
                    True,
                    f"Connected to IBKR API on port {port} (Client ID {client_id})",
                )
            else:
                return (
                    False,
                    f"Failed to connect to IBKR API on port {port} (Client ID {client_id})",
                )
        except Exception as e:
            err_str = str(e)
            if "clientId" in err_str and "already in use" in err_str:
                client_id = int(client_id) + 1
                st.session_state.ibkr_last_client_id = client_id
                continue
            return False, f"Connection error: {e}"
    return (
        False,
        f"Connection error: clientId {client_id} still in use after {max_attempts} attempts.",
    )


if st.sidebar.button("Connect to IBKR API", key="connect_ibkr_api"):
    connected, status = connect_ibkr_api(ibkr_port, ibkr_client_id)
    st.session_state.ibkr_connected = connected
    st.session_state.ibkr_status = status
    # Store last used port/client_id for auto-reconnect
    st.session_state.ibkr_last_port = ibkr_port
    st.session_state.ibkr_last_client_id = ibkr_client_id


if st.sidebar.button("Disconnect from IBKR API", key="disconnect_ibkr_api"):
    ib = st.session_state.get("ibkr_ib")
    disconnect_error = None
    if ib is not None:
        try:
            if ib.isConnected():
                ib.disconnect()
            try:
                ib.shutdown()
            except Exception:
                pass
            # Double-check if still connected
            if hasattr(ib, "isConnected") and ib.isConnected():
                ib.disconnect()
        except Exception as exc:
            disconnect_error = exc
        # Always clear session state reference
        st.session_state.ibkr_ib = None
        st.session_state.ibkr_connected = False
        if disconnect_error:
            st.session_state.ibkr_status = f"Error disconnecting: {disconnect_error}"
            st.sidebar.error(f"Error disconnecting: {disconnect_error}")
        elif hasattr(ib, "isConnected") and ib.isConnected():
            st.session_state.ibkr_status = (
                "Warning: IBKR API may still be connected. Please check TWS/Gateway."
            )
            st.sidebar.warning(
                "IBKR API may still be connected. Please check TWS/Gateway."
            )
        else:
            st.session_state.ibkr_status = "Disconnected from IBKR API."
            st.sidebar.success("Disconnected from IBKR API.")
    else:
        st.session_state.ibkr_connected = False
        st.session_state.ibkr_status = "No active IBKR connection to disconnect."
        st.session_state.ibkr_ib = None
        st.sidebar.info("No active IBKR connection to disconnect.")

# Always show the current IBKR connection status in the sidebar
st.sidebar.markdown(f"**IBKR API Status:** {st.session_state.ibkr_status}")


# Remove duplicate ibkr_port and ibkr_client_id widgets


# --- IBKR Option Chain Fetch ---
st.sidebar.header("IBKR Option Chain Fetch")
ibkr_symbol = st.sidebar.text_input("Underlying Symbol (e.g. AAPL)", value="AAPL")
ibkr_exchange = st.sidebar.text_input("Exchange", value="SMART")
ibkr_currency = st.sidebar.text_input("Currency", value="USD")

# Step 1: Request Expiries
if "ibkr_expiries" not in st.session_state:
    st.session_state.ibkr_expiries = []
if "ibkr_selected_expiry" not in st.session_state:
    st.session_state.ibkr_selected_expiry = ""


def fetch_ibkr_expiries(symbol, exchange, currency, port, client_id):
    import asyncio

    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    ib = st.session_state.get("ibkr_ib")
    if ib is None or not ib.isConnected():
        return [], "IBKR connection is not established. Please connect first."
    from ib_insync import Stock

    try:
        stock = Stock(symbol, exchange, currency)
        ib.qualifyContracts(stock)
        # Now use correct arguments: symbol, '', secType, conId
        contracts = ib.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId)
        if not contracts:
            return (
                [],
                f"No option contracts found for symbol '{symbol}' on exchange '{exchange}'.",
            )
        expiries = sorted(list(contracts[0].expirations))
        return expiries, None
    except Exception as e:
        return [], f"Error fetching expiries: {e}"


if st.sidebar.button("Request Expiries", key="request_expiries"):
    expiries, err = fetch_ibkr_expiries(
        ibkr_symbol, ibkr_exchange, ibkr_currency, ibkr_port, ibkr_client_id
    )
    if err:
        st.sidebar.error(err)
    else:
        st.session_state.ibkr_expiries = expiries
        if expiries:
            st.session_state.ibkr_selected_expiry = expiries[0]


# --- LLM selector: Gemini or Ollama ---
st.sidebar.subheader("Chatbot Choice")
# Try to get Gemini API key from secrets.toml first
GEMINI_API_KEY = None
try:
    GEMINI_API_KEY = st.secrets["gemini"]["api_key"]
except Exception:
    pass

# Only show input box if secrets.toml is missing or does not contain the key
if not GEMINI_API_KEY:
    api_key_input = st.sidebar.text_input(
        "Gemini API Key",
        type="password",
        help="Enter your Gemini API key. It will be stored only for this session.",
    )
    if api_key_input:
        st.session_state["gemini_api_key"] = api_key_input
        GEMINI_API_KEY = api_key_input
    elif "gemini_api_key" in st.session_state and st.session_state["gemini_api_key"]:
        GEMINI_API_KEY = st.session_state["gemini_api_key"]

# LLM selector: Gemini or Ollama
llm_choice = st.sidebar.selectbox(
    "Choose LLM",
    options=["Gemini", "Ollama"],
    index=0,
    help="Select which LLM to use for chat responses.",
)

# Ollama model selection (only shown if Ollama is selected)
ollama_model = "gemma3"
if llm_choice == "Ollama":
    ollama_model = st.sidebar.text_input(
        "Ollama Model",
        value="llama2",
        help="Enter the name of the Ollama model you want to use (e.g., llama2, phi3, mistral, etc.)",
    )


# --- LLM-based expiry suggestion ---

from llm_utils import (
    get_llm_expiry_suggestion,
    query_gemini_flash,
    query_ollama,
    SYSTEM_SNIPPET,
)


ibkr_expiry = ""
if st.sidebar.button("Suggest Expiry Date with LLM", key="suggest_expiry"):
    suggested_expiry = get_llm_expiry_suggestion(
        ibkr_symbol, llm_choice, ollama_model, GEMINI_API_KEY
    )
    if suggested_expiry:
        st.session_state.ibkr_selected_expiry = suggested_expiry
        st.sidebar.success(f"Suggested expiry: {suggested_expiry}")
    else:
        st.sidebar.warning("LLM did not return a valid expiry date.")

import datetime

if st.session_state.ibkr_expiries:
    # Parse expiries into year, month, day
    expiry_dates = [
        datetime.datetime.strptime(e, "%Y-%m-%d")
        for e in st.session_state.ibkr_expiries
    ]
    years = sorted(list(set([d.year for d in expiry_dates])))
    selected_year = st.sidebar.selectbox("Year", years, key="expiry_year_selectbox")
    months = sorted(
        list(set([d.month for d in expiry_dates if d.year == selected_year]))
    )
    selected_month = st.sidebar.selectbox(
        "Month",
        months,
        format_func=lambda m: datetime.date(1900, m, 1).strftime("%B"),
        key="expiry_month_selectbox",
    )
    days = sorted(
        list(
            set(
                [
                    d.day
                    for d in expiry_dates
                    if d.year == selected_year and d.month == selected_month
                ]
            )
        )
    )
    selected_day = st.sidebar.selectbox("Day", days, key="expiry_day_selectbox")
    # Compose selected expiry
    selected_expiry = f"{selected_year:04d}-{selected_month:02d}-{selected_day:02d}"
    st.session_state.ibkr_selected_expiry = selected_expiry
    ibkr_expiry = selected_expiry
elif (
    "ibkr_selected_expiry" in st.session_state and st.session_state.ibkr_selected_expiry
):
    ibkr_expiry = st.session_state.ibkr_selected_expiry


def fetch_ibkr_option_chain(symbol, exchange, currency):
    import asyncio

    try:
        asyncio.get_event_loop()
    except RuntimeError:
        asyncio.set_event_loop(asyncio.new_event_loop())
    ib = st.session_state.get("ibkr_ib")
    if ib is None or not ib.isConnected():
        return (
            pd.DataFrame(),
            "IBKR connection is not established. Please connect first.",
        )
    from ib_insync import Stock, Option

    try:
        stock = Stock(symbol, exchange, currency)
        ib.qualifyContracts(stock)
        ib.reqMarketDataType(3)  # Request delayed market data
        ticker = ib.reqMktData(stock, "", False, False)
        market_price = ticker.marketPrice()

        chains = ib.reqSecDefOptParams(stock.symbol, "", stock.secType, stock.conId)
        chain = next(
            (
                c
                for c in chains
                if c.tradingClass == stock.symbol and c.exchange == exchange
            ),
            None,
        )
        if not chain:
            return (
                pd.DataFrame(),
                f"No option chain found for symbol '{symbol}' on exchange '{exchange}'.",
            )

        strikes = [
            strike
            for strike in chain.strikes
            if strike % 5 == 0 and market_price - 20 < strike < market_price + 20
        ]
        expirations = sorted(exp for exp in chain.expirations)[:3]
        rights = ["C", "P"]
        contracts = [
            Option(
                stock.symbol,
                expiration,
                strike,
                right,
                exchange,
                tradingClass=stock.symbol,
            )
            for right in rights
            for expiration in expirations
            for strike in strikes
        ]
        contracts = ib.qualifyContracts(*contracts)

        # Request market data for each contract individually
        contractData = []
        for idx, contract in enumerate(contracts):
            try:
                ib.reqMarketDataType(3)  # Request delayed market data for each contract
                ticker = ib.reqMktData(contract, "", True, False)
                ib.sleep(0.2)  # Small delay to avoid rate limit
                contractData.append(
                    (
                        contract.lastTradeDateOrContractMonth,
                        contract.strike,
                        contract.right,
                        ticker.time,
                        ticker.close,
                        market_price,
                    )
                )
            except Exception:
                continue
        fields = ["expiration", "strike", "right", "time", "close", "undPrice"]
        df_chain = pd.DataFrame([dict(zip(fields, t)) for t in contractData])
        return df_chain, None
    except Exception as e:
        return (
            pd.DataFrame(),
            f"IBKR Error: {e}. Connection may have dropped or symbol/exchange is invalid.",
        )


fetch_enabled = st.session_state.get("ibkr_connected", False)


if st.sidebar.button("Fetch Option Chain from IBKR", disabled=not fetch_enabled):
    with st.spinner(f"Fetching option chain for {ibkr_symbol} from IBKR..."):
        # Progress bar setup
        progress_bar = st.sidebar.progress(0, text="Fetching option chain...")

        # Ensure event loop is set
        import asyncio

        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())

        ib = st.session_state.get("ibkr_ib")
        if ib is None or not ib.isConnected():
            st.error("IBKR connection is not established. Please connect first.")
        else:
            from ib_insync import Stock, Option, util

            try:
                stock = Stock(ibkr_symbol, ibkr_exchange, ibkr_currency)
                ib.qualifyContracts(stock)
                [ticker] = ib.reqTickers(stock)
                market_price = ticker.marketPrice()

                chains = ib.reqSecDefOptParams(
                    stock.symbol, "", stock.secType, stock.conId
                )
                chain = next(
                    (
                        c
                        for c in chains
                        if c.tradingClass == stock.symbol
                        and c.exchange == ibkr_exchange
                    ),
                    None,
                )
                if not chain:
                    st.error(
                        f"No option chain found for symbol '{ibkr_symbol}' on exchange '{ibkr_exchange}'."
                    )
                else:
                    strikes = [
                        strike
                        for strike in chain.strikes
                        if strike % 5 == 0
                        and market_price - 20 < strike < market_price + 20
                    ]
                    expirations = sorted(exp for exp in chain.expirations)[:3]
                    rights = ["C", "P"]
                    contracts = [
                        Option(
                            stock.symbol,
                            expiration,
                            strike,
                            right,
                            ibkr_exchange,
                            tradingClass=stock.symbol,
                        )
                        for right in rights
                        for expiration in expirations
                        for strike in strikes
                    ]
                    contracts = ib.qualifyContracts(*contracts)
                    total = len(contracts)
                    contractData = []
                    for idx, contract in enumerate(contracts):
                        ticker_list = ib.reqTickers(contract)
                        if ticker_list:
                            t = ticker_list[0]
                            contractData.append(
                                (
                                    t.contract.lastTradeDateOrContractMonth,
                                    t.contract.strike,
                                    t.contract.right,
                                    t.time,
                                    t.close,
                                    market_price,
                                )
                            )
                        # Update progress bar
                        progress_bar.progress(
                            int((idx + 1) / total * 100),
                            text=f"Progress: {int((idx + 1) / total * 100)}%",
                        )
                    fields = [
                        "expiration",
                        "strike",
                        "right",
                        "time",
                        "close",
                        "undPrice",
                    ]
                    df_ibkr = pd.DataFrame([dict(zip(fields, t)) for t in contractData])
                    progress_bar.empty()
                    if not df_ibkr.empty:
                        st.subheader(f"IBKR Option Chain for {ibkr_symbol}")
                        st.dataframe(df_ibkr)
                    else:
                        st.info("No option chain data found.")
            except Exception as e:
                st.error(f"IBKR Error: {e}")


st.sidebar.subheader("Chatbot Choice")
# Try to get Gemini API key from secrets.toml first
GEMINI_API_KEY = None
try:
    GEMINI_API_KEY = st.secrets["gemini"]["api_key"]
except Exception:
    pass

# Only show input box if secrets.toml is missing or does not contain the key
if not GEMINI_API_KEY:
    api_key_input = st.sidebar.text_input(
        "Gemini API Key",
        type="password",
        help="Enter your Gemini API key. It will be stored only for this session.",
    )
    if api_key_input:
        st.session_state["gemini_api_key"] = api_key_input
        GEMINI_API_KEY = api_key_input
    elif "gemini_api_key" in st.session_state and st.session_state["gemini_api_key"]:
        GEMINI_API_KEY = st.session_state["gemini_api_key"]


# System snippet for Gemini context
SYSTEM_SNIPPET = (
    "You are a financial markets expert specializing in options, stocks, and trading strategies. "
    "Your role is to assist with analysis, education, and decision-making for retail and professional traders. "
    "Always provide clear, actionable insights about option chains, volatility, risk management, and portfolio optimization. "
    "If asked about a specific stock, focus on its options, technicals, and relevant market news. "
    "Avoid general chit-chat and keep responses concise, practical, and focused on trading and investing topics."
)

# Chat session time tracking
import datetime

if "chat_time_begin" not in st.session_state:
    st.session_state.chat_time_begin = datetime.datetime.now()
if "chat_time_end" not in st.session_state:
    st.session_state.chat_time_end = None

# Store chat history in session state, always start with system snippet
if "chat_history" not in st.session_state or not st.session_state.chat_history:
    st.session_state.chat_history = [("system", SYSTEM_SNIPPET)]
    st.session_state.chat_time_begin = datetime.datetime.now()
    st.session_state.chat_time_end = None


# LLM selector: Gemini or Ollama
llm_choice = st.sidebar.selectbox(
    "Choose LLM",
    options=["Gemini", "Ollama"],
    index=0,
    help="Select which LLM to use for chat responses.",
    key="llm_choice_selectbox",
)

# Ollama model selection (only shown if Ollama is selected)
ollama_model = "llama2"
if llm_choice == "Ollama":
    ollama_model = st.sidebar.text_input(
        "Ollama Model",
        value="llama2",
        help="Enter the name of the Ollama model you want to use (e.g., llama2, phi3, mistral, etc.)",
    )

# New Chat button
if st.sidebar.button("New Chat", key="new_chat"):
    st.session_state.chat_history = [("system", SYSTEM_SNIPPET)]
    st.session_state.chat_time_begin = datetime.datetime.now()
    st.session_state.chat_time_end = None

user_prompt = st.sidebar.text_area("You:")


# Chatbot interaction
if llm_choice == "Gemini":
    if not GEMINI_API_KEY:
        st.sidebar.warning(
            "Please provide a valid Gemini API key in secrets.toml or the input box above."
        )
    elif st.sidebar.button("Send", key="send_gemini") and user_prompt:
        st.session_state.chat_history.append(("user", user_prompt))
        with st.spinner("Gemini is thinking..."):
            try:
                ai_response = query_gemini_flash(user_prompt, GEMINI_API_KEY)
                st.session_state.chat_history.append(("ai", ai_response))
            except Exception as e:
                st.session_state.chat_history.append(("ai", f"Errore: {e}"))
        st.session_state.chat_time_end = datetime.datetime.now()
elif llm_choice == "Ollama":
    if st.sidebar.button("Send", key="send_ollama") and user_prompt:
        st.session_state.chat_history.append(("user", user_prompt))
        with st.spinner(f"Ollama ({ollama_model}) is thinking..."):
            ai_response = query_ollama(user_prompt, ollama_model)
            st.session_state.chat_history.append(("ai", ai_response))
        st.session_state.chat_time_end = datetime.datetime.now()


# Display chat history as a scrollable chat window in the main page

# Display chat history as a scrollable chat window in the main page
st.markdown("---")
time_begin = st.session_state.get("chat_time_begin")
time_end = st.session_state.get("chat_time_end")
if time_begin:
    time_begin_str = time_begin.strftime("%Y-%m-%d %H:%M:%S")
else:
    time_begin_str = "?"
if time_end:
    time_end_str = time_end.strftime("%Y-%m-%d %H:%M:%S")
else:
    time_end_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
st.markdown(f"## Chat History [{time_begin_str} / {time_end_str}]")
chat_html = """
<style>
.chat-container {
  max-height: 400px;
  overflow-y: auto;
  background: #222;
  padding: 16px;
  border-radius: 8px;
  border: 1px solid #444;
}
.chat-bubble {
  margin-bottom: 12px;
  padding: 10px 16px;
  border-radius: 18px;
  max-width: 80%;
  word-break: break-word;
  white-space: pre-wrap;
  font-size: 1rem;
  color: #f1f1f1;
}
.user-bubble {
  background: #005a9e;
  align-self: flex-end;
  margin-left: auto;
}
.ai-bubble {
  background: #333a3d;
  align-self: flex-start;
  margin-right: auto;
}
.sender-label {
  font-size: 0.85rem;
  color: #bdbdbd;
  margin-bottom: 2px;
}
</style>
<div class="chat-container">
"""
for sender, message in st.session_state.chat_history:
    if sender == "system":
        chat_html += f'<div class="sender-label">System</div><div class="chat-bubble ai-bubble" style="background:#444;color:#f1f1f1;">{message}</div>'
    elif sender == "user":
        chat_html += f'<div class="sender-label">You</div><div class="chat-bubble user-bubble">{message}</div>'
    else:
        chat_html += f'<div class="sender-label">Gemini</div><div class="chat-bubble ai-bubble">{message}</div>'
chat_html += "</div>"
st.markdown(chat_html, unsafe_allow_html=True)
