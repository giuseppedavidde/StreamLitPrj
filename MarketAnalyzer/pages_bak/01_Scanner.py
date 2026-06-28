"""Page 1: Market Scanner — Wyckoff/VP/PA scanning."""

import streamlit as st
import pandas as pd
from agents import ScannerAgent


st.markdown('# 🔍 Scanner')
st.markdown('Scoring Wyckoff + Volume Profile + Price Action + Sentiment + Fundamentali.')

s = ScannerAgent()

col1, col2 = st.columns([2, 1])
with col1:
    ticker_input = st.text_input('Ticker (separati da virgola)', value='HPQ, AAPL, MSFT, NVDA, AMD',
                                 help='Inserisci uno o piu ticker separati da virgola')
with col2:
    run = st.button('🔍 Scansiona', type='primary', use_container_width=True)

if run or not st.session_state.get('scanner_run'):
    st.session_state['scanner_run'] = True
    tickers = [t.strip().upper() for t in ticker_input.split(',') if t.strip()]
    if not tickers:
        st.warning('Inserisci almeno un ticker.')
        st.stop()

    with st.spinner(f'Scansiono {len(tickers)} ticker...'):
        results = []
        progress = st.progress(0)
        for i, ticker in enumerate(tickers):
            try:
                r = s.scan(ticker)
                if 'error' not in r:
                    results.append(r)
            except Exception as e:
                st.error(f'{ticker}: {e}')
            progress.progress((i + 1) / len(tickers))

    if not results:
        st.warning('Nessun risultato valido.')
        st.stop()

    df = pd.DataFrame(results)
    display_cols = ['ticker', 'final_score', 'wyckoff', 'volprof', 'pa', 'sentiment', 'fundamentals', 'pattern']
    df_display = df[[c for c in display_cols if c in df.columns]].copy()
    df_display.columns = ['Ticker', 'Score', 'Wyckoff', 'VP', 'PA', 'Sent', 'Fund', 'Pattern']

    df_display = df_display.sort_values('Score', ascending=False)
    st.dataframe(df_display, use_container_width=True, hide_index=True)

    if len(results) == 1:
        r = results[0]
        st.markdown('---')
        col_a, col_b, col_c, col_d, col_e = st.columns(5)
        score_color = '🟢' if r['final_score'] >= 70 else ('🟡' if r['final_score'] >= 50 else '🔴')
        col_a.metric('Score', f'{r["final_score"]}/100', score_color)
        col_b.metric('Wyckoff', r['wyckoff'])
        col_c.metric('Volume Profile', r['volprof'])
        col_d.metric('Price Action', r['pa'])
        col_e.metric('Pattern', r['pattern'][:15])

        st.markdown('**Dettaglio dimensioni:**')
        for dim, detail in r.get('details', {}).items():
            if detail:
                st.caption(f'  **{dim}:** {detail}')
