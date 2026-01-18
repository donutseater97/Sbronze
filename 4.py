from investgo import get_pair_id, get_historical_prices, get_info
import pandas as pd
from datetime import datetime
import tkinter as tk
from tkinter import ttk
from tkcalendar import DateEntry
import numpy as np
import os
import plotly.graph_objects as go


tickers = ["0P0001CRXW", "0P00006DA4", "0P0001722W", "0P00015OFP"]
funds = {"US": "red", "EU": "blue", "EM": "green", "TECH": "gray"}
ticker_map = dict(zip(tickers, funds.keys()))

# Pair ID ottenuti in un'unica comprehension
pair_ids = {t: get_pair_id([t])[0] for t in tickers} #questa riga serve a prendere gli id dei fondi 

infos, series = [], []
start_date = "01102024"
end_date = datetime.now().strftime("%d%m%Y")

for t, pid in pair_ids.items():
    code = ticker_map[t]

    info = get_info(pid)
    info["ticker"] = code
    infos.append(info)

    hist = get_historical_prices(pid, start_date, end_date).reset_index()
    hist["ticker"] = code
    series.append(hist)

df_info = pd.concat(infos, ignore_index=True) 
df_prices = pd.concat(series, ignore_index=True)

df_prices_pivot = (
    df_prices
    .pivot(index="date", columns="ticker", values="price")
    .reset_index()
    .sort_values("date", ascending=False)
    .bfill()
    .reset_index(drop=True)
)

df_prices_pivot = df_prices_pivot[["date"] + list(funds.keys())] # mette in ordine le colonne.equivale a [["date","US","EU","EM","TECH"]]

print(df_prices_pivot)
