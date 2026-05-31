"""IBKR Tax Calculator — Streamlit Dashboard with AI Agent integration."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import io
import os
import datetime
import json
from fpdf import FPDF

from dotenv import load_dotenv
from ecb_fx import fetch_ecb_rate_range, fetch_ecb_rate_for_date

load_dotenv()

CURRENCY_SYMBOLS = {
    "EUR": "€", "USD": "$", "GBP": "£", "JPY": "¥", "CHF": "₣",
    "CAD": "C$", "AUD": "A$", "SEK": "kr", "NOK": "kr", "DKK": "kr",
    "PLN": "zł", "CZK": "Kč", "HUF": "Ft", "SGD": "S$", "HKD": "HK$",
    "NZD": "NZ$", "MXN": "Mex$", "ZAR": "R", "CNY": "¥", "INR": "₹",
}

BASE_CURRENCIES = sorted(CURRENCY_SYMBOLS.keys())

try:
    from agents import TraderAgent
    from agents.ai_provider import AIProvider
except ImportError:
    TraderAgent = None
    AIProvider = None

st.set_page_config(page_title="IBKR Tax Calculator", layout="wide", page_icon="📊")

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "parsed_data" not in st.session_state:
    st.session_state.parsed_data = None
# Cache for ECB FX rates: nested dict currency -> {date: rate}
if "fx_cache" not in st.session_state:
    st.session_state.fx_cache = {}
# Auto-detect base currency from CSV (only once, before widget creation)
if "base_currency_detected" not in st.session_state:
    st.session_state.base_currency_detected = False
if st.session_state.parsed_data is not None and not st.session_state.base_currency_detected:
    _csv = st.session_state.parsed_data.get("account_info", {}).get("Valuta di base", "")
    if _csv and _csv in BASE_CURRENCIES:
        st.session_state.base_currency = _csv
    st.session_state.base_currency_detected = True
if "base_currency" not in st.session_state:
    st.session_state.base_currency = "EUR"


def create_pdf_report(report_data, country="🇦🇹 Austria"):
    """Generate a professional PDF report for fiscal summary (country-aware)."""
    pdf = FPDF()
    pdf.add_page()

    is_at = "Austria" in country
    pdf.set_font("Arial", "B", 18)
    title = "IBKR Tax Statement - E1kv (Austria)" if is_at else "IBKR Tax Statement - Quadro RT (Italia)"
    pdf.cell(0, 15, title, ln=True, align="C")
    pdf.ln(5)

    pdf.set_font("Arial", "I", 12)
    pdf.cell(0, 10, f"Generated on: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", ln=True, align="C")
    pdf.ln(10)

    pdf.set_font("Arial", "B", 14)
    pdf.set_fill_color(240, 240, 240)
    pdf.cell(0, 10, "Summary Data", ln=True, fill=True)
    pdf.ln(5)

    pdf.set_font("Arial", "", 11)
    for key, value in report_data.items():
        val_str = f"{value:,.2f}" if isinstance(value, float) else str(value)
        pdf.set_font("Arial", "B", 11)
        pdf.cell(80, 8, f"{key}:", border="B")
        pdf.set_font("Arial", "", 11)
        pdf.cell(0, 8, val_str, border="B", ln=True, align="R")

    pdf.ln(20)
    pdf.set_font("Arial", "I", 9)
    disclaimer = (
        "Disclaimer: This report is automatically generated based on the provided IBKR CSV and ECB "
        "exchange rates. It is intended for informational purposes and should be reviewed by a "
        "qualified tax advisor before submission to the competent tax authorities."
    ) if is_at else (
        "Disclaimer: Il presente report è generato automaticamente sulla base dei dati IBKR e dei "
        "tassi di cambio BCE. Ha valore puramente informativo e deve essere verificato da un "
        "commercialista o consulente fiscale abilitato prima del versamento dell'imposta sostitutiva "
        "e della presentazione del Quadro RT/RW."
    )
    pdf.multi_cell(0, 5, disclaimer)

    return bytes(pdf.output())


# ─── ECB FX helpers ─────────────────────────────────────────────────────────

def _get_cached_rate(currency: str, trade_date: datetime.date) -> float:
    """Return cached ECB rate for a currency/date, or 1.0 as fallback."""
    cache = st.session_state.fx_cache
    ccy = currency.upper()
    if ccy == "EUR":
        return 1.0
    ccy_cache = cache.get(ccy, {})
    if trade_date in ccy_cache:
        return ccy_cache[trade_date]
    prior = [d for d in ccy_cache if d <= trade_date]
    if prior:
        return ccy_cache[max(prior)]
    return 1.0


def enrich_trades_base(data: dict, base_currency: str) -> None:
    """Batch-fetch ECB rates for all foreign trade currencies and add base-currency columns.

    Modifies `data['trades']` in-place, adding:
      - fx_rate          : trade_currency per 1 base_currency (rate used for conversion)
      - fx_rate_date     : actual ECB publication date for the rate
      - realized_pl_base : realized_pl converted to base_currency
      - commission_base  : commission converted to base_currency
      - proceeds_base    : proceeds converted to base_currency
      - cost_basis_base  : cost_basis converted to base_currency

    Also converts interest rows to base currency using ECB rates and stores
    `interests_total_base` in data.

    Items already in base_currency are left unchanged (rate = 1.0).
    """
    trades = data.get("trades", [])
    interests = data.get("interests", [])
    base = base_currency.upper()

    # Collect unique (currency, date) pairs where currency != base
    foreign_pairs: dict[str, set[datetime.date]] = {}
    for t in trades:
        ccy = t.get("currency", base).upper()
        if ccy != base:
            try:
                dt = datetime.date.fromisoformat(str(t["datetime"])[:10])
                foreign_pairs.setdefault(ccy, set()).add(dt)
            except ValueError:
                pass
    for i in interests:
        ccy = i.get("currency", base).upper()
        if ccy != base:
            try:
                dt = datetime.date.fromisoformat(str(i["date"])[:10])
                foreign_pairs.setdefault(ccy, set()).add(dt)
            except ValueError:
                pass

    # Fetch ECB rates for each foreign currency (all against EUR)
    ccy_rates: dict[str, dict[datetime.date, float]] = {}
    for ccy, dates in foreign_pairs.items():
        if ccy == "EUR":
            continue
        min_date = min(dates) - datetime.timedelta(days=10)
        max_date = max(dates)
        rate_map = fetch_ecb_rate_range(ccy, min_date, max_date)
        if rate_map:
            sorted_dates = sorted(rate_map.keys())
            date_to_rate = {}
            for d in sorted(dates):
                candidates = [rd for rd in sorted_dates if rd <= d]
                if candidates:
                    chosen = max(candidates)
                    date_to_rate[d] = (rate_map[chosen], chosen)
                else:
                    date_to_rate[d] = (1.0, d)
            ccy_rates[ccy] = date_to_rate
            # Persist into session cache
            cache_ccy = st.session_state.fx_cache.setdefault(ccy, {})
            for d, (rate, _) in date_to_rate.items():
                cache_ccy[d] = rate

    # ECB rate for base currency (always 1.0 since ECB gives X per EUR)
    # Cross-rate formula: amount_base = amount_trade * (ecb_rate[base] / ecb_rate[trade])
    # Since ecb_rate[base] = ECB rate for base (1.0 if base=EUR),
    # amount_base = amount_trade / (ecb_rate[trade] / ecb_rate[base])
    # We store fx_rate = ecb_rate[trade] / ecb_rate[base] (trade per base)

    # Annotate each trade
    for t in trades:
        currency = t.get("currency", base).upper()
        if currency == base:
            t["fx_rate"] = 1.0
            t["fx_rate_date"] = None
            t["realized_pl_base"] = t["realized_pl"]
            t["commission_base"] = t["commission"]
            t["proceeds_base"] = t["proceeds"]
            t["cost_basis_base"] = t["cost_basis"]
            continue
        try:
            dt = datetime.date.fromisoformat(str(t["datetime"])[:10])
        except ValueError:
            dt = None
        rate_val: float | None = None
        rate_date: datetime.date | None = None
        if dt and currency in ccy_rates and dt in ccy_rates[currency]:
            rate_val, rate_date = ccy_rates[currency][dt]
        if rate_val is None:
            rate_val, rate_date = 1.0, None

        # Compute cross-rate: trade_currency per 1 base_currency
        ecb_rate_base = _get_cached_rate(base, dt) if dt else 1.0
        ecb_rate_trade = rate_val
        cross_rate = ecb_rate_trade / ecb_rate_base if ecb_rate_base else 1.0

        t["fx_rate"] = cross_rate
        t["fx_rate_date"] = rate_date
        t["realized_pl_base"] = t["realized_pl"] / cross_rate if cross_rate else t["realized_pl"]
        t["commission_base"] = t["commission"] / cross_rate if cross_rate else t["commission"]
        t["proceeds_base"] = t["proceeds"] / cross_rate if cross_rate else t["proceeds"]
        t["cost_basis_base"] = t["cost_basis"] / cross_rate if cross_rate else t["cost_basis"]

    # Convert interest rows to base currency using ECB rates
    total_base = 0.0
    for i in interests:
        currency = i.get("currency", base).upper()
        if currency == base:
            i["amount_base"] = i["amount"]
        else:
            try:
                dt = datetime.date.fromisoformat(str(i.get("date", ""))[:10])
            except (ValueError, TypeError):
                dt = None
            rate_val_i = _get_cached_rate(currency, dt) if dt else 1.0
            ecb_rate_base_i = _get_cached_rate(base, dt) if dt else 1.0
            cross_rate_i = rate_val_i / ecb_rate_base_i if ecb_rate_base_i else 1.0
            i["amount_base"] = i["amount"] / cross_rate_i if cross_rate_i else i["amount"]
        total_base += i["amount_base"]
    data["interests_total_base"] = round(total_base, 2)


# ─── CSV Parser ─────────────────────────────────────────────────────────────

def parse_ibkr_csv(file) -> dict:
    """Parse IBKR activity statement CSV into structured sections."""
    content = file.read().decode("utf-8") if hasattr(file, "read") else open(file, "r", encoding="utf-8").read()
    lines = content.strip().split("\n")

    data = {
        "account_info": {},
        "nav": [],
        "nav_change": {},
        "mtm_summary": [],
        "realized_unrealized": [],
        "trades": [],
        "open_positions": [],
        "deposits": [],
        "commissions": [],
        "forex_trades": [],
        "total_pl": None,
        "instrument_info": {},
        "interests": [],
        "interests_total_eur": 0.0,
        "interests_total_base": 0.0,
    }

    for line in lines:
        # Use csv reader for proper comma handling inside quotes
        import csv
        row = next(csv.reader(io.StringIO(line)))
        section = row[0].strip() if row else ""
        discriminator = row[1].strip() if len(row) > 1 else ""

        # Account Info
        if section == "Dati del conto" and discriminator == "Data":
            key = row[2].strip() if len(row) > 2 else ""
            val = row[3].strip() if len(row) > 3 else ""
            data["account_info"][key] = val

        # NAV
        elif section == "Valore patrimoniale netto" and discriminator == "Data":
            if len(row) >= 7:
                try:
                    data["nav"].append({
                        "asset_class": row[2].strip(),
                        "previous_total": _safe_float(row[3]),
                        "long_current": _safe_float(row[4]),
                        "short_current": _safe_float(row[5]),
                        "current_total": _safe_float(row[6]),
                        "change": _safe_float(row[7]) if len(row) > 7 else 0,
                    })
                except (ValueError, IndexError):
                    pass

        # NAV Change
        elif section == "Variazione del VPN" and discriminator == "Data":
            key = row[2].strip() if len(row) > 2 else ""
            val = row[3].strip() if len(row) > 3 else ""
            data["nav_change"][key] = _safe_float(val)

        # MTM P/L Summary
        elif section == "Sommario profitti e perdite Mark to market" and discriminator == "Data":
            if len(row) >= 13 and row[2].strip() not in ("Totale", "Totale (tutti i prodotti)",
                                                           "Interessi broker pagati e ricevuti",
                                                           "Altre commissioni"):
                if row[3].strip():  # has symbol
                    data["mtm_summary"].append({
                        "asset_type": row[2].strip(),
                        "symbol": row[3].strip(),
                        "prev_qty": _safe_float(row[4]),
                        "curr_qty": _safe_float(row[5]),
                        "mtm_position": _safe_float(row[8]),
                        "mtm_transaction": _safe_float(row[9]),
                        "mtm_commissions": _safe_float(row[10]),
                        "mtm_total": _safe_float(row[12]),
                    })

        # Realized / Unrealized P/L
        elif section == "Sommario profitti e perdite Realizzati e Non realizzati" and discriminator == "Data":
            if len(row) >= 16 and row[2].strip() not in ("Totale", "Totale (tutti i prodotti)"):
                if row[3].strip():
                    data["realized_unrealized"].append({
                        "asset_type": row[2].strip(),
                        "symbol": row[3].strip(),
                        "cost_adj": _safe_float(row[4]),
                        "realized_profit_st": _safe_float(row[5]),
                        "realized_loss_st": _safe_float(row[6]),
                        "realized_profit_lt": _safe_float(row[7]),
                        "realized_loss_lt": _safe_float(row[8]),
                        "realized_total": _safe_float(row[9]),
                        "unrealized_profit_st": _safe_float(row[10]),
                        "unrealized_loss_st": _safe_float(row[11]),
                        "unrealized_total": _safe_float(row[14]),
                        "total": _safe_float(row[15]),
                    })

        # Trade Details
        elif section == "Dettaglio eseguiti" and discriminator == "Data":
            if len(row) >= 15 and row[2].strip() == "Order":
                asset_type = row[3].strip()
                if asset_type == "Forex":
                    data["forex_trades"].append({
                        "symbol": row[5].strip(),
                        "datetime": row[6].strip(),
                        "quantity": _safe_float(row[7]),
                        "price": _safe_float(row[8]),
                        "proceeds": _safe_float(row[10]),
                        "commission": _safe_float(row[11]),
                    })
                else:
                    data["trades"].append({
                        "asset_type": asset_type,
                        "currency": row[4].strip(),
                        "symbol": row[5].strip(),
                        "datetime": row[6].strip(),
                        "quantity": _safe_float(row[7]),
                        "price": _safe_float(row[8]),
                        "close_price": _safe_float(row[9]),
                        "proceeds": _safe_float(row[10]),
                        "commission": _safe_float(row[11]),
                        "cost_basis": _safe_float(row[12]),
                        "realized_pl": _safe_float(row[13]),
                        "mtm_pl": _safe_float(row[14]),
                        "code": row[15].strip() if len(row) > 15 else "",
                    })

        # Open Positions
        elif section == "Posizioni aperte" and discriminator == "Data":
            if len(row) >= 13 and row[2].strip() == "Summary":
                data["open_positions"].append({
                    "asset_type": row[3].strip(),
                    "currency": row[4].strip(),
                    "symbol": row[5].strip(),
                    "quantity": _safe_float(row[6]),
                    "multiplier": _safe_float(row[7]),
                    "cost_price": _safe_float(row[8]),
                    "cost_basis": _safe_float(row[9]),
                    "close_price": _safe_float(row[10]),
                    "value": _safe_float(row[11]),
                    "unrealized_pl": _safe_float(row[12]),
                })

        # Deposits
        elif section == "Versamenti e prelievi" and discriminator == "Data":
            if len(row) >= 6 and row[2].strip() != "Totale":
                data["deposits"].append({
                    "currency": row[2].strip(),
                    "date": row[3].strip(),
                    "description": row[4].strip(),
                    "amount": _safe_float(row[5]),
                })

        # Total P/L
        elif section == "P/L totale per il periodo del rendiconto":
            if len(row) >= 13:
                data["total_pl"] = _safe_float(row[12])

        # Instrument Info (ISIN)
        elif section == "Informazioni sullo strumento finanziario" and discriminator == "Data":
            atype = row[2].strip() if len(row) > 2 else ""
            symbol = row[3].strip() if len(row) > 3 else ""
            if atype == "Opzioni su indici e su azioni" or not symbol:
                pass  # no ISIN for options
            elif len(row) >= 7:
                isin = row[5].strip()
                if isin and len(isin) >= 10:
                    data["instrument_info"][symbol] = isin

        # Interests
        elif section == "Interessi" and discriminator == "Data":
            currency = row[2].strip() if len(row) > 2 else ""
            if currency == "Totale in EUR":
                val = _safe_float(row[4]) if len(row) > 4 else 0.0
                data["interests_total_eur"] = val
                data["interests_total_base"] = val
            elif currency and currency != "Totale":
                data["interests"].append({
                    "currency": currency,
                    "date": row[3].strip() if len(row) > 3 else "",
                    "description": row[4].strip() if len(row) > 4 else "",
                    "amount": _safe_float(row[5]) if len(row) > 5 else 0,
                })

    return data


def _safe_float(val) -> float:
    """Convert string to float, returning 0 for non-numeric values."""
    if isinstance(val, (int, float)):
        return float(val)
    try:
        cleaned = str(val).strip().replace(",", "").replace("%", "").replace("--", "0")
        return float(cleaned) if cleaned else 0.0
    except (ValueError, TypeError):
        return 0.0


# ─── AI Chat ────────────────────────────────────────────────────────────────

def _build_tax_context(data: dict) -> str:
    """Build a text summary of fiscal data for the AI."""
    lines = []
    # Account
    acc = data.get("account_info", {})
    lines.append(f"ACCOUNT: {acc.get('Nome', 'N/A')} | {acc.get('Conto', 'N/A')} | Base: {acc.get('Valuta di base', 'EUR')}")
    lines.append("")

    # NAV
    lines.append("═══ NET ASSET VALUE ═══")
    for item in data.get("nav", []):
        lines.append(f"  {item['asset_class']}: Previous={item['previous_total']:.2f} → Current={item['current_total']:.2f} (Δ {item['change']:+.2f})")

    # NAV Change
    nav_chg = data.get("nav_change", {})
    if nav_chg:
        lines.append("")
        lines.append("═══ NAV CHANGE BREAKDOWN ═══")
        for k, v in nav_chg.items():
            lines.append(f"  {k}: {v:+.2f}")

    base = st.session_state.get("base_currency", "EUR")
    symbol = CURRENCY_SYMBOLS.get(base, "€")

    # Total P/L
    if data.get("total_pl") is not None:
        lines.append(f"\n═══ TOTAL P/L FOR PERIOD: {data['total_pl']:+.2f} {base} ═══")

    # Realized/Unrealized
    rl = data.get("realized_unrealized", [])
    if rl:
        lines.append("\n═══ REALIZED & UNREALIZED P/L ═══")
        for r in rl:
            lines.append(f"  {r['asset_type']} | {r['symbol']}: Realized={r['realized_total']:+.2f} | Unrealized={r['unrealized_total']:+.2f} | Total={r['total']:+.2f}")

    # Trades — show both original and base-currency converted values
    trades = data.get("trades", [])
    if trades:
        lines.append(f"\n═══ TRADES ({len(trades)} total) — P/L converted to {base} using ECB rates ═══")
        for t in trades:
            side = "BUY" if t["quantity"] > 0 else "SELL"
            pl_base = t.get("realized_pl_base", t["realized_pl"])
            fx = t.get("fx_rate", 1.0)
            comm_base = t.get("commission_base", t["commission"])
            lines.append(
                f"  {t['datetime']} | {side} {abs(t['quantity']):.4f} {t['symbol']} @ {t['price']:.4f} {t['currency']} | "
                f"P/L={t['realized_pl']:+.2f} {t['currency']} ({pl_base:+.2f} {base} @ {fx:.4f}) | "
                f"Comm={t['commission']:.2f} {t['currency']} ({comm_base:.2f} {base}) | Code={t['code']}"
            )

    # Open Positions
    op = data.get("open_positions", [])
    if op:
        lines.append(f"\n═══ OPEN POSITIONS ({len(op)}) ═══")
        for p in op:
            lines.append(
                f"  {p['symbol']}: Qty={p['quantity']:.4f} | Cost={p['cost_basis']:.2f} | Value={p['value']:.2f} | "
                f"Unrealized P/L={p['unrealized_pl']:+.2f} {p['currency']}"
            )

    # Deposits
    deps = data.get("deposits", [])
    if deps:
        total_dep = sum(d["amount"] for d in deps)
        lines.append(f"\n═══ DEPOSITS: {total_dep:,.2f} {base} ({len(deps)} transfers) ═══")

    return "\n".join(lines)


def _chat_with_ai(user_message: str, data: dict) -> str:
    """Send a message to the AI with full fiscal context."""
    if not TraderAgent:
        return "⚠️ AI Agent non disponibile (modulo `agents` non trovato). Installa `custom_agents`."

    context = _build_tax_context(data)
    provider_type = st.session_state.get("ai_provider", "gemini")
    model_name = st.session_state.get("ai_model_name")

    agent = TraderAgent(provider_type=provider_type, model_name=model_name)

    history_text = ""
    for msg in st.session_state.chat_history[-6:]:
        role = "User" if msg["role"] == "user" else "Analyst"
        history_text += f"\n{role}: {msg['content']}\n"

    tax_country = st.session_state.get("tax_country", "🇦🇹 Austria")
    if "Italia" in tax_country:
        tax_context_prompt = "tassazione italiana (26% capital gains, Quadro RT)"
    else:
        tax_context_prompt = "tassazione austriaca (KESt 27,5%, E1kv)"

    today_str = datetime.date.today().strftime("%Y-%m-%d")
    prompt = f"""Sei un consulente fiscale e analista finanziario esperto in {tax_context_prompt}.
