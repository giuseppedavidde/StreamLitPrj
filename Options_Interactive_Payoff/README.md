# Options Interactive Payoff

App **Streamlit** per esplorare in modo interattivo il payoff di posizioni in opzioni
multi-leg, a partire da **ticker + costo/premio per leg**.

> ⚠️ **Nessuna dipendenza da LLM / AI.** Tutto gira in locale: calcolo
> Black-Scholes (scipy) + dati di mercato via **yfinance**. Nessuna chiamata AI.

## Caratteristiche

- **Input ticker**: scarica spot, scadenze disponibili e catena opzioni con yfinance.
- **Builder multi-leg**: tipo (Call/Put), direzione (Long/Short), strike, scadenza,
  quantità (contratti), **premio di carico/costo inseribile a mano** e IV per-leg.
  - Pulsante **“Precompila dal mid”**: riempie i premi dal mid della catena e
    **risolve l’IV per-strike** (replica lo skew di mercato).
- **Motore payoff generalizzato** (stessa formula dell’analisi DRAM):

  ```
  P&L(S, τ) = realized + Σ_legs [ sign · qty · mult · BS(S, K, τ, IV_leg, kind) ] − net_debit
  net_debit = Σ_legs [ sign · qty · mult · entry_premium ]
  ```

- **Output Plotly interattivi**:
  1. P&L **a scadenza** + overlay **fan chart** MTM;
  2. **Fan chart** dedicato (una curva per slice temporale da oggi a scadenza);
  3. **Superficie P&L (prezzo × tempo)** con selettore a 3 viste:
     - **Superficie 3D (matplotlib)** — immagine statica, **non richiede WebGL** *(default)*;
     - **Heatmap 2D (Plotly)** — interattiva, **non richiede WebGL**;
     - **Plotly 3D** — interattiva ma **richiede WebGL**;
  4. **Tabella P&L** sulla griglia prezzi;
  5. Pannello **livelli chiave**:
     - **Max loss (reale)** / **Max profit (reale)**: estremi *analitici* a
       scadenza su `S ∈ [0, +∞)` (punti notevoli: `S=0`, tutti gli strike,
       asintoto `S→+∞`) — **indipendenti dalla griglia**; `illimitato (±∞)`
       quando l'estremo non è limitato (net long/short call sull'ala destra).
     - **Intervallo griglia**: min/max del P&L *sulla sola griglia visualizzata*
       (mostrati nella caption sotto i metric).
     - break-even (nel range), net debit, P&L @ spot;
     - **echo degli input**: tabella dei leg effettivamente parsati (tipo,
       direzione, strike, scadenza, contratti, premio, IV) + spot/rate/
       moltiplicatore/griglia usati, con avvisi se un premio è ≤ 0 o un'IV è
       irrealistica.
     - **Greci netti** (Delta/Gamma/Theta/Vega) del portafoglio.
- Rate: da **^IRX** (yfinance) oppure input manuale.

### Nota WebGL

Le superfici 3D interattive di Plotly (`go.Surface`) richiedono **WebGL**. Se il
browser ha WebGL disabilitato/non disponibile, la vecchia vista 3D restava vuota.
Per questo il default è la superficie **matplotlib** (immagine PNG generata in
memoria, backend `Agg`) e la **heatmap 2D** Plotly è offerta come alternativa
interattiva: entrambe funzionano senza WebGL. La vista **Plotly 3D** resta
disponibile per chi ha WebGL attivo.

Il rilevamento *automatico* dell'assenza di WebGL non è implementato: Streamlit
non espone lo stato del contesto WebGL del browser all'istanza Python e un probe
JS via `components.html` girerebbe in un iframe sandbox senza un canale di
ritorno affidabile verso il server. La scelta quindi è **manuale** (radio nel
pannello), con default sicuro non-WebGL.

## Struttura

```
Options_Interactive_Payoff/
├── app.py                     # entry point Streamlit (UI + Plotly + superficie matplotlib)
├── payoff_engine.py           # motore locale: Black-Scholes, IV solver, payoff, greci
├── models.py                  # modelli Pydantic (OptionLeg, Position, PayoffConfig, ...)
├── data.py                    # accesso dati yfinance (spot, scadenze, catena, ^IRX)
├── tests/
│   ├── test_payoff_engine.py  # test offline, incluso il caso DRAM 59/70
│   └── test_plotting.py       # test superficie matplotlib + heatmap + render AppTest
├── requirements.txt
├── pyproject.toml             # config pytest + pylint
├── .gitignore
└── README.md
```

## Setup

Serve un **virtual environment** (non installare sul Python di sistema):

```bash
cd Options_Interactive_Payoff
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python -r requirements.txt
# oppure: python -m venv .venv && .venv/bin/pip install -r requirements.txt
```

## Avvio

```bash
.venv/bin/streamlit run app.py
```

## Test

```bash
.venv/bin/python -m pytest
```

I test sono **offline** e includono i casi noti:

**DRAM Bull Call Spread 59/70 (scad. 18 Dic 2026)** → max loss **+$304**, max profit
**+$1,404** (indipendenti dalla griglia), punto **$62 → +$604**.

**Short put 23 ×2 (credito 1.62, spot 23.33, scad. 15 Jan 2027)** → max loss reale
**−$4,276** (a `S=0`), max profit **+$324**; il valore resta −$4,276 qualunque sia
`price_min`/`price_max`. Il vecchio metric "Floor" mostrava invece −$1,476 / −$4,274 /
−$276 cambiando la griglia (artefatto della griglia scelta).

> Il valore **−$4,274** visto in app era quello a `price_min = 0.01` (la griglia non
> ammette `0`); il minimo analitico esatto a `S = 0` è **−$4,276**.

## Lint

```bash
.venv/bin/pylint models.py payoff_engine.py data.py app.py
```
