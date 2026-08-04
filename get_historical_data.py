from investgo import get_pair_id, get_historical_prices, get_info
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from io import BytesIO
import warnings
import os

warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')

# Script purpose: collect historical NAV/price data for all tracked funds and
# update the local CSV without overwriting previously stored history.
_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# Load the fund catalog from the local data folder so we know which tickers and
# ISINs need to be queried.
funds = pd.read_csv(os.path.join(_ROOT_DIR, "data", "funds.csv"))
print(f"DEBUG: Funds file loaded from: {os.path.join(_ROOT_DIR, 'data', 'funds.csv')}")
print(f"DEBUG: Funds loaded: {funds['Fund'].tolist()}")
print(f"DEBUG: Number of funds configured: {len(funds)}")

# JPMorgan funds are fetched directly from the JPMorgan AM API (by ISIN);
# everything else goes through investgo or a morningstar fallback.
is_jpm = funds["Fund Name"].str.contains("JPMorgan", case=False, na=False)
jpm_funds = funds[is_jpm]
investgo_funds = funds[~is_jpm]
print(f"DEBUG: JPMorgan funds ({len(jpm_funds)}): {jpm_funds['Fund'].tolist()}")
print(f"DEBUG: investgo funds ({len(investgo_funds)}): {investgo_funds['Fund'].tolist()}")

dfs = []
# Track which source each fund came from in this run (InvestGo, Morningstar, JPMorgan)
fund_sources = {}

# 1. Fetch data for non-JPM funds using investgo, with Morningstar as fallback.
print("Fetching data from investgo...")
start_date = "01011990"  # earliest reasonable default
end_date = datetime.now().strftime("%d%m%Y")
print(f"DEBUG: Fetch window -> start: {start_date}, end: {end_date}")

def fetch_investgo(ticker, fund_name):
    print(f"DEBUG: Fetching investgo data for {fund_name} (ticker={ticker})")
    pair_id = get_pair_id([ticker])[0]
    print(f"DEBUG: investgo pair_id for {ticker}: {pair_id}")
    hist_raw = get_historical_prices(pair_id, start_date, end_date)
    hist = hist_raw.reset_index()

    # Keep only the date and close price columns needed for later merging.
    hist = hist.rename(columns={"date": "Date", "price": fund_name})[["Date", fund_name]]

    # Convert Date to Europe/Rome tz-naive so it matches other sources.
    dt = pd.to_datetime(hist["Date"], errors="coerce")
    dt = dt.dt.tz_localize("Europe/Rome").dt.tz_localize(None)
    hist["Date"] = dt

    hist[fund_name] = pd.to_numeric(hist[fund_name], errors="coerce").round(2)
    print(f"DEBUG: investgo returned {len(hist)} rows for {fund_name}")
    # Record source for this fund
    fund_sources[fund_name] = "InvestGo"
    return hist


def fetch_morningstar(ticker, fund_name):
    print(f"DEBUG: Trying Morningstar fallback for {fund_name} (ticker={ticker})")

    url = (
        "https://tools.morningstar.it/api/rest.svc/timeseries_price/jbyiq3rhyf"
        f"?id={ticker}]2]0]FOITA$$ALL&currencyId=EUR&idtype=Morningstar"
        "&frequency=daily&startDate=1990-01-01&outputType=JSON"
    )

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    r = requests.get(url, headers=headers, timeout=30, allow_redirects=True)

    print("=" * 80)
    print("URL:", r.url)
    print("STATUS:", r.status_code)
    print("CONTENT-TYPE:", r.headers.get("Content-Type"))
    print("FIRST 1000 CHARS:")
    print(r.text[:1000])
    print("=" * 80)

    r.raise_for_status()

    data = r.json()

    detail = data["TimeSeries"]["Security"][0]["HistoryDetail"]

    hist = pd.DataFrame(detail)[["EndDate", "Value"]]
    hist.columns = ["Date", fund_name]
    hist["Date"] = pd.to_datetime(hist["Date"])
    hist[fund_name] = pd.to_numeric(hist[fund_name], errors="coerce").round(2)
    hist = hist.dropna()

    fund_sources[fund_name] = "Morningstar"

    return hist


for _, row in investgo_funds.iterrows():
    fund_name = row["Fund"]
    ticker = row["Ticker"]
    print(f"DEBUG: Processing non-JPM fund -> {fund_name} (ticker={ticker})")
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

