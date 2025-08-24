import datetime
import json

import streamlit as st
from modules.collect_data_utils import (
    collect_data_from_csv,
    collect_numb_sample,
    get_current_user,
)
from modules.general_utils import (
    dynamic_avg,
    format_percentage,
    month_year,
    pd,
    stipendio_annuo_totale,
    sum,
)
from modules.llm_utils import (
    get_gemini_api_key,
    init_chat_state,
    new_chat,
    query_gemini_flash,
    render_chat,
)
from modules.prediction_models import project_future_values
from modules.streamlit_utils import upload_data_folder

# Streamlit Dashboard Title and Description
st.set_page_config(page_title="Budget Analyzer Dashboard", layout="wide")
st.title("Budget Analyzer Dashboard")
st.markdown(
    """
Analisi interattiva del budget personale: riepilogo, visualizzazioni, confronti e previsioni.
"""
)

from modules.streamlit_utils import upload_data_folder

# --- Data folder selection UI ---
st.sidebar.header("Selezione della cartella dati")
data_source = st.sidebar.radio(
    "Scegli la sorgente dei dati:", ["Upload folder", "Usa cartella locale"], index=1
)
PATH = None
uploaded_files = None
if data_source == "Upload folder":
    PATH, uploaded_files = upload_data_folder()
    if not PATH:
        st.warning("Carica almeno un file CSV per continuare.")
        st.stop()
else:
    PATH = (
        f"C:\\Users\\{get_current_user()}\\Downloads\\Telegram Desktop\\Budget Semplice"
    )

# Time Informations
month, year = month_year()

# Crea una lista di date dal settembre 2021 fino al mese e all'anno correnti
date_list = pd.date_range(start="2021-09", end=f"{year}-{month}", freq="MS")

# Lista delle configurazioni per la raccolta dei dati

data_configurations = [
    ("reddito_aggiuntivo_collect", "Reddito", "Reddito aggiuntivo"),
    ("risparmio_netto_collect", "Netto", "Reddito meno spese"),
    ("reddito_collect", "Reddito", "Reddito totale"),
    ("reddito_only_ifx", "Reddito", "Stipendio"),
    ("spese_collect", "Spese", "Spese totali"),
    ("investment_collect", "Spese", "Investimenti"),
    ("costo_casa_collect", "Spese", "Immobili (affitto, mutuo, tasse, assicurazione)"),
    ("spese_straordinarie_collect", "Spese", "Spese Straordinarie"),
    ("spese_cene_pranzo_collect", "Spese", "Cene, Pranzo"),
    # Aggiungi altre configurazioni qui...
]

# Effettua la raccolta dei dati per ogni configurazione e assegna i risultati alle variabili globali
MULTIPLE_FILES = 1
data_collected = {
    config[0]: collect_data_from_csv(
        path=PATH,
        multiple_files=MULTIPLE_FILES,
        file_name=config[1],
        wanted_regexp=config[2],
        scaling_factor=1,
    )
    for config in data_configurations
}

number_months = collect_numb_sample(PATH, "Reddito")
print(f"Dati Collezionati per {number_months} Mesi")

sum_results = {}
avg_results = {}
perct_avg_results = {}
perct_results = {}

risparmio_invest_liquid_total_list = (
    data_collected["investment_collect"] + data_collected["risparmio_netto_collect"]
)
spese_nette_values = (
    data_collected["spese_collect"] - data_collected["investment_collect"]
)

# Stipendio Calcolato in base all'anno ... Basta prendere ultimo indice e andare di 12 mesi indietro e mediare ///TO IMPLEMENT!

# Variabili specifiche non gestite dal ciclo
stipendio_diviso_per_anni, growth_rate, average_growth_rate, observed_years = (
    stipendio_annuo_totale(PATH, number_months, scaling_factor=1)
)

sum_variables = {
    "reddito_total_list": data_collected["reddito_collect"],
    "investement_total_list": data_collected["investment_collect"],
    "risparmio_total_list": data_collected["risparmio_netto_collect"],
    "spese_nette_total_list": spese_nette_values,
}


operations = {"avg": dynamic_avg, "sum": sum}  # Definisci le operazioni utilizzate

for var_name, data in sum_variables.items():
    if var_name.endswith("_total_list"):  # Se la variabile è per la somma totale
        sum_results[f"{var_name}"], sum_results[f"{var_name}_total"] = operations[
            "sum"
        ](data)

