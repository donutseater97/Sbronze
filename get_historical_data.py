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

# Load funds configuration from data/ directory (percorso assoluto)
funds = pd.read_csv(os.path.join(_ROOT_DIR, "data", "funds.csv"))
print(f"DEBUG: Funds loaded: {funds['Fund'].tolist()}")
print(f"DEBUG: Number of funds: {len(funds)}")

# JPMorgan funds are fetched directly from the JPMorgan AM API (by ISIN);
# everything else goes through investgo.
is_jpm = funds["Fund Name"].str.contains("JPMorgan", case=False, na=False)
jpm_funds = funds[is_jpm]
investgo_funds = funds[~is_jpm]
print(f"DEBUG: JPMorgan funds: {jpm_funds['Fund'].tolist()}")
print(f"DEBUG: investgo funds: {investgo_funds['Fund'].tolist()}")

dfs = []

# 1. Fetch data for non-JPM funds using investgo
print("Fetching data from investgo...")
start_date = "01011990"  # earliest reasonable default
end_date = datetime.now().strftime("%d%m%Y")

def fetch_investgo(ticker, fund_name):
    pair_id = get_pair_id([ticker])[0]
    hist_raw = get_historical_prices(pair_id, start_date, end_date)
    hist = hist_raw.reset_index()

    # Keep only date and close price
    hist = hist.rename(columns={"date": "Date", "price": fund_name})[["Date", fund_name]]

    # Convert Date to Europe/Rome tz-naive
    dt = pd.to_datetime(hist["Date"], errors="coerce")
    dt = dt.dt.tz_localize("Europe/Rome").dt.tz_localize(None)
    hist["Date"] = dt

    hist[fund_name] = pd.to_numeric(hist[fund_name], errors="coerce").round(2)
    return hist


def fetch_morningstar(ticker, fund_name):
    """Fallback: Morningstar public timeseries API (same official NAV chain
    that investing.com uses). Ticker is the Morningstar ID from funds.csv."""
    url = (
        "https://tools.morningstar.it/api/rest.svc/timeseries_price/jbyiq3rhyf"
        f"?id={ticker}]2]0]FOITA$$ALL&currencyId=EUR&idtype=Morningstar"
        "&frequency=daily&startDate=1990-01-01&outputType=JSON"
    )
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    r = requests.get(url, headers=headers, timeout=30)
    r.raise_for_status()
    detail = r.json()["TimeSeries"]["Security"][0]["HistoryDetail"]
    hist = pd.DataFrame(detail)[["EndDate", "Value"]]
    hist.columns = ["Date", fund_name]
    hist["Date"] = pd.to_datetime(hist["Date"])
    hist[fund_name] = pd.to_numeric(hist[fund_name], errors="coerce").round(2)
    hist = hist.dropna()
    return hist


for _, row in investgo_funds.iterrows():
    fund_name = row["Fund"]
    ticker = row["Ticker"]
    try:
        hist = fetch_investgo(ticker, fund_name)
        dfs.append(hist)
        print(f"✓ {fund_name}: {len(hist)} rows (investgo)")
    except Exception as e:
        print(f"✗ {fund_name} via investgo: {e} — trying Morningstar fallback...")
        try:
            hist = fetch_morningstar(ticker, fund_name)
            dfs.append(hist)
            print(f"✓ {fund_name}: {len(hist)} rows (Morningstar fallback)")
        except Exception as e2:
            print(f"✗ {fund_name} via Morningstar: {e2}")

# 2. Fetch JPMorgan funds from the JPMorgan AM API
print("\nFetching JPMorgan funds from JPMorgan API...")

def fetch_jpm_nav(isin, fund_name):
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
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    }
    response = requests.get(base_url, params=params, headers=headers, timeout=30)
    response.raise_for_status()

    # Parse Excel response
    df_raw = pd.read_excel(BytesIO(response.content))

    # Clean data: skip header rows
    df = df_raw.iloc[4:].copy()
    df.columns = ['Date', fund_name]
    df = df.dropna()

    # Convert Date and NAV
    df['Date'] = pd.to_datetime(df['Date'], format='%d.%m.%Y')
    df[fund_name] = pd.to_numeric(df[fund_name], errors='coerce').round(2)

    # Convert to Europe/Rome tz-naive
    df['Date'] = df['Date'].dt.tz_localize('Europe/Rome').dt.tz_localize(None)
    return df

for _, row in jpm_funds.iterrows():
    fund_name = row["Fund"]
    isin = row["ISIN"]
    try:
        df = fetch_jpm_nav(isin, fund_name)
        dfs.append(df)
        print(f"✓ {fund_name}: {len(df)} rows (ISIN {isin})")
    except Exception as e:
        print(f"✗ {fund_name}: {e}")
        import traceback
        traceback.print_exc()

# 3. Merge fetched dataframes and update the existing CSV (never overwrite history)
print("\nMerging data...")
csv_path = os.path.join(_ROOT_DIR, "data", "historical_data.csv")

if dfs:
    merged_table = dfs[0]
    for df in dfs[1:]:
        merged_table = pd.merge(merged_table, df, on="Date", how="outer")
else:
    print("✗ No new data fetched")
    merged_table = None

# Load existing CSV so a partial fetch can never destroy history
if os.path.exists(csv_path):
    existing = pd.read_csv(csv_path)
    existing["Date"] = pd.to_datetime(existing["Date"])
else:
    existing = pd.DataFrame(columns=["Date"])

if merged_table is not None:
    if not existing.empty:
        existing = existing.set_index("Date")
        new = merged_table.set_index("Date")
        # New values take precedence on overlapping dates (fixes stale quotes),
        # existing values are kept everywhere else.
        combined = new.combine_first(existing)
    else:
        combined = merged_table.set_index("Date")
    combined = combined.reset_index()
else:
    combined = existing.reset_index() if existing.index.name == "Date" else existing

if combined is not None and not combined.empty:
    combined = combined.sort_values("Date", ascending=True).reset_index(drop=True)

    fund_columns = [col for col in combined.columns if col != "Date"]
    for fund_column in fund_columns:
        combined[fund_column] = combined[fund_column].astype(float)
        series = combined[fund_column]
        first_valid_idx = series.first_valid_index()
        if first_valid_idx is None:
            # All NaN for this fund
            continue
        # Fill before first valid with NaN
        combined.loc[:first_valid_idx - 1, fund_column] = np.nan
        # Manual forward fill to avoid warnings
        filled_values = combined[fund_column].values.copy()
        last_valid = np.nan
        for i in range(len(filled_values)):
            if np.isnan(filled_values[i]):
                filled_values[i] = last_valid
            else:
                last_valid = filled_values[i]
        combined[fund_column] = filled_values

    combined = combined.sort_values("Date", ascending=False).reset_index(drop=True)

    combined["Date"] = pd.to_datetime(combined["Date"]).dt.strftime("%Y-%m-%d")

    available_cols = ["Date"] + [col for col in funds["Fund"].tolist() if col in combined.columns]
    combined = combined[available_cols]

    combined.to_csv(csv_path, index=False, na_rep='')
    print(f"\n✓ Saved data/historical_data.csv with {len(combined)} rows and {len(combined.columns)} columns")
else:
    print("✗ Nothing to save")