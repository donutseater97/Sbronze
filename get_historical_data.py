import os
import re
from datetime import datetime
from io import BytesIO
from urllib.parse import urljoin
import xml.etree.ElementTree as ET

from investgo import get_pair_id, get_historical_prices, get_info
import requests
import pandas as pd
import numpy as np
import warnings

warnings.filterwarnings('ignore', category=UserWarning, module='openpyxl')

_SESSION_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
}
_SPREADSHEET_NS = {"ss": "urn:schemas-microsoft-com:office:spreadsheet"}


def _download_bytes(url, headers=None):
    merged_headers = dict(_SESSION_HEADERS)
    if headers:
        merged_headers.update(headers)
    response = requests.get(url, headers=merged_headers, timeout=30, allow_redirects=True)
    response.raise_for_status()
    return response


def _read_spreadsheetml_workbook(content, worksheet_name=None):
    cleaned = content.lstrip(b"\xef\xbb\xbf").lstrip(b"\xef\xbb\xbf")
    root = ET.fromstring(cleaned)
    worksheets = root.findall(".//ss:Worksheet", _SPREADSHEET_NS)
    if not worksheets:
        raise ValueError("SpreadsheetML workbook has no worksheets")

    worksheet = None
    if worksheet_name:
        for candidate in worksheets:
            if candidate.attrib.get("{urn:schemas-microsoft-com:office:spreadsheet}Name") == worksheet_name:
                worksheet = candidate
                break
    if worksheet is None:
        worksheet = worksheets[0]

    rows = []
    for row in worksheet.findall(".//ss:Row", _SPREADSHEET_NS):
        values = []
        for cell in row.findall("ss:Cell", _SPREADSHEET_NS):
            data = cell.find("ss:Data", _SPREADSHEET_NS)
            values.append(data.text if data is not None else None)
        if any(value not in (None, "") for value in values):
            rows.append(values)

    if not rows:
        return pd.DataFrame()

    width = max(len(row) for row in rows)
    padded = [row + [None] * (width - len(row)) for row in rows]
    df = pd.DataFrame(padded)
    df.columns = df.iloc[0]
    return df.iloc[1:].reset_index(drop=True)


def _normalize_nav_table(df, fund_name):
    if df.empty:
        raise ValueError(f"No NAV data found for {fund_name}")

    lower_columns = {col: str(col).strip().lower() for col in df.columns}
    date_col = next(
        (
            col
            for col in df.columns
            if any(token in lower_columns[col] for token in ("date", "al", "data", "enddate"))
        ),
        df.columns[0],
    )
    value_col = next(
        (
            col
            for col in df.columns
            if col != date_col and any(token in lower_columns[col] for token in ("nav", "value", "price", "close"))
        ),
        None,
    )
    if value_col is None:
        value_col = next(col for col in df.columns if col != date_col)

    out = df[[date_col, value_col]].copy()
    out.columns = ["Date", fund_name]
    out["Date"] = pd.to_datetime(out["Date"], errors="coerce", dayfirst=True)
    out[fund_name] = pd.to_numeric(out[fund_name], errors="coerce").round(2)
    out = out.dropna(subset=["Date", fund_name])
    out["Date"] = out["Date"].dt.tz_localize("Europe/Rome").dt.tz_localize(None)
    return out


def _load_nav_dataframe(response, fund_name, worksheet_name=None):
    content = response.content
    is_spreadsheetml = content.lstrip(b"\xef\xbb\xbf").startswith(b"<?xml") or b"urn:schemas-microsoft-com:office:spreadsheet" in content[:500]
    if is_spreadsheetml:
        return _normalize_nav_table(_read_spreadsheetml_workbook(content, worksheet_name=worksheet_name), fund_name)

    try:
        df_raw = pd.read_excel(BytesIO(content), sheet_name=worksheet_name or 0)
    except Exception:
        df_raw = pd.read_excel(BytesIO(content))
    return _normalize_nav_table(df_raw, fund_name)

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

# 1. Fetch data for non-JPM funds with a ranked fallback chain.
print("Fetching data from investgo, Morningstar, and official sources...")
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


_MORNINGSTAR_KEYS = [
    "jbyiq3rhyf",
    "nen6ere626",
    "t92wz0sj7c",
]


def fetch_morningstar(ticker, fund_name, isin=None):
    print(f"DEBUG: Trying Morningstar fallback for {fund_name} (ticker={ticker})")

    ids = [ticker]
    if isin and isin not in ids:
        ids.append(isin)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    for key in _MORNINGSTAR_KEYS:
        for current_id in ids:
            url = (
                f"https://tools.morningstar.it/api/rest.svc/timeseries_price/{key}"
                f"?id={current_id}]2]0]FOITA$$ALL&idtype=Morningstar"
                "&currencyId=EUR&frequency=daily&startDate=1990-01-01&outputType=JSON"
            )

            r = requests.get(url, headers=headers, timeout=30, allow_redirects=True)

            print("=" * 80)
            print("URL:", r.url)
            print("STATUS:", r.status_code)
            print("CONTENT-TYPE:", r.headers.get("Content-Type"))
            print("FIRST 1000 CHARS:")
            print(r.text[:1000])
            print("=" * 80)

            if r.status_code != 200:
                continue

            try:
                data = r.json()
                detail = data["TimeSeries"]["Security"][0]["HistoryDetail"]
            except Exception as exc:
                print(f"DEBUG: Morningstar parse failed for {fund_name} with {key}/{current_id}: {exc}")
                continue

            hist = pd.DataFrame(detail)[["EndDate", "Value"]]
            hist.columns = ["Date", fund_name]
            hist["Date"] = pd.to_datetime(hist["Date"])
            hist[fund_name] = pd.to_numeric(hist[fund_name], errors="coerce").round(2)
            hist = hist.dropna()

            fund_sources[fund_name] = "Morningstar"
            return hist

    raise RuntimeError(f"Morningstar historical price fallback unavailable for {fund_name}")


