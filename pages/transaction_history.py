"""
pages/transaction_history.py — Pagina "Transaction History".

Mostra la cronologia completa delle transazioni con:
- Filtro fondi e filtro per data
- Tabella dettagliata con contributi, quantità, delta, ecc.
- Metriche totali (gross contribution, net invested, fees, P/L)
"""

import streamlit as st
import pandas as pd

from config import FUND_COLORS
from components.fund_filter import render_fund_filter
from components.styling import style_fund_cell
from utils.formatting import (
    count_decimals,
    get_fund_qty_decimals,
    format_qty,
    format_delta_net_inv,
)


def transaction_history(
    funds: pd.DataFrame,
    transactions: pd.DataFrame,
    hist_data_global: pd.DataFrame,
    last_date_str: str,
):
    """Renderizza la pagina Transaction History.

    Args:
        funds:            DataFrame dei fondi.
        transactions:     DataFrame delle transazioni.
        hist_data_global: DataFrame prezzi storici.
        last_date_str:    Data più recente dei dati storici.
    """
    st.header("📜 Transaction History")

    # ===== FILTRO FONDI =====
    fund_list = funds["Fund"].tolist() if len(funds) > 0 else []
    filter_funds = render_fund_filter(fund_list, FUND_COLORS)

    # ===== FILTRO DATE =====
    col1, col2 = st.columns(2)
    with col1:
        if len(transactions) > 0:
            first_trans_date = pd.to_datetime(transactions["Date"]).min().date()
            if "trans_start_date" not in st.session_state or st.session_state.trans_start_date < first_trans_date:
                st.session_state.trans_start_date = first_trans_date
            start_date = st.date_input("Start Date:", value=st.session_state.trans_start_date, key="trans_start_date_input")
        else:
            start_date = None
    with col2:
        if len(transactions) > 0:
            max_date = pd.to_datetime(transactions["Date"]).max().date()
            end_date = st.date_input("End Date:", value=max_date, key="trans_end_date")
        else:
            end_date = None

    if len(transactions) > 0:
        start_date = st.session_state.trans_start_date_input

    # ===== NESSUNA TRANSAZIONE =====
    if len(transactions) == 0:
        st.info("No transactions yet")
        return

    # ----- Filtra transazioni -----
    trans_df = transactions.copy()
    trans_df["Date"] = pd.to_datetime(trans_df["Date"], errors="coerce")

    if filter_funds:
        trans_df = trans_df[trans_df["Fund"].isin(filter_funds)]
    if start_date:
        trans_df = trans_df[trans_df["Date"] >= pd.to_datetime(start_date)]
    if end_date:
        trans_df = trans_df[trans_df["Date"] <= pd.to_datetime(end_date)]

    trans_df = trans_df.sort_values("Date", ascending=False)

    # ----- Calcola campi derivati -----
    trans_df["Reference Period"] = trans_df["Date"].dt.strftime("%Y %b")
    trans_df["Gross Contribution (real)"] = trans_df["Quantity"] * trans_df["Price (€)"] + trans_df["Fees (€)"]
    trans_df["Gross Contribution (theor)"] = (trans_df["Gross Contribution (real)"] / 10).round() * 10
    trans_df["Net Invested"] = trans_df["Quantity"] * trans_df["Price (€)"]
    trans_df["Δ Net Inv vs Exp"] = trans_df["Net Invested"] - trans_df["Gross Contribution (theor)"] + trans_df["Fees (€)"]
    trans_df["Quantity (theor)"] = (trans_df["Gross Contribution (theor)"] - trans_df["Fees (€)"]) / trans_df["Price (€)"]
    trans_df["Δ Quantity"] = trans_df["Quantity"] - trans_df["Quantity (theor)"]
    trans_df["Date_str"] = trans_df["Date"].dt.strftime("%Y-%m-%d")

    # Precisione decimale per fondo
    fund_qty_decimals = get_fund_qty_decimals(transactions)

    # ----- Prepara DataFrame di display -----
    display_df = trans_df[[
        "Reference Period", "Date_str", "Fund", "Price (€)", "Quantity",
        "Fees (€)", "Gross Contribution (theor)", "Net Invested",
        "Δ Net Inv vs Exp", "Quantity (theor)", "Δ Quantity",
    ]].copy()
    display_df.columns = [
        "Reference Period", "Date", "Fund", "Price (€)", "Quantity",
        "Fees (€)", "Gross Contribution", "Net Invested",
        "Δ Net Inv vs Exp", "Quantity (theor)", "Δ Quantity",
    ]

    # Colonne helper per styling (raw values)
    display_df["_delta_net_inv_raw"] = trans_df["Δ Net Inv vs Exp"].values
    display_df["_delta_qty_raw"] = trans_df["Δ Quantity"].values
    display_df["_delta_net_inv_disp"] = display_df["_delta_net_inv_raw"].apply(format_delta_net_inv)

    def _format_delta_qty_row(row):
        dq = row["_delta_qty_raw"]
        if pd.isna(dq):
            return None
        dp = fund_qty_decimals.get(row["Fund"], 3)
        rounded = round(dq, dp)
        return 0.0 if abs(rounded) < 10 ** (-dp) else rounded

    display_df["_delta_qty_disp"] = display_df.apply(_format_delta_qty_row, axis=1)

    # Formatta Quantity
    display_df["Quantity"] = display_df["Quantity"].apply(format_qty)

    # Combina Net Invested con delta
    display_df["Net Invested (Δ vs Exp)"] = display_df.apply(
        lambda r: f"{r['Net Invested']:.2f} ({r['_delta_net_inv_raw']:+.2f})" if pd.notna(r["_delta_net_inv_raw"]) else f"{r['Net Invested']:.2f}",
        axis=1,
    )

    # Combina Quantity (theor) con delta
    def _format_qty_calc(row):
        dp = fund_qty_decimals.get(row["Fund"], 3)
        q = row["Quantity (theor)"]
        dq = row["_delta_qty_raw"]
        q_str = "" if pd.isna(q) else f"{round(q, dp):.{dp}f}"
        dq_str = f" ({round(dq, dp):+.{dp}f})" if pd.notna(dq) else ""
        return q_str + dq_str

    display_df["Quantity (theor) (Δ vs Q real)"] = display_df.apply(_format_qty_calc, axis=1)

    # Rimuovi colonne intermedie
    display_df = display_df.drop(columns=["Net Invested", "Δ Net Inv vs Exp", "Quantity (theor)", "Δ Quantity"])
    display_df["_fund_type"] = trans_df["Fund"].values

    # ----- Stile tabella -----
    def style_fund_rows(row):
        """Colora Fund col, Net Invested delta e Quantity delta."""
        fund = row["_fund_type"]
        green = "rgba(46, 160, 67, 0.12)"
        red = "rgba(248, 81, 73, 0.12)"
        styles = []
        for col in row.index:
            if col.startswith("_"):
                styles.append("display: none;")
            elif col == "Fund":
                styles.append(style_fund_cell(fund, FUND_COLORS))
            elif col == "Net Invested (Δ vs Exp)":
                dv = row.get("_delta_net_inv_disp", None)
                if dv is None or dv == 0:
                    styles.append("")
                elif dv > 0:
                    styles.append(f"background-color: {green}")
                else:
                    styles.append(f"background-color: {red}")
            elif col == "Quantity (theor) (Δ vs Q real)":
                dv = row.get("_delta_qty_disp", None)
                if dv is None or dv == 0:
                    styles.append("")
                elif dv > 0:
                    styles.append(f"background-color: {green}")
                else:
                    styles.append(f"background-color: {red}")
            else:
                styles.append("")
        return styles

    styled_df = display_df.style.apply(style_fund_rows, axis=1)

    st.dataframe(styled_df, width="stretch", hide_index=True, column_config={
        "Price (€)": st.column_config.NumberColumn(format="€%.2f"),
        "Fees (€)": st.column_config.NumberColumn(format="€%.2f"),
        "Gross Contribution": st.column_config.NumberColumn(format="€%.2f"),
        "_delta_net_inv_raw": None, "_delta_qty_raw": None,
        "_delta_net_inv_disp": None, "_delta_qty_disp": None, "_fund_type": None,
    })

    # CSS per testo piccolo nelle metriche
    st.markdown("""
    <style>
    [data-testid="stMetric"] small { font-size: 0.5em !important; opacity: 0.7; }
    </style>
    """, unsafe_allow_html=True)

    # ===== TOTALS =====
    st.markdown("")
    st.markdown("**Totals (based on filters):**")

    total_gross_theor = trans_df["Gross Contribution (theor)"].sum()
    total_net_invested = trans_df["Net Invested"].sum()
    total_fees = trans_df["Fees (€)"].sum()
    fees_pct = (total_fees / total_gross_theor * 100) if total_gross_theor > 0 else 0.0
    pl_price_approx = trans_df["Δ Net Inv vs Exp"].sum()

    # P/L Quantity
    hist_data = hist_data_global
    pl_qty_approx = 0.0
    pl_qty_approx_now = 0.0
    if len(hist_data) > 0 and "date" in hist_data.columns:
        latest_date = pd.to_datetime(hist_data["date"]).max()
        for _, row in trans_df.iterrows():
            fund = row["Fund"]
            dq_raw = row["Δ Quantity"]
            dp = fund_qty_decimals.get(fund, 3)
            dq = round(dq_raw, dp) if pd.notna(dq_raw) else None
            if dq is not None and abs(dq) < 10 ** (-dp):
                dq = 0.0
            if pd.notna(dq):
                pl_qty_approx += dq * row["Price (€)"]
                if fund in hist_data.columns:
                    lp = hist_data[hist_data["date"] == latest_date][fund].values
                    if len(lp) > 0 and pd.notna(lp[0]):
                        pl_qty_approx_now += dq * lp[0]

    num_contributions = len(trans_df)

    # ----- Sparkline data: cumulative build-up over transactions -----
    trans_asc = trans_df.sort_values("Date", ascending=True)
    spark_gross = trans_asc["Gross Contribution (theor)"].cumsum().tolist()
    spark_net_inv = (trans_asc["Quantity"] * trans_asc["Price (€)"]).cumsum().tolist()
    spark_fees = trans_asc["Fees (€)"].cumsum().tolist()
    spark_pl_price = trans_asc["Δ Net Inv vs Exp"].cumsum().tolist()
    spark_count = list(range(1, num_contributions + 1))
    _empty_spark = [0] * max(num_contributions, 1)

    # Display totals
    r1c1, r1c2, r1c3 = st.columns(3)
    with r1c1:
        st.metric("Total Gross Contribution", f"€ {total_gross_theor:,.2f}", border=True,
                  chart_data=spark_gross if spark_gross else _empty_spark, chart_type="line")
    with r1c2:
        st.metric("Total Net Invested", f"€ {total_net_invested:,.2f}", border=True,
                  chart_data=spark_net_inv if spark_net_inv else _empty_spark, chart_type="line")
    with r1c3:
        st.metric("Fees", f"€ {total_fees:,.2f}", delta=f"↓{fees_pct:.2f}%", delta_color="off", border=True,
                  chart_data=spark_fees if spark_fees else _empty_spark, chart_type="line")

    r2c1, r2c2, r2c3 = st.columns(3)
    with r2c1:
        pl_price_pct = (pl_price_approx / total_gross_theor * 100) if total_gross_theor > 0 else 0
        st.metric(
            "P/L Price approx.", f"€ {pl_price_approx:+,.2f}",
            delta=f"{pl_price_pct:+.2f}%",
            delta_color="normal" if pl_price_approx >= 0 else "off",
            border=True,
            chart_data=spark_pl_price if spark_pl_price else _empty_spark,
            chart_type="line",
        )
    with r2c2:
        pl_qty_display = (
            f"€ {pl_qty_approx:+,.2f} (Now: € {pl_qty_approx_now:+,.2f})"
            if last_date_str != "-" else f"€ {pl_qty_approx:+,.2f}"
        )
        st.metric(f"P/L Quantity approx. (as of {last_date_str})", pl_qty_display, border=True,
                  chart_data=_empty_spark, chart_type="line")
    with r2c3:
        st.metric("Number of Contributions", f"{num_contributions}", border=True,
                  chart_data=spark_count if spark_count else _empty_spark, chart_type="line")
