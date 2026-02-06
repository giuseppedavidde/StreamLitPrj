
import sys
try:
    from agents.ai_provider import AIProvider, GroqWrapper, GeminiWrapper, OllamaWrapper
    from google import genai
    print("Imports successful.")
    
    # Test Gemini Init (mock key logic already in provider)
    try:
        provider = AIProvider(api_key="TEST_KEY", provider_type="gemini")
        print("Gemini Provider inited.")
        # Check if client was created inside wrapper (mock check)
        # Note: We can't easily check wrapper internals without a real call or introspection, 
        wrapper = provider.get_model()
        if hasattr(wrapper, 'client') and wrapper.client:
             print("Gemini Client inside wrapper active.")
        else:
             print("Warning: Gemini Client not active (might be expected if no key valid, but we passed test key).")

    except Exception as e:
        print(f"Gemini Init Error: {e}")
        sys.exit(1)

    print("Verification Passed.")

except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)
except Exception as e:
    print(f"General Error: {e}")
    sys.exit(1)
