"""
Main entry point per l'Analista Finanziario AI (CLI Version).
Permette di scegliere il provider AI e analizzare un ticker da terminale.
"""
import os
import sys
from dotenv import load_dotenv
from agents import MarketDataAgent, GrahamAgent
from agents.ai_provider import AIProvider
from models import FinancialData

def clear_screen():
    """Pulisce la console per una migliore leggibilità."""
    os.system('cls' if os.name == 'nt' else 'clear')

def get_provider_config():
    """
    Gestisce l'interazione utente per selezionare il provider AI.
    Returns:
        tuple: (provider_code, api_key, model_name)
    """
    print("\n--- CONFIGURAZIONE CERVELLO AI ---")
    print("1. Google Gemini (Cloud - Default)")
    print("2. Ollama (Locale - Privacy)")
    print("3. Groq (Cloud - Ultra Veloce)")
    print("4. DeepSeek (Cloud - Economico)")
    
    choice = input("Seleziona [1-4]: ").strip()
    
    provider = "gemini"
    api_key = None
    model_name = None
    
    if choice == "2":
        provider = "ollama"
        models = AIProvider.get_ollama_models()
        if models:
            print("\nModelli Ollama trovati:")
            for i, m in enumerate(models, 1):
                print(f"{i}. {m}")
            
            sel = input(f"Seleziona [1-{len(models)}] o premi Invio per manuale: ").strip()
            if sel.isdigit() and 1 <= int(sel) <= len(models):
                model_name = models[int(sel)-1]
            else:
                model_name = input("Nome modello manuale (default: llama3): ").strip() or "llama3"
        else:
            model_name = input("Nome modello locale (default: llama3): ").strip() or "llama3"
    elif choice == "3":
        provider = "groq"
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
            api_key = input("Inserisci Groq API Key: ").strip()
        model_name = "llama3-70b-8192"
    elif choice == "4":
        provider = "deepseek"
        api_key = os.getenv("DEEPSEEK_API_KEY")
        if not api_key:
            api_key = input("Inserisci DeepSeek API Key: ").strip()
        model_name = "deepseek-chat"
    else:
        # Default Gemini
        provider = "gemini"
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            api_key = input("Inserisci Google API Key: ").strip()
        model_name = "gemini-pro"
            
    return provider, api_key, model_name

def main():
    """Funzione principale dell'applicazione CLI."""
    load_dotenv()
    clear_screen()
    
    print("==========================================")
    print(" 🧐 GRAHAM AI ANALYST - CLI MODE")
    print("==========================================\n")

    # 1. Configurazione
    try:
        provider, api_key, model = get_provider_config()
    except KeyboardInterrupt:
        sys.exit(0)

    while True:
        print(f"\n[{provider.upper()}] Pronto.")
        ticker = input("Inserisci Ticker (es. AAPL) o 'q' per uscire: ").strip().upper()
        
        if ticker == 'Q':
            print("Arrivederci!")
            break
            
        if not ticker:
            continue

        try:
            # 2. Inizializzazione Agente
            print("\n... Inizializzazione Agenti ...")
            market_agent = MarketDataAgent(
                api_key=api_key, 
                provider=provider, 
                model=model
            )

            # 3. Esecuzione
            # Nota: fetch_from_ticker ora stampa i log progressivi a video
            result_package = market_agent.fetch_from_ticker(ticker)

            if result_package:
                financials = result_package.get("financials")
                
                # 4. Analisi Graham
                if financials:
                    print("\n" + "="*60)
                    print(f" ⚖️ ANALISI FINALE DI BENJAMIN GRAHAM ({ticker})")
                    print("="*60)
                    
                    fin_data = FinancialData(**financials)
                    graham = GrahamAgent(fin_data)
                    report = graham.analyze()
                    print(report)
                    print("="*60)
            else:
                print("\n❌ Nessun dato recuperato.")

        except Exception as e: # pylint: disable=broad-exception-caught
            print(f"\n❌ Errore durante l'esecuzione: {e}")

if __name__ == "__main__":
    main()