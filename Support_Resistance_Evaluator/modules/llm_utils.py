import datetime
import os

import requests
import streamlit as st
import toml

API_KEY_PATH = os.path.join(
    os.path.dirname(__file__), "..", "api_key", "gemini_key.toml"
)


def get_gemini_api_key():
    """Return the Gemini API key.

    Lookup order:
    1. Streamlit secrets: st.secrets.get("GEMINI_API_KEY")
    2. Environment variable: os.getenv("GEMINI_API_KEY")
    3. Local TOML file at API_KEY_PATH
    Returns None if no key is found.
    """
    # 1) Streamlit secrets
    try:
        secret_key = (
            st.secrets.get("GEMINI_API_KEY") if hasattr(st, "secrets") else None
        )
        if secret_key:
            return secret_key
    except Exception:
        # If secrets are not available in this environment, move on
        pass

    # 2) Environment variable
    env_key = os.getenv("GEMINI_API_KEY")
    if env_key:
        return env_key

    # 3) Fallback to local file
    try:
        with open(API_KEY_PATH, "r", encoding="utf-8") as f:
            data = toml.load(f)
        return data.get("api_key", None)
    except Exception:
        return None


def save_gemini_api_key(api_key: str | None) -> bool:
    """Save or remove the Gemini API key to the toml file.

    If api_key is None or empty, the file will be removed if present.
    Returns True on success, False on failure.
    """
    try:
        dirpath = os.path.dirname(API_KEY_PATH)
        if not os.path.isdir(dirpath):
            os.makedirs(dirpath, exist_ok=True)

        if not api_key:
            # Remove file if exists
            if os.path.exists(API_KEY_PATH):
                os.remove(API_KEY_PATH)
            return True

        data = {"api_key": api_key}
        with open(API_KEY_PATH, "w", encoding="utf-8") as f:
            toml.dump(data, f)
        return True
    except Exception:
        return False


SYSTEM_SNIPPET = (
    "You are an experienced trading assistant specialized in technical analysis,"
    " particularly support and resistance-based strategies for equities."
    " When given a summary of support/resistance levels, provide concise, actionable trading suggestions:"
    " entry signals (price levels), conservative and aggressive targets, stop-loss recommendations,"
    " position sizing guidance (percentage of capital), trade rationale, and confidence level."
    " Use clear, short bullets and avoid excessive marketing language. Prioritize risk management for retail traders."
)


def init_chat_state():
    if "chat_time_begin" not in st.session_state:
        st.session_state.chat_time_begin = datetime.datetime.now()
    if "chat_time_end" not in st.session_state:
        st.session_state.chat_time_end = None
    if "chat_history" not in st.session_state or not st.session_state.chat_history:
        st.session_state.chat_history = [("system", SYSTEM_SNIPPET)]
        st.session_state.chat_time_begin = datetime.datetime.now()
        st.session_state.chat_time_end = None


def new_chat():
    st.session_state.chat_history = [("system", SYSTEM_SNIPPET)]
    st.session_state.chat_time_begin = datetime.datetime.now()
    st.session_state.chat_time_end = None


def query_gemini_flash(prompt, api_key, context_data=None):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    headers = {"Content-Type": "application/json", "X-goog-api-key": api_key}
    context = SYSTEM_SNIPPET
    if context_data:
        context += "\nDati utente:\n" + context_data
    context += "\n" + prompt
    data = {"contents": [{"parts": [{"text": context}]}]}
    response = requests.post(url, headers=headers, json=data, timeout=15)
    if response.status_code == 200:
        result = response.json()
        try:
            return result["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            return str(result)
    else:
        return f"HTTP Error: {response.status_code} - {response.text}"


def render_chat():
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
    st.markdown(f"## ChatBot History [{time_begin_str} / {time_end_str}]")
    for sender, message in st.session_state.chat_history:
        if sender == "system":
            continue  # Hide system message from chat display
        elif sender == "user":
            st.chat_message("user").write(message)
        else:
            st.chat_message("assistant").write(message)