Oggi è il {today_str}.

Hai accesso ai seguenti dati REALI del rendiconto IBKR annuale:
{context}

{'CONVERSAZIONE PRECEDENTE:' + history_text if history_text else ''}

DOMANDA:
{user_message}

ISTRUZIONI:
- Rispondi SOLO basandoti sui dati forniti. Non inventare numeri.
- Se viene chiesta un'analisi degli errori di trading, identifica i trade in perdita, spiega i pattern di errore e suggerisci miglioramenti.
        - Per questioni fiscali, evidenzia: P/L realizzato vs non realizzato, commissioni deducibili, impatto cambi valuta (conversioni da valute estere alla valuta base {base}).
- Formatta con markdown (bold, tabelle, liste) per leggibilità.
- Rispondi nella lingua dell'utente.
"""

    try:
        actual_model = agent.ai.current_model_name
        response = agent.ai.get_model().generate_content(prompt)
        badge = f"*🤖 Model: `{provider_type}` / `{actual_model}`*\n\n---\n\n"
        return badge + response.text
    except Exception as e:
        return f"❌ AI Error ({provider_type}/{model_name}): {e}"


# ─── Sidebar ────────────────────────────────────────────────────────────────

st.sidebar.title("📊 IBKR Tax Calculator")

if "tax_country" not in st.session_state:
    st.session_state.tax_country = "🇦🇹 Austria"

st.sidebar.radio(
    "Paese di residenza fiscale",
    ["🇦🇹 Austria", "🇮🇹 Italia"],
    key="tax_country",
)
st.sidebar.markdown("---")

base_currency = st.sidebar.selectbox(
    "Valuta base del conto",
    BASE_CURRENCIES,
    index=BASE_CURRENCIES.index(st.session_state.base_currency)
        if st.session_state.base_currency in BASE_CURRENCIES
        else BASE_CURRENCIES.index("EUR"),
    key="base_currency",
    help="Seleziona la valuta base del conto. I calcoli fiscali saranno espressi in questa valuta. "
         "Se un trade è già in questa valuta, non verrà applicata conversione FX.",
)

st.sidebar.markdown("---")

uploaded_file = st.sidebar.file_uploader("Carica rendiconto IBKR (CSV)", type=["csv"])

# Only parse on fresh upload (skip on subsequent reruns)
if uploaded_file and st.session_state.parsed_data is None:
    data = parse_ibkr_csv(uploaded_file)
    st.session_state.fx_cache = {}
    st.session_state.base_currency_detected = False
    with st.sidebar:
        with st.spinner("🌐 Fetching ECB exchange rates…"):
            enrich_trades_base(data, st.session_state.base_currency)
    # ISIN enrichment
    instr = data.get("instrument_info", {})
    for t in data.get("trades", []):
        t["isin"] = instr.get(t["symbol"], "")
    for t in data.get("forex_trades", []):
        t["isin"] = ""
    st.session_state.parsed_data = data
    st.session_state.last_base_currency = st.session_state.base_currency
    st.rerun()

# Re-enrich if base currency changes after initial load
if st.session_state.parsed_data is not None:
    current_base = st.session_state.base_currency
    last_base = st.session_state.get("last_base_currency")
    if current_base != last_base:
        st.session_state.fx_cache = {}
        with st.sidebar:
            with st.spinner(f"🌐 Re-fetching ECB rates for {current_base}…"):
                enrich_trades_base(st.session_state.parsed_data, current_base)
        st.session_state.last_base_currency = current_base
        st.rerun()

# AI Model Selection
if TraderAgent and AIProvider:
    st.sidebar.markdown("---")
    provider, model = AIProvider.render_streamlit_sidebar()
    st.session_state.ai_provider = provider
    st.session_state.ai_model_name = model


# ─── Main Dashboard ─────────────────────────────────────────────────────────

data = st.session_state.parsed_data

if data is None:
    st.title("📊 IBKR Tax Calculator")
    st.info("⬅️ Carica un rendiconto IBKR (CSV) dalla sidebar per iniziare.")
    st.markdown("""
    ### Funzionalità
    - **Dashboard P/L**: Visualizzazione gain/loss per asset class con grafici interattivi
    - **Dettaglio Trade**: Ogni singola operazione con P/L realizzato
    - **Posizioni Aperte**: Stato attuale del portafoglio con P/L non realizzato
    - **Riepilogo Fiscale**: Dati rilevanti per la dichiarazione dei redditi
    - **AI Assistant**: Chatta con l'AI per analizzare errori di trading e ottimizzazione fiscale
    """)
    st.stop()

# Account header
base_ccy = st.session_state.base_currency
ccy_symbol = CURRENCY_SYMBOLS.get(base_ccy, "€")
acc = data["account_info"]
st.title(f"📊 {acc.get('Nome', 'N/A')} — {acc.get('Conto', 'N/A')}")
st.caption(f"Broker: {acc.get('Nome master', '')} | Tipo: {acc.get('Tipo di conto', '')} | Valuta base: {acc.get('Valuta di base', base_ccy)}")

# ─── TAB Navigation ─────────────────────────────────────────────────────────
tab_overview, tab_trades, tab_positions, tab_fiscal, tab_ai = st.tabs([
    "📈 Overview", "📋 Dettaglio Trade", "💼 Posizioni Aperte", "🏛️ Riepilogo Fiscale", "🤖 AI Assistant"
])

# ─── TAB 1: Overview ────────────────────────────────────────────────────────
with tab_overview:
    # KPIs
    nav_chg = data.get("nav_change", {})
    total_pl = data.get("total_pl", 0) or 0
    initial_val = nav_chg.get("Valore iniziale", 0)
    final_val = nav_chg.get("Valore finale", 0)
    deposits = nav_chg.get("Versamenti e prelievi", 0)
    commissions = nav_chg.get("Commissioni", 0)
    mtm_gain = nav_chg.get("Mark to market", 0)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("💰 Valore Finale", f"{ccy_symbol}{final_val:,.2f}", f"{total_pl:+,.2f} P/L")
    col2.metric("📥 Versamenti Totali", f"{ccy_symbol}{deposits:,.2f}")
    col3.metric("📊 Mark to Market", f"{ccy_symbol}{mtm_gain:+,.2f}")
    col4.metric("💸 Commissioni", f"{ccy_symbol}{commissions:,.2f}")

    st.markdown("---")

    # NAV Breakdown
    st.subheader("Asset Allocation")
    nav_items = [n for n in data.get("nav", []) if n["asset_class"] != "Totale"]
    if nav_items:
        col_chart, col_table = st.columns([1, 1])
        with col_chart:
            fig_nav = go.Figure(data=[go.Pie(
                labels=[n["asset_class"] for n in nav_items],
                values=[abs(n["current_total"]) for n in nav_items],
                hole=0.4,
                marker_colors=["#2ecc71", "#3498db", "#e74c3c", "#f39c12"],
                textinfo="label+percent+value",
                texttemplate=f"%{{label}}<br>{ccy_symbol}%{{value:,.2f}}<br>(%{{percent}})",
            )])
            fig_nav.update_layout(title="Composizione Portafoglio", height=400, showlegend=False)
            st.plotly_chart(fig_nav, use_container_width=True)

        with col_table:
            nav_df = pd.DataFrame(nav_items)
            nav_df.columns = ["Classe", "Precedente", "Long", "Short", "Totale", "Variazione"]
            st.dataframe(
                nav_df.style.format({
                    "Precedente": f"{ccy_symbol}{{:,.2f}}",
                    "Long": f"{ccy_symbol}{{:,.2f}}",
                    "Short": f"{ccy_symbol}{{:,.2f}}",
                    "Totale": f"{ccy_symbol}{{:,.2f}}",
                    "Variazione": f"{ccy_symbol}{{:+,.2f}}",
                }).map(lambda v: "color: #2ecc71" if isinstance(v, (int, float)) and v > 0 else "color: #e74c3c" if isinstance(v, (int, float)) and v < 0 else "", subset=["Variazione"]),
                use_container_width=True,
                hide_index=True,
            )

    st.markdown("---")

    # P/L by Symbol (MTM)
    st.subheader("P/L Mark-to-Market per Simbolo")
    mtm = data.get("mtm_summary", [])
    if mtm:
        mtm_df = pd.DataFrame(mtm)
        # Waterfall chart
        mtm_df_sorted = mtm_df.sort_values("mtm_total", ascending=True)
        colors = ["#2ecc71" if v >= 0 else "#e74c3c" for v in mtm_df_sorted["mtm_total"]]
        fig_mtm = go.Figure(go.Bar(
            x=mtm_df_sorted["mtm_total"],
            y=mtm_df_sorted["symbol"],
            orientation="h",
            marker_color=colors,
            text=[f"{ccy_symbol}{v:+,.2f}" for v in mtm_df_sorted["mtm_total"]],
            textposition="auto",
        ))
        fig_mtm.update_layout(
            title=f"P/L MTM per Trade ({base_ccy})",
            xaxis_title=f"P/L ({base_ccy})",
            yaxis_title="",
            height=max(400, len(mtm_df_sorted) * 35),
            margin=dict(l=150),
        )
        st.plotly_chart(fig_mtm, use_container_width=True)

    # P/L by Asset Type
    st.subheader("P/L per Tipo di Attivo")
    if mtm:
        type_pl = mtm_df.groupby("asset_type")["mtm_total"].sum().reset_index()
        type_pl.columns = ["Tipo", "P/L Totale"]
        colors_type = ["#2ecc71" if v >= 0 else "#e74c3c" for v in type_pl["P/L Totale"]]
        fig_type = go.Figure(go.Bar(
            x=type_pl["Tipo"],
            y=type_pl["P/L Totale"],
            marker_color=colors_type,
            text=[f"{ccy_symbol}{v:+,.2f}" for v in type_pl["P/L Totale"]],
            textposition="auto",
        ))
        fig_type.update_layout(title="P/L per Asset Class", yaxis_title=base_ccy, height=400)
        st.plotly_chart(fig_type, use_container_width=True)


# ─── TAB 2: Trade Details ───────────────────────────────────────────────────
with tab_trades:
    trades = data.get("trades", [])
    if not trades:
        st.info("Nessun trade trovato nel rendiconto.")
    else:
        trades_df = pd.DataFrame(trades)
        # Ensure base columns exist (may be missing if enrich wasn't called yet)
        if "realized_pl_base" not in trades_df.columns:
            trades_df["realized_pl_base"] = trades_df["realized_pl"]
            trades_df["commission_base"] = trades_df["commission"]
            trades_df["proceeds_base"] = trades_df["proceeds"]
            trades_df["fx_rate"] = 1.0

        # Filters
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            asset_types = ["Tutti"] + sorted(trades_df["asset_type"].unique().tolist())
            filter_type = st.selectbox("Tipo Attivo", asset_types)
        with col_f2:
            symbols = ["Tutti"] + sorted(trades_df["symbol"].unique().tolist())
            filter_symbol = st.selectbox("Simbolo", symbols)
        with col_f3:
            filter_side = st.selectbox("Direzione", ["Tutti", "BUY", "SELL"])

        filtered = trades_df.copy()
        if filter_type != "Tutti":
            filtered = filtered[filtered["asset_type"] == filter_type]
        if filter_symbol != "Tutti":
            filtered = filtered[filtered["symbol"] == filter_symbol]
        if filter_side == "BUY":
            filtered = filtered[filtered["quantity"] > 0]
        elif filter_side == "SELL":
            filtered = filtered[filtered["quantity"] < 0]

        # Summary metrics — USE base-currency converted values
        total_realized_base = filtered["realized_pl_base"].sum()
        total_realized_orig = filtered["realized_pl"].sum()
        total_comm_base = filtered["commission_base"].sum()
        n_trades = len(filtered)
        winning = len(filtered[filtered["realized_pl_base"] > 0])
        losing = len(filtered[filtered["realized_pl_base"] < 0])

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Trade Totali", n_trades)
        c2.metric(f"P/L Realizzato ({base_ccy})", f"{ccy_symbol}{total_realized_base:+,.2f}",
                  help=f"Valori originali: {total_realized_orig:+,.2f} usando tassi ECB del giorno del trade")
        c3.metric(f"Commissioni ({base_ccy})", f"{ccy_symbol}{total_comm_base:,.2f}")
        c4.metric("Win/Loss", f"{winning}W / {losing}L")

        # Trade table — show both original and base-currency converted P/L
        display_cols = ["datetime", "asset_type", "symbol", "currency", "quantity",
                        "price", "proceeds_base", "commission_base", "realized_pl",
                        "realized_pl_base", "fx_rate", "mtm_pl", "code"]
        display_df = filtered[display_cols].copy()
        display_df.columns = ["Data/Ora", "Tipo", "Simbolo", "Val.", "Qtà", "Prezzo",
                               f"Ricavo ({base_ccy})", f"Comm. ({base_ccy})", "P/L Real. (Orig.)",
                               f"P/L Real. ({base_ccy})", "Tasso ECB", "P/L MTM", "Codice"]

        st.dataframe(
            display_df.style.format({
                "Qtà": "{:,.4f}",
                "Prezzo": "{:,.4f}",
                f"Ricavo ({base_ccy})": f"{ccy_symbol}{{:,.2f}}",
                f"Comm. ({base_ccy})": f"{ccy_symbol}{{:,.2f}}",
                "P/L Real. (Orig.)": "{:+,.2f}",
                f"P/L Real. ({base_ccy})": f"{ccy_symbol}{{:+,.2f}}",
                "Tasso ECB": "{:.4f}",
                "P/L MTM": "{:+,.2f}",
            }).map(
                lambda v: "color: #2ecc71; font-weight: bold" if isinstance(v, (int, float)) and v > 0
                          else "color: #e74c3c; font-weight: bold" if isinstance(v, (int, float)) and v < 0
                          else "",
                subset=[f"P/L Real. ({base_ccy})"]
            ),
            use_container_width=True,
            hide_index=True,
            height=500,
        )

        st.caption(f"💱 La colonna **Tasso ECB** riporta il tasso di cambio ufficiale BCE del giorno del trade (valuta trade per 1 {base_ccy}). Il P/L originale è diviso per questo tasso per ottenere il P/L in {base_ccy}.")

        # Timeline chart — cumulative base-currency P/L
        st.subheader(f"P/L Realizzato nel Tempo ({base_ccy})")
        realized_trades = filtered[filtered["realized_pl_base"] != 0].copy()
        if not realized_trades.empty:
            realized_trades["date"] = pd.to_datetime(realized_trades["datetime"].str[:10])
            daily_pl = realized_trades.groupby("date")["realized_pl_base"].sum().cumsum().reset_index()
            daily_pl.columns = ["Data", f"P/L Cumulativo ({base_ccy})"]
            fig_timeline = go.Figure()
            fig_timeline.add_trace(go.Scatter(
                x=daily_pl["Data"],
                y=daily_pl[f"P/L Cumulativo ({base_ccy})"],
                mode="lines+markers",
                fill="tozeroy",
                line=dict(color="#3498db", width=2),
                fillcolor="rgba(52,152,219,0.1)",
            ))
            fig_timeline.update_layout(
                title=f"P/L Realizzato Cumulativo ({base_ccy} — tassi ECB giornalieri)",
                xaxis_title="Data",
                yaxis_title=base_ccy,
                height=400,
            )
            st.plotly_chart(fig_timeline, use_container_width=True)


# ─── TAB 3: Open Positions ──────────────────────────────────────────────────
with tab_positions:
    positions = data.get("open_positions", [])
    if not positions:
        st.info("Nessuna posizione aperta trovata.")
    else:
        pos_df = pd.DataFrame(positions)

        # KPIs
        total_value = pos_df["value"].sum()
        total_unreal = pos_df["unrealized_pl"].sum()
        total_cost = pos_df["cost_basis"].sum()

        c1, c2, c3 = st.columns(3)
        c1.metric("💰 Valore Totale", f"{ccy_symbol}{total_value:,.2f}")
        c2.metric("📊 P/L Non Realizzato", f"{ccy_symbol}{total_unreal:+,.2f}")
        c3.metric("💵 Costo Base", f"{ccy_symbol}{total_cost:,.2f}")

        # Position table
        display_pos = pos_df[["asset_type", "symbol", "currency", "quantity", "multiplier", "cost_price", "cost_basis", "close_price", "value", "unrealized_pl"]].copy()
        display_pos.columns = ["Tipo", "Simbolo", "Val.", "Qtà", "Molt.", "Prezzo Costo", "Base Costo", "Prezzo Close", "Valore", "P/L Non Real."]

        st.dataframe(
            display_pos.style.format({
                "Qtà": "{:,.4f}",
                "Molt.": "{:.0f}",
                "Prezzo Costo": "{:,.4f}",
                "Base Costo": f"{ccy_symbol}{{:,.2f}}",
                "Prezzo Close": "{:,.4f}",
                "Valore": f"{ccy_symbol}{{:,.2f}}",
                "P/L Non Real.": f"{ccy_symbol}{{:+,.2f}}",
            }).map(
                lambda v: "color: #2ecc71; font-weight: bold" if isinstance(v, (int, float)) and v > 0 else "color: #e74c3c; font-weight: bold" if isinstance(v, (int, float)) and v < 0 else "",
                subset=["P/L Non Real."]
            ),
            use_container_width=True,
            hide_index=True,
        )

        # P/L chart per position
        colors_pos = ["#2ecc71" if v >= 0 else "#e74c3c" for v in pos_df["unrealized_pl"]]
        fig_pos = go.Figure(go.Bar(
            x=pos_df["symbol"],
            y=pos_df["unrealized_pl"],
            marker_color=colors_pos,
            text=[f"{ccy_symbol}{v:+,.2f}" for v in pos_df["unrealized_pl"]],
            textposition="auto",
        ))
        fig_pos.update_layout(title="P/L Non Realizzato per Posizione", yaxis_title=base_ccy, height=400)
        st.plotly_chart(fig_pos, use_container_width=True)


# ─── TAB 4: Tax Summary ─────────────────────────────────────────────────────
with tab_fiscal:
    st.subheader("🏛️ Riepilogo Fiscale Anno")

    # ── P/L totals from trades (converted to base currency via ECB daily rates) ─
    trades_all = data.get("trades", [])
    trades_base_df = pd.DataFrame(trades_all) if trades_all else pd.DataFrame()
    if not trades_base_df.empty and "realized_pl_base" in trades_base_df.columns:
        total_realized_trades_base = trades_base_df["realized_pl_base"].sum()
        total_comm_trades_base = trades_base_df["commission_base"].sum()
        has_fx_conversion = True
    else:
        total_realized_trades_base = None
        total_comm_trades_base = None
        has_fx_conversion = False

    rl = data.get("realized_unrealized", [])
    if rl:
        rl_df = pd.DataFrame(rl)

        total_realized = rl_df["realized_total"].sum()      # from IBKR summary (may be USD)
        total_unrealized = rl_df["unrealized_total"].sum()
        total_realized_profit = rl_df["realized_profit_st"].sum() + rl_df["realized_profit_lt"].sum()
        total_realized_loss = rl_df["realized_loss_st"].sum() + rl_df["realized_loss_lt"].sum()

        st.markdown("### Riepilogo Generale")

        if has_fx_conversion:
            st.info(
                f"💱 **Conversione valuta attiva** (tassi BCE ufficiali giornalieri). "
                f"Le imposte qui sotto sono calcolate sul **P/L convertito in {base_ccy}** usando "
                f"il tasso BCE del giorno di ogni singola operazione."
            )
            net_taxable = total_realized_trades_base
            net_taxable_label = f"P/L Realizzato Netto ({base_ccy}, tassi ECB)"
        else:
            st.warning("⚠️ Dati FX non disponibili — i valori sono in valuta originale del trade.")
            net_taxable = total_realized
            net_taxable_label = "P/L Realizzato Netto (valuta originale)"

        col1, col2, col3, col4 = st.columns(4)
        col1.metric(f"✅ P/L Realizzato {base_ccy}", f"{ccy_symbol}{net_taxable:+,.2f}",
                    help=f"Somma dei P/L realizzati di tutti i trade, convertiti in {base_ccy} al tasso ECB del giorno" if has_fx_conversion else None)
        col2.metric("📈 Profitti Lordi (IBKR)", f"{ccy_symbol}{total_realized_profit:,.2f}")
        col3.metric("📉 Perdite Lorde (IBKR)", f"{ccy_symbol}{total_realized_loss:,.2f}")
        col4.metric("⏳ P/L Non Realizzato", f"{ccy_symbol}{total_unrealized:+,.2f}")

        tax_country = st.session_state.get("tax_country", "🇦🇹 Austria")

        # ── Country-specific fiscal detail ──────────────────────────────────
        st.markdown("---")

        if "Austria" in tax_country:
            st.markdown("### 🇦🇹 Finanzonline — Modulo E1kv (KESt 27,5%)")
            st.info(
                "⚖️ La legge austriaca (§ 27 EStG) richiede che **profitti e perdite siano inseriti "
                "SEPARATAMENTE** (nicht saldiert) e che vengano distinti per categoria:\n\n"
                "- **§ 27 Abs. 3** → Azioni, ETF, Fondi → KZ **994** (Überschüsse) + KZ **892** (Verluste)\n"
                "- **§ 27 Abs. 4** → Derivati, Opzioni, Certificati → KZ **995** (Überschüsse) + KZ **896** (Verluste)"
            )

            if has_fx_conversion and not trades_base_df.empty:
                DERIVATE_KEYWORDS = [
                    "opzion", "option", "derivat", "future", "warrant",
                    "certificat", "cfd", "swap",
                ]

                def _classify_at(asset_type: str) -> str:
                    at_lower = str(asset_type).lower()
                    if any(k in at_lower for k in DERIVATE_KEYWORDS):
                        return "derivate"
                    return "aktien"

                t_df = trades_base_df.copy()
                t_df["at_category"] = t_df["asset_type"].apply(_classify_at)
                t_closed = t_df[t_df["realized_pl_base"] != 0].copy()

                for cat, label_it, label_de, kz_profit, kz_loss, par in [
                    ("aktien",  "📈 Azioni / ETF / Fondi",       "§ 27 Abs. 3 EStG",  994, 892, 3),
                    ("derivate","⚡ Derivati / Opzioni / Futures","§ 27 Abs. 4 EStG",  995, 896, 4),
                ]:
                    cat_df = t_closed[t_closed["at_category"] == cat]
                    gross_profit = cat_df[cat_df["realized_pl_base"] > 0]["realized_pl_base"].sum()
                    gross_loss   = cat_df[cat_df["realized_pl_base"] < 0]["realized_pl_base"].sum()
                    net          = gross_profit + gross_loss
                    kest_net     = max(net, 0) * 0.275
                    n            = len(cat_df)

                    st.markdown(f"#### {label_it} — *{label_de}*")
                    if n == 0:
                        st.caption(f"Nessun trade chiuso in questa categoria ({cat}).")
                        continue

                    col_l, col_r = st.columns(2)
                    with col_l:
                        st.markdown(f"""
