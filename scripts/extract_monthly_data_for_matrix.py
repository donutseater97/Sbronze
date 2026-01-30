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

    # Most recent (max) of those first-observation dates -> candidate start month
    max_first_date = max(d for d in first_dates.values() if pd.notna(d))
    start_period_candidate = max_first_date.to_period("M")

    # Find earliest and latest date present in each month
    df = df.copy()
    df["Period"] = df["Date"].dt.to_period("M")
    month_first_dates = df.groupby("Period")["Date"].min()
    month_last_dates = df.groupby("Period")["Date"].max()

    # Start from the month AFTER the month containing the most recent fund-first-observation.
    # This avoids including a month in which the "youngest" fund only starts at the very end
    # (e.g., Me A Ee first obs on 2023-01-31 -> start in 2023-02).
    start_period = start_period_candidate + 1

    # Select months from start_period onward
    selected_periods = [p for p in month_first_dates.index if p >= start_period]
    selected_dates = month_first_dates.loc[selected_periods].sort_values().values

    # Build monthly dataframe (first-available date of each selected month)
    monthly = df.loc[df["Date"].isin(selected_dates), ["Date"] + funds].sort_values("Date").reset_index(drop=True)

    # Also prepare first and last date per selected period for returns calculation
    first_dates_sel = month_first_dates.loc[selected_periods]
    last_dates_sel = month_last_dates.loc[selected_periods]
    # Write monthly prices unless skipped
    if monthly_output and str(monthly_output).lower() not in ("-", "none", "null", "skip"):
        pd.DataFrame(monthly).to_csv(monthly_output, index=False, date_format="%Y-%m-%d")
        print(f"Wrote {len(monthly)} rows to {monthly_output}")
    else:
        print("Skipped writing monthly prices file as requested (monthly_output set to skip).")

    # Compute monthly simple returns as (first_of_next_month / first_of_current_month - 1)
    # and assign the result to the current month (e.g., Feb return uses 1-Mar / 1-Feb - 1).
    if returns_output and str(returns_output).lower() not in ("-", "none", "null", "skip"):
        rows = []
        first_dates_list = list(first_dates_sel.values)
        for i, (period, first_date) in enumerate(zip(selected_periods, first_dates_list)):
            # next month's first date (None for last period)
            next_first_date = first_dates_list[i + 1] if i + 1 < len(first_dates_list) else None
            if next_first_date is None:
                # no next month available -> NaNs
                row = {f: float('nan') for f in funds}
            else:
                first_row = df.loc[df["Date"] == first_date, funds]
                next_row = df.loc[df["Date"] == next_first_date, funds]
                if first_row.empty or next_row.empty:
                    row = {f: float('nan') for f in funds}
                else:
                    row = ((next_row.iloc[0] / first_row.iloc[0]) - 1).to_dict()
            row["Date"] = first_date
            rows.append(row)

        returns_df = pd.DataFrame(rows)[["Date"] + funds]
        # Convert Date to YYYY-MM string for month indexing
        returns_df["Date"] = pd.to_datetime(returns_df["Date"]).dt.to_period("M").astype(str)
        # Round returns to 8 decimal places and write using fixed-point format
        returns_df[funds] = returns_df[funds].round(8)
        returns_df.to_csv(returns_output, index=False, float_format="%.8f")
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