avg_variables = {
    "risparmio_netto_avg_values": data_collected["risparmio_netto_collect"],
    "reddito_avg_values": data_collected["reddito_collect"],
    "reddito_aggiuntivo_avg_values": data_collected["reddito_aggiuntivo_collect"],
    "reddito_only_ifx_avg_values": data_collected["reddito_only_ifx"],
    "investment_collect_avg_values": data_collected["investment_collect"],
    "risparmio_invest_liquid_avg_values": risparmio_invest_liquid_total_list,
    "risparmio_total_avg_values": sum_results["risparmio_total_list"],
    "spese_total_avg_values": data_collected["spese_collect"],
    "spese_nette_avg_values": spese_nette_values,
    "spese_straordinarie_collect_avg_values": data_collected[
        "spese_straordinarie_collect"
    ],
    "costo_casa_avg_values": data_collected["costo_casa_collect"],
    "spese_cene_pranzo_collect_avg_values": data_collected["spese_cene_pranzo_collect"],
}

for var_name, data in avg_variables.items():
    if var_name.endswith("_avg_values"):  # Se la variabile è per la media
        avg_results[f"{var_name}"] = operations["avg"](data)


############### 1. CALCOLI PERCENTUALI SU VALORI MEDI #######################
# Lista di configurazione per i nomi delle variabili percentuali e le loro formule
perct_avg_variables = {
    "costo_casa_perct_avg_values": ("costo_casa_avg_values", "reddito_avg_values"),
    "investement_total_perct_avg_values": (
        "investment_collect_avg_values",
        "reddito_avg_values",
    ),
    "spese_nette_perct_avg_values": ("spese_nette_avg_values", "reddito_avg_values"),
    "risparmio_no_invest_perct_avg_values": (
        "risparmio_netto_avg_values",
        "reddito_avg_values",
    ),
    "risparmio_global_perct_avg_values": (
        "risparmio_invest_liquid_avg_values",
        "reddito_avg_values",
    ),
    "ratio_stipendio_reddito_avg_values": (
        "reddito_only_ifx_avg_values",
        "reddito_avg_values",
    ),
}

# Calcolo delle percentuali medie
for var_name, (numerator, denominator) in perct_avg_variables.items():
    # Calcola e salva il risultato nel dizionario avg_results
    perct_avg_results[f"{var_name}"] = (
        operations["avg"](avg_results[numerator] / avg_results[denominator]) * 100
    )

############# 2. CALCOLI PERCENTUALI SU VALORI PUNTUALI MEDIATI #########
# Lista di configurazione per i nomi delle variabili percentuali e le loro formule sui valori puntuali
perct_variables = {
    "costo_casa_perct_values": ("costo_casa_collect", "reddito_collect"),
    "investement_total_perct_values": ("investment_collect", "reddito_collect"),
    "spese_nette_perct_values": ("spese_nette_values", "reddito_collect"),
    "risparmio_no_invest_perct_values": ("risparmio_netto_collect", "reddito_collect"),
    "risparmio_global_perct_values": (
        "risparmio_invest_liquid_total_list",
        "reddito_collect",
    ),
}

# Calcolo delle percentuali sui valori puntuali mediati
for var_name, (numerator_collect, denominator_collect) in perct_variables.items():
    if numerator_collect.endswith("_nette_values"):
        perct_results[f"{var_name}"] = (
            operations["avg"](spese_nette_values / data_collected[denominator_collect])
            * 100
        )
    elif numerator_collect.endswith("_total_list"):
        perct_results[f"{var_name}"] = (
            operations["avg"](
                risparmio_invest_liquid_total_list / data_collected[denominator_collect]
            )
            * 100
        )
    else:
        perct_results[f"{var_name}"] = (
            operations["avg"](
                data_collected[numerator_collect] / data_collected[denominator_collect]
            )
            * 100
        )

# Dizionario per i dati
data_summary = {
    "Spese Nette Mensili": format_percentage(
        perct_avg_results["spese_nette_perct_avg_values"][-1]
    ),
    "Risparmio (no Investimenti)": format_percentage(
        perct_avg_results["risparmio_no_invest_perct_avg_values"][-1]
    ),
    "Investimenti": format_percentage(
        perct_avg_results["investement_total_perct_avg_values"][-1]
    ),
    "Reddito Medio": f"€ {avg_results['reddito_avg_values'][-1]:.2f}",
    "Stipendio Medio": f"€ {avg_results['reddito_only_ifx_avg_values'][-1]:.2f}",
    "Spesa Netta Media": f"€ {avg_results['spese_nette_avg_values'][-1]:.2f}",
    "Risparmio Medio Mensile con Investimenti": f"€{avg_results['risparmio_invest_liquid_avg_values'][-1]}",
    "Risparmio Medio Mensile senza Investimenti": f"€{avg_results['risparmio_netto_avg_values'][-1]}",
}

