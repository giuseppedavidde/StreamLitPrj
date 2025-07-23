import datetime
import os

import requests
import streamlit as st
import toml

API_KEY_PATH = os.path.join(
    os.path.dirname(__file__), "..", "api_key", "gemini_key.toml"
)


def get_gemini_api_key():
    try:
        with open(API_KEY_PATH, "r") as f:
            data = toml.load(f)
        return data.get("api_key", None)
    except Exception:
        return None


SYSTEM_SNIPPET = "You are a financial and budgeting expert. Provide concise, actionable insights about personal finance, budgeting, and savings. Avoid chit-chat."


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
    response = requests.post(url, headers=headers, json=data)
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
