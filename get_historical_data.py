from investgo import get_pair_id, get_historical_prices, get_info
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from io import BytesIO
import warnings
import os

warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')

# Directory root del progetto (dove si trova questo script)
_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))


def normalize_date_to_rome_day(date_series):
    dt = pd.to_datetime(date_series, errors="coerce")
    if dt.dt.tz is None:
        dt = dt.dt.tz_localize("Europe/Rome")
    else:
        dt = dt.dt.tz_convert("Europe/Rome")
    return dt.dt.tz_localize(None).dt.normalize()


def prepare_fund_history(df, value_col, source_name):
    df = df.copy()
    df["Date"] = normalize_date_to_rome_day(df["Date"])
    invalid_dates = df["Date"].isna().sum()
    if invalid_dates:
        print(f"⚠ {source_name}: dropping {invalid_dates} rows with invalid dates")
    df = df.dropna(subset=["Date"])

    duplicate_dates = int(df["Date"].duplicated().sum())
    if duplicate_dates:
        print(f"⚠ {source_name}: dropping {duplicate_dates} duplicate Date rows (keeping last)")
        df = df.sort_values("Date").drop_duplicates(subset=["Date"], keep="last")

    df[value_col] = pd.to_numeric(df[value_col], errors="coerce").round(2)
    return df[["Date", value_col]].sort_values("Date").reset_index(drop=True)

# Load funds configuration from data/ directory (percorso assoluto)
funds = pd.read_csv(os.path.join(_ROOT_DIR, "data", "funds.csv"))
print(f"DEBUG: Funds loaded: {funds['Fund'].tolist()}")
print(f"DEBUG: Number of funds: {len(funds)}")

# Separate Me A Ee from the rest
meaee_fund = funds[funds["Fund"] == "Me A Ee"].iloc[0]
investgo_funds = funds[funds["Fund"] != "Me A Ee"]
print(f"DEBUG: investgo_funds: {investgo_funds['Fund'].tolist()}")

dfs = []

# 1. Fetch data for first 5 funds using investgo
print("Fetching data from investgo...")
tickers = investgo_funds["Ticker"].tolist()
ticker_to_fund = dict(zip(investgo_funds["Ticker"], investgo_funds["Fund"]))

# Pair IDs for all tickers
pair_ids = {ticker: get_pair_id([ticker])[0] for ticker in tickers}

start_date = "01011990"  # earliest reasonable default
end_date = datetime.now().strftime("%d%m%Y")

for ticker, pair_id in pair_ids.items():
    fund_name = ticker_to_fund[ticker]
    try:
        hist_raw = get_historical_prices(pair_id, start_date, end_date)
        hist = hist_raw.reset_index()

        # Keep only date and close price
        hist = hist.rename(columns={"date": "Date", "price": fund_name})[["Date", fund_name]]

        hist = prepare_fund_history(hist, fund_name, fund_name)
        dfs.append(hist)
        print(f"✓ {fund_name}: {len(hist)} rows")
    except Exception as e:
        print(f"✗ {fund_name}: {e}")

# 2. Fetch Me A Ee data from JPMorgan API
print("\nFetching Me A Ee from JPMorgan API...")
try:
    isin = meaee_fund["ISIN"]
    print(f"DEBUG: Using ISIN: {isin}")
    base_url = "https://am.jpmorgan.com/FundsMarketingHandler/excel"
    params = {
        "type": "historicalNav",
        "cusip": isin,
        "country": "it",
        "role": "adv",
        "locale": "it-IT",
        "fromDate": "1990-01-01",
        "toDate": datetime.now().strftime("%Y-%m-%d")
    }
    print(f"DEBUG: API params: {params}")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    }
    
    print(f"DEBUG: Making request to {base_url}")
    response = requests.get(base_url, params=params, headers=headers, timeout=30)
    print(f"DEBUG: Response status code: {response.status_code}")
    response.raise_for_status()
    
    # Parse Excel response
    excel_file = BytesIO(response.content)
    df_raw = pd.read_excel(excel_file)
    print(f"DEBUG: Raw Excel shape: {df_raw.shape}")
    
    # Clean data: skip header rows
    df = df_raw.iloc[4:].copy()
    df.columns = ['Date', 'Me A Ee']
    df = df.dropna()
    
    # Convert Date and NAV
    df['Date'] = pd.to_datetime(df['Date'], format='%d.%m.%Y', errors='coerce')
    df = prepare_fund_history(df, 'Me A Ee', 'Me A Ee')

    dfs.append(df)
    print(f"✓ Me A Ee: {len(df)} rows")
except Exception as e:
    print(f"✗ Me A Ee: {e}")
    import traceback
    traceback.print_exc()

# 3. Merge all dataframes
print("\nMerging data...")
if dfs:
    merged_table = dfs[0]
    for df in dfs[1:]:
        merged_table = pd.merge(merged_table, df, on="Date", how="outer")
    
    merged_table = merged_table.sort_values("Date", ascending=True).reset_index(drop=True)
    merged_duplicate_dates = int(merged_table["Date"].duplicated().sum())
    if merged_duplicate_dates:
        print(f"⚠ Merge produced {merged_duplicate_dates} duplicate Date rows; collapsing by last non-null value")
        fund_columns = [col for col in merged_table.columns if col != "Date"]
        aggregations = {
            col: (lambda s: s.dropna().iloc[-1] if s.notna().any() else np.nan)
            for col in fund_columns
        }
        merged_table = (
            merged_table.sort_values("Date")
            .groupby("Date", as_index=False)
            .agg(aggregations)
            .sort_values("Date", ascending=True)
            .reset_index(drop=True)
        )

    fund_columns = [col for col in merged_table.columns if col != "Date"]
    for fund_column in fund_columns:
        series = pd.to_numeric(merged_table[fund_column], errors="coerce")
        first_valid_idx = series.first_valid_index()
        if first_valid_idx is None:
            # All NaN for this fund
            merged_table[fund_column] = series
            continue
        # Fill before first valid with NaN
        series.loc[:first_valid_idx - 1] = np.nan
        orig_non_na = series.notna()
        merged_table[fund_column] = series.ffill()
        changed_real_values = orig_non_na & (~np.isclose(merged_table[fund_column], series, equal_nan=True))
        if changed_real_values.any():
            print(
                f"⚠ {fund_column}: detected {int(changed_real_values.sum())} unexpected changes on originally non-null rows"
            )
        filled_count = int((~orig_non_na & merged_table[fund_column].notna()).sum())
        if filled_count:
            print(f"DEBUG: {fund_column}: forward-filled {filled_count} rows")

    merged_table = merged_table.sort_values("Date", ascending=False).reset_index(drop=True)

    merged_table["Date"] = pd.to_datetime(merged_table["Date"]).dt.strftime("%Y-%m-%d")
    
    desired_order = ["Date"] + funds["Fund"].tolist()
    available_cols = ["Date"] + [col for col in funds["Fund"].tolist() if col in merged_table.columns]
    merged_table = merged_table[available_cols]
    
    merged_table.to_csv(os.path.join(_ROOT_DIR, "data", "historical_data.csv"), index=False, na_rep='')
    print(f"\n✓ Saved data/historical_data.csv with {len(merged_table)} rows and {len(merged_table.columns)} columns")
else:
    print("✗ No data fetched")
