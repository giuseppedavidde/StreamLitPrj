##Generic library for Array and Data-time format
import datetime as dt
import numpy as np
import pandas as pd

##Generic library to create plots
import plotly.graph_objects as go
import plotly.subplots as sp
from ipywidgets import interactive, HBox, VBox, widgets, Layout, ToggleButton, fixed

##Generic library to retrieve stock-Data
import yfinance as yf
import requests
from io import StringIO

##Return the yfinance.Ticker object that stores all the relevant stock informations
from pandas import DataFrame
import warnings

##Return the DATA INFORMATIONS
def month_year():  
    """
    Return the current month and year as integers.

    Returns
    -------
    day : int
        The current day of the month.
    month : int
        The current month of the year.
    year : int
        The current year.
    """ 
    now = dt.datetime.now()
    return now.day, now.month, now.year
    
def collect_data_from_github(github_raw_url):
    """
    Collect data from a GitHub raw URL into a pandas DataFrame.

    Parameters
    ----------
    github_raw_url : str
        The URL of the raw file on GitHub.

    Returns
    -------
    pd.DataFrame or None
        The DataFrame loaded from the file, or None if an error occurred.
    """
    try:
        # L'URL del contenuto raw su GitHub (senza token nell'URL)
        # Esegui la richiesta GET
        response = requests.get(github_raw_url)
        response.raise_for_status()  # Solleva un errore se la risposta non è 200

        # Leggi il contenuto del file come CSV
        csvfile = StringIO(response.text)
        df = pd.read_csv(csvfile, sep=';', header=0)
        
        # Ritorna il DataFrame
        return df
    except Exception as e:
        print(f"Error: {e}")
        return None

def get_stock_data(isin_string):
    try:
        stock_ticker = isin_string
        stock_data = yf.Ticker(stock_ticker)
        stock_info = stock_data.info  # Effettua una richiesta per ottenere le informazioni
        return stock_data
    except ValueError as e:
        print(f"Errore nel recuperare i dati per {isin_string}: {e}")
        return None
    except Exception as e:
        print(f"Si è verificato un errore non previsto per {isin_string}: {e}")
        return None



##Return the hystorical data with date expressed as string --> Suitable for calculations
def get_stock_with_date_index_data(
    stock_data, category, start_date, end_date, ma_period=200
) -> DataFrame | DataFrame:
    """
    Restituisce un DataFrame con la storia dei prezzi di un titolo
    e relativi volumi, insieme a due indicatori tecnici calcolati
    (Moving Average a 200 periodi e On Balance Volume)

    Parameters
    ----------
    stock_data : yf.Ticker
        L'oggetto Ticker di YahooFinance
    category : str
        La categoria del titolo
    start_date : str
        La data di inizio della storia dei prezzi
    end_date : str
        La data di fine della storia dei prezzi
    ma_period : int, optional
        Il numero di periodi per la Moving Average, default 200

    Returns
    -------
    pd.DataFrame
        Il DataFrame con la storia dei prezzi e relativi volumi,
        insieme alle due colonne "MA200" e "OBV"
    """
    full_date_range = pd.date_range(start=start_date, end=end_date, freq="D")
    try:
        if isinstance(stock_data, yf.Ticker):
            hist_data = stock_data.history(start=start_date, end=end_date)
            hist_data.index = hist_data.index.strftime("%Y-%m-%d")
            hist_data = hist_data.reindex(full_date_range.strftime("%Y-%m-%d"))
            hist_data.infer_objects().ffill(inplace=True)

            hist_data_to_return = pd.DataFrame(
                index=full_date_range.strftime("%Y-%m-%d"),
                columns=["symbol","category","stock_price", "volume", "MA200", "OBV"],
            )
            hist_data_to_return["stock_price"] = hist_data["Close"]
            hist_data_to_return["volume"] = hist_data["Volume"]
            hist_data_to_return["category"] = category
            hist_data_to_return["symbol"] = stock_data.ticker
            hist_data_to_return["MA200"] = (
                hist_data_to_return["stock_price"].rolling(window=ma_period).mean()
            )

            # Calcolo dell'indicatore OBV
            hist_data_to_return["OBV"] = np.where(
                hist_data_to_return["stock_price"].diff() > 0,  # type: ignore
                hist_data_to_return["volume"],
                -hist_data_to_return["volume"],
            )
            with warnings.catch_warnings():
                warnings.simplefilter('ignore', FutureWarning)
                hist_data_to_return.ffill(inplace=True)
            return hist_data_to_return
        else:
            raise ValueError(f"stock_data must be a yf.Ticker object, got {type(stock_data)} instead.")
    except Exception as e:
        print(f"Error: {e}")
        hist_data_to_return = pd.DataFrame(
            index=full_date_range.strftime("%Y-%m-%d"),
            columns=["symbol","stock_price", "volume", "MA200", "OBV"],
        )
        return hist_data_to_return