# 2. Fetch JPMorgan funds from the JPMorgan AM API.
print("\nFetching JPMorgan funds from JPMorgan API...")

def fetch_jpm_nav(isin, fund_name):
    print(f"DEBUG: Fetching JPMorgan NAV for {fund_name} (ISIN={isin})")
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

    # Convert to Europe/Rome tz-naive for consistent downstream merging.
    df['Date'] = df['Date'].dt.tz_localize('Europe/Rome').dt.tz_localize(None)
    print(f"DEBUG: JPMorgan source returned {len(df)} rows for {fund_name}")
    # Record source for this fund
    fund_sources[fund_name] = "JPMorgan AM"
    return df

for _, row in jpm_funds.iterrows():
    fund_name = row["Fund"]
    isin = row["ISIN"]
    print(f"DEBUG: Processing JPMorgan fund -> {fund_name} (ISIN={isin})")
    try:
        df = fetch_jpm_nav(isin, fund_name)
        dfs.append(df)
        print(f"✓ {fund_name}: {len(df)} rows (ISIN {isin})")
    except Exception as e:
        print(f"✗ {fund_name}: {e}")
        import traceback
        traceback.print_exc()

# 3. Merge fetched dataframes and update the existing CSV without overwriting history.
print("\nMerging data...")
csv_path = os.path.join(_ROOT_DIR, "data", "historical_data.csv")
print(f"DEBUG: Output CSV path: {csv_path}")

if dfs:
    print(f"DEBUG: Merging {len(dfs)} fetched datasets")
    merged_table = dfs[0]
    for df in dfs[1:]:
        print(f"DEBUG: Merging additional frame with {len(df)} rows and columns {list(df.columns)}")
        merged_table = pd.merge(merged_table, df, on="Date", how="outer")
    print(f"DEBUG: Merged table shape after joins: {merged_table.shape}")
else:
    print("✗ No new data fetched")
    merged_table = None

# Load the existing CSV so a partial fetch can never destroy history.
if os.path.exists(csv_path):
    existing = pd.read_csv(csv_path)
    existing["Date"] = pd.to_datetime(existing["Date"])
    print(f"DEBUG: Existing CSV loaded with {len(existing)} rows and {len(existing.columns)} columns")
else:
    existing = pd.DataFrame(columns=["Date"])
    print("DEBUG: No existing historical data file found; starting from an empty table")

if merged_table is not None:
    if not existing.empty:
        existing = existing.set_index("Date")
        new = merged_table.set_index("Date")
        # New values take precedence on overlapping dates (fixes stale quotes),
        # while existing values are kept everywhere else.
        combined = new.combine_first(existing)
        print("DEBUG: Combined new data with existing history using new-over-existing precedence")
    else:
        combined = merged_table.set_index("Date")
        print("DEBUG: No existing file found, so the merged dataset is being used as-is")
    combined = combined.reset_index()
else:
    combined = existing.reset_index() if existing.index.name == "Date" else existing
    print("DEBUG: No merged table generated; using existing data only")

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
    print(f"DEBUG: Saved columns -> {list(combined.columns)}")
    # --- Generate per-fund source metadata (source, last available date) ---
    try:
        sources = []
        for fund_column in fund_columns:
            # Determine last non-null date for this fund (combined is sorted desc)
            series = combined[fund_column]
            first_valid = series.first_valid_index()
            last_date = combined.loc[first_valid, "Date"] if first_valid is not None else ""
            # Prefer recorded source from this run; else heuristic fallback
            src = fund_sources.get(fund_column)
            if not src:
                if fund_column in jpm_funds["Fund"].tolist():
                    src = "JPMorgan AM"
                else:
                    src = "InvestGo/Morningstar"
            sources.append({"Fund": fund_column, "Source": src, "LastDate": last_date})
        sources_df = pd.DataFrame(sources)
        sources_path = os.path.join(_ROOT_DIR, "data", "historical_sources.csv")
        sources_df.to_csv(sources_path, index=False)
        print(f"DEBUG: Wrote per-fund source metadata to {sources_path}")
    except Exception as _exc:
        print(f"DEBUG: Could not write historical_sources metadata: {_exc}")
else:
    print("✗ Nothing to save")