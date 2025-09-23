import yfinance as yf
import pandas as pd
import numpy as np
import streamlit as st


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

ticker = st.text_input("Ticker (es. AAPL)", value="DUOL").strip().upper()
period = st.selectbox(
    "Periodo storico", ["1y", "2y", "6mo", "3mo", "1mo", "5y"], index=0
)
window = st.slider("Finestra (giorni) per pivot locale (prima/dopo)", 1, 60, 14)
tol_type = st.radio(
    "Tipo di tolleranza per raggruppamento livelli",
    ("relativa (%)", "assoluta (valore)"),
)
if tol_type == "relativa (%)":
    tol_rel = st.slider("Tolleranza relativa (%)", 0.1, 10.0, 0.5) / 100.0
    tol_abs = None
else:
    tol_abs = st.number_input("Tolleranza assoluta (es. 0.5)", min_value=0.0, value=0.5)
    tol_rel = 0.005

debug = st.checkbox("Mostra debug step-by-step", value=False)

if st.button("Calcola e mostra supporti/resistenze"):
    if not ticker:
        st.error("Inserisci un ticker valido.")
    else:
        try:
            valid_data = True
            data = None
            close = None

            # 1) Download dei dati
            try:
                data = yf.download(ticker, period=period, progress=False)
                if data is None or getattr(data, "empty", True):
                    st.error("Impossibile scaricare i dati per il ticker richiesto.")
                    valid_data = False
            except (ValueError, KeyError) as e:
                st.error(f"Errore durante il download dei dati: {str(e)}")
                valid_data = False

            if valid_data:
                if data is None or "Close" not in data.columns:
                    st.error("Colonna Close non presente nei dati scaricati.")
                    valid_data = False
                else:
                    # 2) Preparazione serie temporale
                    close = data["Close"].dropna()
                    close.index = pd.to_datetime(close.index)
                    if debug:
                        st.write("Dati Close (prime righe):")
                        st.dataframe(close.head(10))

                    if len(close) < 2 * window + 1:
                        st.warning(
                            "Serie troppo corta per la finestra richiesta. Riduci la finestra o scegli un periodo più lungo."
                        )
                        valid_data = False

            if valid_data and close is not None:
                # 3) Trova pivot locali
                res_pivots, sup_pivots = find_pivots(close, window)
                if debug:
                    st.write("Pivot (raw) - resistenze:", res_pivots)
                    st.write("Pivot (raw) - supporti:", sup_pivots)

                # 4) Clusterizza i livelli vicini
                clustered_res = cluster_levels(
                    res_pivots, cluster_tol_abs=tol_abs, tol_rel=tol_rel
                )
                clustered_sup = cluster_levels(
                    sup_pivots, cluster_tol_abs=tol_abs, tol_rel=tol_rel
                )
                if debug:
                    st.write("Resistenze clusterizzate:", clustered_res)
                    st.write("Supporti clusterizzati:", clustered_sup)

                # 5) Prepara DataFrame e mostra grafico
                plot_df = prepare_plot_df(close, clustered_res, clustered_sup)
                st.line_chart(plot_df)

                # 6) Mostra livelli tabellati
                st.subheader("Livelli di Resistenza (dall'alto verso il basso)")
                if clustered_res:
                    for i, r in enumerate(sorted(clustered_res, reverse=True), start=1):
                        st.write(f"R{i}: {r:.4f}")
                else:
                    st.write("Nessuna resistenza trovata.")

                st.subheader("Livelli di Supporto (dal basso verso l'alto)")
                if clustered_sup:
                    for i, s in enumerate(sorted(clustered_sup), start=1):
                        st.write(f"S{i}: {s:.4f}")
                else:
                    st.write("Nessun supporto trovato.")

                # 7) Export CSV
                # Prepara liste di uguale lunghezza aggiungendo None per bilanciare
                res_list = sorted(clustered_res, reverse=True) if clustered_res else []
                sup_list = sorted(clustered_sup) if clustered_sup else []
                max_len = max(len(res_list), len(sup_list))
                res_list.extend([None] * (max_len - len(res_list)))
                sup_list.extend([None] * (max_len - len(sup_list)))

                levels_df = pd.DataFrame(
                    {
                        "resistances": res_list,
                        "supports": sup_list,
                    }
                )
                csv = levels_df.to_csv(index=False, na_rep="")
                st.download_button(
                    "Scarica livelli (CSV)", data=csv, file_name=f"{ticker}_levels.csv"
                )

        except (ValueError, KeyError) as e:
            st.error(f"Si è verificato un errore durante l'elaborazione: {str(e)}")
        except Exception as e:
            st.error("Errore imprevisto durante l'elaborazione.")
