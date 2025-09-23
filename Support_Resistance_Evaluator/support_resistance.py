import yfinance as yf
import pandas as pd
import numpy as np
import streamlit as st
from modules.llm_utils import setup_llm, get_options_advice


def find_pivots(series: pd.Series, pivot_window: int, min_points: int = 500):
    """Find local pivots (resistances and supports) in a price series.

    Args:
        series: Serie temporale dei prezzi
        pivot_window: Dimensione della finestra per trovare i pivot
        min_points: Numero minimo di punti prima di applicare il resampling

    Returns:
        Tuple di due liste di float: (resistenze, supporti)
    """
    res = []
    sup = []

    # Se la serie è troppo lunga, facciamo un resampling prima di cercare i pivot
    if len(series) > min_points:
        n_days = (series.index[-1] - series.index[0]).days
        rule = "W" if n_days > 365 * 2 else "D"
        series = series.resample(rule).mean().dropna()

    # Lavoriamo direttamente con la Serie pandas invece di convertire in numpy
    n = len(series)
    if n < 2 * pivot_window + 1:
        return res, sup

    # Calcola i massimi e minimi su finestre mobili per efficienza
    rolling_max = series.rolling(window=2 * pivot_window + 1, center=True).max()
    rolling_min = series.rolling(window=2 * pivot_window + 1, center=True).min()

    # Trova i pivot confrontando i valori con i massimi/minimi locali
    for idx in range(pivot_window, n - pivot_window):
        val = float(series.iloc[idx].item())
        max_val = float(rolling_max.iloc[idx].item())
        min_val = float(rolling_min.iloc[idx].item())

        if np.isclose(val, max_val, atol=1e-8) and val >= max_val:
            res.append(val)
        if np.isclose(val, min_val, atol=1e-8) and val <= min_val:
            sup.append(val)

    return res, sup


def cluster_levels(
    levels: list, cluster_tol_abs: float | None = None, tol_rel: float = 0.005
):
    """Cluster nearby levels into averaged levels.

    If `cluster_tol_abs` is provided, use absolute distance. Otherwise use relative
    tolerance `tol_rel` (fractional).
    """
    if not levels:
        return []
    lv = sorted(float(x) for x in levels)
    clusters = []
    current = [lv[0]]
    for v in lv[1:]:
        ref = float(np.mean(current))
        tol = cluster_tol_abs if cluster_tol_abs is not None else abs(ref * tol_rel)
        if abs(v - ref) <= tol:
            current.append(v)
        else:
            clusters.append(float(np.mean(current)))
            current = [v]
    if current:
        clusters.append(float(np.mean(current)))
    return clusters


def prepare_plot_df(
    close_series: pd.Series, resistances: list, supports: list, max_points: int = 500
):
    """Create a DataFrame for plotting with proper index handling and data reduction.

    Args:
        close_series: Serie temporale dei prezzi di chiusura
        resistances: Lista dei livelli di resistenza
        supports: Lista dei livelli di supporto
        max_points: Numero massimo di punti da plottare (default 500)
    """
    # Resample dei dati se necessario per ridurre i punti
    if len(close_series) > max_points:
        # Calcola l'intervallo di resampling appropriato
        n_days = (close_series.index[-1] - close_series.index[0]).days
        if n_days > 365 * 2:
            rule = "W"  # settimanale per periodi > 2 anni
        else:
            rule = "D"  # giornaliero per periodi più brevi

        # Resample usando la media per ridurre i punti
        close_series = close_series.resample(rule).mean().dropna()

    # Inizializza il DataFrame con la serie Close mantenendo il suo indice
    df = pd.DataFrame(index=close_series.index)
    df["Close"] = close_series

    # Limita il numero di livelli per evitare sovraccarico visivo
    max_levels = 5
    resistances = sorted(resistances, reverse=True)[:max_levels]
    supports = sorted(supports)[:max_levels]

    # Aggiungi i livelli di resistenza e supporto come colonne costanti
    for i, r in enumerate(resistances, start=1):
        df[f"R{i}"] = float(r)
    for i, s in enumerate(supports, start=1):
        df[f"S{i}"] = float(s)
    return df


