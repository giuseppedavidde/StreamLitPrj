"""Budget App"""
import time
import os
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from dotenv import load_dotenv

# Carica variabili d'ambiente
load_dotenv()

# Import AI Provider
try:
    from agents.ai_provider import AIProvider
    from agents.cloud_manager import CloudManager
except ImportError as e:
    st.error(f"Modulo 'agents' non trovato o errore importazione: {e}")
    AIProvider = None 
    CloudManager = None

# Configurazione Pagina
st.set_page_config(page_title="Budget Manager", page_icon="💰", layout="wide")


DATA_FILE = 'budget_database.csv'

# --- Funzioni di Caricamento e Salvataggio ---
def load_data():
    """Carica i dati dal file CSV"""
    try:
        df = pd.read_csv(DATA_FILE)
        # Assicuriamoci che i dati siano ordinati
        df = df.sort_values(by=['Year', 'MonthNum'], ascending=[False, False])
        return df
    except FileNotFoundError:
        st.error(f"File {DATA_FILE} non trovato. Esegui prima lo script di migrazione!")
        return pd.DataFrame()

def save_data(df):
    """Salva i dati nel file CSV"""
    df.to_csv(DATA_FILE, index=False)
    st.toast("Dati salvati con successo!", icon="✅")

# --- Calcoli ---
def calculate_metrics(df):
    """Calcola le metriche"""
    cols = df.columns.tolist()
    
    # Colonne da escludere dai calcoli di somma (metadati o colonne calcolate esistenti)
    excluded_from_sum = ['Year', 'MonthNum', 'Month', 'Notes', 'Reddito meno spese', 'Risparmio %', 'Totale Entrate', 'Totale Uscite']
    
    # Definisci esplicitamente le entrate (evita match parziali errati)
    income_cols = ['Stipendio', 'Reddito aggiuntivo']
    
    # Verifica che le colonne esistano effettivamente nel DF (per sicurezza)
    income_cols = [c for c in income_cols if c in cols]
    
    # Tutto il resto (non escluso e non entrata) è una spesa
    expense_cols = [c for c in cols if c not in income_cols and c not in excluded_from_sum]
    
    # Calcolo Totali
    df['Totale Entrate'] = df[income_cols].sum(axis=1)
    df['Totale Uscite'] = df[expense_cols].sum(axis=1)
    
    # Ricalcolo colonne derivate (sovrascrive quelle del CSV per coerenza)
    df['Reddito meno spese'] = df['Totale Entrate'] - df['Totale Uscite']
    
    # Gestione divisione per zero
    df['Risparmio %'] = df.apply(
        lambda row: (row['Reddito meno spese'] / row['Totale Entrate'] * 100) if row['Totale Entrate'] != 0 else 0, 
        axis=1
    )
    
    return df, expense_cols, income_cols

# --- Interfaccia Utente ---
try:
    from agents.cloud_ui import render_cloud_sync_ui
except ImportError:
    st.error("Modulo 'agents.cloud_ui' non trovato.")
    def render_cloud_sync_ui(DATA_FILE, is_sidebar=True):
        st.error("Funzione Cloud UI non disponibile")
st.title("💰 Gestione Budget Personale")

df = load_data()

