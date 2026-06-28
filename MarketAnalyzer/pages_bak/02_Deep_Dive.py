"""Page 2: Deep Dive — Unified 5-dimension verdict."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from agents import DeepDiveAgent, MarketDataAgent
from utils.styles import apply_theme, get_theme

st.markdown('# 🎯 Deep Dive')
st.markdown('Analisi completa 5-dimensioni con verdetto unificato.')

ticker = st.text_input('Ticker', value='HPQ', help='Inserisci un ticker azionario').strip().upper()
run = st.button('🎯 Analizza', type='primary', use_container_width=True)

if not ticker:
    st.warning('Inserisci un ticker.')
    st.stop()

if run or ticker:
    with st.spinner(f'Analisi {ticker} in corso...'):
        dda = DeepDiveAgent()
        mda = MarketDataAgent()
        result = dda.analyze(ticker)

    if 'error' in result:
        st.error(f'Errore: {result["error"]}')
        st.stop()

    theme = get_theme(ticker)
    verdict = result['verdict']
    score = result['final_score']

    # Header
    st.markdown(apply_theme(ticker), unsafe_allow_html=True)
    score_color = '🟢' if score >= 70 else ('🟡' if score >= 50 else '🔴')
    st.markdown(f'# {score_color} {verdict}  —  `{result["ticker"]}`  **{score}/100**')

    info_cols = st.columns(4)
    info_cols[0].metric('Prezzo', f'$ {result["price"]:.2f}')
    info_cols[1].metric('Nome', result.get('name', '')[:20])
    info_cols[2].metric('Direzione', result.get('direction', 'N/A'))
    info_cols[3].metric('Azione', result.get('action', 'N/A')[:20])

    # Gauge
    fig = go.Figure(go.Indicator(
        mode='gauge+number',
        value=score,
        title={'text': 'Score'},
        gauge={
            'axis': {'range': [0, 100], 'tickwidth': 1},
            'bar': {'color': theme['primary']},
            'steps': [
                {'range': [0, 30], 'color': '#ffcccc'},
                {'range': [30, 50], 'color': '#fff3cc'},
                {'range': [50, 70], 'color': '#ccffcc'},
                {'range': [70, 100], 'color': '#99ff99'},
            ],
            'threshold': {
                'line': {'color': 'red', 'width': 4},
                'thickness': 0.75,
                'value': score,
            },
        },
    ))
    fig.update_layout(height=250, margin=dict(l=30, r=30, t=30, b=30))
    st.plotly_chart(fig, use_container_width=True)

    # 5 dimensioni
    st.markdown('---')
    st.markdown('## Dimensioni')
    dims = result.get('dimensions', {})
    dim_data = []
    for name, (sc, wt) in dims.items():
        contrib = sc * wt
        dim_data.append({'Dimensione': name, 'Score': sc, 'Peso': wt, 'Contributo': contrib})
    dim_df = pd.DataFrame(dim_data)
    st.dataframe(dim_df, use_container_width=True, hide_index=True)

    # Dettaglio per dimensione
    tabs = st.tabs(['Wyckoff', 'Volume Profile', 'Price Action', 'Sentiment', 'Fundamentals', 'TATC'])

    with tabs[0]:
        wy = result.get('wyckoff', {})
        st.markdown(f'**Phase:** {wy.get("phase", "N/A")}')
        st.markdown(f'**Score:** {wy.get("score", "N/A")}/100')
        st.markdown(f'**Range position:** {wy.get("range_pct", "N/A")}%')
        st.markdown(f'**Spring:** {"✅" if wy.get("spring") else "❌"}  |  **Upthrust:** {"✅" if wy.get("upthrust") else "❌"}')
        st.markdown(f'**SOS/SOW:** {wy.get("sos", 0)}/{wy.get("sow", 0)}  |  **HH/HL:** {"✅" if wy.get("hh_hl") else "❌"}')
        st.markdown(f'**Volume ratio 20v60:** {wy.get("vol_ratio_20v60", "N/A")}%')

    with tabs[1]:
        vp = result.get('volume_profile', {})
        st.markdown(f'**Shape:** {vp.get("shape", "N/A")}')
        st.markdown(f'**POC:** ${vp.get("poc", "N/A")}')
        st.markdown(f'**VA:** ${vp.get("val", "N/A")} — ${vp.get("vah", "N/A")}')
        st.markdown(f'**Price vs POC:** {vp.get("price_vs_poc", "N/A")}')
        st.markdown(f'**Price vs VA:** {vp.get("price_vs_va", "N/A")}')
        st.markdown(f'**Score:** {vp.get("score", "N/A")}/100')

    with tabs[2]:
        pa = result.get('price_action', {})
        st.markdown(f'**Verdict:** {pa.get("verdict", "N/A")}')
        st.markdown(f'**Score:** {pa.get("score", "N/A")}/100')
        st.markdown(f'**VPA:** Bull={pa.get("vpa_bull", 0)} Bear={pa.get("vpa_bear", 0)} Rev={pa.get("vpa_rev", 0)}')
        st.markdown(f'**Effort/Result:** {pa.get("er", 0)}')
        st.markdown(f'**EMA25:** {"Rising ▲" if pa.get("ema25_up") else "Flat/Falling ▼"}')
        st.markdown(f'**Buildup:** {"✅" if pa.get("buildup") else "❌"}')
        st.markdown(f'**Weis Score:** {pa.get("weis", 0)}')

    with tabs[3]:
        sent = result.get('sentiment', {})
        st.markdown(f'**Score:** {sent.get("score", "N/A")}/100')
        dims6 = sent.get('dimensions', {})
        if dims6:
            sent_df = pd.DataFrame([
                {'Dimensione': dim, 'Score': data['score'], 'Note': data['details'].get('note', '')}
                for dim, data in dims6.items()
            ])
            st.dataframe(sent_df, use_container_width=True, hide_index=True)

    with tabs[4]:
        fund = result.get('fundamentals', {})
        st.markdown(f'**Score:** {fund.get("score", "N/A")}/100')
        st.markdown(f'**P/E:** {fund.get("pe", "N/A")}')
        st.markdown(f'**Revenue Growth:** {fund.get("rev_growth", "N/A")}%')
        st.markdown(f'**Inst. Ownership:** {fund.get("inst_own", "N/A")}%')
        st.markdown(f'**Margins:** {fund.get("margins", "N/A")}%')
        st.markdown(f'**D/E:** {fund.get("dte", "N/A")}')
        if fund.get('reasons'):
            st.markdown('**Ragioni:**')
            for r in fund['reasons']:
                st.caption(f'  → {r}')

    with tabs[5]:
        tatc = result.get('tatc', {})
        st.markdown(f'**Direction:** {tatc.get("direction", "N/A")}')
        st.markdown(f'**Score:** {tatc.get("score", "N/A")}')
        if tatc.get('signals'):
            st.markdown('**Signals:**')
            for s in tatc['signals']:
                st.caption(f'  → {s}')

    # Price chart
    st.markdown('---')
    st.markdown('## Price History')
    hist = mda.get_history(ticker, '6mo')
    if not hist.empty:
        fig2 = go.Figure()
        fig2.add_trace(go.Candlestick(
            x=hist.index, open=hist['Open'], high=hist['High'],
            low=hist['Low'], close=hist['Close'], name='Price',
        ))
        fig2.add_trace(go.Scatter(
            x=hist.index, y=hist['Close'].rolling(50).mean(),
            line=dict(color='orange', width=1), name='MA50',
        ))
        fig2.update_layout(height=400, margin=dict(l=0, r=0, t=0, b=0),
                           xaxis_rangeslider_visible=False)
        st.plotly_chart(fig2, use_container_width=True)
