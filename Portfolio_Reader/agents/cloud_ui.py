"""Renderizza la UI per il Cloud Sync (GitHub)."""
import streamlit as st
import os
from agents.cloud_manager import CloudManager

def render_cloud_sync_ui(DATA_FILE, is_sidebar=True):
    """Renderizza la UI per il Cloud Sync (GitHub)."""
    parent = st.sidebar if is_sidebar else st
    
    if is_sidebar:
        parent.divider()
    
    # Se siamo in setup mode (no sidebar), espandiamo di default
    with parent.expander("☁️ Cloud Data Sync", expanded=not is_sidebar):
        # 1. Configurazione Token
        env_gh_token = os.getenv("GITHUB_TOKEN")
        github_token = st.text_input("GitHub Token (PAT)", value=env_gh_token if env_gh_token else "", type="password", help="Richiesto per GitHub", key=f"gh_token_{'sb' if is_sidebar else 'main'}")
        
        if CloudManager and github_token:
            cm = CloudManager(github_token)
            
            # Bottone per caricare risorse (Cacheando in session state per evitare chiamate API continue)
            if st.button("🔄 Connetti / Cerca Repo", key=f"btn_conn_{'sb' if is_sidebar else 'main'}"):
                with st.spinner("Cerco repository..."):
                    repos = cm.get_user_repos()
                    st.session_state['gh_repos'] = repos
                    if not repos:
                        st.warning("Nessun repository trovato o token invalido.")
            
            # 2. Selezione Repo
            repo_list = st.session_state.get('gh_repos', [])
            selected_repo = None
            
            if repo_list:
                selected_repo = st.selectbox("Seleziona Repository", repo_list, index=0, key=f"sel_repo_{'sb' if is_sidebar else 'main'}")
            else:
                st.info("Clicca 'Connetti' per caricare i tuoi repository.")

            # 3. Selezione File (Se repo selezionato)
            selected_file_remote = None
            if selected_repo:
                    cache_key_files = f"gh_files_{selected_repo}"
                    
                    if cache_key_files not in st.session_state:
                        with st.spinner(f"Cerco file CSV..."):
                            files = cm.list_csv_files(selected_repo)
                            st.session_state[cache_key_files] = files
                    
                    file_list = st.session_state[cache_key_files]
                    
                    if file_list:
                        default_idx = 0
                        if "Budget App/budget_database.csv" in file_list:
                            default_idx = file_list.index("Budget App/budget_database.csv")
                        
                        selected_file_remote = st.selectbox("File CSV", file_list, index=default_idx, key=f"sel_file_{'sb' if is_sidebar else 'main'}")
                    else:
                        st.warning("Nessun file .csv trovato.")
                        if st.button("Cerca di nuovo", key=f"btn_refresh_{'sb' if is_sidebar else 'main'}"): 
                            del st.session_state[cache_key_files]
                            st.rerun()

            # 4. Azioni
            if selected_repo and selected_file_remote:
                st.caption(f"Remote: `{selected_file_remote}`")
                
                # Setup Keys per Session State
                KEY_DATA = 'portfolio_cloud_data'
                KEY_META = 'portfolio_cloud_source'

                c_down, c_up = st.columns(2)
                with c_down:
                    if st.button("⬇️ Pull", key=f"btn_pull_{'sb' if is_sidebar else 'main'}"):
                            with st.spinner("Scaricamento (In Memory)..."):
                                ok, content = cm.download_file_content(selected_repo, selected_file_remote)
                                if ok:
                                    st.session_state[KEY_DATA] = content
                                    st.session_state[KEY_META] = {
                                        "repo": selected_repo,
                                        "file": selected_file_remote
                                    }
                                    st.toast(f"Scaricato in memoria!", icon="✅")
                                    st.rerun()
                                else:
                                    st.error(str(content))
                with c_up:
                    if st.button("⬆️ Push", key=f"btn_push_{'sb' if is_sidebar else 'main'}"):
                            # Prende dal session state
                            if KEY_DATA in st.session_state and st.session_state[KEY_DATA]:
                                with st.spinner("Caricamento da memoria..."):
                                    # Ensure content is correct type
                                    content_to_upload = st.session_state[KEY_DATA]
                                    if isinstance(content_to_upload, bytes):
                                        content_to_upload = content_to_upload.decode('utf-8')
                                        
                                    ok, msg = cm.upload_file_content(selected_repo, selected_file_remote, content_to_upload, commit_message="Update from Portfolio Reader")
                                    if ok:
                                        st.toast(f"Caricato: {msg}", icon="✅")
                                    else:
                                        st.error(msg)
                            else:
                                st.warning("Nessun dato in memoria da caricare. Fai prima Pull o modifica i dati.")

        else:
                if not CloudManager:
                    st.error("Libreria mancante.")
                elif not github_token:
                    st.info("Inserisci Token GitHub.")
