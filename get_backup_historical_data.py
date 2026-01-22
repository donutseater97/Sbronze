import yfinance as yf         # Import the yfinance library to get financial data
import pandas as pd           # Import pandas for working with tables (dataframes)

# Load tickers dynamically from funds.csv and append .F suffix; keep mapping to Fund names
funds = pd.read_csv("funds.csv")
fund_map = {row["Ticker"]: row["Fund"] for _, row in funds.iterrows() if pd.notna(row["Ticker"])}
tickers = [f"{t}.F" for t in fund_map.keys()]

dfs = []
for ticker in tickers:
    try:
        fund = yf.Ticker(ticker)
        df = fund.history(period="100y", interval="1d").reset_index()[["Date", "Open"]]
        # Normalize date to Europe/Rome timezone, then to naive
        df["Date"] = pd.to_datetime(df["Date"], utc=True).dt.tz_convert('Europe/Rome').dt.tz_localize(None)
        df = df.rename(columns={"Open": ticker})
        dfs.append(df)
    except Exception as e:
        print(f"WARN: failed to fetch {ticker}: {e}")

table = dfs[0]                # Start with the first dataframe

for df in dfs[1:]:            # Loop through the rest of the dataframes
    table = pd.merge(table, df, on="Date", how="outer")  # Merge them together by 'Date'

table = table.sort_values("Date").reset_index(drop=True)

# Forward-fill within each series; NaNs before first value remain NaN
for col in table.columns:
    if col != "Date":
        table[col] = table[col].ffill()

# Round numeric columns to 2 decimals and format Date column
num_cols = [c for c in table.columns if c != "Date"]
table[num_cols] = table[num_cols].round(2)
table["Date"] = table["Date"].dt.strftime("%Y-%m-%d")

table = table.sort_values("Date", ascending=False).reset_index(drop=True)

# Rename columns from ticker symbols to fund names
rename_map = {}
for ticker in fund_map.keys():
    ticker_col = f"{ticker}.F"
    if ticker_col in table.columns:
        rename_map[ticker_col] = fund_map[ticker]
table = table.rename(columns=rename_map)

# Save the table to CSV
table.to_csv("historical_data.csv", index=False)

print("Saved historical_data.csv with", len(table), "rows and", len(table.columns), "columns")