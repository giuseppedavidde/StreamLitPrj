import streamlit as st
import os
import json
import random
import pandas as pd
from dotenv import load_dotenv

# Carica variabili d'ambiente
load_dotenv()

# Import AI Provider
try:
    from agents.ai_provider import AIProvider
except ImportError as e:
    st.error(f"Modulo 'agents' non trovato o errore importazione: {e}")
    AIProvider = None

# Configurazione Pagina
st.set_page_config(page_title="Gesundheit Dashboard", page_icon="🥗", layout="wide")

DATA_FILE = "recipes.json"
INGREDIENTS_DB_FILE = "ingredients_db.json"

# Caricamento DB Ingredienti
try:
    with open(INGREDIENTS_DB_FILE, "r") as f:
        INGREDIENTS_DB = json.load(f)
except (FileNotFoundError, json.JSONDecodeError):
    INGREDIENTS_DB = {}
    st.warning("File ingredients_db.json non trovato. Le ricette verranno generate senza base matematica sicura.")

# --- Costanti Nutrizionali (Integratori pre-calcolati) ---
SUPPLEMENTS = {
    "Nessuno": {"kcal": 0, "pro": 0, "cho": 0, "fat": 0},
    "Protein Iced Coffee (More Nutrition)": {"kcal": 158, "pro": 19.0, "cho": 4.1, "fat": 7.0},
    "Protein Iced Matcha Latte (More Nutrition)": {"kcal": 159, "pro": 17.0, "cho": 11.0, "fat": 4.4},
    "Budino Proteico (More Nutrition)": {"kcal": 196, "pro": 24.0, "cho": 17.0, "fat": 3.3}
}

GIORNI_LAVORATIVI = ["Lunedì", "Martedì", "Mercoledì", "Giovedì", "Venerdì"]

# --- Funzioni di Caricamento e Salvataggio (JSON) ---
def load_data():
    try:
        with open(DATA_FILE, 'r') as f:
            data = json.load(f)
            if not isinstance(data, list):
                return pd.DataFrame()
            return pd.DataFrame(data)
    except (FileNotFoundError, json.JSONDecodeError):
        return pd.DataFrame()

def save_data(df):
    data = df.to_dict(orient='records')
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=4, ensure_ascii=False)
    st.toast("Dati salvati con successo!", icon="✅")

# --- Calcoli Metabolici Base ---
def calculate_base_metrics(height, weight, lean_mass, activity_level, daily_steps):
    lean_mass_kg = weight * (lean_mass / 100.0)
    bmr = 370 + (21.6 * lean_mass_kg)
    
    activity_multipliers = {
        "Sedentario (scrivania)": 1.2,
        "Leggero (1-3 gg/sett)": 1.375,
        "Moderato (3-5 gg/sett)": 1.55,
        "Intenso (6-7 gg/sett)": 1.725,
        "Molto Intenso (atleta)": 1.9
    }
    
    base_multiplier = activity_multipliers.get(activity_level, 1.2)
    step_cal = daily_steps * 0.04 * (weight / 70.0) 
    tdee = (bmr * base_multiplier) + (step_cal * 0.5) 
    return bmr, tdee