# Creazione di un DataFrame pandas
df_summary = pd.DataFrame(
    list(data_summary.items()), columns=["Categoria", "Valore Percentuale"]
)

# Display summary table
st.header("Riepilogo Dati Principali")
st.dataframe(df_summary, use_container_width=True)

# Sidebar for navigation (optional, can be expanded later)
st.sidebar.title("Navigazione")
section = st.sidebar.radio(
    "Vai a sezione:",
    [
        "Riepilogo",
        "Grafici Principali",
        "Confronti",
        "Previsioni (ML)",
    ],
)

# Section: Riepilogo (already shown above)
if section == "Riepilogo":
    st.subheader("Riepilogo sintetico")
    st.dataframe(df_summary, use_container_width=True)
    st.write(f"Dati Collezionati per {number_months} Mesi")

# Dati per i grafici - sostituisci questi con i tuoi dati reali
data = {
    "Risparmio": {
        "data": [
            data_collected["risparmio_netto_collect"],
            avg_results["risparmio_netto_avg_values"],
        ],
        "names": ["Risparmio Netto", "Risparmio Netto Medio"],
    },
    "Reddito": {
        "data": [data_collected["reddito_collect"], avg_results["reddito_avg_values"]],
        "names": ["Reddito Percepito", "Reddito Medio"],
    },
    "Spese Mensili": {
        "data": [
            data_collected["spese_collect"],
            avg_results["spese_total_avg_values"],
        ],
        "names": ["Spese Mensili", "Spese Medie Mensili"],
    },
    "Spese - Investimenti": {
        "data": [spese_nette_values, avg_results["spese_nette_avg_values"]],
        "names": ["Spese - Investimenti Mensili", "Spese - Investimenti Medi"],
    },
    "Spese Straordinarie": {
        "data": [
            data_collected["spese_straordinarie_collect"],
            avg_results["spese_straordinarie_collect_avg_values"],
        ],
        "names": ["Spese Straordinarie", "Spese Straordinarie Medie"],
    },
    "Spese Cene,Pranzo": {
        "data": [
            data_collected["spese_cene_pranzo_collect"],
            avg_results["spese_cene_pranzo_collect_avg_values"],
        ],
        "names": ["Spese Cene,Pranzo", "Spese Cene,Pranzo Medie"],
    },
    "Confronti Reddito, Investimenti, Risparmio": {
        "data": [
            avg_results["investment_collect_avg_values"],
            avg_results["risparmio_total_avg_values"],
            avg_results["reddito_avg_values"],
            sum_results["investement_total_list"],
            sum_results["risparmio_total_list"],
            sum_results["reddito_total_list"],
            sum_results["spese_nette_total_list"],
            data_collected["risparmio_netto_collect"],
            risparmio_invest_liquid_total_list,
            ##stipendio_diviso_per_anni,
        ],
        "names": [
            "Investimenti Mensili Medi",
            "Risparmio Accumulato Medio (Liquidità)",
            "Reddito Mensile Mensile",
            "Investimenti Totali",
            "Risparmio Accumulato (Liquidità)",
            "Reddito Totale",
            "Spese Totali senza Investimenti",
            "Risparmio Mensile senza Investimenti (Liquidità)",
            "Risparmio Liquidità + Investimenti Mensile",
            ##"stipendio diviso per anni"
        ],
    },
    "Confronti Reddito, Investimenti, Risparmio Medio Percentuali": {
        "data": [
            perct_avg_results["investement_total_perct_avg_values"],
            perct_avg_results["risparmio_no_invest_perct_avg_values"],
            perct_avg_results["spese_nette_perct_avg_values"],
            perct_avg_results["risparmio_global_perct_avg_values"],
            perct_avg_results["costo_casa_perct_avg_values"],
        ],
        "names": [
            "Investimenti/Reddito Percentuali AVG Mensili",
            "Risparmio (senza Investimenti)/Reddito Percentuali Accumulato AVG Mensili",
            "Spese Nette/Reddito Percentuali AVG Mensili",
            "Risparmio Globale Percentuali AVG Mensili",
            "Costo Casa AVG Percentuali Mensili",
        ],
    },
    "Confronti Reddito, Investimenti, Risparmio Mensili Percentuali": {
        "data": [
            perct_results["investement_total_perct_values"],
            perct_results["risparmio_no_invest_perct_values"],
            perct_results["spese_nette_perct_values"],
            perct_results["risparmio_global_perct_values"],
            perct_results["costo_casa_perct_values"],
        ],
        "names": [
            "Investimenti/Reddito Percentuali Mensili",
            "Risparmio(senza Investimenti)/Reddito Percentuali Accumulato Mensili",
            "Spese Nette/Reddito Percentuali Mensili",
            "Risparmio Globale Percentuali Mensili",
            "Costo Casa Percentuali Mensili",
        ],
    },
    # Aggiungi altri dataset qui...
}

