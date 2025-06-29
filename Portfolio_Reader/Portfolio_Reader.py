from modules import general_utils
from modules.general_utils import glob, os, np, pd, dt, go, sp, yf
from modules import stock_utils
import warnings
from datetime import datetime as dtm
import requests

import streamlit as st

st.set_page_config(page_title="ETF/Stock Evaluation Dashboard", layout="wide")
st.title("ETF/Stock Evaluation Dashboard")
st.caption("Analyze and visualize your ETF/Stock portfolio and DCA strategies interactively.")

# --- File Upload Section ---
st.sidebar.header("Portfolio Data Upload")
portfolio_source = st.sidebar.radio(
    "Portfolio Source:",
    ["Upload CSV", "GitHub URL"],
    index=0
)
df_portfolio = None
if portfolio_source == "Upload CSV":
    uploaded_file = st.sidebar.file_uploader(
        "Upload your Portfolio CSV (My_Portfolio.csv)",
        type=["csv"],
        help="Upload your portfolio file with columns: Symbol, Category, Shares, Invested (USD), Invested (EUR), etc."
    )
    if uploaded_file is not None:
        df_portfolio = pd.read_csv(uploaded_file, sep=';')
else:
    github_url = st.sidebar.text_input("Paste GitHub raw CSV URL", value="")
    if github_url:
        try:
            df_portfolio = pd.read_csv(github_url, sep=';')
            st.success("Portfolio loaded from GitHub!")
        except Exception as e:
            st.error(f"Failed to load CSV from GitHub: {e}")
if df_portfolio is None:
    # Fallback to default file for local dev
    default_path = os.path.join(os.path.dirname(__file__), "..", "Data_for_Analysis", "My_Portfolio.csv")
    if os.path.exists(default_path):
        st.info("No file uploaded. Using default local file for demonstration.")
        df_portfolio = pd.read_csv(default_path, sep=';')
    else:
        st.warning("Please upload a portfolio CSV file or provide a GitHub URL to continue.")
        st.stop()