| Campo Finanzonline | KZ | Importo {base_ccy} |
|---|---|---|
| Überschüsse 27,5% *(profitti lordi)* | **{kz_profit}** | **{ccy_symbol} {gross_profit:,.2f}** |
| Verluste *(perdite lorde, con segno -)* | **{kz_loss}** | **{ccy_symbol} {gross_loss:,.2f}** |
| Netto (solo informativo, NON da inserire) | — | {ccy_symbol} {net:+,.2f} |
| KeSt stimata sul netto (27,5%) | — | {ccy_symbol} {kest_net:,.2f} |
""")
                    with col_r:
                        st.metric(f"KZ {kz_profit} — Überschüsse", f"{ccy_symbol} {gross_profit:,.2f}",
                                  help=f"Inserire in Finanzonline → E1kv → KZ {kz_profit}")
                        st.metric(f"KZ {kz_loss} — Verluste", f"{ccy_symbol} {gross_loss:,.2f}",
                                  help=f"Inserire con segno NEGATIVO in Finanzonline → E1kv → KZ {kz_loss}")

                    st.caption(
                        f"⚠️ **N.B.:** Inserire KZ {kz_profit} e KZ {kz_loss} **separatamente** (nicht saldiert). "
                        f"Non sommarli. Operazioni incluse: {n}."
                    )
                    st.markdown("")

            else:
                kest_rate = 0.275
                kest_due  = max(net_taxable * kest_rate, 0) if net_taxable > 0 else 0
                st.markdown(f"""
