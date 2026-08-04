"""
get_historical_data.py — Aggiorna data/historical_data.csv con i NAV di tutti i fondi.

Per OGNI fondo prova le sorgenti in cascata, fermandosi alla prima che riesce:
    1. investgo    (investing.com; spesso bloccato dagli IP GitHub Actions)
    2. Morningstar (lt.morningstar.com, endpoint pubblico multi-token)
    3. API ufficiale del fondo (JPMorgan / Fidelity / BlackRock / UBS)

Le sorgenti sono definite in utils/nav_sources.py e condivise con la pagina
Streamlit "Morningstar API data".

La scrittura del CSV non sovrascrive mai lo storico: i nuovi valori hanno
precedenza sulle date sovrapposte (per correggere quote stale), il resto della
storia resta intatto. Genera anche data/historical_sources.csv con la sorgente
effettivamente usata per ciascun fondo.
"""

import os
import warnings
from datetime import datetime

import numpy as np
import pandas as pd

from utils.nav_sources import (
    fetch_investgo_nav,
    fetch_morningstar_nav,
    fetch_jpmorgan_nav,
    OFFICIAL_FUND_SOURCES,
)

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

_ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

funds = pd.read_csv(os.path.join(_ROOT_DIR, "data", "funds.csv"))
print(f"DEBUG: Funds loaded: {funds['Fund'].tolist()}")
print(f"DEBUG: Number of funds configured: {len(funds)}")

dfs = []
fund_sources = {}
start_ddmmyyyy = "01011990"
end_ddmmyyyy = datetime.now().strftime("%d%m%Y")
print(f"DEBUG: Fetch window -> {start_ddmmyyyy} .. {end_ddmmyyyy}")


def fetch_fund(fund_name, ticker, isin, is_jpm):
    """Prova le sorgenti in cascata per un singolo fondo.

    Per i fondi JPMorgan l'API ufficiale è la più affidabile e viene provata per
    prima; per gli altri si prova investgo, poi Morningstar, poi l'eventuale API
    ufficiale del fondo. Ritorna (DataFrame, source_label) o solleva eccezione.
    """
    attempts = []
    if is_jpm:
        attempts.append(("JPMorgan AM", lambda: fetch_jpmorgan_nav(isin, fund_name)))
        attempts.append(("Morningstar", lambda: fetch_morningstar_nav(ticker, fund_name)))
    else:
        attempts.append(("InvestGo", lambda: fetch_investgo_nav(
            ticker, fund_name, start_ddmmyyyy, end_ddmmyyyy)))
        attempts.append(("Morningstar", lambda: fetch_morningstar_nav(ticker, fund_name)))
        official = OFFICIAL_FUND_SOURCES.get(isin)
        if official:
            src_label, fn = official
            attempts.append((src_label, lambda: fn(fund_name)))

    last_err = None
    for label, fn in attempts:
        try:
            print(f"DEBUG: {fund_name}: tentativo via {label}...")
            hist = fn()
            if hist is None or hist.empty:
                raise RuntimeError("dataset vuoto")
            print(f"\u2713 {fund_name}: {len(hist)} righe (fonte: {label})")
            return hist, label
        except Exception as e:
            print(f"\u2717 {fund_name} via {label}: {e}")
            last_err = e
    raise last_err if last_err else RuntimeError("nessuna sorgente disponibile")


for _, row in funds.iterrows():
    fund_name = row["Fund"]
    ticker = row["Ticker"]
    isin = row["ISIN"]
    is_jpm = "JPMorgan" in str(row["Fund Name"])
    print(f"\nDEBUG: === {fund_name} (ticker={ticker}, ISIN={isin}, jpm={is_jpm}) ===")
    try:
        hist, source = fetch_fund(fund_name, ticker, isin, is_jpm)
        dfs.append(hist)
        fund_sources[fund_name] = source
    except Exception as e:
        print(f"\u2717\u2717 {fund_name}: tutte le sorgenti fallite ({e})")

print("\nMerging data...")
csv_path = os.path.join(_ROOT_DIR, "data", "historical_data.csv")

if dfs:
    print(f"DEBUG: Merging {len(dfs)} fetched datasets")
    merged_table = dfs[0]
    for df in dfs[1:]:
        merged_table = pd.merge(merged_table, df, on="Date", how="outer")
    print(f"DEBUG: Merged table shape: {merged_table.shape}")
else:
    print("\u2717 No new data fetched")
    merged_table = None

if os.path.exists(csv_path):
    existing = pd.read_csv(csv_path)
    existing["Date"] = pd.to_datetime(existing["Date"])
    print(f"DEBUG: Existing CSV loaded: {len(existing)} rows, {len(existing.columns)} cols")
else:
    existing = pd.DataFrame(columns=["Date"])
    print("DEBUG: No existing CSV; starting fresh")

if merged_table is not None:
    if not existing.empty:
        existing = existing.set_index("Date")
        new = merged_table.set_index("Date")
        combined = new.combine_first(existing)
        print("DEBUG: Combined new-over-existing")
    else:
        combined = merged_table.set_index("Date")
    combined = combined.reset_index()
else:
    combined = existing.reset_index() if existing.index.name == "Date" else existing
    print("DEBUG: Using existing data only")

if combined is not None and not combined.empty:
    combined = combined.sort_values("Date", ascending=True).reset_index(drop=True)

    fund_columns = [c for c in combined.columns if c != "Date"]
    for col in fund_columns:
        combined[col] = combined[col].astype(float)
        first_valid_idx = combined[col].first_valid_index()
        if first_valid_idx is None:
            continue
        combined.loc[:first_valid_idx - 1, col] = np.nan
        vals = combined[col].values.copy()
        last = np.nan
        for i in range(len(vals)):
            if np.isnan(vals[i]):
                vals[i] = last
            else:
                last = vals[i]
        combined[col] = vals

    combined = combined.sort_values("Date", ascending=False).reset_index(drop=True)
    combined["Date"] = pd.to_datetime(combined["Date"]).dt.strftime("%Y-%m-%d")
    available_cols = ["Date"] + [c for c in funds["Fund"].tolist() if c in combined.columns]
    combined = combined[available_cols]

    combined.to_csv(csv_path, index=False, na_rep="")
    print(f"\n\u2713 Saved data/historical_data.csv: {len(combined)} rows, {len(combined.columns)} cols")

    try:
        rows = []
        for col in fund_columns:
            fv = combined[col].first_valid_index()
            last_date = combined.loc[fv, "Date"] if fv is not None else ""
            src = fund_sources.get(col, "sconosciuta")
            rows.append({"Fund": col, "Source": src, "LastDate": last_date})
        pd.DataFrame(rows).to_csv(
            os.path.join(_ROOT_DIR, "data", "historical_sources.csv"), index=False)
        print("DEBUG: Wrote data/historical_sources.csv")
        for r in rows:
            print(f"   {r['Fund']:8s} <- {r['Source']:12s} (ultimo {r['LastDate']})")
    except Exception as exc:
        print(f"DEBUG: Could not write sources metadata: {exc}")
else:
    print("\u2717 Nothing to save")