# --- CSV Editing & Download Section ---
if df_portfolio is not None:
    with st.expander("Edit Portfolio Data", expanded=False):
        st.sidebar.header("Edit Portfolio Data")
        st.markdown("#### Edit your portfolio below. You can enter formulas (e.g., =A+B or =SUM(A:C)) in the Formula column. After editing, you can save changes directly to your GitHub repository.")
        # Add a Formula column if not present
        if 'Formula' not in df_portfolio.columns:
            df_portfolio['Formula'] = ''
        # Convert all columns to string/object to allow formulas and text
        df_portfolio = df_portfolio.astype(str)
        edited_df = st.data_editor(df_portfolio, num_rows="dynamic", use_container_width=True, key="portfolio_editor")

        # Show number of rows and columns
        n_rows, n_cols = edited_df.shape
        st.info(f"Table shape: {n_rows} rows × {n_cols} columns")

        # Evaluate formulas (try to convert to float where possible)
        import pandas as pd
        import numpy as np
        import re
        def eval_formula(row, df):
            formula = row.get('Formula', '')
            if isinstance(formula, str) and formula.startswith('='):
                expr = formula[1:]
                # Replace column names with row values
                for col in df.columns:
                    if col != 'Formula':
                        # Try to use float if possible
                        try:
                            val = float(row.get(col, 0))
                        except Exception:
                            val = f'"{row.get(col, "")}"'
                        expr = re.sub(rf'\b{col}\b', str(val), expr)
                try:
                    allowed_names = {k: v for k, v in vars(np).items() if not k.startswith('_')}
                    allowed_names.update({'SUM': np.sum, 'MIN': np.min, 'MAX': np.max})
                    result = eval(expr, {"__builtins__": None}, allowed_names)
                    return result
                except Exception:
                    return 'ERR'
            return ''
        edited_df['Formula Result'] = edited_df.apply(lambda row: eval_formula(row, edited_df), axis=1)
        st.dataframe(edited_df)

        csv_data = edited_df.drop(columns=['Formula Result']).to_csv(index=False, sep=';')

        st.markdown("---")
        st.markdown("### Save Changes to GitHub")
        with st.expander("GitHub Settings (required for saving)"):
            github_token = st.text_input("GitHub Personal Access Token (PAT)", type="password", help="Create a token with 'repo' scope at https://github.com/settings/tokens")
            github_repo = st.text_input("GitHub Repository (owner/repo)", value="your-username/your-repo")
            github_file_path = st.text_input("Path to CSV in repo (e.g. Data_for_Analysis/My_Portfolio.csv)", value="Data_for_Analysis/My_Portfolio.csv")
            github_branch = st.text_input("Branch to commit to", value="main")
        if st.button("Save changes to GitHub", type="primary"):
            if not github_token or not github_repo or not github_file_path:
                st.error("Please provide all GitHub settings.")
            else:
                import base64
                api_url = f"https://api.github.com/repos/{github_repo}/contents/{github_file_path}"
                headers = {"Authorization": f"token {github_token}", "Accept": "application/vnd.github.v3+json"}
                # Get the current file SHA (required for update)
                r = requests.get(api_url, headers=headers, params={"ref": github_branch})
                if r.status_code == 200:
                    sha = r.json()["sha"]
                    commit_message = "Update portfolio CSV via Streamlit app"
                    content_b64 = base64.b64encode(csv_data.encode()).decode()
                    data = {
                        "message": commit_message,
                        "content": content_b64,
                        "sha": sha,
                        "branch": github_branch
                    }
                    put_r = requests.put(api_url, headers=headers, json=data)
                    if put_r.status_code in [200, 201]:
                        st.success("CSV updated successfully on GitHub!")
                    else:
                        st.error(f"Failed to update file: {put_r.text}")
                elif r.status_code == 404:
                    # File does not exist, create it
                    commit_message = "Create portfolio CSV via Streamlit app"
                    content_b64 = base64.b64encode(csv_data.encode()).decode()
                    data = {
                        "message": commit_message,
                        "content": content_b64,
                        "branch": github_branch
                    }
                    put_r = requests.put(api_url, headers=headers, json=data)
                    if put_r.status_code in [200, 201]:
                        st.success("CSV created successfully on GitHub!")
                    else:
                        st.error(f"Failed to create file: {put_r.text}")
                else:
                    st.error(f"GitHub API error: {r.text}")
        st.info("You can use formulas like =A+B or =SUM(A:C) in the Formula column. Your GitHub token is only used to update the file and is not stored anywhere.")

# --- User Inputs ---
st.sidebar.header("Analysis Options")
portfolio_mode = st.sidebar.radio(
    "Analysis Mode:",
    ["Single Stock", "Portfolio"],
    index=1
)

# Date selection
today = pd.Timestamp.today()
if portfolio_mode == "Portfolio":
    stock_under_test = df_portfolio
    start_date = st.sidebar.date_input("Start Date", value=today.replace(year=today.year-3))
else:
    stock_symbol = st.sidebar.text_input("Enter Stock Ticker Symbol", value="AAPL")
    category = st.sidebar.selectbox("Category", ["ETF", "Crypto", "Stock"], key="sidebar_category")
    start_date = st.sidebar.date_input("Start Date", value=today.replace(year=today.year-3))
    stock_under_test = stock_symbol
end_date = st.sidebar.date_input("End Date", value=today)
end_date_str = end_date.strftime("%Y-%m-%d")

# --- Data Collection ---
if isinstance(stock_under_test, pd.DataFrame):
    stock_data_object = {}
    for symbol in stock_under_test["Symbol"]:
        if pd.notna(symbol):
            stock_data_object[symbol] = stock_utils.get_stock_data(symbol)
else:
    stock_data_object = stock_utils.get_stock_data(stock_under_test)

