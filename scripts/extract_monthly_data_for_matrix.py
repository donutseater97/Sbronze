#!/usr/bin/env python3
"""
extract_monthly_data_for_matrix.py

Usage:
  python3 scripts/extract_monthly_data_for_matrix.py INPUT_CSV [MONTHLY_OUTPUT] [RETURNS_OUTPUT]

Defaults:
  MONTHLY_OUTPUT -> "monthly_historical_data.csv"
  RETURNS_OUTPUT -> "monthly_returns.csv"

Use '-' or 'none' for either OUTPUT to skip writing that file.

Generates two files needed for matrix calculations:
- monthly_historical_data.csv: earliest available date in each month (from the chosen start month)
- monthly_returns.csv: simple month-over-month returns (rounded, fixed-point format)

Start month: the month containing the most recent first-observation across funds.
"""
import sys
from pathlib import Path
import pandas as pd


def extract_monthly_data_for_matrix(input_csv: str, monthly_output: str = "monthly_historical_data.csv", returns_output: str = "monthly_returns.csv"):
    df = pd.read_csv(input_csv, parse_dates=["Date"])  # parse Date

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

    # Most recent (max) of those first-observation dates -> start month
    max_first_date = max(d for d in first_dates.values() if pd.notna(d))
    start_period = max_first_date.to_period("M")

    # Find earliest date present in each month
    df = df.copy()
    df["Period"] = df["Date"].dt.to_period("M")
    month_first_dates = df.groupby("Period")["Date"].min()

    # Select months from start_period onward
    selected_periods = [p for p in month_first_dates.index if p >= start_period]
    selected_dates = month_first_dates.loc[selected_periods].sort_values().values

    # Build monthly dataframe
    monthly = df.loc[df["Date"].isin(selected_dates), ["Date"] + funds].sort_values("Date").reset_index(drop=True)

    # Write monthly prices unless skipped
    if monthly_output and str(monthly_output).lower() not in ("-", "none", "null", "skip"):
        pd.DataFrame(monthly).to_csv(monthly_output, index=False, date_format="%Y-%m-%d")
        print(f"Wrote {len(monthly)} rows to {monthly_output}")
    else:
        print("Skipped writing monthly prices file as requested (monthly_output set to skip).")

    # Compute monthly simple returns and write unless skipped
    if returns_output and str(returns_output).lower() not in ("-", "none", "null", "skip"):
        monthly_prices = monthly.sort_values("Date").reset_index(drop=True)
        returns_df = monthly_prices.copy()
        returns_df[funds] = returns_df[funds].pct_change()
        # Round returns to 8 decimal places and write using fixed-point format
        returns_df[funds] = returns_df[funds].round(8)
        returns_df.to_csv(returns_output, index=False, date_format="%Y-%m-%d", float_format="%.8f")
        print(f"Wrote {len(returns_df)} rows to {returns_output}")
    else:
        print("Skipped writing monthly returns file as requested (returns_output set to skip).")

    print("Start period:", start_period)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 scripts/extract_monthly_data_for_matrix.py INPUT_CSV [MONTHLY_OUTPUT] [RETURNS_OUTPUT] (use '-' to skip an output)")
        sys.exit(1)
    input_csv = sys.argv[1]
    monthly_output = sys.argv[2] if len(sys.argv) > 2 else "monthly_historical_data.csv"
    returns_output = sys.argv[3] if len(sys.argv) > 3 else "monthly_returns.csv"
    input_path = Path(input_csv)
    if not input_path.exists():
        print(f"Input file {input_csv} not found")
        sys.exit(2)
    extract_monthly_data_for_matrix(input_csv, monthly_output, returns_output)