if not df.empty:
    df, expense_cols, income_cols = calculate_metrics(df)

    # Sidebar per navigazione
    page = st.sidebar.radio("Navigazione", ["Dashboard", "Gestione Dati", "Gestione Mese", "💬 Assistant AI"])

    # --- PAGINA DASHBOARD ---
    # --- PAGINA DASHBOARD ---
    if page == "Dashboard":
        # Custom CSS per card effect
        st.markdown("""
        <style>
        .metric-card {
            background-color: #1E1E1E;
            padding: 15px;
            border-radius: 10px;
            border: 1px solid #333;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        }
        </style>
        """, unsafe_allow_html=True)
        
        st.header("📊 Dashboard")
        
        # --- 0. PREPARAZIONE DATI GLOBALE ---
        df['DateStr'] = df['Year'].astype(str) + "-" + df['MonthNum'].astype(str).str.zfill(2)
        df['DateObj'] = pd.to_datetime(df['DateStr'])
        # Ordiniamo dal passato al presente per calcolo commulativo corretto
        df_sorted_asc = df.sort_values('DateObj', ascending=True)
        df_sorted_asc['Patrimonio'] = df_sorted_asc['Reddito meno spese'].cumsum()
        
        # Ri-ordiniamo decrescente per la visualizzazione (Mese corrente in alto)
        df = df_sorted_asc.sort_values('DateObj', ascending=False)
        
        # --- 1. SETTINGS INTELLIGENZA ARTIFICIALE (Sidebar) ---
        st.sidebar.divider()
        with st.sidebar.expander("🤖 Configurazione AI", expanded=False):
            provider_type = st.selectbox("Provider", ["Gemini", "Ollama"], index=0)
            
            api_key = None
            model_name = None
            
            if provider_type == "Gemini":
                # Recupera API Key da Env o Input
                env_key = os.getenv("GOOGLE_API_KEY")
                api_key = st.text_input("Gemini API Key", value=env_key if env_key else "", type="password", help="Se presente nel file .env verra' caricata automaticamente")
                
                # Recupera lista modelli da AIProvider
                gemini_models = AIProvider.FALLBACK_ORDER
                model_name = st.selectbox("Modello", gemini_models, index=0)
            else:
                # Ollama
                if AIProvider:
                    ollama_models = AIProvider.get_ollama_models()
                    if ollama_models:
                        model_name = st.selectbox("Modello Locale", ollama_models, index=0)
                    else:
                        st.warning("Nessun modello Ollama trovato o Ollama non in esecuzione.")
                        model_name = st.text_input("Nome Modello Manuale", value="llama3")

            # Inizializza Provider nel Session State
            if st.button("Applica Configurazione AI"):
                if AIProvider:
                    try:
                        st.session_state['ai_provider'] = AIProvider(
                            api_key=api_key, 
                            provider_type=provider_type, 
                            model_name=model_name
                        )
                        st.toast(f"AI Attivata: {provider_type} ({model_name})", icon="🟢")
                    except Exception as e:
                        st.error(f"Errore Init AI: {e}")

        # --- 1b. CLOUD DATA SYNC (Sidebar) ---
        render_cloud_sync_ui(DATA_FILE, is_sidebar=True)

        # --- 2. FILTRI TEMPORALI (Sidebar) ---
        st.sidebar.divider()
        st.sidebar.subheader("📅 Filtri Temporali")
        
        # Selettore Mese
        available_months = (df['Month'] + " " + df['Year'].astype(str)).tolist()
        selected_month_str = st.sidebar.selectbox("Seleziona Mese", available_months, index=0)
        
        # Filtro Orizzonte Temporale (Globale per Trend e Patrimonio)
        time_options = [3, 6, 12, 24, "All"]
        selected_time_window = st.sidebar.select_slider("Orizzonte Trend (Mesi)", options=time_options, value=12)
        
        # --- DATI MESE SELEZIONATO ---
        sel_month, sel_year = selected_month_str.split(" ")
        sel_year = int(sel_year)
        selected_row = df[(df['Month'] == sel_month) & (df['Year'] == sel_year)].iloc[0]
        
        # --- 2. NET WORTH & GROWTH (Top Section) ---
        # Calcolo Delta Patrimonio nell'orizzonte temporale selezionato
        current_net_worth = selected_row['Patrimonio']
        
        growth_val = 0
        growth_pct = 0
        has_growth_data = False
        
        if selected_time_window != "All":
            months_back = int(selected_time_window)
            # Troviamo la riga di N mesi fa (approssimato per indice se i dati sono contigui, 
            # ma meglio usare shift o ricerca data. Qui assumiamo continuità per semplicità o cerchiamo nel df)
            # Cerchiamo la data target
            target_date = selected_row['DateObj'] - pd.DateOffset(months=months_back)
            # Troviamo il record più vicino (o esatto) nel passato
            past_records = df[df['DateObj'] <= target_date]
            
            if not past_records.empty:
                past_row = past_records.iloc[0] # Il primo è il più recente tra quelli passati (essendo ordinato desc)
                past_net_worth = past_row['Patrimonio']
                growth_val = current_net_worth - past_net_worth
                growth_pct = (growth_val / abs(past_net_worth) * 100) if past_net_worth != 0 else 0
                has_growth_data = True
        else:
             # All time growth (scartando il valore iniziale se 0, o semplicemente totale accumulato)
             # Patrimonio è cumulativo, quindi 'growth' all time è sostanzialmente il valore attuale (se partiti da 0)
             growth_val = current_net_worth
             has_growth_data = True

        # Display Top Metrics
        with st.container(border=True):
            tc1, tc2 = st.columns([3, 1])
            tc1.metric(
                label="🏦 PATRIMONIO TOTALE PROIETTATO", 
                value=f"€ {current_net_worth:,.2f}", 
                delta=f"{'+' if growth_val >= 0 else ''}€ {growth_val:,.2f} ({growth_pct:.1f}%) negli ultimi {selected_time_window} mesi" if has_growth_data else None
            )
            # Mini sparkline o info extra? Mettiamo data riferimento
            tc2.caption(f"Al {selected_row['Month']} {selected_row['Year']}")


        # --- 3. TOP ROW (Gauge + KPI) ---
        col_gauge, col_kpi = st.columns([1, 2])
        
        with col_gauge:
            # Guage Plotly
            fig_gauge = go.Figure(go.Indicator(
                mode = "gauge+number+delta",
                value = selected_row['Risparmio %'],
                title = {'text': "Risparmio Mensile %"},
                delta = {'reference': 20, 'increasing': {'color': "green"}}, # Target 20%
                gauge = {
                    'axis': {'range': [-100, 100], 'tickwidth': 1, 'tickcolor': "white"},
                    'bar': {'color': "#2ecc71" if selected_row['Risparmio %'] > 0 else "#e74c3c"},
                    'bgcolor': "rgba(0,0,0,0)",
                    'borderwidth': 2,
                    'bordercolor': "#333",
                    'steps': [
                        {'range': [-100, 0], 'color': '#550000'},
                        {'range': [0, 20], 'color': '#555500'},
                        {'range': [20, 100], 'color': '#005500'}
                    ],
                }
            ))
            fig_gauge.update_layout(
                paper_bgcolor="rgba(0,0,0,0)", 
                font={'color': "white"}, 
                margin=dict(l=20, r=20, t=50, b=20),
                height=300
            )
            st.plotly_chart(fig_gauge, width='stretch')
            
            # Valore assoluto sotto il gauge
            st.markdown(f"<h3 style='text-align: center; color: {'#2ecc71' if selected_row['Reddito meno spese'] > 0 else '#e74c3c'}'>€ {selected_row['Reddito meno spese']:,.2f}</h3>", unsafe_allow_html=True)

        with col_kpi:
            # Cards metrics using st_container
            with st.container(border=True):
                c1, c2 = st.columns(2)
                c1.metric("Entrate Totali", f"€ {selected_row['Totale Entrate']:,.2f}", delta="Incasassato")
                c2.metric("Uscite Totali", f"€ {selected_row['Totale Uscite']:,.2f}", delta="- Speso", delta_color="inverse")
            
            st.write("") # Spacer
            
            # Trova la categoria di spesa maggiore
            expenses_only = selected_row[expense_cols]
            top_cat = expenses_only.idxmax()
            top_val = expenses_only.max()
            
            with st.container(border=True):
                st.subheader("⚠️ Categoria Critica")
                st.write(f"**{top_cat}**: € {top_val:,.2f}")
                st.progress(min(top_val / (selected_row['Totale Entrate'] or 1), 1.0), text="Pressione sul Budget")

        # --- 4. MIDDLE ROW (Cash Flow Trend) ---
        # Preparazione dati trend (già calcolati globalmente in parte)
        df_trend = df.sort_values('DateObj')
        
        st.subheader("🌊 Flusso di Cassa")
        
        if selected_time_window != "All":
            df_trend = df_trend.tail(int(selected_time_window))
        
        fig_trend = go.Figure()
        fig_trend.add_trace(go.Scatter(
            x=df_trend['DateObj'], y=df_trend['Totale Entrate'], 
            fill='tozeroy', mode='lines', name='Entrate', 
            line=dict(color='#2ecc71', width=3),
            fillcolor='rgba(46, 204, 113, 0.1)'
        ))
        fig_trend.add_trace(go.Scatter(
            x=df_trend['DateObj'], y=df_trend['Totale Uscite'], 
            fill='tozeroy', mode='lines', name='Uscite', 
            line=dict(color='#e74c3c', width=3),
            fillcolor='rgba(231, 76, 60, 0.1)'
        ))
        
        # Trova la data selezionata come oggetto datetime
        selected_date_obj = pd.to_datetime(selected_row['DateStr'])
        
        # Evidenzia il mese selezionato - ora passando un datetime funziona
        fig_trend.add_vline(x=selected_date_obj.timestamp() * 1000, # Plotly a volte preferisce timestamp ms per assi date
                            line_width=1, line_dash="dash", line_color="white", annotation_text="Selected")

        fig_trend.update_layout(
            template='plotly_dark',
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis_title="",
            yaxis_title="€ Euro",
            xaxis=dict(
                type='date' # Assicura che l'asse sia trattato come data
            ),
            hovermode="x unified",
            margin=dict(l=0, r=0, t=30, b=0),
            height=350,
            legend=dict(orientation="h", y=1.1)
        )
        st.plotly_chart(fig_trend, width='stretch')

        # --- 4. BOTTOM ROW (Breakdown) ---
        c_donut, c_details = st.columns([1, 1])
        
        with c_donut:
            st.subheader("🍩 Breakdown Spese")
            # Filter > 0 per il grafico a Torta (i negativi rompono la visualizzazione settori)
            pie_data = expenses_only[expenses_only > 0]
            
            fig_pie = px.pie(
                values=pie_data.values, 
                names=pie_data.index, 
                hole=0.6,
                color_discrete_sequence=px.colors.qualitative.Pastel
            )
            fig_pie.update_layout(
                template='plotly_dark',
                paper_bgcolor="rgba(0,0,0,0)",
                margin=dict(l=0, r=0, t=30, b=0),
                showlegend=True,
                height=350
            )
            st.plotly_chart(fig_pie, width='stretch')

        with c_details:
            st.subheader("📋 Dettaglio Spese")
            
            # Per la TABELLA includiamo anche i valori negativi (Rimborsi/Storni)
            # Filter != 0 (escludiamo solo gli zero assoluti)
            table_data = expenses_only[expenses_only != 0]
            
            # Ordina spese (dal più costoso al più "negativo")
            sorted_expenses = table_data.sort_values(ascending=False).to_frame(name="Importo")
            
            # Usa la somma delle spese POSITIVE come denominatore per la %
            # Questo permette di avere % sensate per le spese vere, e % negative per i rimborsi (es. -10% rispetto allo speso)
            total_positive_expenses = expenses_only[expenses_only > 0].sum()
            
            if total_positive_expenses > 0:
                sorted_expenses['%'] = ((sorted_expenses['Importo'] / total_positive_expenses * 100).astype(float).round(1).astype(str) + '%')
            else:
                 sorted_expenses['%'] = "0%"

            # Top 5 Voci (Spese più alte)
            st.write("**Top 5 Voci**")
            st.dataframe(
                sorted_expenses.head(5).style.format({'Importo': '€ {:,.2f}'}), 
                width='stretch',
                height=250
            )
            
            # Altre Spese & Rimborsi (tutto il resto)
            if len(sorted_expenses) > 5:
                # Se ci sono valori negativi spesso finiscono in fondo
                has_negatives = (sorted_expenses['Importo'] < 0).any()
                label_expander = "🔍 Altre Spese e Rimborsi" if has_negatives else "🔍 Altre Spese"
                
                with st.expander(label_expander):
                    st.dataframe(
                        sorted_expenses.iloc[5:].style.format({'Importo': '€ {:,.2f}'}), 
                        width='stretch'
                    )

        st.divider()

        # --- 5. ADVANCED STATS SECTION ---
        st.header("🏆 Analisi Risparmio Avanzata")
        
        with st.container(border=True):
            # A) Trend Risparmio %
            st.subheader("📈 Andamento % Risparmio")
            fig_sav = go.Figure()
            
            # Coloriamo la linea in base al valore (Verde positivo, Rosso negativo)
            # Plotly non ha 'gradient line' nativo semplice, usiamo marker color map o semplicemente linea
            # Usiamo Bar chart per vedere meglio positivi/negativi o Linea + Area? Linea è richiesta.
            
            df_trend_all = df.sort_values('DateObj') # Tutto lo storico per il trend di lungo periodo
            
            fig_sav.add_trace(go.Scatter(
                x=df_trend_all['DateObj'], y=df_trend_all['Risparmio %'],
                mode='lines+markers',
                name='Risparmio %',
                line=dict(width=3, color='#f1c40f'), # Giallo/Oro per focus
                hovertemplate='%{y:.1f}%<extra></extra>'
            ))
            
            # Linea 0
            fig_sav.add_hline(y=0, line_dash="dash", line_color="white", opacity=0.3)
            # Linea Obiettivo (es. 20%)
            fig_sav.add_hline(y=20, line_dash="dash", line_color="#2ecc71", opacity=0.5, annotation_text="Obiettivo 20%")

            fig_sav.update_layout(
                template='plotly_dark',
                paper_bgcolor="rgba(0,0,0,0)",
                plot_bgcolor="rgba(0,0,0,0)",
                xaxis_title="",
                yaxis_title="%",
                height=300,
                margin=dict(l=0, r=0, t=30, b=0)
            )
            st.plotly_chart(fig_sav, width='stretch')

            c_best, c_drivers = st.columns([1, 1])
            
            with c_best:
                st.subheader("🌟 Mesi Migliori")
                # Top 3 Mesi per Risparmio %
                best_months = df.sort_values('Risparmio %', ascending=False).head(3)
                
                for i, (_, row) in enumerate(best_months.iterrows()):
                    with st.container(border=True):
                        cols = st.columns([1, 2])
                        cols[0].metric(f"#{i+1}", f"{row['Risparmio %']:.1f}%")
                        cols[1].write(f"**{row['Month']} {row['Year']}**")
                        cols[1].caption(f"Netto: € {row['Reddito meno spese']:,.0f}")

            with c_drivers:
                st.subheader("🔍 Driver di Successo")
                # Analisi: Confrontiamo il MIGLIOR mese con la MEDIA storica delle spese
                if not best_months.empty:
                    best_month_row = best_months.iloc[0]
                    avg_expenses = df[expense_cols].mean()
                    best_month_expenses = best_month_row[expense_cols]
                    
                    # Calcola differenze (Negativo = Ho speso MENO della media -> Bene)
                    diffs = best_month_expenses - avg_expenses
                    
                    # Prendiamo i top 3 'risparmi' (differenze più negative)
                    savings_drivers = diffs.sort_values().head(3)
                    
                    st.write(f"Nel tuo mese migliore (**{best_month_row['Month']} {best_month_row['Year']}**), hai speso molto meno della media in:")
                    
                    for cat, diff in savings_drivers.items():
                        if diff < 0: # Solo se effettivamente c'è stato risparmio
                             st.markdown(f"- **{cat}**: :green[**€ {diff:,.0f}**] rispetto alla media")
                        else:
                            st.write("Nessuna riduzione significativa di spese trovata rispetto alla media.")
                    
                    # Contributo Entrate (Se il successo è dovuto a più guadagno)
                    avg_income = df['Totale Entrate'].mean()
                    income_diff = best_month_row['Totale Entrate'] - avg_income
                    if income_diff > 0:
                        st.markdown(f"💰 Inoltre, hai guadagnato :green[**€ {income_diff:,.0f}**] in più della media.")
                else:
                    st.info("Dati insufficienti per l'analisi.")

    # --- PAGINA GESTIONE DATI (EDIT) ---
    elif page == "Gestione Dati":
        st.header("📝 Modifica Dati")
        st.info("Modifica i valori direttamente nella tabella qui sotto. Le colonne dei Totali sono calcolate automaticamente.")
        
        # Mostriamo solo le colonne editabili (escludiamo i totali calcolati)
        editable_cols = ['Year', 'MonthNum', 'Month'] + income_cols + expense_cols
        
        edited_df = st.data_editor(
            df[editable_cols],
            num_rows="dynamic",
            width='stretch',
            height=600,
            column_config={
                "Year": st.column_config.NumberColumn("Anno", format="%d"),
                "MonthNum": st.column_config.NumberColumn("Mese (Num)", format="%d"),
            }
        )

        # Pulsante per salvare
        if st.button("Salva Modifiche", type="primary"):
            # Salviamo solo le colonne editabili, i totali si ricalcolano al reload
            save_data(edited_df)
            st.rerun()



    # --- PAGINA GESTIONE MESE (AGGIUNGI/INCREMENTA) ---
    elif page == "Gestione Mese":
        st.header("➕ Gestione Mese")
        st.write("Seleziona il mese e l'anno. Se il mese esiste già, potrai **aggiungere** importi a quelli esistenti (incrementale). Se non esiste, verrà creato.")
        
        # Selezione Periodo (fuori dal form per permettere refresh logico)
        col_y, col_m = st.columns(2)
        today = pd.Timestamp.now()
        year_input = col_y.number_input("Anno", min_value=2020, max_value=2030, value=today.year)
        month_input = col_m.selectbox("Mese", list(df['Month'].unique()), index=today.month - 1 if today.month <= 12 else 0)

        # Mappa inversa per trovare il numero del mese
        month_map = {'January': 1, 'February': 2, 'March': 3, 'April': 4, 'May': 5, 'June': 6,
                        'July': 7, 'August': 8, 'September': 9, 'October': 10, 'November': 11, 'December': 12}
        month_num = month_map.get(month_input, 1)

        # Check esistenza
        existing_mask = (df['Year'] == year_input) & (df['Month'] == month_input)
        is_existing = df[existing_mask].any().any() # Check if any row matches
        
        existing_row = None
        if is_existing:
            existing_row = df[existing_mask].iloc[0]
            st.info(f"📅 **Mese Trovato:** {month_input} {year_input}. **Modalità Incrementale Attiva** (Gli importi inseriti verranno SOMMATI a quelli attuali).")
            # Mostra riepilogo attuale
            with st.expander("Vedi Valori Attuali", expanded=False):
                st.dataframe(existing_row.to_frame().T)
        else:
            st.success(f"✨ **Nuovo Mese:** {month_input} {year_input}. **Modalità Creazione**.")

        with st.form("month_manage_form"):
            st.subheader("Entrate (Aggiungi)")
            new_incomes = {}
            cols = st.columns(len(income_cols))
            for i, col_name in enumerate(income_cols):
                base_val = 0.0
                curr_label = ""
                if is_existing:
                    curr_val = existing_row[col_name]
                    curr_label = f" (Attuale: €{curr_val:,.2f})"
                
                new_incomes[col_name] = cols[i%len(cols)].number_input(f"{col_name}{curr_label}", value=0.0, step=100.0)

            st.subheader("Uscite (Aggiungi)")
            new_expenses = {}
            # Creiamo una griglia per le spese
            cols = st.columns(3) 
            for i, col_name in enumerate(expense_cols):
                curr_label = ""
                if is_existing:
                    curr_val = existing_row[col_name]
                    curr_label = f" (Att: €{curr_val:,.0f})"
                
                new_expenses[col_name] = cols[i%3].number_input(f"{col_name}{curr_label}", value=0.0, step=10.0)

            btn_label = "Aggiorna Mese" if is_existing else "Crea Mese"
            submitted = st.form_submit_button(btn_label)
            
            if submitted:
                if is_existing:
                    # UPDATE LOGIC
                    for col, val in new_incomes.items():
                        if val != 0:
                            df.loc[existing_mask, col] += val
                    
                    for col, val in new_expenses.items():
                        if val != 0:
                            df.loc[existing_mask, col] += val
                    
                    save_data(df)
                    st.success(f"Dati aggiornati per {month_input} {year_input}!")
                    st.rerun()

                else:
                    # CREATE LOGIC
                    new_row = {'Year': year_input, 'Month': month_input, 'MonthNum': month_num}
                    new_row.update(new_incomes)
                    new_row.update(new_expenses)
                    
                    # Aggiungi al dataframe esistente (assicurandoci di avere solo le colonne base)
                    base_df = df[['Year', 'MonthNum', 'Month'] + income_cols + expense_cols]
                    new_df = pd.DataFrame([new_row])
                    updated_df = pd.concat([new_df, base_df], ignore_index=True)
                    
                    save_data(updated_df)
                    st.success("Mese creato con successo!")
                    st.rerun()

    # --- PAGINA AI ASSISTANT ---
    elif page == "💬 Assistant AI":
        st.header("💬 Financial Assistant")
        st.caption("Chiedi al tuo assistente personale informazioni sul tuo budget.")
        
        # Check se il provider è configurato
        if 'ai_provider' not in st.session_state or st.session_state['ai_provider'] is None:
            st.warning("⚠️ Configura prima l'AI nella sidebar (scegli Provider e Modello e clicca Applica).")
        else:
            # 1. Inizializza cronologia chat
            if "messages" not in st.session_state:
                st.session_state.messages = []

            # 2. Visualizza messaggi precedenti
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

            # 3. Input Utente
            if prompt := st.chat_input("Chiedi qualcosa sui tuoi numeri..."):
                # Aggiungi messaggio utente
                st.session_state.messages.append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)

                # 4. Generazione Risposta
                # 4. Generazione Risposta
                with st.chat_message("assistant"):
                    # Preparazione Contesto Dati
                    def get_data_context(df_in):
                        """Crea un contesto testuale dai dati recenti."""
                        # Prendiamo tutti i dati per non intasare il contesto
                        limit = len(df_in) 
                        df_ctx = df_in.head(limit).copy()
                        # Rimuoviamo colonne inutili per leggibilità
                        cols_to_drop = ['DateObj', 'Notes', 'DateStr'] + [c for c in df_ctx.columns if c.startswith('Unnamed')]
                        df_ctx = df_ctx.drop(columns=[c for c in cols_to_drop if c in df_ctx.columns], errors='ignore')
                        
                        csv_data = df_ctx.to_csv(index=False)
                        return f"""
                        SEI UN ESPERTO ANALISTA FINANZIARIO.
                        Analizza i seguenti dati di budget personale (ultimi {limit} mesi).
                        Rispondi in italiano. Sii conciso e diretto. Usa markdown per tabelle o grassetto.
                        
                        ISTRUZIONE IMPORTANTE:
                        Prima di dare la risposta finale, scrivi un blocco riga per riga indicando cosa stai analizzando, iniziando con 'Thinking:'.
                        Esempio:
                        Thinking: Analizzo le entrate degli ultimi 3 mesi...
                        Thinking: Controllo le spese straordinarie...
                        Thinking: Calcolo la media del risparmio...
                        
                        [RISPOSTA FINALE QUI]
                        
                        DATI CSV:
                        {csv_data}
                        """
                    
                    try:
                        # Costruzione Prompt Completo
                        system_context = get_data_context(df)
                        final_prompt = f"{system_context}\n\nDOMANDA UTENTE: {prompt}"
                        
                        # Streaming
                        stream_gen = st.session_state['ai_provider'].get_model().generate_stream(final_prompt)
                        response_text = st.write_stream(stream_gen)
                        
                        st.session_state.messages.append({"role": "assistant", "content": response_text})
                        
                    except Exception as e:
                        err_msg = f"Errore durante l'analisi: {e}"
                        st.error(err_msg)
                        st.session_state.messages.append({"role": "assistant", "content": err_msg})

else:
    # --- SETUP MODE ---
    st.info("👋 Benvenuto! Nessun database trovato. Iniziamo con il setup.")
    st.divider()
    
    col_cloud, col_local = st.columns(2)
    
    with col_cloud:
        st.subheader("☁️ Scarica da Cloud (GitHub)")
        st.write("Collega il tuo account GitHub per scaricare il database.")
        render_cloud_sync_ui(DATA_FILE, is_sidebar=False)
        
    with col_local:
        st.subheader("📂 Carica CSV Locale")
        st.write("Se hai un file `budget_database.csv` locale, caricalo qui.")
        uploaded_file = st.file_uploader("Scegli un file CSV", type="csv")
        
        if uploaded_file is not None:
            try:
                # Leggi per validare (opzionale) o salva direttamente
                with open(DATA_FILE, "wb") as f:
                    f.write(uploaded_file.getbuffer())
                st.success(f"File salvato come {DATA_FILE}! Riavvio app...")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Errore salvataggio: {e}")