# --- Generatore Matematico Pasti (Algoritmo Lineare Python) ---
def assemble_meal_math(target_c, target_p, target_f, used_main_items, is_breakfast=False, is_snack=False):
    if not INGREDIENTS_DB:
        return {"ingredients_str": "Carica Database", "used_names": [], "macros": {"k":0,"p":0,"c":0,"f":0}}
        
    if is_breakfast or is_snack:
        cat_c = "breakfast_carb"
        cat_p = "breakfast_pro"
        cat_f = "breakfast_fat"
        cat_v = None
    else:
        cat_c = "carb"
        cat_p = "protein"
        cat_f = "fat"
        cat_v = "veggie"
        
    def pick_item(category, exclusion_list):
        items = INGREDIENTS_DB.get(category, [])
        valid = [i for i in items if i['name'] not in exclusion_list]
        if not valid and items: valid = items # fallback
        return random.choice(valid) if valid else None
        
    c_source = pick_item(cat_c, used_main_items)
    p_source = pick_item(cat_p, used_main_items)
    f_source = pick_item(cat_f, [])
    
    veggie_source = None
    rem_c, rem_p, rem_f = target_c, target_p, target_f
    w_v = 0
    
    if cat_v:
        veggie_source = pick_item(cat_v, [])
        w_v = 150 # 150g di verdura fissa
        if veggie_source:
            rem_c = max(0, rem_c - (w_v/100.0)*veggie_source['cho'])
            rem_p = max(0, rem_p - (w_v/100.0)*veggie_source['pro'])
            rem_f = max(0, rem_f - (w_v/100.0)*veggie_source['fat'])
            
    # Ottimizzatore a griglia 5g per macro primari (Carbo vs Proteine)
    best_wc, best_wp = 0, 0
    min_err = float('inf')
    
    if c_source and p_source:
        for wc in range(0, 200, 5):
            for wp in range(0, 250, 5):
                c_tot = (wc/100.0)*c_source['cho'] + (wp/100.0)*p_source['cho']
                p_tot = (wc/100.0)*c_source['pro'] + (wp/100.0)*p_source['pro']
                err = abs(c_tot - rem_c) + abs(p_tot - rem_p)
                if err < min_err:
                    min_err, best_wc, best_wp = err, wc, wp
                    
    # Risoluzione grassi residui
    best_wf = 0
    if f_source:
        f_tot = 0
        if c_source: f_tot += (best_wc/100.0)*c_source['fat']
        if p_source: f_tot += (best_wp/100.0)*p_source['fat']
        req_f = rem_f - f_tot
        if req_f > 0 and f_source['fat'] > 0:
            best_wf = (req_f / f_source['fat']) * 100.0
            
    # Calcolo perfetamente allineato dalle vere grammature scelte
    def calc_m(src, weight):
        if not src: return 0,0,0,0
        return (weight/100)*src['cho'], (weight/100)*src['pro'], (weight/100)*src['fat'], (weight/100)*src['kcal']
    
    c_c, c_p, c_f, c_k = calc_m(c_source, best_wc)
    p_c, p_p, p_f, p_k = calc_m(p_source, best_wp)
    f_c, f_p, f_f, f_k = calc_m(f_source, best_wf)
    v_c, v_p, v_f, v_k = calc_m(veggie_source, w_v)
    
    tot_c = round(c_c + p_c + f_c + v_c)
    tot_p = round(c_p + p_p + f_p + v_p)
    tot_f = round(c_f + p_f + f_f + v_f)
    tot_k = round(c_k + p_k + f_k + v_k)
    
    ingredients = []
    if best_wc > 0 and c_source: ingredients.append(f"{c_source['name']} {int(best_wc)}g")
    if best_wp > 0 and p_source: ingredients.append(f"{p_source['name']} {int(best_wp)}g")
    if best_wf > 0 and f_source: ingredients.append(f"{f_source['name']} {int(best_wf)}g")
    if w_v > 0 and veggie_source: ingredients.append(f"{veggie_source['name']} {int(w_v)}g")
    
    names_used = []
    if c_source: names_used.append(c_source['name'])
    if p_source: names_used.append(p_source['name'])
    
    return {
        "ingredients_str": ", ".join(ingredients),
        "used_names": names_used,
        "macros": { "k": tot_k, "p": tot_p, "c": tot_c, "f": tot_f }
    }


# --- UI Setup e Configurazione ---
st.title("🥗 Gesundheit Dashboard")

