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
TRANSACTIONS_FILE = "transactions.csv"

# ---------- COLOR MAPPING ----------
FUND_COLORS = {
    "US": "#EF553B",      # red
    "EU": "#3A46EF",      # blue
    "EM": "#4FC35D",      # green
    "Tech": "#B5B5B5",    # gray
    "Me A Ee": "#BC59F5",  # purple
    "EU HY": "#4CC2DF"  # light blue
}

# ---------- LOAD DATA ----------
def load_data():
    if os.path.exists(FUNDS_FILE):
        funds = pd.read_csv(FUNDS_FILE)
    else:
        funds = pd.DataFrame(columns=["isin", "ticker", "name", "fund"])

    if os.path.exists(TRANSACTIONS_FILE):
        transactions = pd.read_csv(TRANSACTIONS_FILE, parse_dates=["date"])
    else:
        transactions = pd.DataFrame(columns=["fund", "date", "quantity", "price", "fees"])

    return funds, transactions

funds, transactions = load_data()

# ---------- OPTIONAL MIGRATION FROM contributions.csv ----------
def migrate_contributions_to_transactions(funds_df):
    contrib_file = "contributions.csv"
    if not os.path.exists(contrib_file):
        return None
    # If transactions does not exist or is empty, migrate
    if (not os.path.exists(TRANSACTIONS_FILE)) or pd.read_csv(TRANSACTIONS_FILE).empty:
        contribs = pd.read_csv(contrib_file, parse_dates=["date"])
        rows = []
        for _, r in contribs.iterrows():
            fid = r.get("fundId")
            fund_type = None
            fund_name = None
            if funds_df is not None and len(funds_df) > 0 and fid is not None:
                if "id" in funds_df.columns:
                    m = funds_df[funds_df["id"] == fid]
                elif "ticker" in funds_df.columns:
                    m = funds_df[funds_df["ticker"] == fid]
                else:
                    m = pd.DataFrame()
                if len(m) > 0:
                    fund_type = m.iloc[0].get("fund")
                    fund_name = m.iloc[0].get("name")
            rows.append({
                "fund": fund_type if fund_type is not None else r.get("fund", "Unknown"),
                "fund_name": fund_name if fund_name is not None else (str(fid) if fid is not None else "Unknown"),
                "date": r["date"],
                "quantity": r["quantity"],
                "price": r["price"],
                "fees": r["fees"],
            })
        pd.DataFrame(rows).to_csv(TRANSACTIONS_FILE, index=False)
        return pd.read_csv(TRANSACTIONS_FILE, parse_dates=["date"])
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
                fund_type = st.selectbox(
                    "Fund Category",
                    ["US", "EU", "EM", "Tech", "Me A Ee", "EU HY"]
                )
            with col2:
                ticker = st.text_input("Ticker", placeholder="e.g., 0P0001CRXW")
            name = st.text_input(
                "Fund Name",
                placeholder="e.g., JPMorgan Funds - US Select Equity Plus Fund D (acc) - EUR"
            )
            submitted = st.form_submit_button("Add Fund")
            if submitted:
                if not isin.strip() or not ticker.strip() or not name.strip():
                    st.error("All fields are required")
                else:
                    new_fund = pd.DataFrame([{
                        "isin": isin,
                        "ticker": ticker,
                        "name": name,
                        "fund": fund_type,
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
                quantity = st.number_input("Quantity", min_value=0.0)
                price = st.number_input("Price", min_value=0.0)
                fees = st.number_input("Fees", min_value=0.0)
                submitted_c = st.form_submit_button("Add Transaction")
                if submitted_c:
                    if quantity <= 0 or price <= 0:
                        st.error("Quantity and Price must be greater than 0")
                    else:
                        fund_type = funds[funds["name"] == fund_name]["fund"].values[0]
                        new_contrib = pd.DataFrame([{
                            "fund": fund_type,
                            "fund_name": fund_name,
                            "date": contrib_date,
                            "quantity": quantity,
                            "price": price,
                            "fees": fees,
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
        trans_df["invested"] = trans_df["quantity"] * trans_df["price"] + trans_df["fees"]
        trans_df = trans_df.sort_values("date", ascending=False)
        for _, row in trans_df.iterrows():
            color = FUND_COLORS.get(row.get("fund", ""), "#000000")
            st.markdown(
                f"""
                <div style="border-left: 4px solid {color}; padding: 10px; margin: 5px 0; background-color: #f9f9f9; border-radius: 4px;">
                    <p style="color: {color}; font-weight: bold; margin: 0;">{row.get('fund_name', 'Unknown')}</p>
                    <p style="margin: 5px 0; color: #666;">
                        <strong>Date:</strong> {row['date']} | 
                        <strong>Qty:</strong> {row['quantity']:.4f} | 
                        <strong>Price:</strong> €{row['price']:.2f} | 
                        <strong>Fees:</strong> €{row['fees']:.2f} | 
                        <strong>Total:</strong> €{row['invested']:.2f}
                    </p>
                </div>
                """,
                unsafe_allow_html=True
            )
    else:
        st.info("No transactions yet")

else:
    # ---------- PORTFOLIO SUMMARY ----------
    st.header("📈 Portfolio Summary")
    if len(transactions) > 0:
        df = transactions.copy()
        df["invested"] = df["quantity"] * df["price"] + df["fees"]
        summary = df.groupby("fund").agg(
            total_quantity=("quantity", "sum"),
            total_invested=("invested", "sum")
        ).reset_index()
        st.dataframe(summary, use_container_width=True)
        st.metric("Total Invested (€)", round(summary["total_invested"].sum(), 2))
    else:
        st.info("No transactions yet")

    # ---------- CHARTS ----------
    st.divider()
    st.header("📊 Charts")
    if len(transactions) > 0:
        df = transactions.copy()
        df["invested"] = df["quantity"] * df["price"] + df["fees"]
        alloc = df.groupby("fund")["invested"].sum().reset_index()
        alloc = alloc.sort_values("invested", ascending=True)
        st.subheader("Allocation by Fund")
        color_scale = alt.Scale(domain=list(FUND_COLORS.keys()), range=list(FUND_COLORS.values()))
        alloc_chart = (
            alt.Chart(alloc)
            .mark_bar()
            .encode(
                x=alt.X("invested:Q", title="Invested (€)"),
                y=alt.Y("fund:N", sort='-x', title="Fund"),
                color=alt.Color("fund:N", scale=color_scale, legend=None),
                tooltip=["fund:N", "invested:Q"],
            )
            .properties(height=300)
        )
        st.altair_chart(alloc_chart, use_container_width=True)

        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df = df.dropna(subset=["date"])  
        if len(df) > 0:
            time_df = df.groupby("date")["invested"].sum().reset_index()
            time_df = time_df.sort_values("date")
            st.subheader("Invested Over Time")
            time_chart = (
                alt.Chart(time_df)
                .mark_line()
                .encode(
                    x=alt.X("date:T", title="Date"),
                    y=alt.Y("invested:Q", title="Invested (€)"),
                    tooltip=["date:T", "invested:Q"],
                )
            )
            st.altair_chart(time_chart, use_container_width=True)
        else:
            st.info("No valid dates for 'Invested Over Time' chart")

        if len(df) > 0:
            df["month_date"] = df["date"].dt.to_period("M").dt.to_timestamp()
            monthly = df.groupby("month_date")["invested"].sum().reset_index()
            monthly = monthly.sort_values("month_date")
            st.subheader("Monthly Investments")
            monthly_chart = (
                alt.Chart(monthly)
                .mark_bar()
                .encode(
                    x=alt.X("month_date:T", title="Month", axis=alt.Axis(format="%Y-%m")),
                    y=alt.Y("invested:Q", title="Invested (€)"),
                    tooltip=["month_date:T", "invested:Q"],
                )
            )
            st.altair_chart(monthly_chart, use_container_width=True)
        else:
            st.info("No valid dates for 'Monthly Investments' chart")
    else:
        st.info("No transactions yet")

