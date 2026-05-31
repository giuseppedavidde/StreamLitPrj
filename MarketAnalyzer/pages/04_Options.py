"""Page 4: Options Strategist — multi-book strategy selector."""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from agents import OptionsStrategistAgent, OptionsAgent

st.markdown('# 🎲 Options Strategist')
st.markdown('Selezione strategie multi-libro basata su verdetto + IV + DTE.')

osa = OptionsStrategistAgent()
oa = OptionsAgent()

ticker = st.text_input('Ticker', value='HPQ').strip().upper()
col1, col2, col3 = st.columns(3)
with col1:
    verdict_score = st.slider('Verdetto Score (0-100)', 0, 100, 70,
                              help='Dal Deep Dive unificato')
with col2:
    direction = st.selectbox('Direzione', ['Bullish', 'Bearish', 'Neutral', 'Volatile'])
with col3:
    target_dte = st.slider('DTE target', 15, 365, 45)

in_position = st.checkbox('Gia in posizione (azionario)', False)

if st.button('🎲 Suggerisci Strategie', type='primary', use_container_width=True):
    with st.spinner(f'Analizzo strategie per {ticker}...'):
        result = osa.suggest(ticker, verdict_score, direction,
                              in_position=in_position, target_dte=target_dte)

    if not result.get('strategies'):
        st.warning('Nessuna strategia trovata per i parametri dati.')
        st.stop()

    st.markdown(f'**IV Regime:** {result["iv_regime"].upper()}  |  **Prezzo:** ${result["price"]:.2f}')

    df = pd.DataFrame(result['strategies'])
    display = df[['strategy', 'source', 'fit_score', 'outlook', 'max_risk',
                  'suggested_dte', 'theta_profile']].copy()
    display.columns = ['Strategia', 'Fonte', 'Fit', 'Outlook', 'Rischio Max',
                       'DTE', 'Theta']
    display = display.sort_values('Fit', ascending=False)
    st.dataframe(display, use_container_width=True, hide_index=True)

    # Dettaglio strategia
    st.markdown('---')
    st.markdown('## Dettaglio Strategia')
    selected_strat = st.selectbox('Seleziona strategia',
                                   options=[s['strategy'] for s in result['strategies']])
    if selected_strat:
        strat = next(s for s in result['strategies'] if s['strategy'] == selected_strat)
        st.markdown(f'**Descrizione:** {strat["description"]}')
        st.markdown(f'**Fonte:** {strat["source"]}')
        st.markdown(f'**Outlook:** {strat["outlook"]}')
        st.markdown(f'**Rischio Max:** {strat["max_risk"]}')
        st.markdown(f'**Delta approx:** {strat.get("delta_approx", "N/A")}')
        st.markdown(f'**Theta:** {strat.get("theta_profile", "N/A")}')
        st.markdown(f'**Vega:** {strat.get("vega_profile", "N/A")}')
        if strat.get('suggested_expiry'):
            st.markdown(f'**Scadenza suggerita:** {strat["suggested_expiry"]} ({strat.get("suggested_dte", "?")} DTE)')

    # Synthetic Long 2:1
    if any('Synthetic' in s['strategy'] for s in result['strategies']):
        st.markdown('---')
        st.markdown('## 🚀 Synthetic Long 2:1 Quote')
        if st.button('Genera Quote'):
            sl = osa.synthetic_long_2x_quote(ticker, target_dte=target_dte)
            if sl:
                st.json(sl)
            else:
                st.warning('Impossibile quotare Synthetic Long 2:1 — dati opzioni insufficienti.')

    # Payoff chart
    st.markdown('---')
    st.markdown('## Payoff Chart')
    pay_ticker = st.text_input('Payoff Ticker', value=ticker)
    pay_type = st.selectbox('Tipo payoff', ['Bull Call Spread', 'Bear Put Spread', 'Iron Condor'])
    if st.button('Genera Payoff'):
        if pay_type == 'Bull Call Spread':
            price = oa.mda.get_price(pay_ticker)
            expiry = oa.mda.find_closest_expiry(pay_ticker, 60)
            payoff = oa.payoff_scenarios(
                pay_ticker, pay_type,
                strikes=[round(price * 0.95, 1), round(price * 1.05, 1)],
                premiums=[1.5, 0.5],
                sides=['buy call', 'sell call'],
                expiry=expiry or 'N/A',
            )
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=payoff['prices'], y=payoff['at_expiry'],
                                     mode='lines', name='At Expiry'))
            fig.add_trace(go.Scatter(x=payoff['prices'], y=payoff['at_half'],
                                     mode='lines', name='At Half', line=dict(dash='dash')))
            fig.add_hline(y=0, line_color='gray', line_width=0.5)
            for b in payoff['breakevens']:
                fig.add_vline(x=b, line_color='green', line_width=1, line_dash='dot')
            fig.update_layout(height=400, title=f'{pay_ticker} {pay_type}')
            st.plotly_chart(fig, use_container_width=True)

    # Theta decay
    st.markdown('---')
    st.markdown('## Theta Decay')
    th_ticker = st.text_input('Theta Ticker', value=ticker)
    th_strike = st.number_input('Strike', value=round(float(result.get('price', 30)), 1))
    th_type = st.selectbox('Tipo', ['call', 'put'])
    if st.button('Calcola Decay'):
        decay = oa.theta_decay(th_ticker, strike=th_strike, option_type=th_type)
        if decay:
            fig2 = go.Figure()
            fig2.add_trace(go.Scatter(x=[d['dte'] for d in decay],
                                      y=[d['price'] for d in decay],
                                      mode='lines', name='Price'))
            fig2.add_trace(go.Scatter(x=[d['dte'] for d in decay],
                                      y=[d['theta'] for d in decay],
                                      mode='lines', name='Theta', yaxis='y2'))
            fig2.update_layout(
                height=350,
                title=f'{th_ticker} ${th_strike:.1f} {th_type} — Theta Decay',
                yaxis=dict(title='Price'),
                yaxis2=dict(title='Theta', overlaying='y', side='right'),
            )
            st.plotly_chart(fig2, use_container_width=True)