with st.sidebar:
    st.header("👤 I tuoi Parametri Fisici")
    col1, col2 = st.columns(2)
    height = col1.number_input("Altezza (cm)", min_value=100, max_value=250, value=175)
    weight = col2.number_input("Peso (kg)", min_value=30, max_value=200, value=75)
    lean_mass = st.number_input("Massa Magra (%)", min_value=5.0, max_value=95.0, value=80.0)
    
    activity_level = st.selectbox("Attività Fisica", [
        "Sedentario (scrivania)", "Leggero (1-3 gg/sett)", "Moderato (3-5 gg/sett)", 
        "Intenso (6-7 gg/sett)", "Molto Intenso (atleta)"
    ], index=2)
    daily_steps = st.number_input("Passi giornalieri medi", min_value=0, max_value=50000, value=8000, step=500)
    
    st.divider()
    st.header("⚙️ Gestione Dieta")
    weekend_buffer = st.slider("Buffer Relax Weekend (%)", min_value=0, max_value=30, value=10)
    
    st.markdown("**Distribuzione Calorie AI (Pasti Liberi)**")
    meal_dist_col1, meal_dist_col2 = st.columns(2)
    dist_breakfast = meal_dist_col1.number_input("Colazione %", min_value=0, max_value=100, value=20, step=5)
    dist_snack = meal_dist_col2.number_input("Spuntino MAT %", min_value=0, max_value=100, value=10, step=5)
    dist_lunch = meal_dist_col1.number_input("Pranzo %", min_value=0, max_value=100, value=35, step=5)
    dist_snack_pm = meal_dist_col2.number_input("Spuntino POM %", min_value=0, max_value=100, value=0, step=5, help="Solo nei giorni di Riposo senza integratore")
    dist_dinner = meal_dist_col1.number_input("Cena %", min_value=0, max_value=100, value=35, step=5)
    
    total_dist_train = dist_breakfast + dist_snack + dist_lunch + dist_dinner
    total_dist_rest = dist_breakfast + dist_snack + dist_lunch + dist_snack_pm + dist_dinner
    
    if total_dist_train != 100:
        st.error(f"Errore: la somma (senza Spuntino POM) per i giorni di Allenamento fa {total_dist_train}%, deve fare 100%!")
    if total_dist_rest != 100:
        st.error(f"Errore: la somma (INCLUSO Spuntino POM) per i giorni di Riposo fa {total_dist_rest}%, deve fare 100%!")

    st.divider()
    
    with st.expander("🤖 Configurazione AI", expanded=False):
        provider_type = st.selectbox("Provider", ["Gemini", "Groq", "Ollama", "Puter"], index=0)
        api_key = None
        model_name = None

        if provider_type == "Gemini":
            env_key = os.getenv("GOOGLE_API_KEY")
            api_key = st.text_input("Gemini API Key", value=env_key if env_key else "", type="password")
            if AIProvider:
                try:
                    gemini_models = AIProvider.get_gemini_models(api_key=api_key or env_key)
                except Exception:
                    gemini_models = AIProvider.FALLBACK_ORDER
            else:
                gemini_models = ["gemini-2.5-flash"]
            model_name = st.selectbox("Modello", gemini_models, index=0)
        elif provider_type == "Groq":
            env_key = os.getenv("GROQ_API_KEY")
            api_key = st.text_input("Groq API Key", value=env_key if env_key else "", type="password")
            if AIProvider:
                groq_models = AIProvider.get_groq_models(api_key=env_key)
                model_name = st.selectbox("Modello", groq_models, index=0)
        elif provider_type == "Ollama":
            if AIProvider:
                ollama_models = AIProvider.get_ollama_models()
                if ollama_models:
                    model_name = st.selectbox("Modello Locale", ollama_models, index=0)
                else:
                    st.warning("Nessun modello trovato in locale, controlla che Ollama sia in esecuzione.")
                    model_name = st.text_input("Nome Modello (manuale)", value="llama3")
            else:
                model_name = st.text_input("Nome Modello (manuale)", value="llama3")
        elif provider_type == "Puter":
            env_key = os.getenv("PUTER_API_KEY")
            api_key = st.text_input("Puter API Key", value=env_key if env_key else "", type="password")
            if AIProvider:
                puter_models = AIProvider.get_puter_models()
                model_name = st.selectbox("Modello (Claude/Gemini)", puter_models, index=0)
        
        if st.button("Applica Configurazione AI"):
            if AIProvider:
                try:
                    st.session_state["ai_provider"] = AIProvider(
                        api_key=api_key, provider_type=provider_type, model_name=model_name
                    )
                    st.toast(f"AI Attivata: {provider_type} ({model_name})", icon="🟢")
                except Exception as e:
                    st.error(f"Errore Init AI: {e}")

bmr, tdee = calculate_base_metrics(height, weight, lean_mass, activity_level, daily_steps)

