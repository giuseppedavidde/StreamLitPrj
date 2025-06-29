# Budget Analyzer Streamlit Dashboard

This project is a Streamlit-based dashboard for interactive analysis and prediction of personal budget data. The dashboard is inspired by the logic and structure of the `Interactive_Budget_Reviewer` notebook and is modularized following the approach used in `Portfolio_Reader`, with reusable utility modules.

## Project Structure
- `Budget_Analyzer.py`: Main Streamlit dashboard entry point.
- `modules/`: Utility modules for data collection, general utilities, plotting, and prediction.
- `requirements.txt`: Python dependencies for the project.
- `README.md`: This documentation file.

## How to Run
1. Install dependencies:
   ```sh
   pip install -r requirements.txt
   ```
2. Start the dashboard:
   ```sh
   streamlit run Budget_Analyzer.py
   ```

## Features
- Data extraction and aggregation from CSV files
- Interactive analysis of budget, income, and expenses
- Visual summaries and comparisons with interactive Plotly charts
- Machine learning-based predictions for future budget trends
- Modular code for easy extension and maintenance

## Dependencies
- Python 3.8+
- See `requirements.txt` for all required packages

---

**Author:** [Your Name]
