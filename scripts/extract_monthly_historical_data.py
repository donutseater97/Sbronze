#!/usr/bin/env python3
"""
extract_monthly_historical_data.py

Usage:
  python3 scripts/extract_monthly_historical_data.py /path/to/historical_data.csv /path/to/monthly_historical_data.csv [RETURNS_CSV]
  (use '-' or 'none' as OUTPUT_CSV to skip writing monthly prices and generate only returns)

Creates a CSV with the first available date of each month (earliest date present in that month)
starting from the month that contains the most recent first-observation across funds (option 1 per request).

"""
import sys
from pathlib import Path
import pandas as pd


def extract_monthly_historical_data(input_csv: str, output_csv: str, returns_output: str = None):
    df = pd.read_csv(input_csv, parse_dates=["Date"])  # keep Date parsed

    # Ensure sorted ascending by date
    df = df.sort_values("Date").reset_index(drop=True)

    # Identify fund columns (all except Date)
    funds = [c for c in df.columns if c != "Date"]

    # Convert fund columns to numeric and coerce errors to NaN
    df[funds] = df[funds].apply(pd.to_numeric, errors="coerce")

    # First non-null date for each fund
    first_dates = {}
    for f in funds:
        non_null = df.loc[df[f].notna(), "Date"]
        first_dates[f] = non_null.min() if not non_null.empty else pd.NaT

    # Most recent (max) of those first-observation dates
    # This is the "youngest" fund's first observation
    max_first_date = max(d for d in first_dates.values() if pd.notna(d))
    start_period = max_first_date.to_period("M")

    # Find earliest date present in each month (dataset's earliest date in that month)
    df = df.copy()
    df["Period"] = df["Date"].dt.to_period("M")
    month_first_dates = df.groupby("Period")["Date"].min()

    # Filter periods from start_period through the last available period
    selected_periods = [p for p in month_first_dates.index if p >= start_period]

    # Collect the corresponding dates
    selected_dates = month_first_dates.loc[selected_periods].sort_values().values

    # Build monthly dataframe using those dates
    monthly = df.loc[df["Date"].isin(selected_dates), ["Date"] + funds].sort_values("Date").reset_index(drop=True)

    # Write monthly output unless user asked to skip (pass '-' or 'none' as OUTPUT_CSV to skip)
    if output_csv and str(output_csv).lower() not in ("-", "none", "null", "skip"):
        pd.DataFrame(monthly).to_csv(output_csv, index=False, date_format="%Y-%m-%d")
        print(f"Wrote {len(monthly)} rows to {output_csv}")
    else:
        print("Skipped writing monthly prices file as requested (output_csv set to skip).")

    # Optionally compute simple monthly returns and write to CSV
    if returns_output:
        monthly_prices = monthly.sort_values("Date").reset_index(drop=True)
        returns_df = monthly_prices.copy()
        # simple returns: pct_change month-over-month
        returns_df[funds] = returns_df[funds].pct_change()
        # Round returns to 8 decimal places and use fixed-point format to avoid scientific notation
        returns_df[funds] = returns_df[funds].round(8)
        returns_df.to_csv(returns_output, index=False, date_format="%Y-%m-%d", float_format="%.8f")
        print(f"Wrote {len(returns_df)} rows to {returns_output}")

    # Print start period
    print("Start period:", start_period)


if __name__ == "__main__":
    # Deprecated wrapper: forward to new script "extract_monthly_data_for_matrix.py"
    if len(sys.argv) < 2:
        print("Deprecated: use scripts/extract_monthly_data_for_matrix.py INPUT_CSV [MONTHLY_OUTPUT] [RETURNS_OUTPUT]")
        sys.exit(1)
    import subprocess
    new_script = Path(__file__).parent / "extract_monthly_data_for_matrix.py"
    args = [sys.executable, str(new_script)] + sys.argv[1:]
    subprocess.run(args)