# Calcoli Settimanali base
weekly_tdee = tdee * 7
buffer_mod = weekend_buffer / 100.0
weekday_tdee = tdee * (1.0 - buffer_mod)
weekend_tdee = tdee + ((tdee * buffer_mod * 5) / 2) 

target_pro = weight * 2.0 
target_fat = weight * 1.0 
target_cho = (weekday_tdee - (target_pro * 4) - (target_fat * 9)) / 4

df = load_data()

tab_dash, tab_gen, tab_rec = st.tabs(["Dashboard Metriche", "📅 Scheduler Settimanale AI", "Ricettario / Storico"])

with tab_dash:
    st.header("📊 Il tuo Profilo Metabolico")
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        c1.metric("BMR", f"{bmr:,.0f} kcal")
        c2.metric("TDEE Base", f"{tdee:,.0f} kcal")
        c3.metric(f"Totale Settimanale", f"{weekly_tdee:,.0f} kcal")

    st.markdown("### Allocamento Calorie (Target Lun-Ven)")
    c4, c5, c6, c7 = st.columns(4)
    c4.metric(f"Giornaliere (Lun-Ven)", f"{weekday_tdee:,.0f} kcal")
    c5.metric("Proteine (🥩)", f"{target_pro:,.0f} g")
    c6.metric("Grassi (🥑)", f"{target_fat:,.0f} g")
    c7.metric("Carboidrati (🍚)", f"{target_cho:,.0f} g")

