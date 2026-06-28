"""Page 3: ETF Explorer — dual mode."""

import streamlit as st
import pandas as pd
from agents import ETFExplorerAgent

st.markdown('# 📈 ETF Explorer')
st.markdown('Due modalita: trova sottovalutati dentro un ETF, o scansiona l\'universo ETF.')

e = ETFExplorerAgent()

mode = st.radio('Modalita', ['🎯 Mode 1: Trova sottovalutati in ETF',
                              '🌐 Mode 2: Scansiona universo ETF'],
                horizontal=True)

if 'Mode 1' in mode:
    st.markdown('---')
    universe = e.list_universe()
    etf_ticker = st.selectbox('Seleziona ETF', options=list(universe.keys()),
                              format_func=lambda t: f'{t} — {universe[t]}', index=2)

    col1, col2 = st.columns(2)
    with col1:
        top_n = st.slider('Top N risultati', 3, 20, 10)
    with col2:
        min_wt = st.slider('Peso minimo %', 0.1, 5.0, 0.5) / 100

    if st.button('🔍 Trova', type='primary', use_container_width=True):
        with st.spinner(f'Scansiono {etf_ticker}...'):
            results = e.mode1_find_undervalued(etf_ticker, top_n=top_n, min_weight=min_wt)

        if not results:
            st.warning('Nessun risultato trovato.')
            st.stop()

        df = pd.DataFrame(results)
        display = df[['ticker', 'final_score', 'wyckoff', 'volprof', 'pa', 'sentiment', 'fundamentals', 'pattern', 'etf_weight']]
        display.columns = ['Ticker', 'Score', 'Wyckoff', 'VP', 'PA', 'Sent', 'Fund', 'Pattern', 'Wt %']
        st.dataframe(display, use_container_width=True, hide_index=True)

        st.markdown('### Sector Exposure')
        sectors = e.get_etf_sector_exposure(etf_ticker)
        if sectors:
            sec_df = pd.DataFrame([
                {'Sector': k.capitalize(), 'Weight': v}
                for k, v in sorted(sectors.items(), key=lambda x: x[1], reverse=True)
            ])
            st.dataframe(sec_df, use_container_width=True, hide_index=True)

        st.markdown('### Top Holdings')
        holdings = e.get_etf_holdings_table(etf_ticker, n=15)
        if not holdings.empty:
            st.dataframe(holdings, use_container_width=True, hide_index=True)

else:
    st.markdown('---')
    col1, col2, col3 = st.columns(3)
    with col1:
        top_n = st.slider('Top N ETF', 3, 15, 5)
    with col2:
        min_ws = st.slider('Peso minimo %', 0.1, 5.0, 0.5) / 100
    with col3:
        min_score = st.slider('Score minimo', 20, 80, 50)

    if st.button('🌐 Scansiona Universo', type='primary', use_container_width=True):
        with st.spinner('Scansiono tutto l\'universo ETF... (ci vuole un po\')'):
            results = e.mode2_scan_universe(
                top_n=top_n, min_weight=min_ws, min_holdings_score=min_score,
            )

        if not results:
            st.warning('Nessun ETF trovato con lo score minimo richiesto.')
            st.stop()

        df = pd.DataFrame(results)
        display = df[['etf_ticker', 'etf_name', 'avg_score', 'holdings_scanned']]
        display.columns = ['Ticker', 'Nome', 'Avg Score', 'Scanned']
        st.dataframe(display, use_container_width=True, hide_index=True)

        st.markdown('### Dettaglio ETF selezionato')
        selected = st.selectbox('Vedi dettaglio', options=[r['etf_ticker'] for r in results])
        if selected:
            sectors = e.get_etf_sector_exposure(selected)
            if sectors:
                sec_df = pd.DataFrame([
                    {'Sector': k.capitalize(), 'Weight': v}
                    for k, v in sorted(sectors.items(), key=lambda x: x[1], reverse=True)
                ])
                st.dataframe(sec_df, use_container_width=True, hide_index=True)
