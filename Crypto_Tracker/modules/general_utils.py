##Generic library for Array and Data-time format
import datetime as dt
import math

import numpy as np
import pandas as pd

##Github
my_token = ""


def month_year():
    now = dt.datetime.now()
    return now.month, now.year


# Funzione per formattare i valori percentuali
def format_percentage(value):
    return "{:.2f}%".format(value)


def simple_mean(previous_avg, new_value, n):
    # You need to define this function for computing the new average.
    # Assuming `previous_avg` is the average of the first `n-1` items,
    # `new_value` is the nth item, and `n` is the total count,
    # the new average will be computed as follows:
    return ((previous_avg * (n - 1)) + new_value) / n


def dynamic_avg(values):
    # This function calculates the dynamic average of a list of values.
    risparmio_netto_avg_values = []
    avg_intermediate = []

    for i, value in enumerate(values):
        if i == 0:
            # The average of the first element is the element itself.
            new_avg = value
        else:
            # Compute the new average based on the previous one.
            new_avg = simple_mean(avg_intermediate[i - 1], value, i + 1)

        # Append the new average to the intermediate list.
        avg_intermediate.append(new_avg)

        # Append the new average to the final list of averages.
        risparmio_netto_avg_values.append(new_avg)

    # Convert the list of averages to a numpy array.
    return np.array(risparmio_netto_avg_values)


def sum(values):
    sum_value = 0
    sum_value_list = []
    for i, value in enumerate(values):
        sum_value += value
        sum_value_list.append(sum_value)
    return np.array(sum_value_list), sum_value


# Definire una funzione generica per calcolare la somma e la media
def calculate_sum_and_average(variable_name, data, operation_funcs):
    sum_value = operation_funcs["sum"](data) if "sum" in operation_funcs else None
    avg_value = operation_funcs["avg"](data) if "avg" in operation_funcs else None
    return sum_value, avg_value


def reddito_annuo(
    reference_year, reference_month, path, scaling_factor, collect_data_func=None
):
    if collect_data_func is None:
        raise ValueError(
            "Devi passare la funzione per raccogliere i dati come parametro (es. collect_data_from_list_csv)"
        )
    reddito_collect = collect_data_func(
        path,
        multiple_files=1,
        file_name="Reddito",
        wanted_regexp="Stipendio",
        scaling_factor=scaling_factor,
    )
    initial_date_record = pd.to_datetime("2021-09-01")
    start_date = pd.to_datetime(f"{reference_year}-{reference_month}")
    reddito_annuo_result = 0.0
    delta_in_months_rounded = 0.0
    try:
        if initial_date_record <= start_date:
            delta = start_date - initial_date_record
            delta_in_months = delta.days / (
                30
                if reference_year % 4 == 0
                and (reference_year % 100 != 0 or reference_year % 400 == 0)
                else 31
            )
            delta_in_months_rounded = (
                math.floor(delta_in_months + 0.5)
                if delta_in_months % 1 >= 0.5
                else (
                    math.ceil(delta_in_months - 0.5)
                    if delta_in_months % 1 < 0.5
                    else delta_in_months
                )
            )
            delta_in_months_rounded = min(delta_in_months_rounded, len(reddito_collect))
    except ValueError:
        print(f"Impossibile accedere a {reddito_collect} in float.")
    if delta_in_months_rounded <= 12:
        for i in range(int(delta_in_months_rounded)):
            reddito_annuo_result += reddito_collect[i]
    else:
        for i in range(int(delta_in_months_rounded - 12), int(delta_in_months_rounded)):
            reddito_annuo_result += reddito_collect[i]
    return reddito_annuo_result


def numero_anni(number_samples):
    calculated_numero_anni = number_samples // 12
    return calculated_numero_anni


def stipendio_annuo_totale(path, number_samples, scaling_factor):
    numero_anni_osservati = numero_anni(number_samples=number_samples)
    stipendio_diviso_per_anni = []
    growth_rate = []
    average_growth_rate = []
    start_ref_year = 2022
    ref_month = 9
    date_list = pd.date_range(
        start=f"{start_ref_year}-{ref_month}",
        end=f"{
            start_ref_year - 1 + numero_anni_osservati}-{ref_month}",
        freq="MS",
    )
    date_anni = {date_list[0], date_list[-1]}
    date_anni = pd.DatetimeIndex(date_anni)  # type: ignore
    for i in range(numero_anni_osservati):
        redd_obs_year = reddito_annuo(
            reference_year=start_ref_year + i,
            reference_month=ref_month,
            path=path,
            scaling_factor=scaling_factor,
        )
        stipendio_diviso_per_anni = np.append(stipendio_diviso_per_anni, redd_obs_year)
    # Calcola la differenza tra ogni valore e il precedente
    diff = np.diff(stipendio_diviso_per_anni)
    # Rimuovere l'elemento di posizione 0
    diff = np.squeeze(diff)
    # Calcola il tasso di crescita
    growth_rate = diff / stipendio_diviso_per_anni[:-1]
    # Calcola il tasso di crescita medio
    average_growth_rate = np.mean(growth_rate)
    return stipendio_diviso_per_anni, growth_rate, average_growth_rate, date_anni
