import streamlit as st
import pandas as pd
from datetime import date
import os
import streamlit as st

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
CONTRIB_FILE = "contributions.csv"

# ---------- LOAD DATA ----------
def load_data():
    if os.path.exists(FUNDS_FILE):
        funds = pd.read_csv(FUNDS_FILE)
    else:
        funds = pd.DataFrame(columns=["isin", "id", "name", "fund", "color"])

    if os.path.exists(CONTRIB_FILE):
        contribs = pd.read_csv(CONTRIB_FILE, parse_dates=["date"])
    else:
        contribs = pd.DataFrame(columns=["fundId", "date", "quantity", "price", "fees"])

    return funds, contribs

funds, contributions = load_data()

# ---------- ADD FUND ----------
st.header("➕ Add Fund")

if IS_OWNER:
    with st.form("add_fund"):
        isin = st.text_input("ISIN")
        fund_id = st.text_input("Fund ID")
        name = st.text_input("Fund Name")
        fund_type = st.selectbox(
            "Fund Category",
            ["US", "EU", "EM", "Tech", "MeAEe", "EU HY"]
        )
        color = st.selectbox(
            "Color",
            ["red", "blue", "green", "grey", "purple", "light blue"]
        )

        submitted = st.form_submit_button("Add Fund")

        if submitted:
            new_fund = pd.DataFrame([{
                "isin": isin,
                "id": fund_id,
                "name": name,
                "fund": fund_type,
                "color": color
            }])
            funds = pd.concat([funds, new_fund], ignore_index=True)
            funds.to_csv(FUNDS_FILE, index=False)
            st.success("Fund added")
else:
    st.info("Viewer mode (read-only)")

st.divider()

# ---------- ADD CONTRIBUTION ----------
st.header("💰 Add Contribution")

if len(funds) == 0:
    st.info("Add a fund first")
else:
    if IS_OWNER:
        with st.form("add_contribution"):
            fundId = st.selectbox("Fund", funds["id"])
            contrib_date = st.date_input("Date", date.today())
            quantity = st.number_input("Quantity", min_value=0.0)
            price = st.number_input("Price", min_value=0.0)
            fees = st.number_input("Fees", min_value=0.0)

            submitted_c = st.form_submit_button("Add Contribution")

            if submitted_c:
                new_contrib = pd.DataFrame([{
                    "fundId": fundId,
                    "date": contrib_date,
                    "quantity": quantity,
                    "price": price,
                    "fees": fees,
                    "is_dca": st.checkbox("Is DCA?")
                }])
                contributions = pd.concat([contributions, new_contrib], ignore_index=True)
                contributions.to_csv(CONTRIB_FILE, index=False)
                st.success("Contribution added")
    else:
        st.info("Viewer mode (read-only)")

st.divider()

# ---------- PORTFOLIO SUMMARY ----------
st.header("📈 Portfolio Summary")

if len(contributions) > 0:
    df = contributions.copy()
    df["invested"] = df["quantity"] * df["price"] + df["fees"]

    summary = df.groupby("fundId").agg(
        total_quantity=("quantity", "sum"),
        total_invested=("invested", "sum")
    ).reset_index()

    st.dataframe(summary, use_container_width=True)

    st.metric(
        "Total Invested (€)",
        round(summary["total_invested"].sum(), 2)
    )
else:
    st.info("No contributions yet")

# ---------- CHARTS ----------

st.divider()
st.header("📊 Charts")

if len(contributions) > 0:
    df = contributions.copy()
    df["invested"] = df["quantity"] * df["price"] + df["fees"]

    # ----- Allocation by fund -----
    alloc = df.groupby("fundId")["invested"].sum().reset_index()

    st.subheader("Allocation by Fund")
    st.bar_chart(
        alloc.set_index("fundId")
    )

    # ----- Invested over time -----
    time_df = df.groupby("date")["invested"].sum().reset_index()
    time_df = time_df.sort_values("date")

    st.subheader("Invested Over Time")
    st.line_chart(
        time_df.set_index("date")
    )

    # ----- Monthly totals -----
    df["month"] = pd.to_datetime(df["date"]).dt.to_period("M").astype(str)
    monthly = df.groupby("month")["invested"].sum().reset_index()

    st.subheader("Monthly Investments")
    st.bar_chart(
        monthly.set_index("month")
    )

