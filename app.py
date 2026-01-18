import streamlit as st
import pandas as pd
from datetime import date
import os
import altair as alt

# ---------- AUTHENTICATION ----------
OWNER_PASSWORD = "123"

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

if not st.session_state.authenticated:
    pwd = st.text_input("Enter password to edit data:", type="password")
    if pwd == OWNER_PASSWORD:
        st.session_state.authenticated = True
    else:
        st.info("Viewer mode — forms are hidden")
        st.session_state.authenticated = False

IS_OWNER = st.session_state.authenticated

# ---------- APP SETUP ----------
st.set_page_config(page_title="Portfolio Tracker", layout="wide")
st.title("📊 Portfolio Tracker")

FUNDS_FILE = "funds.csv"
TRANSACTIONS_FILE = "transaction_history.csv"

# ---------- COLOR MAPPING ----------
FUND_COLORS = {}

# ---------- LOAD DATA ----------
def load_data():
    if os.path.exists(FUNDS_FILE):
        funds = pd.read_csv(FUNDS_FILE)
    else:
        funds = pd.DataFrame(columns=["ISIN", "Ticker", "Fund", "Fund Name", "Type", "Colour"])

    if os.path.exists(TRANSACTIONS_FILE):
        transactions = pd.read_csv(TRANSACTIONS_FILE, parse_dates=["Date"])
    else:
        transactions = pd.DataFrame(columns=["Date", "Fund", "Price (€)", "Quantity", "Fees (€)"])

    return funds, transactions

funds, transactions = load_data()

# Build FUND_COLORS from funds data (extract hex code from formatted string)
for _, row in funds.iterrows():
    # Extract hex code from format "color name #XXXXXX ▯"
    colour_str = row["Colour"]
    hex_code = colour_str.split("#")[1].split()[0] if "#" in colour_str else colour_str
    FUND_COLORS[row["Fund"]] = f"#{hex_code}"

# ---------- OPTIONAL MIGRATION FROM contributions.csv ----------
def migrate_contributions_to_transactions(funds_df):
    # Migration no longer needed; using transaction_history.csv directly
    return None

# Run migration once if needed
migrated = migrate_contributions_to_transactions(funds)
if migrated is not None:
    transactions = migrated

# ---------- SIDEBAR NAVIGATION ----------
st.sidebar.header("Navigation")
page = st.sidebar.radio(
    "Go to",
    [
        "Portfolio Summary & Charts",
        "Transaction History",
        "Add Transaction & Add Fund",
    ],
    index=0,
)

# ---------- ADD FUND ----------
if page == "Add Transaction & Add Fund":
    st.header("➕ Add Fund")

    if IS_OWNER:
        with st.form("add_fund"):
            col1, col2 = st.columns(2)
            with col1:
                isin = st.text_input("ISIN", placeholder="e.g., LU0281484963")
                fund_cat = st.selectbox(
                    "Fund",
                    ["US", "EU", "EM", "Tech", "Me A Ee", "EU HY"]
                )
            with col2:
                ticker = st.text_input("Ticker", placeholder="e.g., 0P0001CRXW")
            name = st.text_input(
                "Fund Name",
                placeholder="e.g., JPMorgan Funds - US Select Equity Plus Fund D (acc) - EUR"
            )
            fund_type = st.selectbox(
                "Type",
                ["Equity", "Bond"]
            )
            colour = st.color_picker("Colour", value="#C00000")
            submitted = st.form_submit_button("Add Fund")
            if submitted:
                if not isin.strip() or not ticker.strip() or not name.strip():
                    st.error("All fields are required")
                else:
                    new_fund = pd.DataFrame([{
                        "ISIN": isin,
                        "Ticker": ticker,
                        "Fund": fund_cat,
                        "Fund Name": name,
                        "Type": fund_type,
                        "Colour": colour,
                    }])
                    funds = pd.concat([funds, new_fund], ignore_index=True)
                    funds.to_csv(FUNDS_FILE, index=False)
                    st.success("Fund added")
                    st.rerun()
    else:
        st.info("Viewer mode (read-only)")

    st.divider()

    st.header("💰 Add Transaction")
    if len(funds) == 0:
        st.info("Add a fund first")
    else:
        if IS_OWNER:
            with st.form("add_Transaction"):
                fund_name = st.selectbox("Fund", funds["name"]) 
                contrib_date = st.date_input("Date", date.today())
                quantity = st.number_input("Quantity", min_value=0.0, step=0.001, format="%f")
                price = st.number_input("Price", min_value=0.0)
                fees = st.number_input("Fees", min_value=0.0)
                submitted_c = st.form_submit_button("Add Transaction")
                if submitted_c:
                    if quantity <= 0 or price <= 0:
                        st.error("Quantity and Price must be greater than 0")
                    else:
                        fund_type = funds[funds["name"] == fund_name]["fund"].values[0]
                        new_contrib = pd.DataFrame([{
                            "Date": contrib_date.strftime("%Y-%m-%d"),
                            "Fund": fund_type,
                            "Price (€)": price,
                            "Quantity": quantity,
                            "Fees (€)": fees,
                        }])
                        transactions = pd.concat([transactions, new_contrib], ignore_index=True)
                        transactions.to_csv(TRANSACTIONS_FILE, index=False)
                        st.success("Transaction added")
                        st.rerun()
        else:
            st.info("Viewer mode (read-only)")

