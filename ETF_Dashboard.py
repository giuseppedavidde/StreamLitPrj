import streamlit as st
import pandas as pd
from modules import general_utils, stock_utils
import warnings
import os
from datetime import datetime as dtm

st.set_page_config(page_title="ETF/Stock Evaluation Dashboard", layout="wide")
st.title("ETF/Stock Evaluation Dashboard")
st.caption("Analyze and visualize your ETF/Stock portfolio and DCA strategies interactively.")

# --- File Upload Section ---
st.sidebar.header("Portfolio Data Upload")
uploaded_file = st.sidebar.file_uploader(
    "Upload your Portfolio CSV (My_Portfolio.csv)",
    type=["csv"],
    help="Upload your portfolio file with columns: Symbol, Category, Shares, Invested (USD), Invested (EUR), etc."
)

if uploaded_file is not None:
    df_portfolio = pd.read_csv(uploaded_file, sep=';')
else:
    # Fallback to default file for local dev
    default_path = os.path.join(os.path.dirname(__file__), "..", "Data_for_Analysis", "My_Portfolio.csv")
    if os.path.exists(default_path):
        st.info("No file uploaded. Using default local file for demonstration.")
        df_portfolio = pd.read_csv(default_path, sep=';')
    else:
        st.warning("Please upload a portfolio CSV file to continue.")
        st.stop()

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
    category = st.sidebar.selectbox("Category", ["ETF", "Crypto", "Stock"])
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

# --- Main Analysis Logic ---
if isinstance(stock_under_test, pd.DataFrame):
    st.subheader("Portfolio Overview")
    st.dataframe(stock_under_test)
    # --- DCA and Gain Calculations ---
    st.markdown("### Portfolio DCA and Gain Analysis")
    # USDEUR DailyRate Change
    forex_data = stock_data_object["USDEUR=X"].history(period="1d") if "USDEUR=X" in stock_data_object else None
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
            category = stock_under_test.loc[stock_under_test["Symbol"] == symbol, "Category"].iloc[0]
            shares = stock_under_test.loc[stock_under_test["Symbol"] == symbol, "Shares"].iloc[0]
            invested_capital_usd = stock_under_test.loc[stock_under_test["Symbol"] == symbol, "Invested (USD)"].iloc[0]
            invested_capital_eur = stock_under_test.loc[stock_under_test["Symbol"] == symbol, "Invested (EUR)"].iloc[0]
            invested_capital_usd_dict[symbol] = invested_capital_usd
            shares_dict[symbol] = shares
            shares_info = stock_data_object[symbol].history(period="1d")
            if invested_capital_usd_dict[symbol] > 0.0:
                shares_value_dict[symbol] = shares_info["Close"].iloc[-1] * latest_rate
            elif symbol in ["IE00BK5BQT80", "IE00BFMXXD54"]:
                shares_value_dict[symbol] = shares_info["Close"].iloc[-1] * latest_rate
            else:
                shares_value_dict[symbol] = shares_info["Close"].iloc[-1]
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
    invested_capital_invested = float(stock_under_test["Total Invested (EUR)"].iloc[0] + stock_under_test["Total Invested (USD)"].iloc[0]*latest_rate)
    st.metric("Total Invested (EUR)", f"{invested_capital_invested:,.2f}")
    st.metric("Total Return (EUR)", f"{total_gain:,.2f}")
    st.metric("Total Return %", f"{(total_gain/invested_capital_invested)*100:.2f}%")
    # Pie charts for invested capital by category
    import plotly.graph_objects as go
    def safe_create_pie_chart(labels, values, title_text):
        if not labels or not values or sum(values) == 0:
            st.info(f"No data to display for: {title_text}")
            return None
        fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=0.3)])
        fig.update_layout(title_text=title_text)
        return fig

    st.markdown("#### BEGINNING: Capitale Totale Investito per Categoria")
    fig1 = safe_create_pie_chart(list(capital_by_category.keys()), list(capital_by_category.values()), 'BEGINNING: Capitale Totale Investito per Categoria')
    if fig1 is not None:
        st.plotly_chart(fig1, use_container_width=True)

    st.markdown("#### TODAY: Capitale Totale Investito per Categoria")
    fig2 = safe_create_pie_chart(list(capital_by_category_today.keys()), list(capital_by_category_today.values()), 'TODAY: Capitale Totale Investito per Categoria')
    if fig2 is not None:
        st.plotly_chart(fig2, use_container_width=True)

    # Pie charts for weights by symbol in each category
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
    invested_capital_invested = st.number_input("Insert how much you want to invest in EUR", min_value=0.0, value=1000.0, step=100.0)
    start_date_dca = st.date_input("Enter the start date for DCA Strategy", value=start_date)
    end_date_dca = st.date_input("Enter the end date for DCA Strategy", value=end_date)
    start_date_dca_str = start_date_dca.strftime("%Y-%m-%d")
    end_date_dca_str = end_date_dca.strftime("%Y-%m-%d")
    ma_period = st.number_input("Moving Average Period (MA)", min_value=1, value=200, step=1)
    # Get stock data
    stock_data_dca_values = stock_utils.get_stock_with_date_index_data(
        stock_data=stock_data_object,
        category=category,
        start_date=start_date_dca_str,
        end_date=end_date_dca_str,
        ma_period=ma_period
    )
    st.dataframe(stock_data_dca_values)
    # Plot price, MA200, OBV
    st.markdown("#### Stock Price, MA200, OBV")
    import plotly.graph_objects as go
    dates = stock_data_dca_values.index
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=dates, y=stock_data_dca_values["stock_price"], mode="lines", name="Stock Price"))
    fig.add_trace(go.Scatter(x=dates, y=stock_data_dca_values["MA200"], mode="lines", name="MA200"))
    fig.add_trace(go.Scatter(x=dates, y=stock_data_dca_values["OBV"], mode="lines", name="OBV", yaxis="y2"))
    fig.update_layout(
        title=f"{stock_under_test} Stock Price, MA200, OBV",
        xaxis_title="Date",
        yaxis_title="Price",
        yaxis2=dict(title="OBV", overlaying="y", side="right", showgrid=False),
        legend_title="Legend",
        hovermode="x unified"
    )
    st.plotly_chart(fig, use_container_width=True)
# --- Footer ---
st.caption("This dashboard is for informational purposes only. Always consult a financial advisor for investment decisions.")