# Main Plots Section
if section == "Grafici principali":
    st.subheader("Grafici principali del budget")
    # Let user select which main plot to view
    main_plot_options = [
        k for k in data.keys() if not k.startswith("Confronti")
    ]  # Exclude comparison keys
    selected_main_plot = st.selectbox(
        "Seleziona grafico principale:", main_plot_options
    )
    plot_data = data[selected_main_plot]
    from modules import plot_utils

    plot_utils.create_plot(
        x=list(range(len(plot_data["data"][0]))),
        y=plot_data["data"],
        name_trace=plot_data["names"],
        name_graph=selected_main_plot,
        overlap=True,
        n_traces=len(plot_data["data"]),
    )

# Comparisons Section
if section == "Confronti":
    st.subheader("Confronti tra categorie/spese")
    comparison_options = [
        k for k in data.keys() if k.startswith("Confronti")
    ]  # Only comparison keys
    selected_comparison = st.selectbox("Seleziona confronto:", comparison_options)
    plot_data = data[selected_comparison]
    from modules import plot_utils

    plot_utils.create_plot(
        x=list(range(len(plot_data["data"][0]))),
        y=plot_data["data"],
        name_trace=plot_data["names"],
        name_graph=selected_comparison,
        overlap=True,
        n_traces=len(plot_data["data"]),
    )

