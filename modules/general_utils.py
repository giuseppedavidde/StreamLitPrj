##Generic library for Array and Data-time format
import datetime as dt
import numpy as np
import pandas as pd
import glob
import math
import os
from pathlib import Path

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

##Github
my_token = ""
