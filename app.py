import streamlit as st
import pandas as pd
from datetime import date

st.set_page_config(page_title="Portfolio Tracker", layout="wide")

st.title("📊 Portfolio Tracker")

# ---------- DATA STORAGE ----------
if "funds" not in st.session_state:
    st.session_state.funds = pd.DataFrame(columns=[
        "isin", "id", "name", "fund", "color"
    ])

if "contributions" not in st.session_state:
    st.session_state.contributions = pd.DataFrame(columns=[
        "fundId", "date", "quantity", "price", "fees"
    ])

# ---------- ADD FUND ----------
st.header("➕ Add Fund")

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
        st.session_state.funds = pd.concat(
            [st.session_state.funds, new_fund],
            ignore_index=True
        )
        st.success("Fund added")

st.divider()

# ---------- ADD CONTRIBUTION ----------
st.header("💰 Add Contribution")

if len(st.session_state.funds) == 0:
    st.info("Add a fund first")
else:
    with st.form("add_contribution"):
        fundId = st.selectbox(
            "Fund",
            st.session_state.funds["id"]
        )
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
                "fees": fees
            }])
            st.session_state.contributions = pd.concat(
                [st.session_state.contributions, new_contrib],
                ignore_index=True
            )
            st.success("Contribution added")

st.divider()

# ---------- PORTFOLIO SUMMARY ----------
st.header("📈 Portfolio Summary")

if len(st.session_state.contributions) > 0:
    df = st.session_state.contributions.copy()
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
