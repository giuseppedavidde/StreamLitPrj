"""Page 5: Knowledge Base — live skill browsing."""

import streamlit as st
from agents import KnowledgeAgent

st.markdown('# 📚 Knowledge Base')
st.markdown('Accesso live a tutti gli skill opencode installati.')

ka = KnowledgeAgent()

skills = ka.list_skills()
categories = ka.get_categories()

tab1, tab2, tab3 = st.tabs(['📂 Skills Browser', '🔍 Search', '🗂 Categorie'])

with tab1:
    st.markdown(f'### Skills disponibili ({len(skills)})')
    skill_names = [s['name'] for s in skills]
    selected = st.selectbox('Seleziona skill', options=skill_names)

    if selected:
        st.markdown(f'**{selected}**')
        files = ka.list_files(selected)
        if files:
            file_choice = st.radio('File', options=['SKILL.md'] + [f for f in files if f != 'SKILL.md'],
                                   horizontal=True)
            content = ka.read_skill(selected, file_choice)
            if content:
                st.markdown(f'### {file_choice}')
                with st.expander('Mostra contenuto', expanded=True):
                    st.text(content[:3000] + ('\n... (troncato)' if len(content) > 3000 else ''))
            else:
                st.warning('File non trovato.')

        # Estrai strategie
        if selected in ('options-playbook', 'options-course-workbook',
                        'options-crash-course', 'options-strategy-suggestions',
                        'wyckoff-2-0', 'volume-profile', 'trades-about-to-happen'):
            strategies = ka.get_strategies(selected)
            st.markdown('---')
            st.markdown(f'### Strategie estratte ({len(strategies)})')
            for s in strategies[:20]:
                with st.expander(f'{s.get("name", "?")}'):
                    st.markdown(f'**Source:** {s.get("source", "N/A")}')
                    st.markdown(f'**Desc:** {s.get("description", "")[:300]}')

with tab2:
    query = st.text_input('Cerca in tutte le skills', placeholder='es. Spring, IV, Delta, accumulation...')
    cat_filter = st.selectbox('Filtra per categoria',
                               options=['Tutte'] + list(categories.keys()))

    if query and len(query) >= 2:
        with st.spinner('Cerco...'):
            cat = cat_filter if cat_filter != 'Tutte' else None
            results = ka.search_skills(query, category=cat)

        if results:
            st.markdown(f'### Trovati {sum(len(r["matches"]) for r in results)} match')
            for r in results[:10]:
                with st.expander(f'**{r["skill"]}** — {r["file"]}'):
                    for m in r['matches'][:5]:
                        st.caption(f'Line {m["line"]}: {m["text"][:200]}')
        else:
            st.info('Nessun risultato.')

with tab3:
    st.markdown('### Categorie')
    for cat_name, cat_skills in sorted(categories.items()):
        with st.expander(f'**{cat_name.capitalize()}** ({len(cat_skills)} skills)'):
            for sk in cat_skills:
                st.markdown(f'- {sk}')
                desc = ka.read_skill(sk, 'SKILL.md')
                if desc:
                    first_line = desc.strip().split('\n')[0].replace('#', '').strip()
                    st.caption(f'  {first_line[:100]}')