# ML/Prediction Section
if section == "Previsioni (ML)":
    st.subheader("Previsioni e analisi avanzate")
    st.markdown("#### Previsione spese future")
    months_ahead = st.slider("Mesi da prevedere", 1, 12, 3)
    # Example: use project_future_values for prediction
    try:
        from modules.prediction_models import project_future_values

        # Simulazione
        inflation_rate = 0.02  # % di inflazione annuale
        inflation_rate_salary = 0.015  # scala mobile stipendio
        ratio_stipendio_reddito = perct_avg_results[
            "ratio_stipendio_reddito_avg_values"
        ]
        inflation_rate_avg_reddito = ratio_stipendio_reddito[-1] * inflation_rate_salary
        new_house = 1  # Switch Cambio Casa
        if new_house == 0:
            ratio_new_old_apartment = 1
        else:
            ratio_new_old_apartment = 1291.54 / 791.84
        inflation_rate_casa = 0.02
        months_to_project = 12  # Simulazione su N mesi
        # Scaling Factor Spese Straordinarie --> 0.2 = -20% , 0.7 = -70% ...
        scaling_factor_spese_straordinarie = 0.8
        ################# VALORI PREDETTI ##############################
        ####### regressor_alpha close to 0 ---> Linear Regression ######
        costo_casa_predicted_values, costo_casa_hystory_values, date_index_project = (
            project_future_values(
                data_collected["costo_casa_collect"],
                avg_results["costo_casa_avg_values"],
                months_to_project,
                inflation_rate_casa,
            )
        )

        (
            reddito_aggiuntivo_predicted_values,
            reddito_aggiuntivo_hystory_values,
            date_index_project,
        ) = project_future_values(
            data_collected["reddito_aggiuntivo_collect"],
            avg_results["reddito_aggiuntivo_avg_values"],
            months_to_project,
            0.0,
        )
        stipendio_predicted_values, stipendio_hystory_values, date_index_project = (
            project_future_values(
                data_collected["reddito_only_ifx"],
                avg_results["reddito_only_ifx_avg_values"],
                months_to_project,
                inflation_rate_salary,
            )
        )
        investment_predicted_values, investment_hystory_values, date_index_project = (
            project_future_values(
                data_collected["investment_collect"],
                avg_results["investment_collect_avg_values"],
                months_to_project,
                0.00001,
            )
        )
        spese_nette_da_predire = spese_nette_values - (
            data_collected["spese_straordinarie_collect"]
            * scaling_factor_spese_straordinarie
        )
        spese_nette_da_predire_avg_values = operations["avg"](spese_nette_da_predire)
        spese_nette_predicted_values, spese_nette_hystory_values, date_index_project = (
            project_future_values(
                spese_nette_da_predire,
                spese_nette_da_predire_avg_values,
                months_to_project,
                inflation_rate,
            )
        )
        (
            risparmio_netto_predicted_values,
            risparmio_netto_hystory_values,
            date_index_project,
        ) = project_future_values(
            data_collected["risparmio_netto_collect"],
            avg_results["risparmio_netto_avg_values"],
            months_to_project,
            0.0,
        )
        ################ CALCOLI PERCENTUALI PREDETTI ######################
        reddito_predicted_collect = (
            reddito_aggiuntivo_hystory_values["Data_Combined"].values
            + stipendio_hystory_values["Data_Combined"].values
        )  # type: ignore
        reddito_predicted_total_values_list, reddito_predicted_total_value = sum(
            reddito_predicted_collect
        )
        reddito_predicted_avg_values = dynamic_avg(reddito_predicted_collect)
        stipendio_predicted_collect = stipendio_hystory_values["Data_Combined"].values
        stipendio_predicted_avg_values = dynamic_avg(stipendio_predicted_collect)
        stipendio_predicted_total_values_list, stipendio_predicted_total_value = sum(
            stipendio_predicted_collect
        )
        costo_casa_hystory_values[date_list.size :] *= ratio_new_old_apartment
        costo_casa_predicted_collect = costo_casa_hystory_values["Data_Combined"].values
        costo_casa_predicted_avg_values = dynamic_avg(costo_casa_predicted_collect)
        costo_casa_predicted_total_values_list, costo_casa_predicted_total_value = sum(
            costo_casa_predicted_collect
        )
        investment_predicted_collect = investment_hystory_values["Data_Combined"].values
        investment_predicted_avg_values = dynamic_avg(investment_predicted_collect)
        investment_predicted_total_values_list, investment_predicted_total_value = sum(
            investment_predicted_collect
        )
        spese_nette_predicted_collect = spese_nette_hystory_values[
            "Data_Combined"
        ].values
        spese_nette_predicted_avg_values = dynamic_avg(spese_nette_predicted_collect)
        (spese_nette_predicted_total_values_list, spese_nette_predicted_total_value) = (
            sum(spese_nette_predicted_collect)
        )
        risparmio_netto_predicted_collect = risparmio_netto_hystory_values[
            "Data_Combined"
        ].values
        (
            risparmio_netto_predicted_total_values_list,
            risparmio_netto_predicted_total_value,
        ) = sum(risparmio_netto_predicted_collect)
        risparmio_netto_predicted_avg_values = dynamic_avg(
            risparmio_netto_predicted_collect
        )
    except Exception as e:
        st.error(f"Errore durante la previsione: {e}")

# --- Gemini ChatBot Section ---
st.sidebar.markdown("---")
st.sidebar.header("Gemini ChatBot")
init_chat_state()
GEMINI_API_KEY = get_gemini_api_key()
if not GEMINI_API_KEY:
    st.sidebar.warning("Please add your Gemini API key to api_key/gemini_key.toml.")
if st.sidebar.button("New Chat", key="new_chat_gemini"):
    new_chat()
user_prompt = st.sidebar.text_area("You (ChatBot):")
# Prepare context data for LLM
context_data = json.dumps(
    {
        "number_months": number_months,
        "data_summary": data_summary,
        "main_metrics": {
            k: v.tolist() if hasattr(v, "tolist") else v
            for k, v in avg_results.items()
            if k.endswith("_avg_values")
        },
    }
)
if GEMINI_API_KEY and st.sidebar.button("Send", key="send_gemini") and user_prompt:
    st.session_state.chat_history.append(("user", user_prompt))
    with st.spinner("Gemini is thinking..."):
        try:
            ai_response = query_gemini_flash(
                user_prompt, GEMINI_API_KEY, context_data=context_data
            )
            # Insert latest AI response at the beginning of chat history
            st.session_state.chat_history = [
                ("ai", ai_response)
            ] + st.session_state.chat_history
        except Exception as e:
            st.session_state.chat_history = [
                ("ai", f"Error: {e}")
            ] + st.session_state.chat_history
    st.session_state.chat_time_end = datetime.datetime.now()
render_chat()

folder_path, uploaded_files = upload_data_folder()
if folder_path:
    # Use your collect_data_utils functions to process files in folder_path
    # Example:
    # data = collect_data_from_csv(folder_path, True, "your_file_pattern", "your_regexp")
    pass
