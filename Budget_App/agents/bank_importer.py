"""
Module for handling Bank CSV Import and AI Categorization.
This module encapsulates the logic to read a bank export file, 
categorize its transactions using an AI model, and aggregate the results
to match the Budget Application's database schema.
"""

import pandas as pd
import json
import io

class BankImporter:
    """Handles the import and processing of bank statements."""
    
    def __init__(self, ai_provider):
        """
        Args:
            ai_provider: An instance of the AIProvider class to be used for categorization.
        """
        self.ai_provider = ai_provider

    def _clean_amount(self, amount_str):
        """Converts German format (1.234,56) to float (1234.56)."""
        if isinstance(amount_str, (int, float)):
            return float(amount_str)
        if pd.isna(amount_str) or amount_str == "":
            return 0.0
        
        # Remove thousands separator (.), replace decimal separator (,)
        clean = str(amount_str).replace('.', '')
        clean = clean.replace(',', '.')
        try:
            return float(clean)
        except ValueError:
            return 0.0

    def _load_csv(self, file_buffer):
        """Loads CSV from buffer trying different encodings."""
        try:
            # Try latin1 first for German bank exports
            df = pd.read_csv(file_buffer, sep=';', encoding='latin1')
            return df
        except UnicodeDecodeError:
            file_buffer.seek(0)
            try:
                # Fallback to cp1252
                df = pd.read_csv(file_buffer, sep=';', encoding='cp1252')
                return df
            except Exception:
                file_buffer.seek(0)
                # Fallback to utf-8 just in case
                df = pd.read_csv(file_buffer, sep=';', encoding='utf-8')
                return df
        except Exception as e:
            raise Exception(f"Failed to read CSV: {e}")

    def process_file(self, file_buffer, target_categories, income_cols, progress_callback=None):
        """
        Processes the uploaded bank file (CSV or PDF).
        
        Args:
            file_buffer: The file object from streamlit uploader.
            target_categories (list): List of valid expense/income categories.
            income_cols (list): List of categories considered as Income.
            progress_callback (func): Optional callback (percent: float, message: str).

        Returns:
            dict: {
                'detailed_df': DataFrame with individual transactions and AI mappings.
                'aggregated_df': DataFrame with monthly totals matching the budget DB.
                'report_md': Markdown string for the comparison report.
            }
        """
        # 0. Detect File Type
        file_name = file_buffer.name.lower()
        
        # 1. Load Data
        df = None
        if file_name.endswith('.pdf'):
            if progress_callback:
                progress_callback(0.0, "Estrazione dati da PDF (Multimodale)...")
            try:
                # Read bytes for PDF
                pdf_bytes = file_buffer.getvalue()
                df = self._extract_from_pdf(pdf_bytes)
            except Exception as e:
                raise ValueError(f"Errore estrazione PDF: {e}")
        else:
            # Assume CSV
            df = self._load_csv(file_buffer)
            
        if df is None or df.empty:
            raise ValueError("File is empty or could not be read.")

        # 2. Prepare for AI Categorization
        model = self.ai_provider.get_model(json_mode=True)
        mappings = {}
        
        # Keep original category for comparison (if present, else empty)
        if 'Kategorie' not in df.columns:
            df['Kategorie'] = 'Da Categorizzare'
            
        df['Analyzed_Category'] = df['Kategorie'] 

        items_to_process = []
        for index, row in df.iterrows():
            desc = f"{row.get('Umsatztext', '')} {row.get('Buchungstext', '')} {row.get('Name des Partners', '')}".strip()
            amount = row.get('Betrag', '0')
            old_cat = row.get('Kategorie', '')
            
            items_to_process.append({
                "id": index,
                "description": desc,
                "amount": amount,
                "old_category": old_cat
            })

        # 3. Process in Batches
        
        BATCH_SIZE = 20
        total_batches = (len(items_to_process) + BATCH_SIZE - 1) // BATCH_SIZE
        
        for i in range(0, len(items_to_process), BATCH_SIZE):
            current_batch_num = i // BATCH_SIZE + 1
            if progress_callback:
                # Adjust progress to account for PDF step
                base_c = 0.2 if file_name.endswith('.pdf') else 0.0
                percent = base_c + (i / len(items_to_process)) * (0.9 - base_c)
                progress_callback(percent, f"Analisi AI in corso: Batch {current_batch_num}/{total_batches}...")
            
            # ... batch processing logic calls model ... 
            
            batch = items_to_process[i:i+BATCH_SIZE]
            
            prompt_text = f"""
            You are an expert financial assistant.
            Your task is to MAP bank transactions to valid budget categories.
            
            VALID CATEGORIES (Exact Match Required):
            {target_categories}
            
            RULES:
            1. "Freizeit & Genuss" is generic. You MUST be specific based on the description:
            - Restaurants, Bars, Food delivery -> 'Cene, Pranzo'
            - Pharmacies (Apotheke, DM often), Doctors -> 'Medicinali'
            - Trains, Buses, Taxi, Uber -> 'Trasporti'
            - Flights, Hotels, Airbnb, Cinema, Events -> 'Viaggi, Divertimento'
            - Gas stations (Tankstelle) -> 'Carburante'
            - Subscriptions (Spotify, Netflix) -> 'PayPal + Abbonamenti'
            2. "Lebensmittel" (Groceries) or Supermarkets -> 'Alimentari'.
            3. "Mobilität" usually maps to 'Carburante' or 'Trasporti'.
            4. "Miete" (Rent) / Insurance -> 'Immobili (affitto, mutuo, tasse, assicurazione)'.
            5. Salary/Wages -> 'Stipendio'.
            6. Incoming transfers -> 'Reddito aggiuntivo' (unless typical salary).
            
            TRANSACTIONS:
            {json.dumps(batch)}
            
            Return JSON:
            {{ "mappings": [ {{ "id": <id>, "new_category": "<ValidCategory>" }} ] }}
            """
            
            try:
                response = model.generate_content(prompt_text)
                # Helper for Gemini/Ollama response wrapper differences
                text_response = response.text if hasattr(response, 'text') else str(response)
                
                # Simple cleanup for potential markdown code blocks
                if "```json" in text_response:
                    text_response = text_response.replace("```json", "").replace("```", "")
                
                result = json.loads(text_response)
                
                for m in result.get("mappings", []):
                    mappings[m['id']] = m['new_category']
            except Exception as e:
                print(f"Error in batch {i}: {e}")
                # Skip batch or partially fail? We'll leave original categories.
        
        if progress_callback:
            progress_callback(0.9, "Applicazione modifiche e calcoli finali...")

        # 4. Apply Mappings
        df['New_Category'] = df['Analyzed_Category'] # Default
        for idx, new_cat in mappings.items():
            if idx in df.index and new_cat in target_categories:
                df.at[idx, 'New_Category'] = new_cat

        # 5. Clean Data for Aggregation
        df['Betrag_Float'] = df['Betrag'].apply(self._clean_amount)

        # Parse Dates
        try:
            df['DateObj'] = pd.to_datetime(df['Buchungsdatum'], format='%d/%m/%Y')
        except Exception:
            df['DateObj'] = pd.to_datetime(df['Buchungsdatum'], dayfirst=True, errors='coerce')

        df['Year'] = df['DateObj'].dt.year
        df['MonthNum'] = df['DateObj'].dt.month
        df['Month'] = df['DateObj'].dt.strftime('%B')

        # 6. Generate Report Markdown
        report_md = self.generate_report(df)

        # 7. Aggregate
        aggregated_df = self.aggregate_data(df, target_categories, income_cols)
        
        if progress_callback:
            progress_callback(1.0, "Fatto!")

        return {
            'detailed_df': df,
            'aggregated_df': aggregated_df,
            'report_md': report_md
        }

    def _extract_from_pdf(self, pdf_bytes):
        """Extracts transactions from PDF bytes using Multimodal AI."""
        prompt = """
        Extract ALL bank transactions from this PDF statement.
        Return a JSON list of objects with these exact fields:
        - "Buchungsdatum": Date DD.MM.YYYY
        - "Umsatztext": Description/Payee
        - "Betrag": Amount as string (e.g. "-12,50" or "1.200,00"). Use European format.
        
        Example JSON:
        [
          {"Buchungsdatum": "01.01.2024", "Umsatztext": "Amazon", "Betrag": "-25,90"},
          {"Buchungsdatum": "15.01.2024", "Umsatztext": "Salary", "Betrag": "2500,00"}
        ]
        """
        
        model = self.ai_provider.get_model(json_mode=True)
        
        # Multimodal call: [Text, PDF_Bytes]
        # AIProvider wrapper (GeminiWrapper) usually handles list if valid.
        # We need to pass mime_type wrapper or raw bytes if supported.
        # Checking AIProvider implementation from context:
        # It handles `final_prompt` which can be structure with mime_type.
        

        
        request_content = [
            prompt,
            {"mime_type": "application/pdf", "data": pdf_bytes}
        ]
        
        response = model.generate_content(request_content)
        text_resp = response.text if hasattr(response, 'text') else str(response)
        
        # Clean markdown
        if "```json" in text_resp:
            text_resp = text_resp.replace("```json", "").replace("```", "")
        
        data = json.loads(text_resp)
        
        # Use 'transactions' key if wrapped, else assume list
        if isinstance(data, dict):
            data = data.get('transactions', data.get('items', []))
            
        df = pd.DataFrame(data)
        
        return df 


    def generate_report(self, df):
        """Generates a markdown table highlighting changes."""
        md = "| Date | Description | Amount | Original Category | **New AI Category** |\n"
        md += "|---|---|---|---|---|\n"
        
        for idx, row in df.iterrows():
            desc = f"{row.get('Umsatztext', '')} {row.get('Name des Partners', '')}".strip()[:40]
            old = row.get('Analyzed_Category', '')
            new = row.get('New_Category', '')
            amt = row.get('Betrag_Float', 0)
            date = str(row.get('Buchungsdatum', ''))
            
            # Formatting
            desc = desc.replace("|", "-") # Avoid breaking MD table
            
            # Highlight changes
            if old != new:
                new_display = f"**:green[{new}]**" # Streamlit markdown color
            else:
                new_display = new
            
            md += f"| {date} | {desc} | {amt:.2f} | {old} | {new_display} |\n"
            
        return md

    def aggregate_data(self, df, target_categories, income_cols):
        """Aggregates transactions into monthly totals per category."""
        
        def adjust_sign(row):
            val = row['Betrag_Float']
            cat = row['New_Category']
            if cat in income_cols:
                return val if val > 0 else 0 
            else:
                # Expenses: Convert negative bank amount to positive budget amount
                return -val

        df['Budget_Amount'] = df.apply(adjust_sign, axis=1)

        pivot_df = df.pivot_table(
            index=['Year', 'MonthNum', 'Month'], 
            columns='New_Category', 
            values='Budget_Amount', 
            aggfunc='sum',
            fill_value=0.0
        ).reset_index()

        # Ensure all columns exist
        for cat in target_categories:
            if cat not in pivot_df.columns:
                pivot_df[cat] = 0.0

        # Calculate Totals
        present_income = [c for c in income_cols if c in pivot_df.columns]
        present_expense = [c for c in target_categories if c not in income_cols and c in pivot_df.columns]

        pivot_df['Totale Entrate'] = pivot_df[present_income].sum(axis=1)
        pivot_df['Totale Uscite'] = pivot_df[present_expense].sum(axis=1)
        pivot_df['Reddito meno spese'] = pivot_df['Totale Entrate'] - pivot_df['Totale Uscite']
        pivot_df['Risparmio %'] = pivot_df.apply(
            lambda row: (row['Reddito meno spese'] / row['Totale Entrate'] * 100) if row['Totale Entrate'] != 0 else 0, 
            axis=1
        )
        
        # Return aggregated df
        return pivot_df