| Voce | Importo |
|------|---------|
| {net_taxable_label} | {ccy_symbol}{net_taxable:+,.2f} |
| KESt stimata (27,5%) | **{ccy_symbol}{kest_due:,.2f}** |
""")

        else:
            st.markdown("### 🇮🇹 Quadro RT — REDDITI PF (Imposta Sostitutiva 26%)")
            st.info(
                "⚖️ La normativa italiana (Art. 67, comma 1, TUIR) richiede la "
                "classificazione delle plusvalenze/minusvalenze per categoria:\n\n"
                "- **Non qualificate** (Azioni, ETF, Obbligazioni) → Rigo **RT51** (plus) / **RT53** (minus)\n"
                "- **Derivati** (Opzioni, Futures, Warrant, Certificati) → Rigo **RT31** (plus) / **RT32** (minus)\n"
                "- **Cripto-attività** → Rigo **RT88** (plus) / **RT89** (minus)"
            )

            if has_fx_conversion and not trades_base_df.empty:
                DERIVATE_KEYWORDS = [
                    "opzion", "option", "derivat", "future", "warrant",
                    "certificat", "cfd", "swap",
                ]
                CRYPTO_KEYWORDS = ["crypto", "cripto"]

                def _classify_it(asset_type: str) -> str:
                    at_lower = str(asset_type).lower()
                    if any(k in at_lower for k in CRYPTO_KEYWORDS):
                        return "crypto"
                    if any(k in at_lower for k in DERIVATE_KEYWORDS):
                        return "derivatives"
                    return "non_qualified"

                t_df = trades_base_df.copy()
                t_df["it_category"] = t_df["asset_type"].apply(_classify_it)
                t_closed = t_df[t_df["realized_pl_base"] != 0].copy()

                IT_CATEGORIES = [
                    ("non_qualified", "📈 Azioni / ETF / Obbligazioni", "RT51", "RT53", 0.26),
                    ("derivatives",   "⚡ Derivati / Opzioni / Futures", "RT31", "RT32", 0.26),
                    ("crypto",        "₿ Cripto-attività",             "RT88", "RT89", 0.26),
                ]

                for cat, label_it, rigo_plus, rigo_minus, aliquota in IT_CATEGORIES:
                    cat_df = t_closed[t_closed["it_category"] == cat]
                    gross_profit = cat_df[cat_df["realized_pl_base"] > 0]["realized_pl_base"].sum()
                    gross_loss   = cat_df[cat_df["realized_pl_base"] < 0]["realized_pl_base"].sum()
                    net          = gross_profit + gross_loss
                    imposta      = max(net, 0) * aliquota
                    n            = len(cat_df)

                    st.markdown(f"#### {label_it}")
                    if n == 0:
                        st.caption(f"Nessun trade chiuso in questa categoria ({cat}).")
                        continue

                    col_l, col_r = st.columns(2)
                    with col_l:
                        st.markdown(f"""
