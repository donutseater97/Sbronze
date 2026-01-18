import yfinance as yf         # Import the yfinance library to get financial data
import pandas as pd           # Import pandas for working with tables (dataframes)
from datetime import datetime # Import datetime to get current date and time

tickers = [     
    "0P0001QEPX.F"   
]

dfs = []                      # Create an empty list to store each fund's data
for ticker in tickers:        # Loop through each ticker symbol in the list
    fund = yf.Ticker(ticker)
    df = fund.history().reset_index()[["Date", "Open"]]         # Make 'Date' a column and keep only 'Date' and 'Open' price
    df = df.rename(columns={"Open": ticker})          # Rename 'Open' column to the ticker symbol
    dfs.append(df) 
# Merge all dataframes on 'Date' so each ticker's prices are in separate columns
table = dfs[0]                # Start with the first dataframe
for df in dfs[1:]:            # Loop through the rest of the dataframes
    table = pd.merge(table, df, on="Date", how="outer")  # Merge them together by 'Date'

# Round all numeric columns to 2 decimal places
table.iloc[:, 1:] = table.iloc[:, 1:].round(2)

print(table)                  # Print the final table to the terminal