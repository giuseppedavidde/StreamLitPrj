from modules import general_utils
from modules.general_utils import Path, glob, os, np, pd, dt
#import pandas as pd


def get_current_user():
    return os.getlogin()

# Ottieni i nomi dei file CSV nella tua directory
path = ""


def collect_file(path, name):
    """
    Collect files from the given path that match the given name, 
    sort them by modification time in descending order and return
    the sorted list of files and the number of files found.

    Parameters
    ----------

    path : str
        The path to the directory containing the files to collect.
    name : str
        The name of the files to collect, without extension.

    Returns
    -------

    list
        A sorted list of the collected files.
    int
        The number of collected files.
    """
    filenames = glob.iglob(path + f"/*202*-{name}.csv", recursive=True)
    filenames = sorted(filenames, key=os.path.getmtime, reverse=True)
    number_sample = sum(1 for _ in filenames)
    return filenames, number_sample



def collect_numb_sample(path,file_name):
    """
    Collect the number of files from the given path that match the given name, 
    by using the collect_file function.

    Parameters
    ----------

    path : str
        The path to the directory containing the files to collect.
    file_name : str
        The name of the files to collect, without extension.

    Returns
    -------

    int
        The number of collected files.
    """
    filenames, number_sample = collect_file(path, file_name)
    return number_sample

def collect_data_from_list_csv(path, multiple_files, file_name, wanted_regexp, scaling_factor):
    """
    Collects data from CSV files in the specified path that match the given file name
    and description, and scales the collected values by the scaling factor.

    Parameters
    ----------

    path : str
        The path to the directory containing the files to read.
    file_name : str
        The name pattern of the files to read, without extension.
    wanted_regexp : str
        The description pattern to match within each file.
    scaling_factor : float
        The factor by which to scale the collected values.

    Returns
    -------

    np.ndarray
        An array of collected and scaled values.

    Raises
    ------

    ValueError
        If a value cannot be converted to float, a message is printed.
    """
    if multiple_files :
        filenames, number_sample = collect_file(path, file_name)
    else :
        filenames = [file_name] #List of a single file
    
    print(f"{filenames}")
    
    data = []

    for filename in filenames:
        with open(filename, "r", encoding="utf-8") as f:
            next(f)  # Skip header
            for line in f:
                desc, value = line.strip().split(";")
                if desc == wanted_regexp:
                    value = value.replace("€", "").replace(".", "").replace(",", ".").strip()
                    try:
                        value = float(value) * scaling_factor
                    except ValueError:
                        print(f"Impossibile convertire {value} in float.")
                    else:
                        data.append(value)
                    break
            else:
                print(f"Nessun valore trovato per {wanted_regexp} in {filename}.")
    return np.array(data)

def collect_data_from_csv(path, multiple_files, file_name, wanted_regexp, scaling_factor=1):
    """
    Collect data from a CSV file in the given path, with the given name pattern, and
    matching the given description pattern. The collected values are scaled by the
    given factor.

    Parameters
    ----------

    path : str
        The path to the directory containing the files.
    file_name : str
        The name pattern of the files to read, without extension.
    wanted_regexp : str
        The description pattern to match within each file.
    scaling_factor : float
        The factor by which to scale the collected values.

    Returns
    -------

    np.ndarray
        An array of collected and scaled values.
    """
    data = collect_data_from_list_csv(
        path,
        multiple_files=multiple_files,
        file_name=file_name,
        wanted_regexp=wanted_regexp,
        scaling_factor=scaling_factor
    )
    return data

def collect_bitpanda_data(filepath):
    """
    Collects specific data from a Bitpanda CSV file.

    Parameters
    ----------

    filepath : str
        The path to the Bitpanda CSV file.

    Returns
    -------

    dict
        A dictionary containing the collected data.
    """
    try:
        df = pd.read_csv(filepath, skiprows=6)
    except pd.errors.EmptyDataError:
        print(f"Error: The file {filepath} does not have enough rows to skip.")
        return {}

    # Lookup table for column indices
    column_lut = {
        "Transaction ID": 0,
        "Timestamp": 1,
        "Transaction Type": 2,
        "Amount Fiat": 4,
        "Amount Asset": 6,
        "Asset": 7,
        "Asset market price": 8,
        "Fee": 12
    }

    data_to_retrieve = [
        ("trans_id_collect", "Transaction ID"),
        ("date_collect", "Timestamp"),
        ("trans_type_collect", "Transaction Type"),
        ("asset_collect", "Asset"),
        ("amount_fiat_collect", "Amount Fiat"),
        ("amount_asset_collect", "Amount Asset"),
        ("asset_market_price_collect", "Asset market price"),
        ("fee_asset_collect", "Fee"),
    ]
    
    collected_data = {key: [] for key, _ in data_to_retrieve}
    
    for _, row in df.iterrows():
        for key, column_name in data_to_retrieve:
            column_index = column_lut[column_name]
            collected_data[key].append(row[column_index])
    
    return collected_data

def sort_data_by_asset(data):
    sorted_data = {key: [] for key in data}
    sorted_indices = sorted(range(len(data['asset_collect'])), key=lambda k: data['asset_collect'][k])
    for i in sorted_indices:
        for key in data:
            sorted_data[key].append(data[key][i])
    return sorted_data