def get_info_investment(
    stock_data, invested_capital, start_date, end_date, purchase_frequency
):
    # Crea un intervallo di date dal start_date al end_date con purchase_frequency interval
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', FutureWarning)
        purchase_dates = (
            pd.date_range(start_date, end_date, freq=purchase_frequency)
            ).strftime("%Y-%m-%d")
    # Crea un DataFrame vuoto che coprirà ogni giorno tra start_date e end_date
    daily_investment_df = pd.DataFrame(
        index=(pd.date_range(start=start_date, end=end_date, freq="D")).strftime(
            "%Y-%m-%d"
        ),
        columns=[
            "price",
            "shares_bought",
            "average_cost",
            "total_investment",
            "total_shares",
            "daily_stock_price",
            "purchase_dates",
        ],
    )
    ##To suppress some Pandas Warnings
    total_investment = 0
    total_shares = 0

    # Ciclo attraverso ogni data di acquisto
    for date in purchase_dates:
        purchase_amount = invested_capital / len(purchase_dates)
        total_investment += purchase_amount
        daily_stock_price = stock_data.loc[date, "stock_price"]
        shares_bought = purchase_amount / daily_stock_price if daily_stock_price else 0
        total_shares += shares_bought
        # Imposta i valori per il giorno di acquisto
        daily_investment_df.loc[date] = [
            daily_stock_price,
            shares_bought,
            total_investment / total_shares if total_shares else 0,
            total_investment,
            total_shares,
            daily_stock_price,
            purchase_dates,
        ]

    # Riempie in avanti i giorni senza acquisti con i valori dell'ultimo acquisto noto
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', FutureWarning)
        daily_investment_df.ffill(inplace=True)

    # Stock price between purchase_dates
    daily_investment_df["daily_stock_price"] = stock_data["stock_price"]

    # Calcola i valori di mercato giornalieri e i guadagni
    daily_investment_df["market_value"] = (
        daily_investment_df["daily_stock_price"] * daily_investment_df["total_shares"]
    )
    daily_investment_df["daily_gain"] = (
        daily_investment_df["market_value"] - daily_investment_df["total_investment"]
    )
    daily_investment_df["daily_gain_perc"] = (
        daily_investment_df["daily_gain"] / daily_investment_df["total_investment"]
    ) * 100

    # Riempe in NAN
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', FutureWarning)
        daily_investment_df.ffill(inplace=True)

    final_data = {
        "symbol": stock_data["symbol"],
        "category": stock_data["category"],
        "average_cost": daily_investment_df["average_cost"],
        "market_value": daily_investment_df["market_value"],
        "daily_gain": daily_investment_df["daily_gain"],
        "daily_gain_perc": daily_investment_df["daily_gain_perc"],
        "total_shares": daily_investment_df["total_shares"],
        "total_investment": daily_investment_df["total_investment"],
        "purchase_dates": daily_investment_df["purchase_dates"].to_list(),
    }

    return final_data


# Find which is the best strategy of investment
def get_best_investment_strategy(results):
    """
    Determines the best investment strategy based on the provided results.

    Iterates through a dictionary of investment results, each associated with a
    frequency, to identify the strategy with the lowest average cost. For each
    strategy, it calculates and compares the average cost, number of shares,
    last purchase date, return value, and market value. The strategy with the
    lowest average cost is deemed the best.

    Args:
        results (dict): A dictionary where keys are investment frequencies and
                        values are dictionaries containing investment results
                        with keys 'average_cost', 'total_shares',
                        'purchase_dates', 'daily_gain', and 'market_value'.

    Returns:
        tuple: A tuple containing the best strategy frequency, best average cost,
               best number of shares, best market value, and the last purchase date.
    """
    best_strategy = None
    best_average_cost = float("inf")
    best_number_shares = 0
    best_return_value = 0
    best_market_value = 0

    for freq, result in results.items():
        average_cost = result["average_cost"].iloc[-1]
        number_shares = result["total_shares"].iloc[-1]
        last_date_purchase = result["purchase_dates"][-1]  ##It is a list
        final_return_value = result["daily_gain"].iloc[-1]
        market_value = result["market_value"].iloc[-1]

        if average_cost < best_average_cost:
            best_strategy = freq
            best_average_cost = average_cost
            best_number_shares = number_shares
            best_last_date_purchase = last_date_purchase
            best_return_value = final_return_value
            best_market_value = market_value
    print(
        f"The winning strategy is {best_strategy} with an average cost of {best_average_cost:.2f} , {best_number_shares:.2f} shares and last purchase on {best_last_date_purchase} with a return value of {best_return_value} USD."
    )
    print(f"The final market value at is : {best_market_value} USD")
    return (best_strategy, best_average_cost, best_number_shares, best_market_value)

