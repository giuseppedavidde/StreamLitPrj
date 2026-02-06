"""
Main entry point per l'Analista Finanziario AI (CLI Version).
Permette di eseguire diagnostica per il provider AI.
"""
import time
import os
import sys
from dotenv import load_dotenv

# Load env before importing agents
load_dotenv()

# Force AI_DEBUG to true
os.environ["AI_DEBUG"] = "true"

try:
    from agents.ai_provider import AIProvider
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

def run_diagnostics():
    """
    Esegue diagnostica per il provider AI.
    """
    print("--- DIAGNOSTICS START ---")
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("ERROR: GOOGLE_API_KEY not found in env.")
        return

    print(f"API Key present: {api_key[:5]}...")

    print("Initializing AIProvider with gemini-1.5-flash...")
    try:
        provider = AIProvider(api_key=api_key, provider_type="gemini", model_name="gemini-1.5-flash")
    except Exception as e: # pylint: disable=broad-exception-caught
        print(f"Provider Init Error: {e}")
        return

    print(f"Current Model: {provider.current_model_name}")
    print(f"Available Chain: {provider.available_models_chain}")

    model = provider.get_model(json_mode=True)
    
    print("\nAttempting generation loop to trigger rate limit or catch error...")
    for i in range(1, 6):
        print(f"\nRequest {i}...")
        start = time.time()
        try:
            # Simple prompt
            resp = model.generate_content("Respond with JSON: {'status': 'ok'}")
            print(f"Success! Response: {resp.text}")
        except Exception as e: # pylint: disable=broad-exception-caught
            print(f"!!! CAUGHT EXCEPTION in Loop: {type(e).__name__}: {e}")
            # If it's a RuntimeError from the wrapper, likely it swallowed the real error except what was logged
        print(f"Time taken: {time.time() - start:.2f}s")

if __name__ == "__main__":
    run_diagnostics()