# --- Main Analysis Logic ---i-+
if isinstance(stock_under_test, pd.DataFrame):
    st.subheader("Portfolio Overview")
    st.dataframe(stock_under_test)
    # --- DCA and Gain Calculations ---
    st.markdown("### Portfolio DCA and Gain Analysis")
    # USDEUR DailyRate Change
    forex_data = None
    if isinstance(stock_data_object, dict) and "USDEUR=X" in stock_data_object and stock_data_object["USDEUR=X"] is not None:
        try:
            forex_data = stock_data_object["USDEUR=X"].history(period="1d")
        except Exception:
            forex_data = None
    latest_rate = forex_data["Close"].iloc[-1] if forex_data is not None else 1.0
    # Dictionaries for calculations
    invested_capital_usd_dict = {}
    invested_capital_eur_dict = {}
    invested_capital_eur_dict_today = {}
    shares_dict = {}
    shares_cost_dict = {}
    shares_value_dict = {}
    gain_shares_absolute_value_dict = {}
    gain_shares_percentage_dict = {}
    capital_by_category = {cat: 0.0 for cat in stock_under_test["Category"].unique()}
    capital_by_category_today = {cat: 0.0 for cat in stock_under_test["Category"].unique()}
    weight_by_symbol = {}
    weight_by_symbol_today = {}
    total_gain = 0.0
    end_date_dca = end_date_str
    for symbol in stock_under_test["Symbol"]:
        if symbol != "USDEUR=X" and pd.notna(symbol):
            idx = stock_under_test.index[stock_under_test["Symbol"] == symbol][0]
            category = stock_under_test.at[idx, "Category"]
            shares = float(stock_under_test.at[idx, "Shares"])
            invested_capital_usd = float(stock_under_test.at[idx, "Invested (USD)"])
            invested_capital_eur = float(stock_under_test.at[idx, "Invested (EUR)"])
            invested_capital_usd_dict[symbol] = invested_capital_usd
            shares_dict[symbol] = shares
            shares_info = None
            if isinstance(stock_data_object, dict) and symbol in stock_data_object and stock_data_object[symbol] is not None:
                try:
                    shares_info = stock_data_object[symbol].history(period="1d")
                except Exception:
                    shares_info = None
            if shares_info is not None:
                if invested_capital_usd_dict[symbol] > 0.0:
                    shares_value_dict[symbol] = shares_info["Close"].iloc[-1] * latest_rate
                elif symbol in ["IE00BK5BQT80", "IE00BFMXXD54"]:
                    shares_value_dict[symbol] = shares_info["Close"].iloc[-1] * latest_rate
                else:
                    shares_value_dict[symbol] = shares_info["Close"].iloc[-1]
            else:
                shares_value_dict[symbol] = 0.0
            invested_capital_eur_dict[symbol] = (invested_capital_usd_dict[symbol] * latest_rate + invested_capital_eur) if invested_capital_usd_dict[symbol] > 0.0 else invested_capital_eur
            invested_capital_eur_dict_today[symbol] = (shares * shares_value_dict[symbol])
            shares_cost_dict[symbol] = invested_capital_eur_dict[symbol]/shares_dict[symbol] if shares_dict[symbol] > 0.0 else 0.0
            gain_shares_absolute_value_dict[symbol] = (shares_value_dict[symbol]*shares_dict[symbol]) - invested_capital_eur_dict[symbol]
            gain_shares_percentage_dict[symbol] = (gain_shares_absolute_value_dict[symbol]/invested_capital_eur_dict[symbol])*100 if invested_capital_eur_dict[symbol] else 0.0
            total_gain += gain_shares_absolute_value_dict[symbol]
            if category not in capital_by_category:
                capital_by_category[category] = 0.0
            capital_by_category[category] += invested_capital_eur_dict[symbol]
            capital_by_category_today[category] += invested_capital_eur_dict_today[symbol]
            weight_by_symbol[symbol] = {"invested": invested_capital_eur_dict[symbol], "category": category}
            weight_by_symbol_today[symbol] = {"invested": invested_capital_eur_dict_today[symbol], "category": category}
    # Calculate weights for each symbol in each category
    for symbol, data in weight_by_symbol.items():
        category_total = capital_by_category[data["category"]]
        if category_total > 0.0:
            weight_by_symbol[symbol]["weight"] = data["invested"] / category_total * 100
        else:
            weight_by_symbol[symbol]["weight"] = 0.0
    for symbol, data in weight_by_symbol_today.items():
        category_total_today = capital_by_category_today[data["category"]]
        if category_total_today > 0.0:
            weight_by_symbol_today[symbol]["weight"] = data["invested"] / category_total_today * 100
        else:
            weight_by_symbol_today[symbol]["weight"] = 0.0
    # DataFrame for invested capital
    df_invested_capital = pd.DataFrame({
        'Symbol': list(invested_capital_eur_dict.keys()),
        'BEGINNING: Invested Capital (EUR)': list(invested_capital_eur_dict.values()),
        'TODAY: Invested Capital (EUR)': list(invested_capital_eur_dict_today.values()),
        'Shares': list(shares_dict.values()),
        'Share Value (EUR)': list(shares_value_dict.values()),
        'Share Cost (EUR)': list(shares_cost_dict.values()),
        'Gain (EUR)': list(gain_shares_absolute_value_dict.values()),
        'Gain %': list(gain_shares_percentage_dict.values()),
    })
    st.dataframe(df_invested_capital)
    eur = float(stock_under_test["Total Invested (EUR)"].iloc[0])
    usd = float(stock_under_test["Total Invested (USD)"].iloc[0])
    invested_capital_invested = eur + usd * latest_rate
    st.metric("Total Invested (EUR)", f"{invested_capital_invested:,.2f}")
    st.metric("Total Return (EUR)", f"{total_gain:,.2f}")
    st.metric("Total Return %", f"{(total_gain/invested_capital_invested)*100:.2f}%")
    # Pie charts for invested capital by category
    def safe_create_pie_chart(labels, values, title_text):
        if not labels or not values or sum(values) == 0:
            st.info(f"No data to display for: {title_text}")
            return None
        fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=0.3)])
        fig.update_layout(title_text=title_text)
        return fig
    with st.expander("Show Invested Capital by Category Pie Charts"):
        st.markdown("#### BEGINNING: Capitale Totale Investito per Categoria")
        fig1 = safe_create_pie_chart(list(capital_by_category.keys()), list(capital_by_category.values()), 'BEGINNING: Capitale Totale Investito per Categoria')
        if fig1 is not None:
            st.plotly_chart(fig1, use_container_width=True)

        st.markdown("#### TODAY: Capitale Totale Investito per Categoria")
        fig2 = safe_create_pie_chart(list(capital_by_category_today.keys()), list(capital_by_category_today.values()), 'TODAY: Capitale Totale Investito per Categoria')
        if fig2 is not None:
            st.plotly_chart(fig2, use_container_width=True)

    # Pie charts for weights by symbol in each category
    with st.expander("Show Weights by Symbol in Each Category Pie Charts"):
        for category in capital_by_category.keys():
            if category == "Forex":
                continue
            category_symbols = [symbol for symbol, data in weight_by_symbol.items() if data['category'] == category]
            category_weights = [data['weight'] for symbol, data in weight_by_symbol.items() if data['category'] == category]
            category_weights_today = [data['weight'] for symbol, data in weight_by_symbol_today.items() if data['category'] == category]
            if category_symbols and category_weights and sum(category_weights) > 0:
                st.markdown(f'#### BEGINNING: Peso Percentuale per Simbolo in Categoria "{category}"')
                fig3 = safe_create_pie_chart(category_symbols, category_weights, f'BEGINNING: Peso Percentuale per Simbolo in Categoria "{category}"')
                if fig3 is not None:
                    st.plotly_chart(fig3, use_container_width=True)
            if category_symbols and category_weights_today and sum(category_weights_today) > 0:
                st.markdown(f'#### TODAY: Peso Percentuale per Simbolo in Categoria "{category}"')
                fig4 = safe_create_pie_chart(category_symbols, category_weights_today, f'TODAY: Peso Percentuale per Simbolo in Categoria "{category}"')
                if fig4 is not None:
                    st.plotly_chart(fig4, use_container_width=True)
    # DCA logic and plotting can be added here as in the notebook