##To be used in order to plot the stock behavior along two dates that you choose
def plot_stock_data(ticker, stock_data, start_date, end_date):   
    """
    Plot the stock price history between two dates.

    Parameters:
        ticker (str): The stock ticker symbol.
        stock_data (pandas.DataFrame): The stock data with 'stock_price' column.
        start_date (str): The start date in 'YYYY-MM-DD' format.
        end_date (str): The end date in 'YYYY-MM-DD' format.

    Returns:
        None
    """
    try:
        ## hist_data = stock_data.history(start=start_date, end=end_date)
        fig = go.Figure(
            data=[go.Scatter(x=stock_data.index, y=stock_data["stock_price"])]
        )
        fig.update_layout(
            title=f"stock <b>{ticker}</b> Price History",
            xaxis_title="Date",
            yaxis_title="Price (USD)",
        )
        fig.show()
    except Exception as e:
        print(f"Error: {e}")


def create_plot(x, y, name_trace, name_graph, xaxis_title, yaxis_title):
    """
    Creates and displays a plot with multiple traces.

    Parameters:
        x (list of list): A list of lists containing x-coordinates for each trace.
        y (list of list): A list of lists containing y-coordinates for each trace.
        name_trace (list): A list of names for each trace.
        name_graph (str): The title of the graph.
        xaxis_title (str): The title for the x-axis.
        yaxis_title (str): The title for the y-axis.

    Returns:
        plotly.graph_objs._figure.Figure: The generated figure object.
    """
    fig = go.Figure()
    for x_list, y_list, name in zip(x, y, name_trace):
        fig.add_trace(
            go.Scatter(
                x=x_list,
                y=y_list,
                mode="lines+markers+text",
                name=name,
            )
        )
    fig.update_layout(
        title=name_graph,
        xaxis_title=xaxis_title,
        yaxis_title=yaxis_title,
        legend_title="Legenda",
        hovermode="x",
    )
    fig.show()
    return fig

def create_pie_chart(data, labels, values, title_text, hole_size=0.3):
    # """
    # Crea un grafico a torta generico con i dati forniti.
    # 
    # Args:
    # - data: Dizionario o DataFrame con dati da plottare.
    # - labels: Lista di etichette per i segmenti del grafico a torta.
    # - values: Lista di valori per i segmenti del grafico a torta.
    # - title_text: Titolo del grafico a torta.
    # - hole_size: Dimensione del buco centrale nel grafico a torta (per grafici tipo donut).
    # """
        fig = go.Figure(data=[go.Pie(labels=labels, values=values, hole=hole_size)])
        fig.update_layout(title_text=title_text)
        fig.show()

# Definisci la funzione per creare e aggiornare il grafico
# Inizializza un grafico vuoto che verrà aggiornato o sovrascritto
def create_interactive_plot(stock_data_df_or_dict,results,field,exception_field_string, exception_field_array, freq):
        """
        Creates and displays an interactive plot with multiple traces.

        Parameters:
            stock_data_df_or_dict (dict or pandas.DataFrame): A dictionary or DataFrame containing stock data.
            results (dict): A dictionary containing stock data results.
            field (str): The field to plot.
            exception_field_string (str): The string for the exception field.
            exception_field_array (dict): A dictionary containing exception field data.
            freq (str): The frequency to plot.

        Returns:
            plotly.graph_objs._figure.Figure: The generated figure object.
        """
        global global_fig
        global_fig = go.Figure()
        traces = []
        if isinstance(stock_data_df_or_dict, dict):
            if field == exception_field_string:
                y_data = exception_field_array[freq]
                x_data = exception_field_array[freq].index
                traces.append(go.Scatter(
                        x=x_data, y=y_data, mode='lines', name=f"{freq} {field}"
                    ))
            else:
                for symbol, stock_df in stock_data_df_or_dict.items():
                    if freq in results and symbol in results[freq]:
                        # Aggiungi il dato di questa stock alla lista 'y'
                        y_data = results[freq][symbol][field] 
                        x_data = results[freq][symbol][field].index
                        traces.append(go.Scatter(
                            x=x_data, y=y_data, mode='lines', name=f"{symbol} {freq} {field}"
                        ))
        else:
            # Aggiungi il dato di questa stock alla lista 'y'
                y_data = results[freq][field]
                traces.append(go.Scatter(
                x=results[freq][field].index, y=y_data, mode='lines', name=f"{freq} {field}"
                ))
            # Aggiorna o configura il grafico con le trace attuali
        for trace in traces:
            global_fig.add_trace(trace)
        global_fig.update_layout(
            title=f"{field.title()} over Time ({freq})",
            xaxis={'title': "Date"},
            yaxis={'title': field.title()},
            hovermode='closest'
            )
        global_fig.show()

# Visualizzazione della tabella
def show_table(df):
    # Crea una lista di liste, una per ogni colonna del DataFrame
    """
    Visualizza una tabella dati utilizzando una figura di plotly go.Table

    Args:
        df (pandas.DataFrame): DataFrame contenente i dati da visualizzare
    """
    cell_values = [df[col].tolist() for col in df.columns]
    
    fig = go.Figure(data=[go.Table(
        header=dict(values=list(df.columns),
                    fill_color='aquamarine',
                    align='left'),
        cells=dict(values=cell_values,
                   fill_color='lightgreen',
                   align='left'))
    ])
    fig.show()
