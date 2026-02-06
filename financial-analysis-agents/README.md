# Financial Analysis Agents

A Python-based framework for financial analysis using **Benjamin Graham's principles** from *"Reading and Understanding Financial Statements"*. The project leverages AI (Google Gemini) to extract and structure financial data from raw text, then applies Graham's analytical methods to evaluate stocks.

## 📋 Features

- **Graham Analysis Agent**: Implements Graham's "Multiple Method" from Part 2 of his book, calculating key financial ratios and metrics
- **Data Builder Agent**: Uses Google Gemini API to intelligently extract and structure financial data from raw balance sheet text
- **Market Data Agent**: Fetches real financial data from Yahoo Finance and structures it using AI
- **Multiple Input Modes**:
  - Analyze pre-loaded JSON files from the `/data` folder
  - Manually input raw financial data and let AI extract values
  - Download ticker data from Yahoo Finance and analyze automatically
- **Type-Safe Data Schema**: Standardized `FinancialData` dataclass with automatic post-initialization validation

## 🎯 Project Structure

```
financial-analysis-agents/
├── agents/                 # Agent implementations
│   ├── __init__.py
│   ├── graham.py           # Benjamin Graham analysis engine
│   ├── builder.py          # AI-powered data extraction
│   └── market_data.py      # Yahoo Finance integration
│
├── models/                 # Data structures
│   ├── __init__.py
│   └── data_schema.py      # FinancialData dataclass with validation
│
├── data/                   # Sample input files
│   └── example_company.json
│
├── utils/                  # Helper functions
│   ├── __init__.py
│   └── loader.py           # JSON file loading utilities
│
├── .gitignore              # Git ignore rules
├── main.py                 # Main entry point
├── README.md               # This file
└── requirements.txt        # Python dependencies
```

## 🧩 Agents (Componenti e Scopi)

Questa sezione descrive ciascun `agent` presente nella cartella `agents/`, il suo scopo, gli input attesi, l'output e note operative importanti.

- `GrahamAgent`
  - Scopo: Esegue l'analisi finanziaria secondo i principi di Benjamin Graham (margini, copertura interessi, liquidità, P/E, P/B, ecc.).
  - Input: un oggetto `FinancialData` (dataclass) con i valori contabili e di mercato.
  - Output: report testuale o struttura con i principali indicatori e un verdict sintetico.
  - Note: I parametri soglia (es. interessi copertura, percentuale di debito) sono facilmente adattabili direttamente in `agents/graham.py`.

- `DataBuilderAgent`
  - Scopo: Estrarre e normalizzare dati finanziari da testo grezzo (bilanci, sezioni MD&A, tabelle) usando il provider AI.
  - Input: stringa di testo grezzo (o dossier generato da `MarketDataAgent`).
  - Output: dizionario compatibile con il costruttore `FinancialData` (es. `asdict(FinancialData(...))`).
  - Note: Implementa regole precise per `long_term_debt` e `total_liabilities` e salva i file JSON in `/data`.

- `MarketDataAgent`
  - Scopo: Coordinatore (facade) per il flusso completo: download dati (Yahoo Finance) → summary AI → build dati → review → eventuale cross-check.
  - Input: ticker (es. `AAPL`) e (opzionalmente) `GOOGLE_API_KEY` per chiamate AI.
  - Output: dizionario finale dei dati finanziari validati (pronto per `FinancialData`).
  - Note: Integra `SummaryAgent`, `DataBuilderAgent`, `ReviewAgent`, `ETFFinderAgent`, `CrossCheckAgent` per produrre un dossier robusto.

- `SummaryAgent`
  - Scopo: Generare un riassunto qualitativo e discorsivo del dossier finanziario (ruolo di "narratore").
  - Input: testo/dossier finanziario.
  - Output: stringa riassuntiva (max ~12 righe) focalizzata su business, trend utili, dividendi, salute finanziaria.