def fetch_fidelity_nav(url, fund_name):
    print(f"DEBUG: Trying Fidelity source for {fund_name}")
    response = _download_bytes(url)
    hist = _load_nav_dataframe(response, fund_name)
    fund_sources[fund_name] = "Fidelity"
    return hist


def fetch_blackrock_nav(page_url, fund_name):
    print(f"DEBUG: Trying BlackRock source for {fund_name}")
    if "fileType=xls" in page_url:
        download_url = page_url.replace("&amp;", "&")
    else:
        page = requests.get(page_url, headers=_SESSION_HEADERS, timeout=30, allow_redirects=True)
        page.raise_for_status()
        match = re.search(
            r'<a[^>]+aria-label="Download data file"[^>]+href="([^"]+fileType=xls[^"]+)"',
            page.text,
        )
        if not match:
            raise RuntimeError(f"Could not find BlackRock download link for {fund_name}")
        download_url = urljoin(page_url, match.group(1).replace("&amp;", "&"))
    response = _download_bytes(download_url, headers={"Referer": page_url})
    hist = _load_nav_dataframe(response, fund_name, worksheet_name="Storico")
    fund_sources[fund_name] = "BlackRock"
    print(f"DEBUG: BlackRock source returned {len(hist)} rows for {fund_name}")
    return hist


def fetch_ubs_nav(url, fund_name):
    print(f"DEBUG: Trying UBS source for {fund_name}")
    candidates = [
        url,
        url.replace("period=7%20giorni", "period=All"),
        url.replace("period=7%20giorni", "period=all"),
        url.replace("period=7%20giorni", "period=Dal%20lancio"),
    ]
    last_error = None
    for candidate in candidates:
        try:
            response = _download_bytes(candidate)
            hist = _load_nav_dataframe(response, fund_name)
            fund_sources[fund_name] = "UBS"
            print(f"DEBUG: UBS source returned {len(hist)} rows for {fund_name}")
            return hist
        except Exception as exc:
            last_error = exc
            print(f"DEBUG: UBS candidate failed for {fund_name}: {exc}")
    raise RuntimeError(f"UBS source unavailable for {fund_name}: {last_error}")


OFFICIAL_FUND_SOURCES = {
    "EU": lambda fund_name: fetch_fidelity_nav(
        "https://www.fidelity-italia.it/api/ce/fdh/HistoricalNav.xlsx?id=LU0261952682&countries=it&country=it&languages=it%2Cen&language=it&channels=ce.private-investor%2Cce.professional-investor&channel=ce.professional-investor&r=1784794788568",
        fund_name,
    ),
    "Tech": lambda fund_name: fetch_fidelity_nav(
        "https://www.fidelity-italia.it/api/ce/fdh/HistoricalNav.xlsx?id=LU1213836080&countries=it&country=it&languages=it%2Cen&language=it&channels=ce.private-investor%2Cce.professional-investor&channel=ce.professional-investor&r=1784794852605",
        fund_name,
    ),
    "EM": lambda fund_name: fetch_blackrock_nav(
        "https://www.blackrock.com/it/consulenti/products/280749/bsf-blackrock-emerging-markets-equity-strategies-e2-eur/1538022822380.ajax?fileType=xls&fileName=BSF-Emerging-Markets-Equity-Strategies-Fund-Class-E2-EUR_fund&dataType=fund",
        fund_name,
    ),
    "EU HY": lambda fund_name: fetch_ubs_nav(
        "https://www.ubs.com/app/HA4/api/api/price-services/358/downloadtoexcel?currency=EUR&period=7%20giorni&ssp=0&toDate=22.07.2026&fromDate=15.07.2026&locale=it_IT_RETL&sgmtKey=ubsf.emwh&profile_variant=&fileName=UBSFunds_Prices_",
        fund_name,
    ),
}


def fetch_official_source(fund_name):
    source = OFFICIAL_FUND_SOURCES.get(fund_name)
    if source is None:
        raise KeyError(fund_name)
    return source(fund_name)


for _, row in investgo_funds.iterrows():
    fund_name = row["Fund"]
    ticker = row["Ticker"]
    print(f"DEBUG: Processing non-JPM fund -> {fund_name} (ticker={ticker})")
    fetchers = [
        ("investgo", lambda: fetch_investgo(ticker, fund_name)),
        ("Morningstar", lambda: fetch_morningstar(ticker, fund_name, isin=row.get("ISIN"))),
        ("official source", lambda: fetch_official_source(fund_name)),
    ]
    hist = None
    last_error = None
    for label, fetcher in fetchers:
        try:
            hist = fetcher()
            dfs.append(hist)
            print(f"✓ {fund_name}: {len(hist)} rows ({label})")
            break
        except Exception as exc:
            last_error = exc
            print(f"✗ {fund_name} via {label}: {exc}")
    if hist is None:
        print(f"✗ {fund_name}: all non-JPM sources failed ({last_error})")

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