| Campo Quadro RT | Rigo | Importo {base_ccy} |
|---|---|---|
| Plusvalenze {aliquota*100:.0f}% | **{rigo_plus}** | **{ccy_symbol} {gross_profit:,.2f}** |
| Minusvalenze | **{rigo_minus}** | **{ccy_symbol} {gross_loss:,.2f}** |
| Netto (solo informativo) | — | {ccy_symbol} {net:+,.2f} |
| Imposta sostitutiva ({aliquota*100:.0f}%) | — | {ccy_symbol} {imposta:,.2f} |
| Codice tributo F24 | — | **1100** |
""")
                    with col_r:
                        st.metric(f"Rigo {rigo_plus} — Plusvalenze", f"{ccy_symbol} {gross_profit:,.2f}",
                                  help=f"Inserire in REDDITI PF → Quadro RT → Rigo {rigo_plus}")
                        st.metric(f"Rigo {rigo_minus} — Minusvalenze", f"{ccy_symbol} {gross_loss:,.2f}",
                                  help=f"Inserire in REDDITI PF → Quadro RT → Rigo {rigo_minus}")

                    st.caption(
                        f"⚠️ **N.B.:** Plusvalenze e minusvalenze vanno inserite **separatamente** nei rispettivi righi. "
                        f"Operazioni incluse: {n}. Minusvalenze riportabili 4 periodi d'imposta."
                    )
                    st.markdown("")

                # ── RM — Redditi di Capitale Fonte Estera ────────────────────
                interests = data.get("interests", [])
                interests_total_ibkr = data.get("interests_total_eur", 0.0)
                interests_total_base = data.get("interests_total_base", 0.0)
                st.markdown("---")
                st.subheader("📊 Quadro RM — Redditi di Capitale Fonte Estera")
                st.info(
                    "Gli interessi/proventi da fonte estera vanno dichiarati in **Quadro RM, "
                    "Sezione II-A, Rigo RM31** (art. 18 TUIR), soggetti a imposta sostitutiva 26%."
                )
                if interests_total_ibkr > 0:
                    imposta_rm = max(interests_total_ibkr * 0.26, 0)
                    st.markdown(f"""