with tab_gen:
    st.header("🛠️ Ingegnere Nutrizionale (Python Math + AI)")
    st.info("I calcoli macro e l'assemblaggio degli ingredienti sono svolti algoritmicamente da Python tramite un database locale per evitare allucinazioni. L'AI genererà solo creativamente titoli e istruzioni sulle materie prime già fornite e bilanciate.")
    
    training_days = st.multiselect("Giorni di Allenamento", GIORNI_LAVORATIVI, default=["Lunedì", "Mercoledì", "Venerdì"])
    user_prompt = st.text_area("Richieste personalizzate per l'AI", placeholder="Es. voglio pietanze estive")
    
    st.markdown("### 🔢 Log Risoluzione Equazioni Lineari (Python)")
    with st.expander("Ispeziona Matrice Ingredienti Python", expanded=False):
        supp_keys = [k for k in SUPPLEMENTS.keys() if k != "Nessuno"]
        supp_idx = 0
        
        # daily_math_plan conterrà in toto il pasto: {"c": {"ingr_str": "...", "macros": {...}, "used": [...] } ... }
        daily_math_plan = {}
        
        for d_name in GIORNI_LAVORATIVI:
            st.divider()
            is_training = d_name in training_days
            allocated_supplement = "Nessuno"
            if is_training:
                 allocated_supplement = supp_keys[supp_idx % len(supp_keys)]
                 supp_idx += 1
            
            supp_val = SUPPLEMENTS[allocated_supplement]
            rem_kcal = weekday_tdee - supp_val['kcal']
            rem_pro = target_pro - supp_val['pro']
            rem_cho = target_cho - supp_val['cho']
            rem_fat = target_fat - supp_val['fat']
            
            st.write(f"**{d_name}** | Allenamento: {'Sì' if is_training else 'No'} | Integratore: {allocated_supplement}")
            
            # Setup pasto per pasto determinando % del giorno
            math_meals = {}
            if is_training:
                math_meals = {"c": dist_breakfast, "sm": dist_snack, "pr": dist_lunch, "ce": dist_dinner}
                supp_fixed = True
            else:
                math_meals = {"c": dist_breakfast, "sm": dist_snack, "pr": dist_lunch, "sp": dist_snack_pm, "ce": dist_dinner}
                supp_fixed = False
                
            day_result = {}
            used_today = []
            
            for m_key, pct in math_meals.items():
                if pct > 0:
                    t_c = rem_cho * (pct/100.0)
                    t_p = rem_pro * (pct/100.0)
                    t_f = rem_fat * (pct/100.0)
                    
                    is_bf = m_key == "c"
                    is_snk = m_key in ["sm", "sp"]
                    
                    calc_pasto = assemble_meal_math(t_c, t_p, t_f, used_today, is_breakfast=is_bf, is_snack=is_snk)
                    # Aggiunge gli usati alla blacklist giornaliera di Python per non ripetere lo stesso item
                    used_today.extend(calc_pasto["used_names"]) 
                    day_result[m_key] = calc_pasto
                    
                    st.caption(f"- **{m_key.upper()}**: {calc_pasto['ingredients_str']} (Kcal: {calc_pasto['macros']['k']})")
                    
            if supp_fixed:
                day_result["_supp"] = allocated_supplement
            else:
                day_result["_supp"] = "Nessuno"
                
            daily_math_plan[d_name] = day_result

    can_generate = (total_dist_train == 100) and (total_dist_rest == 100)
    
    if st.button("🚀 Genera Settimana (LUN-VEN)", type="primary", disabled=not can_generate):
        if "ai_provider" not in st.session_state or st.session_state["ai_provider"] is None:
            st.error("Configura l'AI dalla sidebar (Provider e API Key).")
        else:
            with st.spinner("Python ha blindato gli ingredienti. L'AI sta scrivendo istruzioni coerenti..."):
                provider = st.session_state["ai_provider"]
                model = provider.get_model(json_mode=True)
                
                # Stringa di contesto per l'AI
                lines = []
                for d_name in GIORNI_LAVORATIVI:
                    maths = daily_math_plan[d_name]
                    lines.append(f"Giorno: {d_name}")
                    for m, data in maths.items():
                        if m != "_supp":
                            lines.append(f"  Pasto {m}: USA ESATTAMENTE QUESTI INGREDIENTI: {data['ingredients_str']}")
                
                str_context = "\n".join(lines)

                # Prompt testuale pulito per l'AI (solo Testo, Niente Matematica)
                system_prompt = f"""
Sei un assistente per lo Chef. Il tuo Mastro Chef (Python) ha già deciso MATEMATICAMENTE le grammature e gli ingredienti perfetti per l'intera settimana lavorativa. NON MODIFICARLE.
Tutto quello che è stato preparato lo trovi qui:
{str_context}

IL TUO UNICO COMPITO:
Restituirmi un output in formato JSON che contenga, per ciascun pasto richiesto in ogni giorno, un ARRAY formato ESATTAMENTE da sole DUE STRINGHE testuali:
1. "Titolo Ricetta Inventato"
2. "Istruzioni di cottura brevissime"

REGOLE TASSATIVE:
1. Niente calcoli. Non stampare Kcal, pro, carbo nè chiavi di dizionario per essi. Python lo sa già.
2. Formato Obbligatorio (JSON ultracompresso):
{{
  "Lunedì": {{ "c": ["Overnight..", "Mescola avena..."], "sm": ["Snack", "Mangia..."], "pr": ["...", "..."], "sp": ["...","..."](se richiesto), "ce": ["...","..."] }},
  "Martedì": {{...}}
}}
Chiavi usate: c=Colazione, sm=Spuntino Mat, pr=Pranzo, sp=Spuntino Pom, ce=Cena.
Richieste facoltative: {user_prompt}
"""              
                try:
                    response = model.generate_content(system_prompt)
                    resp_t = response.text.strip()
                    
                    if resp_t.startswith("```json"): resp_t = resp_t[7:-3]
                    elif resp_t.startswith("```"): resp_t = resp_t[3:-3]
                        
                    ai_plan = json.loads(resp_t)
                    st.success("✨ Scheduler Settimanale Elaborato! La Matematica ha incrociato l'AI.")
                    st.session_state["loaded_week_plan"] = ai_plan
                    st.session_state["daily_math_plan"] = daily_math_plan

                except json.JSONDecodeError as e:
                    st.error(f"Errore JSON Decode. \n{e}\n\n{resp_t}")
                except Exception as e:
                    st.error(f"Errore GenAI: {e}")

    # RENDERIZZAZIONE PIANO
    if "loaded_week_plan" in st.session_state:
        ai_plan = st.session_state["loaded_week_plan"]
        math_plan = st.session_state["daily_math_plan"]
        
        tabs_giorni = st.tabs(GIORNI_LAVORATIVI)
        flat_recipes_to_save = []
        meal_names = {"c": "Colazione", "sm": "Spuntino Mattina", "pr": "Pranzo", "sp": "Spuntino Pomeridiano", "ce": "Cena"}
        
        for idx, tab in enumerate(tabs_giorni):
            d_name = GIORNI_LAVORATIVI[idx]
            d_math = math_plan.get(d_name, {})
            d_ai = ai_plan.get(d_name, {})
            
            supp = d_math.get("_supp", "Nessuno")
            is_training = supp != "Nessuno"
            
            with tab:
                st.subheader(f"{d_name} - {'💪 Allenamento' if is_training else '🛋️ Riposo'}")
                
                # Render combinato: Testo (AI) + Numeri&Ingredienti (Python)
                def render_combo_meal(k_short):
                    arr_testi = d_ai.get(k_short)
                    m_dati = d_math.get(k_short)
                    
                    if arr_testi and isinstance(arr_testi, list) and len(arr_testi) >= 2 and isinstance(m_dati, dict):
                        if "ingredients_str" not in m_dati:
                            st.warning(f"Il piano per {k_short} è vecchio o incompatibile. Clicca 'Genera Settimana' per ricalcolare.")
                            return
                        name, desc = arr_testi[0], arr_testi[1]
                        ingr_str = m_dati["ingredients_str"]
                        macros = m_dati["macros"]
                        
                        with st.container(border=True):
                            st.markdown(f"**{meal_names.get(k_short, k_short)}** | {name}")
                            st.caption(f"🛒 *{ingr_str}*")  # Componente logica Python
                            
                            c_k, c_p, c_c, c_f = st.columns(4)
                            c_k.metric("Kcal", f"{macros['k']}") # 100% Blindati da Python
                            c_p.metric("Pro", f"{macros['p']}g")
                            c_c.metric("Carbo", f"{macros['c']}g")
                            c_f.metric("Fat", f"{macros['f']}g")
                            
                            st.write(desc) # Istruzioni dall'AI
                            
                            flat_recipes_to_save.append({
                                "Giorno": d_name, "Pasto": meal_names.get(k_short, k_short), "Nome": name,
                                "Calories": macros['k'], "Protein": macros['p'], "Carbs": macros['c'], "Fat": macros['f'], 
                                "Ingredients": ingr_str, "Details": desc
                            })
                
                render_combo_meal("c")
                render_combo_meal("sm")
                render_combo_meal("pr")
                
                if not is_training:
                    render_combo_meal("sp")
                else:
                    if supp != "Nessuno":
                        with st.container(border=True):
                            s_val = SUPPLEMENTS[supp]
                            st.markdown(f"**Spuntino Pomeridiano (FISSO)** | {supp}")
                            c_k, c_p, c_c, c_f = st.columns(4)
                            c_k.metric("Kcal", s_val["kcal"])
                            c_p.metric("Pro", f"{s_val['pro']}g")
                            c_c.metric("Carbo", f"{s_val['cho']}g")
                            c_f.metric("Fat", f"{s_val['fat']}g")
                            st.info("Preparazione: Miscelare con 300ml Latte Mandorla zero zuccheri.")
                            
                            flat_recipes_to_save.append({
                                "Giorno": d_name, "Pasto": "Spuntino Pomeridiano", "Nome": supp,
                                "Calories": s_val["kcal"], "Protein": s_val['pro'], "Carbs": s_val['cho'], "Fat": s_val['fat'], 
                                "Ingredients": "Polvere Formulata", "Details": "Integratore Python Hardcoded"
                            })
                            
                render_combo_meal("ce")
        
        st.divider()
        if st.button("💾 Salva Settimana nel Database", type="secondary"):
             current_df = load_data()
             new_df = pd.DataFrame(flat_recipes_to_save)
             if current_df.empty:
                 merged = new_df
             else:
                 merged = pd.concat([current_df, new_df], ignore_index=True)
             save_data(merged)

with tab_rec:
    st.header("📖 Ricettario Storico")
    if not df.empty:
        st.write("Le tue ricette salvate e i piani settimanali scorsi.")
        edited = st.data_editor(df, num_rows="dynamic", use_container_width=True, height=600)
        if st.button("Salva Database Editato"):
            save_data(edited)
            st.rerun()
    else:
        st.info("Ricettario vuoto.")
