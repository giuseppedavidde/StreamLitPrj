"""
Modulo per la gestione della Knowledge Base (Libri, Documenti).
Permette di caricare file e recuperare il contenuto per arricchire l'analisi AI.
"""

import glob
import os
from typing import List

from pypdf import PdfReader


class KnowledgeBase:
    """Gestisce l'archiviazione e il recupero di documenti 'conoscenza' per l'agente."""

    def __init__(self, storage_dir: str = "knowledge_base"):
        self.storage_dir = storage_dir
        if not os.path.exists(self.storage_dir):
            os.makedirs(self.storage_dir)

    def save_document(self, uploaded_file) -> str:
        """Salva un file caricato (da Streamlit) nella directory di storage."""
        try:
            file_path = os.path.join(self.storage_dir, uploaded_file.name)
            with open(file_path, "wb") as f:
                f.write(uploaded_file.getbuffer())
            return f"✅ File salvato: {uploaded_file.name}"
        except Exception as e:
            return f"❌ Errore salvataggio {uploaded_file.name}: {e}"

    def save_text_content(self, filename: str, content: str) -> str:
        """Salva contenuto testuale direttamente in un file nella KB."""
        try:
            # Assicurati che abbia estensione .txt
            if not filename.endswith(".txt"):
                filename += ".txt"

            file_path = os.path.join(self.storage_dir, filename)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            return f"✅ Contenuto salvato in KB: {filename}"
        except Exception as e:
            return f"❌ Errore salvataggio KB {filename}: {e}"

    def get_context(self) -> str:
        """Legge tutti i file nella knowledge base e ritorna un unico testo di contesto."""
        context_parts = []

        # 1. Leggi file TXT
        txt_files = glob.glob(os.path.join(self.storage_dir, "*.txt"))
        for txt in txt_files:
            try:
                with open(txt, "r", encoding="utf-8") as f:
                    context_parts.append(
                        f"--- DOCUMENTO: {os.path.basename(txt)} ---\n{f.read()}\n"
                    )
            except Exception as e:
                print(f"Errore lettura {txt}: {e}")

        # 2. Leggi file PDF
        pdf_files = glob.glob(os.path.join(self.storage_dir, "*.pdf"))
        for pdf in pdf_files:
            try:
                reader = PdfReader(pdf)
                text = ""
                # Leggi prime 50 pagine per performance (o tutto se serve, ma occhio ai token)
                max_pages = 50
                for i, page in enumerate(reader.pages):
                    if i >= max_pages:
                        break
                    text += page.extract_text() + "\n"

                context_parts.append(
                    f"--- DOCUMENTO: {os.path.basename(pdf)} (Prime {max_pages} pag) ---\n{text}\n"
                )
            except Exception as e:
                print(f"Errore lettura {pdf}: {e}")

        if not context_parts:
            return ""

        return "\n".join(context_parts)

    def list_documents(self) -> List[str]:
        """Ritorna la lista dei file presenti."""
        files = os.listdir(self.storage_dir)
        return [f for f in files if f.endswith(".txt") or f.endswith(".pdf")]

    def clear_database(self):
        """Cancella tutti i file."""
        files = glob.glob(os.path.join(self.storage_dir, "*"))
        for f in files:
            try:
                os.remove(f)
            except Exception:
                pass