# --- Streamlit UI ---
st.title("Support & Resistance — Visualizzazione Storica")

# Inizializzazione efficiente dello stato
if "app_state" not in st.session_state:
    st.session_state.app_state = {
        "llm_model": None,
        "chat": {"messages": [], "last_analysis": None},
        "data": {"ticker": None, "price": None, "resistances": [], "supports": []},
    }

# Inizializza LLM solo se necessario
if not st.session_state.app_state["llm_model"]:
    try:
        st.session_state.app_state["llm_model"] = setup_llm()
    except Exception as e:
        st.error(f"Errore configurazione LLM: {str(e)}")

# Layout UI ottimizzato
col1, col2 = st.columns([3, 1])
with col1:
    ticker = st.text_input("Ticker (es. AAPL)", value="DUOL").strip().upper()
    period = st.selectbox(
        "Periodo storico", ["1y", "2y", "6mo", "3mo", "1mo", "5y"], index=0
    )
    window = st.slider("Finestra (giorni) per pivot locale (prima/dopo)", 1, 60, 14)

with col2:
    tol_type = st.radio("Tipo di tolleranza", ("relativa (%)", "assoluta (valore)"))
    if tol_type == "relativa (%)":
        tol_rel = st.slider("Tolleranza (%)", 0.1, 10.0, 0.5) / 100.0
        tol_abs = None
    else:
        tol_abs = st.number_input("Tolleranza", min_value=0.0, value=0.5)
        tol_rel = 0.005

debug = st.checkbox("Debug mode", value=False)

# Tabs per separare analisi e chat
tab1, tab2 = st.tabs(["📊 Analisi Tecnica", "💬 Chat Analista"])

with tab1:
    if st.button("Calcola Livelli"):
        if not ticker:
            st.error("Inserisci un ticker valido.")
        else:
            try:
                # Download e preparazione dati
                with st.spinner("Scaricamento dati..."):
                    data = yf.download(ticker, period=period, progress=False)
                    if data is None or data.empty or "Close" not in data.columns:
                        st.error("Dati non disponibili per questo ticker.")
                    else:
                        close = data["Close"].dropna()
                        close.index = pd.to_datetime(close.index)

                        if len(close) < 2 * window + 1:
                            st.warning(
                                "Serie troppo corta per la finestra selezionata."
                            )

                        else:
                            # Calcolo livelli
                            res_pivots, sup_pivots = find_pivots(close, window)
                            if debug:
                                st.write(
                                    "Pivot trovati:", len(res_pivots) + len(sup_pivots)
                                )

                            # Clusterizza i livelli
                            clustered_res = cluster_levels(
                                res_pivots, cluster_tol_abs=tol_abs, tol_rel=tol_rel
                            )
                            clustered_sup = cluster_levels(
                                sup_pivots, cluster_tol_abs=tol_abs, tol_rel=tol_rel
                            )

                            # Grafico
                            plot_df = prepare_plot_df(
                                close, clustered_res, clustered_sup
                            )
                            st.line_chart(plot_df)

                            # Livelli
                            col3, col4 = st.columns(2)
                            with col3:
                                st.subheader("⬆️ Resistenze")
                                for i, r in enumerate(
                                    sorted(clustered_res, reverse=True), 1
                                ):
                                    st.write(f"R{i}: ${r:.4f}")

                            with col4:
                                st.subheader("⬇️ Supporti")
                                for i, s in enumerate(sorted(clustered_sup), 1):
                                    st.write(f"S{i}: ${s:.4f}")

                            # Export CSV
                            res_list = (
                                sorted(clustered_res, reverse=True)
                                if clustered_res
                                else []
                            )
                            sup_list = sorted(clustered_sup) if clustered_sup else []
                            max_len = max(len(res_list), len(sup_list))
                            res_list.extend([None] * (max_len - len(res_list)))
                            sup_list.extend([None] * (max_len - len(sup_list)))

                            # Export CSV
                            levels_df = pd.DataFrame(
                                {
                                    "resistances": res_list,
                                    "supports": sup_list,
                                }
                            )
                            csv = levels_df.to_csv(index=False, na_rep="")
                            st.download_button(
                                "Scarica livelli (CSV)",
                                data=csv,
                                file_name=f"{ticker}_levels.csv",
                            )

                            # Aggiorna stato per la chat
                            st.session_state.app_state["data"].update(
                                {
                                    "ticker": ticker,
                                    "price": float(close.iloc[-1]),
                                    "resistances": clustered_res,
                                    "supports": clustered_sup,
                                }
                            )
                            # Reset chat solo se cambiano i dati
                            if st.session_state.app_state["chat"]["messages"]:
                                st.session_state.app_state["chat"]["messages"] = []
                                st.session_state.app_state["chat"][
                                    "last_analysis"
                                ] = None

            except Exception as e:
                st.error(f"Errore nell'elaborazione: {str(e)}")