else:
    st.subheader(f"Stock Overview: {stock_under_test}")
    # --- Single Stock Analysis and DCA Logic ---
    st.markdown("### Single Stock DCA and Gain Analysis")
    # User input for investment and DCA dates
    category = None  # Ensure category is always defined
    invested_capital_invested = st.number_input("Insert how much you want to invest in EUR", min_value=0.0, value=1000.0, step=100.0)
    start_date_dca = st.date_input("Enter the start date for DCA Strategy", value=start_date)
    end_date_dca = st.date_input("Enter the end date for DCA Strategy", value=end_date)
    # --- ADJUST END DATE TO LAST AVAILABLE TRADING DAY ---
    import datetime
    today_dt = pd.Timestamp.today().normalize().date()
    if end_date_dca >= today_dt:
        # Try to get last available trading day from Yahoo Finance
        temp_ticker = stock_utils.get_stock_data(stock_under_test)
        if temp_ticker is not None:
            hist = temp_ticker.history(period="5d")
            if not hist.empty:
                last_trading_day = hist.index[-1].to_pydatetime().date()
                if last_trading_day < end_date_dca:
                    st.warning(f"End date adjusted from {end_date_dca.strftime('%Y-%m-%d')} to last available trading day: {last_trading_day}")
                    end_date_dca = last_trading_day
            else:
                st.warning("Could not determine last trading day, using selected end date.")
        else:
            st.warning("Could not retrieve ticker data. Please check the ticker symbol.")
    start_date_dca_str = start_date_dca.strftime("%Y-%m-%d")
    end_date_dca_str = end_date_dca.strftime("%Y-%m-%d")
    ma_period = st.number_input("Moving Average Period (MA)", min_value=1, value=200, step=1)
    if category is None:
        category = st.sidebar.selectbox("Category", ["ETF", "Crypto", "Stock"], key="single_stock_category")
    # Get stock data
    stock_data_dca_values = stock_utils.get_stock_with_date_index_data(
        stock_data=stock_data_object,
        category=category,
        start_date=start_date_dca_str,
        end_date=end_date_dca_str,
        ma_period=ma_period
    )
    st.dataframe(stock_data_dca_values)
    # Debug info for user
    st.markdown(f"**Ticker:** `{stock_under_test}`  ")
    st.markdown(f"**Date Range:** {start_date_dca_str} to {end_date_dca_str}")
    st.markdown(f"**Data shape:** {stock_data_dca_values.shape}")
    # Show error if all stock_price or MA200 are NaN or error column present
    if (stock_data_dca_values['stock_price'].isna().all() or stock_data_dca_values['MA200'].isna().all() or 'error' in stock_data_dca_values.columns):
        st.error("No valid stock price or MA200 data found for this ticker and date range. Please check the ticker symbol and date range.\n" + str(stock_data_dca_values.get('error', '')))
    else:
        # Plot price and MA200 (OBV removed)
        st.markdown("#### Stock Price and MA200")
        # Ensure index is DatetimeIndex and sorted for rolling calculation
        stock_data_dca_values = stock_data_dca_values.copy()
        if not isinstance(stock_data_dca_values.index, pd.DatetimeIndex):
            stock_data_dca_values.index = pd.to_datetime(stock_data_dca_values.index)
        stock_data_dca_values = stock_data_dca_values.sort_index()
        # Recalculate MA200 to ensure correctness
        stock_data_dca_values["MA200"] = stock_data_dca_values["stock_price"].rolling(window=ma_period).mean()
        dates = stock_data_dca_values.index
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=dates, y=stock_data_dca_values["stock_price"], mode="lines", name="Stock Price"))
        fig.add_trace(go.Scatter(x=dates, y=stock_data_dca_values["MA200"], mode="lines", name="MA200"))
        fig.update_layout(
            title=f"{stock_under_test} Stock Price and MA200",
            xaxis_title="Date",
            yaxis_title="Price",
            legend_title="Legend",
            hovermode="x unified"
        )
        st.plotly_chart(fig, use_container_width=True)
# --- Footer ---
st.caption("This dashboard is for informational purposes only. Always consult a financial advisor for investment decisions.")
