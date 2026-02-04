# 💰 Gestione Budget Personale (AI-Powered)

Un'applicazione Streamlit avanzata per la gestione delle finanze personali, potenziata dall'Intelligenza Artificiale per l'importazione e la categorizzazione automatica delle spese bancarie.

## ✨ Funzionalità Principali

*   **📊 Dashboard Interattiva**: Visualizza l'andamento del Patrimonio, il Flusso di Cassa mensile e i breakdown di spesa.
*   **🤖 Importazione Banca con AI**: Carica direttamente i file PDF o CSV della tua banca. L'AI (Google Gemini) estrarrà le transazioni e le categorizzerà automaticamente.
*   **➕ Gestione Incrementale**: Aggiungi nuovi dati mese per mese senza sovrascrivere lo storico.
*   **☁️ Cloud Sync**: (Opzionale) Sincronizza il database su GitHub per backup e accesso multipiattaforma.
*   **📈 Proiezioni**: Monitora il "Totale Investito" e il "Patrimonio" con calcoli di crescita automatici.

## 🚀 Installazione

1.  **Clona il repository**:
    ```bash
    git clone https://github.com/tuo-username/Budget_App.git
    cd Budget_App
    ```

2.  **Crea un Virtual Environment** (raccomandato):
    ```bash
    python -m venv .venv
    # Windows
    .venv\Scripts\activate
    # Mac/Linux
    source .venv/bin/activate
    ```

3.  **Installa le dipendenze**:
    ```bash
    pip install -r requirements.txt
    ```

## 🔑 Configurazione API Key (AI)

Per sfruttare l'importazione automatica (e specialmente la lettura dei PDF), l'app utilizza i modelli generativi di Google (Gemini).

### 1. Ottieni la tua API Key
Vai su **Google AI Studio** per generare una chiave gratuita:
👉 **[Ottieni Google Gemini API Key qui](https://aistudio.google.com/app/apikey)**

### 2. Imposta la Chiave nel Progetto
Hai due modi per inserire la chiave:

*   **Metodo A: File `.env` (Consigliato per sviluppo)**
    Crea un file chiamato `.env` nella cartella principale e aggiungi:
    ```env
    GOOGLE_API_KEY="la-tua-chiave-qui"
    ```
    *L'app caricherà automaticamente la chiave all'avvio.*

*   **Metodo B: Inserimento da Interfaccia**
    Nella sidebar dell'applicazione, vai su **"💬 Assistant AI"** o apri il menu **"🤖 Configurazione AI"**. Incolla la tua chiave nell'apposito campo e premi Invio.

### 🔌 Alternativa Locale (Ollama)
L'app supporta anche modelli locali tramite Ollama (es. Llama 3). 
*   Assicurati di avere [Ollama](https://ollama.com/) installato e in esecuzione (`ollama serve`).
*   Configura il provider su "Ollama" dalla sidebar.

## 📱 Guida all'Uso

### 1. Dashboard
All'apertura, vedrai una panoramica completa.
*   **Filtri Temporali**: Usa la sidebar per cambiare l'orizzonte temporale (es. ultimi 3, 6, 12 mesi).
*   **Indicatori**: "Patrimonio Totale" e "Totale Investito" mostrano la tua ricchezza attuale.

### 2. Importazione Dati (Gestione Mese)
1.  Vai alla sezione **"Gestione Mese"**.
2.  Apri il pannello **"📂 Importa da Estratto Conto Banca (AI)"**.
3.  Trascina il tuo estratto conto (**PDF** o CSV).
4.  Clicca su **"🚀 Analizza e Categorizza"**.
5.  Attendi che l'AI legga il file.
6.  Controlla la tabella dei risultati. Se necessario, correggi le categorie errate dal menu a tendina.
7.  Clicca **"Salva Modifiche"** per archiviare il mese.