with tab2:
    if not st.session_state.app_state["data"]["ticker"]:
        st.warning("🔍 Prima calcola i livelli tecnici")
    else:
        chat_col1, chat_col2 = st.columns([2, 1])

        with chat_col1:
            st.markdown("### 💬 Conversazione")
            for msg in st.session_state.app_state["chat"]["messages"]:
                st.markdown("---")
                if msg["role"] == "user":
                    st.markdown(f"**👤 Tu**: {msg['content']}")
                else:
                    st.markdown(msg["content"])

        with chat_col2:
            state = st.session_state.app_state

            # Mostra dati tecnici attuali
            st.markdown("### 📊 Livelli Attuali")
            st.markdown(
                f"**{state['data']['ticker']} - ${state['data']['price']:.2f}**"
            )
            st.markdown("**Resistenze**:")
            for r in sorted(state["data"]["resistances"], reverse=True):
                st.markdown(f"- ${r:.2f}")
            st.markdown("**Supporti**:")
            for s in sorted(state["data"]["supports"]):
                st.markdown(f"- ${s:.2f}")

            # Controlli chat
            st.markdown("### 🤖 Azioni")
            if st.button("🔄 Nuova Analisi"):
                with st.spinner("Analisi in corso..."):
                    try:
                        advice = get_options_advice(
                            model=state["llm_model"],
                            ticker=state["data"]["ticker"],
                            current_price=state["data"]["price"],
                            resistances=sorted(
                                state["data"]["resistances"], reverse=True
                            ),
                            supports=sorted(state["data"]["supports"]),
                        )
                        state["chat"]["messages"].append(
                            {"role": "assistant", "content": advice}
                        )
                        state["chat"]["last_analysis"] = advice
                        st.rerun()
                    except Exception as e:
                        st.error(f"Errore analisi: {str(e)}")

            question = st.text_input("💭 La tua domanda:", key="question")
            if st.button("📤 Invia") and question:
                state["chat"]["messages"].append({"role": "user", "content": question})
                with st.spinner("Elaborazione..."):
                    try:
                        response = get_options_advice(
                            model=state["llm_model"],
                            ticker=state["data"]["ticker"],
                            current_price=state["data"]["price"],
                            resistances=state["data"]["resistances"],
                            supports=state["data"]["supports"],
                            context=state["chat"]["last_analysis"],
                            is_follow_up=True,
                            follow_up_question=question,
                        )
                        state["chat"]["messages"].append(
                            {"role": "assistant", "content": response}
                        )
                        st.rerun()
                    except Exception as e:
                        st.error(f"Errore: {str(e)}")

            if st.button("🗑️ Reset Chat"):
                state["chat"]["messages"] = []
                state["chat"]["last_analysis"] = None
                st.rerun()