- `ReviewAgent` (AuditAgent)
  - Scopo: Eseguire un audit interno dei campi critici (policy "Zero Trust"). Segnala campi sospetti da validare.
  - Input: `ticker` e oggetto `FinancialData`.
  - Output: tupla `(report_text, suspicious_fields)` dove `suspicious_fields` è una lista di nomi di campi da verificare.
  - Note: Fornisce la lista di campi che devono essere passati al `CrossCheckAgent`.

- `CrossCheckAgent`
  - Scopo: Validazione incrociata ibrida: usa `FinvizAgent` (dati strutturati) e, se necessario, ricerche web per confermare/correggere campi critici.
  - Input: `ticker`, dati originali, lista di campi da controllare.
  - Output: dizionario con correzioni suggerite per i campi verificati.

- `ETFFinderAgent`
  - Scopo: Individuare ETF che detengono il titolo dato; combina stime AI con dati reali (Yahoo) per stimare esposizione.
  - Input: `ticker`, `sector` (opzionale).
  - Output: lista di dizionari `{etf_ticker, etf_name, total_aum, weight_percentage, category}`.

- `FinvizAgent`
  - Scopo: Recuperare dati fondamentali strutturati (P/E, Total Debt, Book/sh, Dividend, ecc.) da Finviz come fonte primaria per il cross-check.
  - Input: `ticker`.
  - Output: dizionario con campi fondamentali mappati.

- `AIProvider` / `ai_provider.py`
  - Scopo: Wrapper per inizializzare e fornire accesso ai modelli AI (es. Google Gemini). Centralizza creazione di modelli in `json_mode` o `text`.
  - Note: Usato da molti agent (DataBuilder, Summary, Review, CrossCheck, ETFFinder) per mantenere coerenza nelle chiamate.

Se desideri un esempio d'uso programmatico rapido per testare un singolo agent:

```python
from agents import DataBuilderAgent

builder = DataBuilderAgent(api_key='YOUR_KEY')
raw = open('data/example_company.json').read()  # o testo grezzo
result = builder.build_from_text(raw)
print(result)
```

Questo flusso viene orchestrato automaticamente da `MarketDataAgent` se usi la modalità ticker in `main.py`.

## 🔍 Esempi di Output

Di seguito alcuni esempi sintetici di output che potresti vedere durante l'esecuzione degli agent.

- Esempio di report sintetico prodotto da `GrahamAgent`:

```
--- GRAHAM ANALYSIS REPORT: ACME Corp. ---
Profit Margin: 12.5% (Operating Income / Sales)
Interest Coverage: 6.2x (Operating Income / Interest Charges)
Current Ratio: 1.8 (Current Assets / Current Liabilities)
Quick Ratio: 1.2 ((Current Assets - Inventory) / Current Liabilities)
Book Value / Share: $42.15
Price-to-Book: 1.8
Debt Ratio: 22.5% (Total Liabilities / Capitalization)
P/E Ratio: 13.7
Earnings Yield: 7.3%

Verdict: INVESTIMENTO CONSERVATIVO - Margine di sicurezza accettabile, debito sotto controllo.
Recommendations: Monitorare trend utili trimestrali e confermare long_term_debt via CrossCheckAgent.
```

- Esempio di output da `DataBuilderAgent` (dizionario JSON-ready):

```json
{
  "total_assets": 125000000.0,
  "current_assets": 45000000.0,
  "current_liabilities": 25000000.0,
  "inventory": 5000000.0,
  "intangible_assets": 2000000.0,
  "total_liabilities": 55000000.0,
  "long_term_debt": 12000000.0,
  "preferred_stock": 0.0,
  "common_stock": 30000000.0,
  "surplus": 5000000.0,
  "sales": 98000000.0,
  "operating_income": 12250000.0,
  "net_income": 9000000.0,
  "interest_charges": 200000.0,
  "preferred_dividends": 0.0,
  "shares_outstanding": 1000000.0,
  "current_market_price": 85.0
}
```