elif page == "Transaction History":
    st.header("📜 Transaction History")
    if len(transactions) > 0:
        trans_df = transactions.copy()
        trans_df["Date"] = pd.to_datetime(trans_df["Date"], errors="coerce")
        trans_df = trans_df.sort_values("Date", ascending=False)
        
        # Calculate derived fields
        trans_df["Reference Period"] = trans_df["Date"].dt.strftime("%Y %b")
        trans_df["Invested (calc)"] = trans_df["Quantity"] * trans_df["Price (€)"] + trans_df["Fees (€)"]
        trans_df["Invested (theor)"] = (trans_df["Invested (calc)"] / 10).round() * 10
        trans_df["Date_str"] = trans_df["Date"].dt.strftime("%Y-%m-%d")
        
        # Select and reorder columns for display
        display_df = trans_df[["Reference Period", "Date_str", "Fund", "Price (€)", "Quantity", "Fees (€)", "Invested (calc)", "Invested (theor)"]].copy()
        display_df.columns = ["Reference Period", "Date", "Fund", "Price (€)", "Quantity", "Fees (€)", "Invested (calc)", "Invested (theor)"]
        
        # Format numbers to show minimum decimals
        def format_number(x):
            if pd.isna(x):
                return ""
            if isinstance(x, (int, float)):
                if x == int(x):
                    return str(int(x))
                return f"{x:.10g}"
            return str(x)
        
        display_df["Price (€)"] = display_df["Price (€)"].apply(format_number)
        display_df["Quantity"] = display_df["Quantity"].apply(format_number)
        display_df["Fees (€)"] = display_df["Fees (€)"].apply(format_number)
        display_df["Invested (calc)"] = display_df["Invested (calc)"].apply(format_number)
        display_df["Invested (theor)"] = display_df["Invested (theor)"].apply(format_number)
        
        # Add fund column for styling
        display_df["_fund_type"] = trans_df["Fund"].values
        
        # Create styled dataframe with color hue
        def style_fund_rows(row):
            fund_type = row["_fund_type"]
            hex_color = FUND_COLORS.get(fund_type, "#000000")
            # Convert hex to rgba with light alpha
            hex_color = hex_color.lstrip('#')
            rgba = f"rgba({int(hex_color[0:2], 16)}, {int(hex_color[2:4], 16)}, {int(hex_color[4:6], 16)}, 0.15)"
            return ["background-color: " + rgba if col != "_fund_type" else "display: none;" for col in row.index]
        
        styled_df = display_df.style.apply(style_fund_rows, axis=1)
        
        # Display interactive dataframe with sorting and filtering
        st.dataframe(styled_df, use_container_width=True, hide_index=True)
    else:
        st.info("No transactions yet")

else:
    # ---------- PORTFOLIO SUMMARY ----------
    st.header("📈 Portfolio Summary")
    if len(transactions) > 0:
        df = transactions.copy()
        df["invested"] = df["Quantity"] * df["Price (€)"] + df["Fees (€)"]
        summary = df.groupby("Fund").agg(
            total_quantity=("Quantity", "sum"),
            total_invested=("invested", "sum")
        ).reset_index()
        summary.columns = ["fund", "total_quantity", "total_invested"]
        st.dataframe(summary, use_container_width=True)
        st.metric("Total Invested (€)", round(summary["total_invested"].sum(), 2))
    else:
        st.info("No transactions yet")

    # ---------- CHARTS ----------
    st.divider()
    st.header("📊 Charts")
    if len(transactions) > 0:
        df = transactions.copy()
        df["invested"] = df["Quantity"] * df["Price (€)"] + df["Fees (€)"]
        alloc = df.groupby("Fund")["invested"].sum().reset_index()
        alloc = alloc.sort_values("invested", ascending=True)
        st.subheader("Allocation by Fund")
        color_scale = alt.Scale(domain=list(FUND_COLORS.keys()), range=list(FUND_COLORS.values()))
        alloc_chart = (
            alt.Chart(alloc)
            .mark_bar()
            .encode(
                x=alt.X("invested:Q", title="Invested (€)"),
                y=alt.Y("Fund:N", sort='-x', title="Fund"),
                color=alt.Color("Fund:N", scale=color_scale, legend=None),
                tooltip=["Fund:N", "invested:Q"],
            )
            .properties(height=300)
        )
        st.altair_chart(alloc_chart, use_container_width=True)

        df["date_dt"] = pd.to_datetime(df["Date"], errors="coerce")
        df = df.dropna(subset=["date_dt"])  
        if len(df) > 0:
            time_df = df.groupby("date_dt")["invested"].sum().reset_index()
            time_df = time_df.sort_values("date_dt")
            time_df.columns = ["Date", "invested"]
            st.subheader("Invested Over Time")
            time_chart = (
                alt.Chart(time_df)
                .mark_line()
                .encode(
                    x=alt.X("Date:T", title="Date"),
                    y=alt.Y("invested:Q", title="Invested (€)"),
                    tooltip=["Date:T", "invested:Q"],
                )
            )
            st.altair_chart(time_chart, use_container_width=True)
        else:
            st.info("No valid dates for 'Invested Over Time' chart")

        if len(df) > 0:
            df["month_date"] = df["date_dt"].dt.to_period("M").dt.to_timestamp()
            monthly = df.groupby("month_date")["invested"].sum().reset_index()
            monthly = monthly.sort_values("month_date")
            monthly.columns = ["Month", "invested"]
            st.subheader("Monthly Investments")
            monthly_chart = (
                alt.Chart(monthly)
                .mark_bar()
                .encode(
                    x=alt.X("Month:T", title="Month", axis=alt.Axis(format="%Y-%m")),
                    y=alt.Y("invested:Q", title="Invested (€)"),
                    tooltip=["Month:T", "invested:Q"],
                )
            )
            st.altair_chart(monthly_chart, use_container_width=True)
        else:
            st.info("No valid dates for 'Monthly Investments' chart")
    else:
        st.info("No transactions yet")

