"""
Test script to fetch historical fund data using investgo library.
This will attempt to download historical prices for all funds in funds.csv.
"""

from investgo import get_pair_id, get_historical_prices, get_info
import pandas as pd
from datetime import datetime
import os

def fetch_historical_data():
    """Fetch historical data for all funds in funds.csv"""
    
    # Load funds from CSV
    if not os.path.exists("funds.csv"):
        print("❌ funds.csv not found!")
        return
    
    funds_df = pd.read_csv("funds.csv")
    print(f"📊 Loaded {len(funds_df)} funds from funds.csv")
    print(funds_df[["Fund", "Ticker", "Fund Name"]].to_string(index=False))
    print("\n" + "="*80 + "\n")
    
    # Extract tickers and fund codes
    tickers = funds_df["Ticker"].tolist()
    fund_codes = funds_df["Fund"].tolist()
    fund_colors = funds_df["Colour"].tolist()
    
    # Create mappings
    ticker_to_fund = dict(zip(tickers, fund_codes))
    fund_to_color = dict(zip(fund_codes, fund_colors))
    
    print("🔍 Fetching pair IDs for tickers...")
    
    # Get pair IDs for all tickers
    pair_ids = {}
    for ticker in tickers:
        try:
            pair_id = get_pair_id([ticker])[0]
            pair_ids[ticker] = pair_id
            fund_code = ticker_to_fund[ticker]
            print(f"  ✓ {fund_code} ({ticker}): Pair ID = {pair_id}")
        except Exception as e:
            print(f"  ✗ {ticker}: Failed to get pair ID - {e}")
    
    if not pair_ids:
        print("\n❌ No pair IDs found. Cannot proceed.")
        return
    
    print(f"\n✓ Successfully found {len(pair_ids)} pair IDs\n")
    print("="*80 + "\n")
    
    # Set date range
    start_date = "01102024"  # October 1, 2024
    end_date = datetime.now().strftime("%d%m%Y")
    print(f"📅 Fetching data from {start_date} to {end_date}\n")
    
    # Fetch info and historical prices
    infos = []
    series = []
    
    for ticker, pair_id in pair_ids.items():
        fund_code = ticker_to_fund[ticker]
        print(f"📈 Fetching data for {fund_code} ({ticker})...")
        
        try:
            # Get fund info
            info = get_info(pair_id)
            info["ticker"] = ticker
            info["fund_code"] = fund_code
            infos.append(info)
            print(f"  ✓ Info retrieved")
            
            # Get historical prices
            hist = get_historical_prices(pair_id, start_date, end_date).reset_index()
            hist["ticker"] = ticker
            hist["fund_code"] = fund_code
            series.append(hist)
            print(f"  ✓ Historical prices retrieved: {len(hist)} data points")
            
        except Exception as e:
            print(f"  ✗ Error: {e}")
    
    if not series:
        print("\n❌ No historical data retrieved. Exiting.")
        return
    
    print("\n" + "="*80 + "\n")
    print("💾 Processing and saving data...")
    
    # Combine all info and prices
    df_info = pd.concat(infos, ignore_index=True)
    df_prices = pd.concat(series, ignore_index=True)
    
    print(f"  ✓ Combined {len(df_prices)} price records")
    
    # Pivot prices table (date as rows, fund codes as columns)
    df_prices_pivot = (
        df_prices
        .pivot(index="date", columns="fund_code", values="price")
        .reset_index()
        .sort_values("date", ascending=False)
        .bfill()  # Backfill missing values
        .reset_index(drop=True)
    )
    
    # Reorder columns: date first, then fund codes in original order
    available_funds = [f for f in fund_codes if f in df_prices_pivot.columns]
    df_prices_pivot = df_prices_pivot[["date"] + available_funds]
    
    # Save to CSV files
    df_info.to_csv("fund_info.csv", index=False)
    df_prices_pivot.to_csv("historical_prices.csv", index=False)
    
    print(f"  ✓ Saved fund info to fund_info.csv")
    print(f"  ✓ Saved historical prices to historical_prices.csv")
    
    print("\n" + "="*80 + "\n")
    print("📊 Summary:")
    print(f"  • Funds processed: {len(available_funds)}")
    print(f"  • Date range: {df_prices_pivot['date'].min()} to {df_prices_pivot['date'].max()}")
    print(f"  • Total records: {len(df_prices_pivot)}")
    print("\n✅ Data fetch complete!\n")
    
    # Display preview
    print("Preview of historical_prices.csv:")
    print(df_prices_pivot.head(10).to_string(index=False))
    
    return df_prices_pivot, df_info


if __name__ == "__main__":
    print("\n" + "="*80)
    print("  HISTORICAL FUND DATA FETCHER")
    print("="*80 + "\n")
    
    try:
        df_prices, df_info = fetch_historical_data()
        
        if df_prices is not None:
            print("\n" + "="*80)
            print("✅ SUCCESS: Historical data fetched and saved!")
            print("="*80 + "\n")
        else:
            print("\n" + "="*80)
            print("⚠️  WARNING: No data was fetched. Check errors above.")
            print("="*80 + "\n")
            
    except Exception as e:
        print("\n" + "="*80)
        print(f"❌ ERROR: {e}")
        print("="*80 + "\n")
        import traceback
        traceback.print_exc()
