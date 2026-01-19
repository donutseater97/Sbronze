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
        df = fund.history(period="max", interval="1d").reset_index()[["Date", "Open"]]
        # Normalize date to naive and keep daily resolution
        df["Date"] = pd.to_datetime(df["Date"], utc=True).dt.tz_localize(None)
        df = df.rename(columns={"Open": ticker})
        dfs.append(df)
    except Exception as e:
        print(f"WARN: failed to fetch {ticker}: {e}")

if not dfs:
    raise SystemExit("No data fetched; check tickers or network")

# Merge all dataframes on Date with outer join
table = dfs[0]
for df in dfs[1:]:
    table = pd.merge(table, df, on="Date", how="outer")

# Sort by Date ascending
table = table.sort_values("Date").reset_index(drop=True)

# Forward-fill within each series; NaNs before first value remain NaN
for col in table.columns:
    if col != "Date":
        table[col] = table[col].ffill()

# Round numeric columns to 2 decimals
num_cols = [c for c in table.columns if c != "Date"]
table[num_cols] = table[num_cols].round(2)

# Map ticker columns to Fund names (e.g., 0P0001CRXW.F -> US)
rename_map = {}
for ticker in fund_map.keys():
    yahoo_col = f"{ticker}.F"
    if yahoo_col in table.columns:
        rename_map[yahoo_col] = fund_map[ticker]
table = table.rename(columns=rename_map)

# Ensure Date is string yyyy-mm-dd
table["Date"] = pd.to_datetime(table["Date"]).dt.strftime("%Y-%m-%d")

# Save to CSV for downstream use
table.to_csv("historical_data.csv", index=False)
print("Saved historical_data.csv with", len(table), "rows and", len(table.columns), "columns")