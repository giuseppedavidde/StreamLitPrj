import requests
import json

SYSTEM_SNIPPET = (
    "You are a financial markets expert specializing in options, stocks, and trading strategies. "
    "Your role is to assist with analysis, education, and decision-making for retail and professional traders. "
    "Always provide clear, actionable insights about option chains, volatility, risk management, and portfolio optimization. "
    "If asked about a specific stock, focus on its options, technicals, and relevant market news. "
    "Avoid general chit-chat and keep responses concise, practical, and focused on trading and investing topics."
)


def query_gemini_flash(prompt, api_key, system_snippet=SYSTEM_SNIPPET):
    url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
    headers = {"Content-Type": "application/json", "X-goog-api-key": api_key}
    context = system_snippet + "\n" + prompt
    data = {"contents": [{"parts": [{"text": context}]}]}
    response = requests.post(url, headers=headers, json=data, timeout=30)
    if response.status_code == 200:
        result = response.json()
        try:
            return result["candidates"][0]["content"]["parts"][0]["text"]
        except Exception:
            return str(result)
    else:
        return f"Errore HTTP: {response.status_code} - {response.text}"


def query_ollama(prompt, model_name, system_snippet=SYSTEM_SNIPPET):
    url = "http://localhost:11434/api/generate"
    context = system_snippet + "\n" + prompt
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
                    except json.JSONDecodeError:
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


def get_llm_expiry_suggestion(
    symbol, llm_choice, ollama_model, gemini_api_key, system_snippet=SYSTEM_SNIPPET
):
    import datetime

    today = datetime.date.today().strftime("%Y-%m-%d")
    prompt = (
        f"Given today's date is {today}, what is a reasonable expiry date for options on {symbol}? "
        "Please suggest a date within the next 1-3 months that is commonly traded. Respond with only the date in YYYY-MM-DD format."
    )
    if llm_choice == "Gemini" and gemini_api_key:
        return query_gemini_flash(prompt, gemini_api_key, system_snippet).strip()
    elif llm_choice == "Ollama":
        return query_ollama(prompt, ollama_model, system_snippet).strip()
    return ""
