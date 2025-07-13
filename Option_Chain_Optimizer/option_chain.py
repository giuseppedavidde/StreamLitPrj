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
st.sidebar.markdown("---")
st.sidebar.header("IBKR API Connection")
if "ibkr_connected" not in st.session_state:
    st.session_state.ibkr_connected = False
if "ibkr_status" not in st.session_state:
    st.session_state.ibkr_status = "Not connected"

ibkr_port = st.sidebar.selectbox(
    "API Port",
    options=[7497, 7496],
    index=0,
    help="7496 for TWS Real Trading, 7497 for Paper Trading",
)
ibkr_client_id = st.sidebar.number_input(
    "Client ID", min_value=1, max_value=999, value=1
)


def connect_ibkr_api(port, client_id):
    import asyncio

    # Check for any existing IBKR connection and disconnect it first
    old_ib = st.session_state.get("ibkr_ib")
    if old_ib is not None:
        try:
            if old_ib.isConnected():
                old_ib.disconnect()
            try:
                old_ib.shutdown()
            except Exception:
                pass
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
    try:
        ib.connect("127.0.0.1", int(port), clientId=int(client_id), timeout=5)
        if ib.isConnected():
            st.session_state.ibkr_ib = ib
            return True, f"Connected to IBKR API on port {port} (Client ID {client_id})"
        else:
            return (
                False,
                f"Failed to connect to IBKR API on port {port} (Client ID {client_id})",
            )
    except Exception as e:
        return False, f"Connection error: {e}"


if st.sidebar.button("Connect to IBKR API", key="connect_ibkr_api"):
    connected, status = connect_ibkr_api(ibkr_port, ibkr_client_id)
    st.session_state.ibkr_connected = connected
    st.session_state.ibkr_status = status

st.sidebar.write(f"**Connection Status:** {st.session_state.ibkr_status}")

# Disconnect button for IBKR API
if st.sidebar.button("Disconnect from IBKR API", key="disconnect_ibkr_api"):
    ib = st.session_state.get("ibkr_ib")
    if ib is not None:
        try:
            # Check for pending requests or connection state
            if ib.isConnected():
                ib.disconnect()
            try:
                ib.shutdown()
            except Exception:
                pass
            st.session_state.ibkr_connected = False
            st.session_state.ibkr_status = "Disconnected from IBKR API."
            st.session_state.ibkr_ib = None
            st.sidebar.success("Disconnected from IBKR API.")
        except Exception as e:
            st.session_state.ibkr_connected = False
            st.session_state.ibkr_status = f"Error disconnecting: {e}"
            st.session_state.ibkr_ib = None
            st.sidebar.error(f"Error disconnecting: {e}")
    else:
        st.session_state.ibkr_connected = False
        st.session_state.ibkr_status = "No active IBKR connection to disconnect."
        st.session_state.ibkr_ib = None
        st.sidebar.info("No active IBKR connection to disconnect.")


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
    try:
        contracts = ib.reqSecDefOptParams(symbol, "", exchange, symbol)
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


# Step 2: Select Expiry
if st.session_state.ibkr_expiries:
    ibkr_expiry = st.sidebar.selectbox(
        "Select Expiry", st.session_state.ibkr_expiries, index=0
    )
    st.session_state.ibkr_selected_expiry = ibkr_expiry
else:
    ibkr_expiry = ""


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
    from ib_insync import Stock, Option, util

    try:
        stock = Stock(symbol, exchange, currency)
        ib.qualifyContracts(stock)
        [ticker] = ib.reqTickers(stock)
        market_price = ticker.marketPrice()

        chains = ib.reqSecDefOptParams(symbol, "", stock.secType, stock.conId)
        chain = next(
            (c for c in chains if c.tradingClass == symbol and c.exchange == exchange),
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
            Option(symbol, expiration, strike, right, exchange, tradingClass=symbol)
            for right in rights
            for expiration in expirations
            for strike in strikes
        ]
        contracts = ib.qualifyContracts(*contracts)
        tickers = ib.reqTickers(*contracts)
        contractData = [
            (
                t.contract.lastTradeDateOrContractMonth,
                t.contract.strike,
                t.contract.right,
                t.time,
                t.close,
                market_price,
            )
            for t in tickers
            if t.contract is not None
        ]
        fields = ["expiration", "strike", "right", "time", "close", "undPrice"]
        df = pd.DataFrame([dict(zip(fields, t)) for t in contractData])
        return df, None
    except Exception as e:
        return (
            pd.DataFrame(),
            f"IBKR Error: {e}. Connection may have dropped or symbol/exchange is invalid.",
        )


fetch_enabled = st.session_state.get("ibkr_connected", False)
if st.sidebar.button("Fetch Option Chain from IBKR", disabled=not fetch_enabled):
    with st.spinner(f"Fetching option chain for {ibkr_symbol} from IBKR..."):
        df_ibkr, err = fetch_ibkr_option_chain(
            ibkr_symbol,
            ibkr_exchange,
            ibkr_currency,
        )
        if err:
            st.error(f"IBKR Error: {err}")
        elif not df_ibkr.empty:
            st.subheader(f"IBKR Option Chain for {ibkr_symbol}")
            st.dataframe(df_ibkr)
        else:
            st.info("No option chain data found.")


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
)

# Ollama model selection (only shown if Ollama is selected)
ollama_model = "gemma3"
if llm_choice == "Ollama":
    ollama_model = st.sidebar.text_input(
        "Ollama Model",
        value="gemma3",
        help="Enter the name of the Ollama model you want to use (e.g., llama2, phi3, mistral, etc.)",
    )

# New Chat button
if st.sidebar.button("New Chat", key="new_chat"):
    st.session_state.chat_history = [("system", SYSTEM_SNIPPET)]
    st.session_state.chat_time_begin = datetime.datetime.now()
    st.session_state.chat_time_end = None

user_prompt = st.sidebar.text_area("You:")


# Gemini API call
def query_gemini_flash(prompt, api_key):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    headers = {"Content-Type": "application/json", "X-goog-api-key": api_key}
    context = SYSTEM_SNIPPET + "\n" + prompt
    data = {"contents": [{"parts": [{"text": context}]}]}
    response = requests.post(url, headers=headers, json=data)
    if response.status_code == 200:
        result = response.json()
        try:
            return result["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            return str(result)
    else:
        return f"Errore HTTP: {response.status_code} - {response.text}"


# Ollama API call
def query_ollama(prompt, model_name):
    url = "http://localhost:11434/api/generate"
    context = SYSTEM_SNIPPET + "\n" + prompt
    data = {"model": model_name, "prompt": context}
    try:
        response = requests.post(url, json=data, timeout=60, stream=True)
        if response.status_code == 200:
            responses = []
            for line in response.iter_lines():
                if line:
                    try:
                        obj = json.loads(line.decode("utf-8"))
                        if "response" in obj:
                            responses.append(obj["response"])
                    except Exception:
                        pass
            return (
                " ".join(responses).replace("  ", " ").strip()
                if responses
                else "No response from Ollama."
            )
        else:
            return f"Ollama Error: {response.status_code} - {response.text}"
    except Exception as e:
        return f"Ollama Exception: {e}"


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