## 🧩 Estendere / Creare un Nuovo Agent (Template)

Per aggiungere un nuovo `agent` segui questa procedura consigliata e usa il template minimale qui sotto.

1. Crea un nuovo file in `agents/` (es. `my_agent.py`).
2. Implementa una classe con un'interfaccia chiara: `__init__(...)`, metodi pubblici come `run(...)` o `process(...)`.
3. Documenta input, output e possibili eccezioni nel docstring della classe.
4. Aggiorna `agents/__init__.py` per esportare il nuovo agent (aggiungilo a `__all__`).
5. Aggiungi test unitari in una cartella `tests/` (es. `tests/test_my_agent.py`).

Template minimale per un nuovo agent:

```python
"""Esempio di nuovo Agent minimale."""
from typing import Optional, Any

class MyAgent:
  """
  Scopo: descrivi brevemente lo scopo dell'agent.

  Input: descrivi l'input atteso.
  Output: descrivi l'output prodotto.
  """

  def __init__(self, api_key: Optional[str] = None):
    # Configurazioni e inizializzazione del provider AI / risorse
    self.api_key = api_key

  def run(self, payload: Any) -> Optional[Any]:
    """Esegui l'operazione principale dell'agent.

    - Valida l'input
    - Esegui trasformazioni
    - Restituisci un oggetto JSON-serializzabile o None in caso di errore
    """
    try:
      # Logica principale
      result = {"status": "ok", "data": payload}
      return result
    except (ValueError, TypeError) as e:
      # Gestisci errori previsti
      print(f"Errore durante l'esecuzione di MyAgent: {e}")
      return None
    except Exception:
      # Non sopprimere eccezioni generiche: rialza dopo logging
      raise
```

Consigli pratici:
- Preferisci eccezioni specifiche invece di `except Exception`.
- Aggiungi logging (modulo `logging`) invece di `print` per produzione.
- Scrivi test che coprano casi buoni e casi di errore.
- Mantieni input/output JSON-serializzabili per facilità di persistenza e cross-check.

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Git
- Google API Key (for AI-powered data extraction)

### 1. Clone and Setup

```bash
# Clone the repository
git clone https://github.com/giuseppedavidde/MyGITprj.git
cd MyGITprj/financial-analysis-agents

# Create a virtual environment
python -m venv venv

# Activate virtual environment
# On Windows:
venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate

# Install dependencies
pip install --upgrade pip
pip install -r requirements.txt
```

### 2. Configure Google API Key

Create a `.env` file in the project root:

```bash
# .env
GOOGLE_API_KEY=your_google_api_key_here
```

**How to get a Google API Key:**
1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable the **Generative AI API**
4. Create an API key in the credentials section
5. Copy and paste it into your `.env` file

### 3. Run the Application

```bash
python main.py
```

You'll see an interactive menu:

```
1. Analyze local JSON file (from /data folder)
2. Build data manually (paste raw financial text)
3. Download ticker data (Yahoo Finance + AI analysis)
```

## 📖 Usage Modes

### Mode 1: Analyze Local JSON Files

1. Place a JSON file in the `data/` folder (e.g., `apple.json`)
2. Run `python main.py` and select option **1**
3. Choose the file to analyze
4. View the Graham analysis report

**Example JSON file structure** (`data/example_company.json`):
```json
{
  "total_assets": 352755000000.0,
  "current_assets": 135405000000.0,
  "current_liabilities": 105718000000.0,
  "inventory": 2608000000.0,
  "intangible_assets": 0.0,
  "total_liabilities": 302096000000.0,
  "preferred_stock": 0.0,
  "common_stock": 73993000000.0,
  "surplus": -23334000000.0,
  "sales": 383285000000.0,
  "operating_income": 119505000000.0,
  "net_income": 96995000000.0,
  "interest_charges": 2645000000.0,
  "preferred_dividends": 0.0,
  "shares_outstanding": 15728000000.0,
  "current_market_price": 234.5
}
```