| Campo RM | Valore |
|---|---|---|
| Tipo provento | Interessi su titoli (prestito titoli / SYEP) |
| Rigo | **RM31** |
| **Totale interessi ({base_ccy})** (broker) | **{ccy_symbol} {interests_total_ibkr:,.2f}** |
| ↳ Tasso BCE giornaliero ({base_ccy}) | {ccy_symbol} {interests_total_base:,.2f} |
| Imposta sostitutiva (26%) | **{ccy_symbol} {imposta_rm:,.2f}** |
| Codice tributo F24 | **1100** |
""")
                    with st.expander("📋 Dettaglio interessi per operazione"):
                        int_df = pd.DataFrame(interests)
                        if not int_df.empty:
                            cols_display = ["Valuta", "Data", "Descrizione", "Importo"]
                            cols_data = ["currency", "date", "description", "amount"]
                            if "amount_base" in int_df.columns:
                                cols_display.append(f"Importo {base_ccy} (BCE)")
                                cols_data.append("amount_base")
                            display = int_df[cols_data].copy()
                            display.columns = cols_display
                            st.dataframe(
                                display.style.format(
                                    {"Importo": f"{ccy_symbol}{{:,.6f}}", f"Importo {base_ccy} (BCE)": f"{ccy_symbol}{{:,.6f}}"}
                                ),
                                use_container_width=True,
                                hide_index=True,
                            )
                else:
                    st.caption("Nessun interesse o dividendo registrato nel periodo.")

                # ── RW Monitoring for Italy ──────────────────────────────────
                st.markdown("---")
                st.subheader("🌍 Monitoraggio RW — Investimenti Esteri")
                st.info(
                    "Obbligatorio se il **valore medio** degli investimenti esteri "
                    f"supera {ccy_symbol} 15.000 (Art. 4, DL 167/1990)."
                )

                if not trades_base_df.empty:
                    nav_initial = data.get("nav_change", {}).get("Valore iniziale", 0)
                    nav_final = data.get("nav_change", {}).get("Valore finale", 0)
                    if nav_initial > 0 or nav_final > 0:
                        avg_value = (nav_initial + nav_final) / 2
                    else:
                        total_proceeds = trades_base_df["proceeds_base"].sum()
                        total_cost = trades_base_df["cost_basis_base"].sum()
                        avg_value = max(total_proceeds, total_cost) * 0.5

                    st.markdown(f"""
| Campo RW | Valore |
|---|---|---|
| **Patrimonio iniziale** (01/01) | {ccy_symbol} {nav_initial:,.2f} |
| **Patrimonio finale** (31/12) | {ccy_symbol} {nav_final:,.2f} |
| **Formula valore medio** | ({nav_initial:,.2f} + {nav_final:,.2f}) / 2 |
| **Valore medio investimenti** | **{ccy_symbol} {avg_value:,.2f}** |
| Soglia monitoraggio | {ccy_symbol} 15.000 |
""")

                    if avg_value > 15000:
                        ivafe = max(avg_value * 0.002, 0)
                        st.warning("⚠️ Soglia monitoraggio **superata** — compilare Quadro RW.")
                        st.markdown(f"""
| IVAFE dovuta (0,20%) | **{ccy_symbol} {ivafe:,.2f}** |
| Rigo RW | **RW1 — RW4** |
| Sezione | I-A (Patrimoni finanziari) |
""")
                    else:
                        st.success(
                            f"✅ Soglia monitoraggio **non superata**. "
                            "Obbligo dichiarativo RW non dovuto."
                        )

            else:
                imposta_it = max(net_taxable * 0.26, 0) if net_taxable > 0 else 0
                st.markdown(f"""
