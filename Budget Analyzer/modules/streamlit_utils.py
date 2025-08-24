import streamlit as st
import tempfile
import os


def set_page_config():
    st.set_page_config(page_title="Budget Analyzer", layout="wide")


def show_title_and_intro():
    st.title("INTERACTIVE BUDGET REVIEWER and PREDICTER")
    st.markdown("**Here where we declare the needed libraries and global variable**")


def upload_csv_files():
    st.header("Upload CSV Files")
    uploaded_files = st.file_uploader(
        "Carica uno o più file CSV (puoi selezionare più file)",
        type=["csv"],
        accept_multiple_files=True,
    )
    path = None
    if uploaded_files:
        temp_dir = tempfile.mkdtemp()
        for file in uploaded_files:
            with open(f"{temp_dir}/{file.name}", "wb") as f:
                f.write(file.getbuffer())
        path = temp_dir
        st.success(f"{len(uploaded_files)} file caricati con successo!")
    return path, uploaded_files


def upload_data_folder():
    st.header("Upload Data Folder")
    uploaded_files = st.file_uploader(
        "Upload all CSV files from your data folder",
        type=["csv"],
        accept_multiple_files=True,
    )
    folder_path = None
    if uploaded_files:
        temp_dir = tempfile.mkdtemp()
        for file in uploaded_files:
            with open(os.path.join(temp_dir, file.name), "wb") as f:
                f.write(file.getbuffer())
        folder_path = temp_dir
        st.success(f"{len(uploaded_files)} files uploaded to {folder_path}")
    return folder_path, uploaded_files


def show_info_message(msg):
    st.info(msg)


def show_success_message(msg):
    st.success(msg)


def show_header(msg):
    st.header(msg)


def show_table(df):
    st.dataframe(df)


def selectbox(label, options):
    return st.selectbox(label, options)
