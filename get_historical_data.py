from investgo import get_pair_id, get_historical_prices, get_info
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from io import BytesIO
import warnings

warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')

# Load funds configuration
funds = pd.read_csv("funds.csv")

# Separate Me A Ee from the rest
meaee_fund = funds[funds["Fund"] == "Me A Ee"].iloc[0]
investgo_funds = funds[funds["Fund"] != "Me A Ee"]

dfs = []

# 1. Fetch data for first 5 funds using investgo
print("Fetching data from investgo...")
tickers = investgo_funds["Ticker"].tolist()
ticker_to_fund = dict(zip(investgo_funds["Ticker"], investgo_funds["Fund"]))

# Pair IDs for all tickers
pair_ids = {t: get_pair_id([t])[0] for t in tickers}

start_date = "01011990"  # earliest reasonable default
end_date = datetime.now().strftime("%d%m%Y")

for ticker, pair_id in pair_ids.items():
    fund_name = ticker_to_fund[ticker]
    try:
        hist_raw = get_historical_prices(pair_id, start_date, end_date)
        hist = hist_raw.reset_index()

        # Keep only date and close price
        hist = hist.rename(columns={"date": "Date", "price": fund_name})[["Date", fund_name]]

        # Convert Date to Europe/Rome tz-naive
        dt = pd.to_datetime(hist["Date"], errors="coerce")
        dt = dt.dt.tz_localize("Europe/Rome").dt.tz_localize(None)
        hist["Date"] = dt

        hist[fund_name] = pd.to_numeric(hist[fund_name], errors="coerce").round(2)
        dfs.append(hist)
        print(f"✓ {fund_name}: {len(hist)} rows")
    except Exception as e:
        print(f"✗ {fund_name}: {e}")

# 2. Fetch Me A Ee data from JPMorgan API
print("\nFetching Me A Ee from JPMorgan API...")
try:
    isin = meaee_fund["ISIN"]
    base_url = "https://am.jpmorgan.com/FundsMarketingHandler/excel"
    params = {
        "type": "historicalNav",
        "cusip": isin,
        "country": "it",
        "role": "adv",
        "locale": "it-IT",
        "fromDate": "2023-01-01",
        "toDate": datetime.now().strftime("%Y-%m-%d")
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    }
    
    response = requests.get(base_url, params=params, headers=headers)
    response.raise_for_status()
    
    # Parse Excel response
    excel_file = BytesIO(response.content)
    df_raw = pd.read_excel(excel_file)
    
    # Clean data: skip header rows
    df = df_raw.iloc[4:].copy()
    df.columns = ['Date', 'Me A Ee']
    df = df.dropna()
    
    # Convert Date and NAV
    df['Date'] = pd.to_datetime(df['Date'], format='%d.%m.%Y')
    df['Me A Ee'] = pd.to_numeric(df['Me A Ee'], errors='coerce').round(2)
    
    # Convert to Europe/Rome timezone
    df['Date'] = df['Date'].dt.tz_localize('Europe/Rome').dt.tz_localize(None)
    
    dfs.append(df)
    print(f"✓ Me A Ee: {len(df)} rows")
except Exception as e:
    print(f"✗ Me A Ee: {e}")

# 3. Merge all dataframes
print("\nMerging data...")
if dfs:
    merged_table = dfs[0]
    for df in dfs[1:]:
        merged_table = pd.merge(merged_table, df, on="Date", how="outer")
    
    merged_table = merged_table.sort_values("Date", ascending=True).reset_index(drop=True)

    fund_columns = [col for col in merged_table.columns if col != "Date"]
    for fund_column in fund_columns:
        merged_table[fund_column] = merged_table[fund_column].astype(float)
        series = merged_table[fund_column]
        first_valid_idx = series.first_valid_index()
        if first_valid_idx is None:
            # All NaN for this fund
            continue
        # Fill before first valid with NaN
        merged_table.loc[:first_valid_idx - 1, fund_column] = np.nan
        # Manual forward fill to avoid warnings
        filled_values = merged_table[fund_column].values.copy()
        last_valid = np.nan
        for i in range(len(filled_values)):
            if np.isnan(filled_values[i]):
                filled_values[i] = last_valid
            else:
                last_valid = filled_values[i]
        merged_table[fund_column] = filled_values

    merged_table = merged_table.sort_values("Date", ascending=False).reset_index(drop=True)

    merged_table["Date"] = pd.to_datetime(merged_table["Date"]).dt.strftime("%Y-%m-%d")
    
    desired_order = ["Date"] + funds["Fund"].tolist()
    available_cols = ["Date"] + [col for col in funds["Fund"].tolist() if col in merged_table.columns]
    merged_table = merged_table[available_cols]
    
    merged_table.to_csv("historical_data.csv", index=False, na_rep='')
    print(f"\n✓ Saved historical_data.csv with {len(merged_table)} rows and {len(merged_table.columns)} columns")
else:
    print("✗ No data fetched")