| Voce | Importo |
|------|---------|
| {net_taxable_label} | {ccy_symbol}{net_taxable:+,.2f} |
| Imposta sostitutiva (26%) | **{ccy_symbol}{imposta_it:,.2f}** |
| Codice tributo F24 | **1100** |
""")



        # ── Per-trade breakdown split by tax category ─────────────────────────
        if has_fx_conversion and not trades_base_df.empty:
            st.markdown("---")
            st.subheader(f"Dettaglio P/L per Operazione ({base_ccy}, tassi ECB giornalieri)")

            # Prepare detail dataframe
            detail_df = trades_base_df.copy()
            detail_df["data_operazione"] = detail_df["datetime"].str[:10]
            detail_df["data_tasso_ecb"] = detail_df["fx_rate_date"].apply(
                lambda d: str(d) if d is not None else ""
            )
            detail_df["tasso_leggibile"] = detail_df["fx_rate"].apply(
                lambda r: f"1 {base_ccy} = {r:.4f} valuta trade" if r and r != 1.0 else "N/A"
            )
            detail_df["tasso_inverso"] = detail_df["fx_rate"].apply(
                lambda r: f"1 valuta trade = {1/r:.4f} {base_ccy}" if r and r != 1.0 else "N/A"
            )

            DERIVATE_KEYWORDS = [
                "opzion", "option", "derivat", "future", "warrant",
                "certificat", "cfd", "swap",
            ]
            CRYPTO_KEYWORDS = ["crypto", "cripto"]

            tax_country = st.session_state.get("tax_country", "🇦🇹 Austria")

            if "Austria" in tax_country:
                def _classify(at: str) -> str:
                    return "derivate" if any(k in str(at).lower() for k in DERIVATE_KEYWORDS) else "aktien"

                detail_df["cat"] = detail_df["asset_type"].apply(_classify)
                detail_closed = detail_df[detail_df["realized_pl_base"] != 0].copy()

                _FMT = {
                    "Qtà": "{:,.4f}", "Prezzo": "{:,.4f}",
                    "P/L (Orig.)": "{:+,.2f}", f"P/L ({base_ccy})": f"{ccy_symbol}{{:+,.2f}}",
                    f"Comm. ({base_ccy})": f"{ccy_symbol}{{:,.2f}}",
                }

                AT_LOOP = [
                    ("aktien", "📈", "Azioni / ETF / Fondi", "§ 27 Abs. 3 EStG", 994, 892),
                    ("derivate", "⚡", "Derivati / Opzioni / Futures", "§ 27 Abs. 4 EStG", 995, 896),
                ]

                for cat, emoji, label_it, label_de, kz_profit, kz_loss in AT_LOOP:
                    cat_rows = detail_closed[detail_closed["cat"] == cat].sort_values(
                        ["data_operazione", "symbol"]
                    )
                    gross_profit = cat_rows[cat_rows["realized_pl_base"] > 0]["realized_pl_base"].sum()
                    gross_loss   = cat_rows[cat_rows["realized_pl_base"] < 0]["realized_pl_base"].sum()
                    net          = gross_profit + gross_loss

                    st.markdown(f"#### {emoji} {label_it} — *{label_de}*")
                    if cat_rows.empty:
                        st.caption("Nessuna operazione chiusa in questa categoria.")
                        continue

                    disp = cat_rows[["data_operazione", "symbol", "asset_type", "currency",
                        "quantity", "price", "realized_pl", "tasso_leggibile", "tasso_inverso",
                        "data_tasso_ecb", "realized_pl_base", "commission_base"]].copy()
                    disp.columns = ["Giorno Operazione", "Simbolo", "Tipo", "Val.",
                        "Qtà", "Prezzo", "P/L (Orig.)", "Cambio BCE (÷)", "Cambio BCE (×)",
                        "Data Tasso ECB", f"P/L ({base_ccy})", f"Comm. ({base_ccy})"]

                    st.dataframe(
                        disp.style.format(_FMT).map(
                            lambda v: "color: #2ecc71; font-weight: bold" if isinstance(v, (int, float)) and v > 0
                                      else "color: #e74c3c; font-weight: bold" if isinstance(v, (int, float)) and v < 0
                                      else "",
                            subset=[f"P/L ({base_ccy})"]
                        ), use_container_width=True, hide_index=True,
                        height=min(500, max(150, len(disp) * 38)),
                    )

                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric(f"✅ KZ {kz_profit} Überschüsse", f"{ccy_symbol} {gross_profit:,.2f}",
                              help=f"Inserire in Finanzonline KZ {kz_profit}")
                    c2.metric(f"🔴 KZ {kz_loss} Verluste", f"{ccy_symbol} {gross_loss:,.2f}",
                              help=f"Inserire in Finanzonline KZ {kz_loss}")
                    c3.metric("Netto (info)", f"{ccy_symbol} {net:+,.2f}",
                              help="Solo informativo — non corrisponde a un campo Finanzonline")
                    c4.metric("KeSt stimata (27,5%)", f"{ccy_symbol} {max(net, 0) * 0.275:,.2f}",
                              help="KeSt = max(Netto, 0) × 27,5%")
                    st.markdown("")

                st.caption(
                    "I totali KZ corrispondono al riepilogo Finanzonline E1kv qui sopra."
                )

            else:
                def _classify_it_local(at: str) -> str:
                    at_lower = str(at).lower()
                    if any(k in at_lower for k in CRYPTO_KEYWORDS):
                        return "crypto"
                    if any(k in at_lower for k in DERIVATE_KEYWORDS):
                        return "derivatives"
                    return "non_qualified"

                detail_df["cat"] = detail_df["asset_type"].apply(_classify_it_local)
                detail_closed = detail_df[detail_df["realized_pl_base"] != 0].copy()

                _FMT = {
                    "Qtà": "{:,.4f}", "Prezzo": "{:,.4f}",
                    "P/L (Orig.)": "{:+,.2f}", f"P/L ({base_ccy})": f"{ccy_symbol}{{:+,.2f}}",
                    f"Comm. ({base_ccy})": f"{ccy_symbol}{{:,.2f}}",
                }

                IT_LOOP = [
                    ("non_qualified", "📈", "Azioni / ETF / Obbligazioni", "RT51", "RT53", 0.26),
                    ("derivatives", "⚡", "Derivati / Opzioni / Futures", "RT31", "RT32", 0.26),
                    ("crypto", "₿", "Cripto-attività", "RT88", "RT89", 0.26),
                ]

                for cat, emoji, label_it, rigo_plus, rigo_minus, aliquota in IT_LOOP:
                    cat_rows = detail_closed[detail_closed["cat"] == cat].sort_values(
                        ["data_operazione", "symbol"]
                    )
                    gross_profit = cat_rows[cat_rows["realized_pl_base"] > 0]["realized_pl_base"].sum()
                    gross_loss   = cat_rows[cat_rows["realized_pl_base"] < 0]["realized_pl_base"].sum()
                    net          = gross_profit + gross_loss

                    st.markdown(f"#### {emoji} {label_it}")
                    if cat_rows.empty:
                        st.caption("Nessuna operazione chiusa in questa categoria.")
                        continue

                    disp = cat_rows[["data_operazione", "symbol", "asset_type", "currency",
                        "quantity", "price", "realized_pl", "tasso_leggibile", "tasso_inverso",
                        "data_tasso_ecb", "realized_pl_base", "commission_base"]].copy()
                    disp.columns = ["Giorno Operazione", "Simbolo", "Tipo", "Val.",
                        "Qtà", "Prezzo", "P/L (Orig.)", "Cambio BCE (÷)", "Cambio BCE (×)",
                        "Data Tasso ECB", f"P/L ({base_ccy})", f"Comm. ({base_ccy})"]

                    st.dataframe(
                        disp.style.format(_FMT).map(
                            lambda v: "color: #2ecc71; font-weight: bold" if isinstance(v, (int, float)) and v > 0
                                      else "color: #e74c3c; font-weight: bold" if isinstance(v, (int, float)) and v < 0
                                      else "",
                            subset=[f"P/L ({base_ccy})"]
                        ), use_container_width=True, hide_index=True,
                        height=min(500, max(150, len(disp) * 38)),
                    )

                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric(f"✅ Rigo {rigo_plus} — Plusvalenze", f"{ccy_symbol} {gross_profit:,.2f}",
                              help=f"Inserire in REDDITI PF → Quadro RT → Rigo {rigo_plus}")
                    c2.metric(f"🔴 Rigo {rigo_minus} — Minusvalenze", f"{ccy_symbol} {gross_loss:,.2f}",
                              help=f"Inserire in REDDITI PF → Quadro RT → Rigo {rigo_minus}")
                    c3.metric("Netto (info)", f"{ccy_symbol} {net:+,.2f}", help="Solo informativo")
                    c4.metric(f"Imposta sost. ({aliquota*100:.0f}%)", f"{ccy_symbol} {max(net, 0) * aliquota:,.2f}",
                              help=f"Cod. tributo F24: 1100")
                    st.markdown("")

                st.caption(
                    "I totali per rigo RT corrispondono al riepilogo Quadro RT qui sopra."
                )

            # Bar chart aggregated by symbol — shared for both countries
            sym_base = (
                trades_base_df[trades_base_df["realized_pl_base"] != 0]
                .groupby("symbol").agg(pl_base=("realized_pl_base", "sum"))
                .reset_index().sort_values("pl_base", ascending=True)
            )
            colors_sym = ["#2ecc71" if v >= 0 else "#e74c3c" for v in sym_base["pl_base"]]
            fig_sym = go.Figure(go.Bar(
                x=sym_base["pl_base"], y=sym_base["symbol"], orientation="h",
                marker_color=colors_sym,
                text=[f"{ccy_symbol}{v:+,.2f}" for v in sym_base["pl_base"]], textposition="auto",
            ))
            fig_sym.update_layout(
                title=f"P/L Realizzato per Simbolo ({base_ccy} — tassi ECB giornalieri)",
                xaxis_title=base_ccy, height=max(400, len(sym_base) * 35), margin=dict(l=180),
            )
            st.plotly_chart(fig_sym, use_container_width=True)

        # ── IBKR Realized/Unrealized summary table ───────────────────────────
        st.markdown("---")
        st.subheader("Dettaglio P/L IBKR per Simbolo (Realizzato + Non Realizzato)")

        display_rl = rl_df[["asset_type", "symbol", "realized_profit_st", "realized_loss_st", "realized_total", "unrealized_total", "total"]].copy()
        display_rl.columns = ["Tipo", "Simbolo", "Profitto S/T", "Perdita S/T", "Realizzato Tot.", "Non Real. Tot.", "Totale"]

        st.dataframe(
            display_rl.style.format({
                "Profitto S/T": "{:,.2f}",
                "Perdita S/T": "{:,.2f}",
                "Realizzato Tot.": "{:+,.2f}",
                "Non Real. Tot.": "{:+,.2f}",
                "Totale": "{:+,.2f}",
            }).map(
                lambda v: "color: #2ecc71; font-weight: bold" if isinstance(v, (int, float)) and v > 0
                          else "color: #e74c3c; font-weight: bold" if isinstance(v, (int, float)) and v < 0
                          else "",
                subset=["Realizzato Tot.", "Non Real. Tot.", "Totale"]
            ),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(f"⚠️ I valori in questa tabella provengono direttamente dal riepilogo IBKR e potrebbero essere in valuta originale. Per i valori fiscalmente corretti in {base_ccy} usa la tabella sopra (tassi ECB giornalieri).")

    else:
        st.info("Nessun dato P/L realizzato/non realizzato trovato.")

    # Deposits section
    deps = data.get("deposits", [])
    if deps:
        st.markdown("---")
        st.subheader("📥 Versamenti")
        dep_df = pd.DataFrame(deps)
        dep_df.columns = ["Valuta", "Data", "Descrizione", "Importo"]
        st.dataframe(
            dep_df.style.format({"Importo": f"{ccy_symbol}{{:,.2f}}"}),
            use_container_width=True,
            hide_index=True,
        )
        st.metric("Totale Versamenti", f"{ccy_symbol}{sum(d['amount'] for d in deps):,.2f}")

    # ── Final Reporting Section ──────────────────────────────────────────────
    st.markdown("---")
    st.subheader("📥 Esportazione Report Fiscale")
    rpt_country = st.session_state.get("tax_country", "🇦🇹 Austria")
    if "Austria" in rpt_country:
        st.info("Genera un riepilogo in formato JSON o PDF dei campi KZ richiesti per Finanzonline (E1kv).")
    else:
        st.info("Genera un riepilogo in formato JSON o PDF dei dati Quadro RT per REDDITI PF (Italia).")

    # Aggregate data for reporting
    report_dict = {
        "Account": acc.get("Nome", "N/A"),
        "Portfolio ID": acc.get("Conto", "N/A"),
        "Base Currency": base_ccy,
        "Report Date": datetime.date.today().strftime("%Y-%m-%d"),
        f"Net Realized P/L ({base_ccy})": round(net_taxable, 2) if 'net_taxable' in locals() else 0.0,
    }

    # Add country-specific metrics
    try:
        if 't_closed' in locals() and t_closed is not None and not t_closed.empty:
            if "Austria" in rpt_country and "at_category" in t_closed.columns:
                for cat, label, kz_p, kz_l in [
                    ("aktien", "Stocks/ETFs/Funds", 994, 892),
                    ("derivate", "Derivatives/Options", 995, 896),
                ]:
                    cat_df = t_closed[t_closed["at_category"] == cat]
                    report_dict[f"{label} - KZ {kz_p} (Profits, {base_ccy})"] = round(
                        cat_df[cat_df["realized_pl_base"] > 0]["realized_pl_base"].sum(), 2
                    )
                    report_dict[f"{label} - KZ {kz_l} (Losses, {base_ccy})"] = round(
                        cat_df[cat_df["realized_pl_base"] < 0]["realized_pl_base"].sum(), 2
                    )
            elif "it_category" in t_closed.columns:
                for cat, label, rigo_p, rigo_l in [
                    ("non_qualified", "Non-qualified", "RT51", "RT53"),
                    ("derivatives", "Derivatives", "RT31", "RT32"),
                    ("crypto", "Crypto", "RT88", "RT89"),
                ]:
                    cat_df = t_closed[t_closed["it_category"] == cat]
                    report_dict[f"{label} - {rigo_p} (Gains, {base_ccy})"] = round(
                        cat_df[cat_df["realized_pl_base"] > 0]["realized_pl_base"].sum(), 2
                    )
                    report_dict[f"{label} - {rigo_l} (Losses, {base_ccy})"] = round(
                        cat_df[cat_df["realized_pl_base"] < 0]["realized_pl_base"].sum(), 2
                    )
            # Add RM and RW data for Italy
            if "Italia" in rpt_country:
                report_dict[f"RM31 - Interessi fonte estera ({base_ccy})"] = round(
                    data.get("interests_total_eur", 0.0), 2
                )
                report_dict[f"RM31 - Interessi importo BCE ({base_ccy})"] = round(
                    data.get("interests_total_base", 0.0), 2
                )
                nav_init = data.get("nav_change", {}).get("Valore iniziale", 0)
                nav_fin = data.get("nav_change", {}).get("Valore finale", 0)
                report_dict[f"RW - Patrimonio iniziale ({base_ccy})"] = round(nav_init, 2)
                report_dict[f"RW - Patrimonio finale ({base_ccy})"] = round(nav_fin, 2)
                report_dict[f"RW - Valore medio ({base_ccy})"] = round((nav_init + nav_fin) / 2, 2)
    except (NameError, AttributeError):
        pass

    col_btn1, col_btn2 = st.columns(2)
    with col_btn1:
        def clean_val(v):
            try:
                import numpy as np
                if isinstance(v, (np.float64, np.float32, np.int64, np.int32)):
                    return float(v)
            except ImportError:
                pass
            return v

        json_ready_report = {k: clean_val(v) for k, v in report_dict.items()}

        st.download_button(
            label="💾 Scarica Report JSON",
            data=json.dumps(json_ready_report, indent=4),
            file_name=f"IBKR_Tax_Report_{datetime.date.today()}.json",
            mime="application/json"
        )
    with col_btn2:
        pdf_data = create_pdf_report(report_dict, rpt_country)
        st.download_button(
            label="📄 Scarica Report PDF",
            data=pdf_data,
            file_name=f"IBKR_Tax_Report_{datetime.date.today()}.pdf",
            mime="application/pdf"
        )


# ─── TAB 5: AI Assistant ────────────────────────────────────────────────────
with tab_ai:
    st.subheader("🤖 AI Tax & Trading Analyst")

    if not TraderAgent:
        st.warning(
            "AI Agent non disponibile. Installa il pacchetto `custom_agents`:\n\n"
            "```bash\npip install -e ../../../Custom_Agents\n```"
        )
    else:
        st.markdown("Chiedi all'AI di analizzare i tuoi errori di trading, ottimizzazione fiscale, o qualsiasi domanda sui dati.")

        # Quick action buttons
        st.markdown("**Domande rapide:**")
        qcol1, qcol2, qcol3 = st.columns(3)
        with qcol1:
            if st.button("📊 Analisi errori di trading", use_container_width=True):
                st.session_state.quick_prompt = "Analizza tutti i miei trade in perdita. Per ognuno, spiega cosa è andato storto, identifica pattern di errore comuni e suggerisci miglioramenti concreti."
        with qcol2:
            if st.button("🏛️ Riepilogo fiscale completo", use_container_width=True):
                tax_q = st.session_state.get("tax_country", "🇦🇹 Austria")
                if "Italia" in tax_q:
                    tax_info = "tasse da pagare (Italia 26%)"
                else:
                    tax_info = "tasse da pagare (Austria 27,5%)"
                bc = st.session_state.get("base_currency", "EUR")
                st.session_state.quick_prompt = f"Fornisci un riepilogo fiscale completo: P/L realizzato netto, {tax_info}, commissioni deducibili, e impatto del cambio valuta (conversione in {bc})."
        with qcol3:
            if st.button("🎯 Migliori e peggiori trade", use_container_width=True):
                st.session_state.quick_prompt = "Elenca i 5 migliori e i 5 peggiori trade dell'anno con analisi dettagliata di cosa ha funzionato e cosa no."

        # Chat history
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"], avatar="🤖" if msg["role"] == "assistant" else "👤"):
                st.markdown(msg["content"])

        # Handle quick prompt
        quick = st.session_state.pop("quick_prompt", None)
        if quick:
            st.session_state.chat_history.append({"role": "user", "content": quick})
            with st.chat_message("user", avatar="👤"):
                st.markdown(quick)
            with st.chat_message("assistant", avatar="🤖"):
                with st.spinner("🤖 Analizzando..."):
                    response = _chat_with_ai(quick, data)
                    st.markdown(response)
            st.session_state.chat_history.append({"role": "assistant", "content": response})
            st.rerun()

        # Free chat input
        if user_input := st.chat_input("Chiedi all'AI analista..."):
            st.session_state.chat_history.append({"role": "user", "content": user_input})
            with st.chat_message("user", avatar="👤"):
                st.markdown(user_input)
            with st.chat_message("assistant", avatar="🤖"):
                with st.spinner("🤖 Analizzando..."):
                    response = _chat_with_ai(user_input, data)
                    st.markdown(response)
            st.session_state.chat_history.append({"role": "assistant", "content": response})
            st.rerun()
