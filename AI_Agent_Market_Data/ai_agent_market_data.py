# Install required packages if not already installed:
# pip install llama-index llama-index-llms-openai openai


import streamlit as st
from llama_index.core import VectorStoreIndex, SimpleDirectoryReader, Settings
from llama_index.llms.openai import OpenAI
from llama_index.llms.anthropic import Anthropic
from llama_index.core.tools.code_interpreter import CodeInterpreterToolSpec
from llama_index.core.agent import FunctionCallingAgent
from llama_index.core.llms import CustomLLM
from dotenv import load_dotenv
import requests
import json

load_dotenv()


st.set_page_config(page_title="AI Finance Agent Dashboard", layout="wide")
st.title("AI Finance Agent Dashboard")

# Sidebar: LLM selection
st.sidebar.header("LLM Selection")
llm_choice = st.sidebar.selectbox("Choose LLM", ["OpenAI", "Ollama (local)"])
ollama_model = st.sidebar.text_input(
    "Ollama Model",
    value="llama2",
    help="Model name for local Ollama (e.g. llama2, phi3, mistral)",
)
openai_model = st.sidebar.text_input(
    "OpenAI Model",
    value="gpt-3.5-turbo",
    help="Model name for OpenAI (e.g. gpt-3.5-turbo, gpt-4)",
)

# Sidebar: Document upload
st.sidebar.header("Upload Finance Documents")
uploaded_files = st.sidebar.file_uploader(
    "Upload files (PDF, CSV, TXT, etc.)", accept_multiple_files=True
)

# Save uploaded files to a temp folder
import os
import tempfile

data_dir = tempfile.mkdtemp()
if uploaded_files:
    for file in uploaded_files:
        with open(os.path.join(data_dir, file.name), "wb") as f:
            f.write(file.getbuffer())
else:
    data_dir = "data"  # fallback to default folder if nothing uploaded


# Load documents
documents = SimpleDirectoryReader(data_dir).load_data()
index = VectorStoreIndex.from_documents(documents)
query_engine = index.as_query_engine()

# Add code interpreter tool
code_spec = tool_spec()
tools = code_spec.to_tool_list()


# --- LLM selection logic (OpenAI or local Ollama) ---


class LocalOllamaLLM(CustomLLM):
    def __init__(self, model_name="llama2"):
        super().__init__()
        self.model_name = model_name

    def chat(self, messages, **kwargs):
        # messages: list of dicts with 'role' and 'content'
        prompt = "\n".join([m["content"] for m in messages if m["role"] == "user"])
        url = "http://localhost:11434/api/generate"
        data = {"model": self.model_name, "prompt": prompt}
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
                return {
                    "role": "assistant",
                    "content": " ".join(responses).replace("  ", " ").strip(),
                }
            else:
                return {
                    "role": "assistant",
                    "content": f"Ollama Error: {response.status_code} - {response.text}",
                }
        except Exception as e:
            return {"role": "assistant", "content": f"Ollama Exception: {e}"}


# Choose which LLM to use based on sidebar selection
if llm_choice == "OpenAI":
    from llama_index.llms.openai import OpenAI

    llm_selected = OpenAI(model=openai_model)
elif llm_choice == "Ollama (local)":
    llm_selected = LocalOllamaLLM(model_name=ollama_model)
else:
    llm_selected = Anthropic(model="claude-3-opus-20240229")


# 4. Create the agent using FunctionCallingAgent
agent = FunctionAgent(
    tools,
    llm=llm_selected,
    verbose=True,
    allow_parallel_tool_calls=False,
    system_prompt=(
        "You are a financial markets expert AI. "
        "Answer questions about stocks, options, and finance using the provided data and your knowledge."
    ),
)

# 5. Streamlit chat interface
st.header("Chat with the AI Finance Agent")
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

user_input = st.text_area("You:", "", key="user_input")
if st.button("Send") and user_input.strip():
    st.session_state.chat_history.append(("user", user_input))
    with st.spinner("AI is thinking..."):
        response = agent.chat(user_input)
    st.session_state.chat_history.append(("ai", str(response)))

# Display chat history
for sender, message in st.session_state.chat_history:
    if sender == "user":
        st.markdown(f"**You:** {message}")
    else:
        st.markdown(f"**AI:** {message}")
