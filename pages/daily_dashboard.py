"""
pages/daily_dashboard.py — Pagina "Daily Dashboard".

Mostra metric cards con sparklines per monitorare i cambiamenti giornalieri
dei singoli fondi e del portafoglio in generale.
"""

import streamlit as st
import pandas as pd

from config import FUND_COLORS


def daily_dashboard(
    funds: pd.DataFrame,
    transactions: pd.DataFrame,
    hist_data_global: pd.DataFrame,
    last_date_str: str,
):
    """Renderizza la pagina Daily Dashboard.

    Args:
        funds:            DataFrame dei fondi.
        transactions:     DataFrame delle transazioni.
        hist_data_global: DataFrame prezzi storici (colonna 'date' + fondi).
        last_date_str:    Data più recente dei dati storici.
    """
    st.header(f"📋 Daily Dashboard — {last_date_str}")

    if len(transactions) == 0:
        st.info("No transactions yet. Add some transactions to see your dashboard.")
        return

    hist_data = hist_data_global
    if len(hist_data) == 0 or "date" not in hist_data.columns:
        st.info("No historical data available.")
        return

    # Usa filtro fondi dallo stato sessione
    if "fund_filter" not in st.session_state or len(st.session_state.fund_filter) == 0:
        filter_funds = funds["Fund"].tolist() if len(funds) > 0 else []
    else:
        filter_funds = st.session_state.fund_filter

    if len(filter_funds) == 0:
        st.info("No funds selected.")
        return

    # Prepara dati
    hist_sorted = hist_data.sort_values("date", ascending=True).reset_index(drop=True)

    # Transazioni cumulate per fondo
    tx_sorted = transactions.copy()
    tx_sorted["Date"] = pd.to_datetime(tx_sorted["Date"], errors="coerce")
    tx_sorted = tx_sorted.dropna(subset=["Date"]).sort_values("Date")

    # Quantità corrente per fondo
    fund_qty = {}
    for fund in filter_funds:
        fund_qty[fund] = tx_sorted[tx_sorted["Fund"] == fund]["Quantity"].sum()

    # Ultimi N giorni di dati per sparkline
    SPARK_DAYS = 30
    spark_data = hist_sorted.tail(SPARK_DAYS).reset_index(drop=True)

    # Ultime 2 date per calcolo delta giornaliero
    if len(hist_sorted) < 2:
        st.info("Not enough historical data for daily comparison.")
        return

    latest_row = hist_sorted.iloc[-1]
    prev_row = hist_sorted.iloc[-2]

    # =====================================================================
    # SEZIONE 1: PORTFOLIO DAILY PERFORMANCE
    # =====================================================================
    st.subheader("🏦 Portfolio Daily Performance")

    # Calcola Daily P&L totale e MV precedente
    total_daily_pnl = 0.0
    total_mv_yesterday = 0.0
    for fund in filter_funds:
        if fund not in hist_sorted.columns:
            continue
        price_today = pd.to_numeric(pd.Series([latest_row[fund]]), errors="coerce").iloc[0]
        price_yesterday = pd.to_numeric(pd.Series([prev_row[fund]]), errors="coerce").iloc[0]
        qty = fund_qty.get(fund, 0)
        if pd.notna(price_yesterday):
            total_mv_yesterday += qty * price_yesterday
        if pd.notna(price_today) and pd.notna(price_yesterday):
            total_daily_pnl += qty * (price_today - price_yesterday)

    # Sparkline per P&L giornaliero portafoglio
    portfolio_pnl_spark = []
    for i in range(1, len(spark_data)):
        day_pnl = 0.0
        for fund in filter_funds:
            if fund in spark_data.columns:
                p_today = pd.to_numeric(pd.Series([spark_data.iloc[i][fund]]), errors="coerce").iloc[0]
                p_prev = pd.to_numeric(pd.Series([spark_data.iloc[i - 1][fund]]), errors="coerce").iloc[0]
                if pd.notna(p_today) and pd.notna(p_prev):
                    day_pnl += fund_qty.get(fund, 0) * (p_today - p_prev)
        portfolio_pnl_spark.append(day_pnl)

    portfolio_pnl_pct = (total_daily_pnl / total_mv_yesterday * 100) if total_mv_yesterday > 0 else 0.0
    st.metric(
        "Daily P&L",
        f"€{total_daily_pnl:+,.2f}",
        delta=f"{portfolio_pnl_pct:+.2f}%",
        delta_color="off",
        border=True,
        chart_data=portfolio_pnl_spark,
        chart_type="bar",
    )

    st.divider()

    # =====================================================================
    # SEZIONE 2: DAILY PERFORMANCE BY FUND
    # =====================================================================
    st.subheader("📊 Daily Performance by Fund")

    # Una colonna per fondo
    cols = st.columns(len(filter_funds))

    for col_idx, fund in enumerate(filter_funds):
        with cols[col_idx]:
            if fund not in hist_sorted.columns:
                st.warning(f"No data for {fund}")
                continue

            price_today = pd.to_numeric(
                pd.Series([latest_row[fund]]), errors="coerce"
            ).iloc[0]
            price_yesterday = pd.to_numeric(
                pd.Series([prev_row[fund]]), errors="coerce"
            ).iloc[0]
            qty = fund_qty.get(fund, 0)

            if pd.isna(price_today):
                st.warning(f"No price data for {fund}")
                continue

            # Calcoli delta giornaliero
            if pd.notna(price_yesterday) and price_yesterday > 0:
                nav_change = price_today - price_yesterday
                nav_change_pct = (nav_change / price_yesterday) * 100
                daily_pnl = qty * nav_change
            else:
                nav_change = 0.0
                nav_change_pct = 0.0
                daily_pnl = 0.0

            # Sparkline: storico prezzi (per NAV)
            fund_prices = pd.to_numeric(spark_data[fund], errors="coerce").tolist()

            # Sparkline: storico daily P&L (per Daily P&L)
            fund_pnl_spark = []
            fund_price_series = pd.to_numeric(spark_data[fund], errors="coerce")
            for i in range(1, len(fund_price_series)):
                p_cur = fund_price_series.iloc[i]
                p_prev = fund_price_series.iloc[i - 1]
                if pd.notna(p_cur) and pd.notna(p_prev):
                    fund_pnl_spark.append(qty * (p_cur - p_prev))
                else:
                    fund_pnl_spark.append(0.0)

            # Fund header con colore
            color = FUND_COLORS.get(fund, "#999999")
            st.markdown(
                f"<h4 style='color:{color}; margin-bottom:0;'>{fund}</h4>",
                unsafe_allow_html=True,
            )

            # Card 1: NAV (con delta solo % e line sparkline)
            st.metric(
                "NAV",
                f"€{price_today:.2f}",
                delta=f"{nav_change_pct:+.2f}%",
                delta_color="normal",
                border=True,
                chart_data=fund_prices,
                chart_type="line",
            )

            # Card 2: Daily P&L (con delta % su MV portafoglio, bar chart storico)
            fund_pnl_pct = (daily_pnl / total_mv_yesterday * 100) if total_mv_yesterday > 0 else 0.0
            st.metric(
                "Daily P&L",
                f"€{daily_pnl:+,.2f}",
                delta=f"{fund_pnl_pct:+.2f}%",
                delta_color="off",
                border=True,
                chart_data=fund_pnl_spark,
                chart_type="bar",
            )