### Mode 2: Manual Data Entry with AI

1. Run `python main.py` and select option **2**
2. Paste raw financial statement text (from annual reports, financial websites, etc.)
3. The AI will extract and structure the data automatically
4. Optionally save the structured data as JSON for future analysis
5. Run Graham analysis immediately or later

### Mode 3: Yahoo Finance + AI Analysis

1. Run `python main.py` and select option **3**
2. Enter a stock ticker symbol (e.g., `AAPL`, `TSLA`, `GME`)
3. The app will:
   - Fetch financial data from Yahoo Finance
   - Structure it using Google Gemini AI
   - Run Graham's analysis automatically
   - Display the full report

## 📊 Graham Analysis Metrics

The `GrahamAgent` computes the following financial ratios based on Graham's methodology:

| Metric | Description | Graham's Reference |
|--------|-------------|-------------------|
| **Profit Margin** | Operating income / Sales | Part 2, Chapter 14 |
| **Interest Coverage** | Operating income / Interest charges | Minimum 2.5x–3x |
| **Current Ratio** | Current assets / Current liabilities | Minimum 2:1 for industrial |
| **Quick Ratio** | (Current assets - Inventory) / Current liabilities | Target 1:1 |
| **Book Value per Share** | (Equity - Intangible assets) / Shares | Ch. 21 |
| **Price-to-Book** | Market price / Book value | Indicator of safety margin |
| **Debt Ratio** | Total liabilities / Capitalization | Max 25–30% debt |
| **P/E Ratio** | Market price / EPS | Graham: < 15 for stable |
| **Earnings Yield** | EPS / Market price | Bond-equivalent comparison |

## 🛠️ Development

### Install Development Tools

The `requirements.txt` includes:
- **black**: Code formatting
- **flake8**: Linting and style checks
- **mypy**: Static type checking
- **pytest**: Unit testing framework

### Format and Lint Code

```bash
# Format with black
black .

# Check with flake8
flake8 .

# Type check with mypy
mypy agents models utils main.py
```

### Run Tests

```bash
pytest
```

## 🔐 Security & Best Practices

- **API Keys**: Store in `.env` file, never commit to git (see `.gitignore`)
- **Large Data Files**: CSV/XLS files and archives are ignored by default
- **Sensitive Data**: Remove personal financial data before committing
- **Error Handling**: All agent exceptions are caught with specific error types (not generic `Exception`)

## 📝 Configuration

### Environment Variables (`.env`)

```
GOOGLE_API_KEY=your_api_key_here
```

### Customizing Graham's Thresholds

Edit `agents/graham.py` to adjust Graham's minimum ratios:
- Interest coverage threshold (line ~40)
- Debt ratio limits (line ~70)
- P/E ratio cutoffs (line ~85)

## 🐛 Troubleshooting

| Issue | Solution |
|-------|----------|
| `GOOGLE_API_KEY not found` | Ensure `.env` file exists in project root with your API key |
| `Module not found` | Run `pip install -r requirements.txt` and ensure virtual env is activated |
| `Yahoo Finance timeout` | Check internet connection; ticker symbol might be invalid |
| `JSON parsing error` | Validate JSON syntax in `/data` folder with [jsonlint.com](https://jsonlint.com) |

## 📚 References

- **Book**: Benjamin Graham, *"Reading and Understanding Financial Statements"*
- **API**: [Google Generative AI](https://ai.google.dev/)
- **Data**: [Yahoo Finance](https://finance.yahoo.com/)

## 📄 License

This project is part of the MyGITprj repository. Check the main repository for license details.

## 👤 Author

Davidde Giuseppe ([@giuseppedavidde](https://github.com/giuseppedavidde))

---

**Last Updated**: December 2, 2025
