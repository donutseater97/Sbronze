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

    # Gross contribution per fondo
    fund_gc = {}
    for fund in filter_funds:
        fund_tx = tx_sorted[tx_sorted["Fund"] == fund]
        gc_real = (fund_tx["Quantity"] * fund_tx["Price (€)"] + fund_tx["Fees (€)"]).sum()
        fund_gc[fund] = round(gc_real / 10) * 10  # arrotondamento theor

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
    # SEZIONE 1: PORTFOLIO TOTALS
    # =====================================================================
    st.subheader("🏦 Portfolio Overview")

    # Calcola MV totale e precedente
    total_mv_today = 0.0
    total_mv_yesterday = 0.0
    total_gc = sum(fund_gc.values())
    total_daily_pnl = 0.0

    for fund in filter_funds:
        if fund not in hist_sorted.columns:
            continue
        price_today = pd.to_numeric(pd.Series([latest_row[fund]]), errors="coerce").iloc[0]
        price_yesterday = pd.to_numeric(pd.Series([prev_row[fund]]), errors="coerce").iloc[0]
        qty = fund_qty.get(fund, 0)
        if pd.notna(price_today):
            total_mv_today += qty * price_today
        if pd.notna(price_yesterday):
            total_mv_yesterday += qty * price_yesterday
        if pd.notna(price_today) and pd.notna(price_yesterday):
            total_daily_pnl += qty * (price_today - price_yesterday)

    total_return = total_mv_today - total_gc
    total_return_pct = (total_return / total_gc * 100) if total_gc > 0 else 0.0
    daily_pnl_pct = (total_daily_pnl / total_mv_yesterday * 100) if total_mv_yesterday > 0 else 0.0

    # Sparkline per MV totale portafoglio (ultimi 30 giorni)
    portfolio_mv_spark = []
    for _, row in spark_data.iterrows():
        day_mv = 0.0
        for fund in filter_funds:
            if fund in row.index:
                p = pd.to_numeric(pd.Series([row[fund]]), errors="coerce").iloc[0]
                if pd.notna(p):
                    day_mv += fund_qty.get(fund, 0) * p
        portfolio_mv_spark.append(day_mv)

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

    # Sparkline per total return portafoglio
    portfolio_return_spark = []
    for _, row in spark_data.iterrows():
        day_mv = 0.0
        for fund in filter_funds:
            if fund in row.index:
                p = pd.to_numeric(pd.Series([row[fund]]), errors="coerce").iloc[0]
                if pd.notna(p):
                    day_mv += fund_qty.get(fund, 0) * p
        portfolio_return_spark.append(day_mv - total_gc)

    # Row 1: Portfolio metrics
    p1, p2, p3, p4 = st.columns(4)
    with p1:
        st.metric(
            "Total Market Value",
            f"€{total_mv_today:,.2f}",
            delta=f"€{total_daily_pnl:,.2f}",
            delta_color="normal",
            border=True,
            chart_data=portfolio_mv_spark,
            chart_type="area",
        )
    with p2:
        st.metric(
            "Daily P&L",
            f"€{total_daily_pnl:+,.2f}",
            delta=f"{daily_pnl_pct:+.2f}%",
            delta_color="normal",
            border=True,
            chart_data=portfolio_pnl_spark,
            chart_type="bar",
        )
    with p3:
        st.metric(
            "Total Return",
            f"€{total_return:+,.2f}",
            delta=f"{total_return_pct:+.2f}%",
            delta_color="normal",
            border=True,
            chart_data=portfolio_return_spark,
            chart_type="line",
        )
    with p4:
        st.metric(
            "Gross Contributions",
            f"€{total_gc:,.2f}",
            delta=None,
            delta_color="off",
            border=True,
        )

    st.divider()

    # =====================================================================
    # SEZIONE 2: INDIVIDUAL FUND CARDS
    # =====================================================================
    st.subheader("📊 Fund Details")

    # Due fondi per riga
    fund_pairs = [filter_funds[i:i + 2] for i in range(0, len(filter_funds), 2)]

    for pair in fund_pairs:
        cols = st.columns(2)
        for col_idx, fund in enumerate(pair):
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
                gc = fund_gc.get(fund, 0)

                if pd.isna(price_today):
                    st.warning(f"No price data for {fund}")
                    continue

                mv = qty * price_today
                fund_return = mv - gc
                fund_return_pct = (fund_return / gc * 100) if gc > 0 else 0.0

                # Calcoli delta giornaliero
                if pd.notna(price_yesterday) and price_yesterday > 0:
                    nav_change = price_today - price_yesterday
                    nav_change_pct = (nav_change / price_yesterday) * 100
                    daily_pnl = qty * nav_change
                else:
                    nav_change = 0.0
                    nav_change_pct = 0.0
                    daily_pnl = 0.0

                # Sparkline dati
                fund_prices = pd.to_numeric(spark_data[fund], errors="coerce").tolist()
                fund_mv_spark = [qty * p if pd.notna(p) else 0 for p in fund_prices]

                # Fund header con colore
                color = FUND_COLORS.get(fund, "#999999")
                st.markdown(
                    f"<h4 style='color:{color}; margin-bottom:0;'>{fund}</h4>",
                    unsafe_allow_html=True,
                )

                # Riga 1: NAV + Daily P&L
                m1, m2 = st.columns(2)
                with m1:
                    st.metric(
                        "NAV",
                        f"€{price_today:.2f}",
                        delta=f"€{nav_change:+.2f} ({nav_change_pct:+.2f}%)",
                        delta_color="normal",
                        border=True,
                        chart_data=fund_prices,
                        chart_type="line",
                    )
                with m2:
                    st.metric(
                        "Daily P&L",
                        f"€{daily_pnl:+,.2f}",
                        delta=f"{nav_change_pct:+.2f}%",
                        delta_color="normal",
                        border=True,
                        chart_data=fund_prices,
                        chart_type="bar",
                    )

                # Riga 2: Market Value + Total Return
                m3, m4 = st.columns(2)
                with m3:
                    st.metric(
                        "Market Value",
                        f"€{mv:,.2f}",
                        delta=f"€{daily_pnl:+,.2f}",
                        delta_color="normal",
                        border=True,
                        chart_data=fund_mv_spark,
                        chart_type="area",
                    )
                with m4:
                    st.metric(
                        "Total Return",
                        f"€{fund_return:+,.2f}",
                        delta=f"{fund_return_pct:+.2f}%",
                        delta_color="normal",
                        border=True,
                    )

                st.markdown("---")
