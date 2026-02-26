"""
pages/overview_and_charts.py — Pagina "Overview & Charts".

Mostra il riepilogo del portafoglio con:
- Tabella summary con metriche per fondo (gross contribution, market value, returns, ecc.)
- Metriche totali (total return, net return, daily P/L, fees)
- Grafico Revenue P&L (market value nel tempo)
- Grafico Investment Evolution (contributi a scalino + market value)
- Pie chart allocazione (Gross Contributions + Market Value)
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from config import FUND_COLORS, load_historical_prices
from components.fund_filter import render_fund_filter
from components.styling import hex_to_rgba, style_fund_cell
from components.chart_helpers import (
    apply_standard_xaxis,
    get_plotly_config,
    RANGE_SELECTOR_BUTTONS_SHORT,
)
from utils.formatting import count_decimals, format_qty


def overview_and_charts(
    funds: pd.DataFrame,
    transactions: pd.DataFrame,
    hist_data_global: pd.DataFrame,
    last_date_str: str,
):
    """Renderizza la pagina Overview & Charts.

    Args:
        funds:            DataFrame dei fondi.
        transactions:     DataFrame delle transazioni.
        hist_data_global: DataFrame prezzi storici (colonna 'date' + fondi).
        last_date_str:    Data più recente dei dati storici (es. '2026-02-24').
    """

    # ===== HEADER =====
    st.header(f"📈 Portfolio Summary as of {last_date_str}")

    # ===== FILTRO FONDI =====
    fund_list = funds["Fund"].tolist() if len(funds) > 0 else []
    filter_funds = render_fund_filter(fund_list, FUND_COLORS)

    # ===== NESSUNA TRANSAZIONE =====
    if len(transactions) == 0:
        st.info("No transactions yet")
        return

    # ----- Prepara dati transazioni -----
    df = transactions.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["Date"])

    # Applica filtro fondi
    if filter_funds:
        df = df[df["Fund"].isin(filter_funds)]

    # ----- Calcola metriche per fondo -----
    df["Gross Contribution (real)"] = df["Quantity"] * df["Price (€)"] + df["Fees (€)"]
    df["Gross Contribution (theor)"] = (df["Gross Contribution (real)"] / 10).round() * 10
    df["Net Invested"] = df["Quantity"] * df["Price (€)"]

    summary = df.groupby("Fund").agg({
        "Quantity": "sum",
        "Fees (€)": "sum",
        "Gross Contribution (theor)": "sum",
        "Net Invested": "sum",
    }).reset_index()

    summary = summary.rename(columns={
        "Gross Contribution (theor)": "Gross Contributions (€)",
        "Net Invested": "Net Invested (€)",
    })

    # Average NAV = (contributi - commissioni) / quantità
    summary["Average NAV (€)"] = (
        (summary["Gross Contributions (€)"] - summary["Fees (€)"]) / summary["Quantity"]
    )

    # ----- Precisione decimale per quantità (per fondo) -----
    try:
        fund_qty_dec = (
            transactions.groupby("Fund")["Quantity"]
            .apply(lambda s: max((count_decimals(v) for v in s if pd.notna(v)), default=0))
            .to_dict()
        )
    except Exception:
        fund_qty_dec = {}
    fund_qty_dec = {f: min(int(d or 0), 3) for f, d in fund_qty_dec.items()}

    def format_qty_overview(row):
        """Formatta la quantità con la precisione del fondo."""
        dp = fund_qty_dec.get(row["Fund"], 3)
        return format_qty(row["Quantity"], dp)

    # Salva quantità numerica prima di formattare
    qty_numeric = summary["Quantity"].astype(float).copy()

    # ----- Prezzi più recenti e Market Value -----
    hist_data = hist_data_global
    last_hist_date = (
        pd.to_datetime(hist_data["date"]).max()
        if len(hist_data) > 0 and "date" in hist_data.columns
        else None
    )

    latest_pct_map = {}
    latest_abs_change_map = {}

    if len(hist_data) > 0 and "date" in hist_data.columns:
        latest_date = pd.to_datetime(hist_data["date"]).max()
        latest_prices = {}
        for fund in summary["Fund"]:
            if fund in hist_data.columns:
                price_vals = hist_data[hist_data["date"] == latest_date][fund].values
                if len(price_vals) > 0 and pd.notna(price_vals[0]):
                    latest_prices[fund] = price_vals[0]
        summary["Latest Price (€)"] = summary["Fund"].map(latest_prices)
        summary["Market Value (€)"] = qty_numeric * summary["Latest Price (€)"].fillna(0.0)

        # Variazione giornaliera % e € per fondo
        hist_sorted = hist_data.sort_values("date", ascending=False)
        for fund in summary["Fund"]:
            if fund in hist_sorted.columns:
                s = pd.to_numeric(hist_sorted[fund], errors="coerce")
                if len(s) > 1 and pd.notna(s.iloc[0]) and pd.notna(s.iloc[1]):
                    pct = (s.iloc[0] / s.iloc[1] - 1.0) * 100.0
                    latest_pct_map[fund] = round(float(pct), 2)
                    latest_abs_change_map[fund] = float(s.iloc[0] - s.iloc[1])
    else:
        summary["Latest Price (€)"] = 0.0
        summary["Market Value (€)"] = 0.0

    # Formatta quantità per display
    summary["Quantity"] = summary.apply(format_qty_overview, axis=1)

    # ----- Calcola Return, Net Return, MoM, Weight -----
    summary["Total Return (€)"] = summary["Market Value (€)"] - summary["Gross Contributions (€)"]
    summary["Total Return (%)"] = (
        summary["Total Return (€)"] / summary["Gross Contributions (€)"] * 100
    ).round(2)
    summary["Total Return [€ (%)]"] = (
        summary["Total Return (€)"].round(2).astype(str)
        + " ("
        + summary["Total Return (%)"].astype(str)
        + "%)"
    )

    summary["Net Return (€)"] = summary["Market Value (€)"] - summary["Net Invested (€)"]
    summary["Net Return (%)"] = (
        summary["Net Return (€)"] / summary["Net Invested (€)"] * 100
    ).round(2)
    summary["Net Return [€ (%)]"] = (
        summary["Net Return (€)"].round(2).astype(str)
        + " ("
        + summary["Net Return (%)"].astype(str)
        + "%)"
    )

    # MoM performance
    df["month"] = df["Date"].dt.to_period("M")
    current_month = df["month"].max()
    prev_month = current_month - 1
    mom_performance = {}
    for fund in summary["Fund"]:
        fund_df = df[df["Fund"] == fund]
        cur_price = fund_df[fund_df["month"] == current_month]["Price (€)"].mean()
        prv_price = fund_df[fund_df["month"] == prev_month]["Price (€)"].mean()
        if pd.notna(prv_price) and prv_price > 0 and pd.notna(cur_price):
            mom_performance[fund] = (cur_price - prv_price) / prv_price * 100
        else:
            mom_performance[fund] = 0.0
    summary["MoM performance (%)"] = summary["Fund"].map(mom_performance).round(2)

    # Peso per Market Value
    total_market_value = summary["Market Value (€)"].sum()
    summary["Weight (Mkt Value)"] = (
        summary["Market Value (€)"] / total_market_value * 100
    ).round(2)

    # Ordina per ordine di funds.csv
    fund_order = funds["Fund"].tolist()
    summary["fund_order"] = summary["Fund"].map({f: i for i, f in enumerate(fund_order)})
    summary = summary.sort_values("fund_order").reset_index(drop=True)

    # ===== TABELLA SUMMARY =====
    display_summary = summary[[
        "Fund", "Gross Contributions (€)", "Net Invested (€)", "Fees (€)",
        "Latest Price (€)", "Average NAV (€)", "Quantity", "Market Value (€)",
        "Total Return [€ (%)]", "Net Return [€ (%)]",
        "MoM performance (%)", "Weight (Mkt Value)",
    ]].copy()

    display_summary = display_summary.rename(
        columns={"Total Return [€ (%)]": "Return [€ (%)]"}
    )

    # Valori grezzi per colorazione condizionale
    display_summary["_Total_Return_raw"] = summary["Total Return (€)"]
    display_summary["_Net_Return_raw"] = summary["Net Return (€)"]
    display_summary["_MoM_raw"] = summary["MoM performance (%)"]

    # Formattazione colonne €
    for col in ["Gross Contributions (€)", "Net Invested (€)", "Fees (€)", "Average NAV (€)"]:
        display_summary[col] = display_summary[col].apply(lambda x: f"€ {x:,.2f}")

    # Latest Price con % variazione giornaliera
    def _fmt_latest_price_row(row):
        fund = row["Fund"]
        price = summary.loc[summary["Fund"] == fund, "Latest Price (€)"].values[0]
        base = f"€ {float(price):,.2f}" if pd.notna(price) else "€ 0.00"
        pct = latest_pct_map.get(fund)
        if pct is None:
            return base
        if pct == 0:
            return f"{base} (0.00%)"
        sign = "+" if pct > 0 else ""
        return f"{base} ({sign}{pct:.2f}%)"

    display_summary["Latest Price (€)"] = display_summary.apply(_fmt_latest_price_row, axis=1)

    # Market Value formattato
    def _fmt_mv_row(row):
        fund = row["Fund"]
        mv = summary.loc[summary["Fund"] == fund, "Market Value (€)"].values[0]
        return f"€ {float(mv):,.2f}" if pd.notna(mv) else "€ 0.00"

    display_summary["Market Value (€)"] = display_summary.apply(_fmt_mv_row, axis=1)
    display_summary["MoM performance (%)"] = display_summary["MoM performance (%)"].apply(
        lambda x: f"{x:.2f}%"
    )
    display_summary["Weight (Mkt Value)"] = display_summary["Weight (Mkt Value)"].apply(
        lambda x: f"{x:.2f}%"
    )

    # Lookup per colorazione
    raw_values = (
        display_summary[["Fund", "_Total_Return_raw", "_Net_Return_raw", "_MoM_raw"]]
        .set_index("Fund")
    )

    # Rimuovi colonne helper
    display_summary = display_summary.drop(
        columns=["_Total_Return_raw", "_Net_Return_raw", "_MoM_raw"]
    )

    # ----- Stile tabella -----
    def style_fund_rows(row):
        """Colora: Fund col → colore fondo, Return/MoM → verde/rosso."""
        fund_name = row["Fund"]
        tr_raw = raw_values.loc[fund_name, "_Total_Return_raw"]
        nr_raw = raw_values.loc[fund_name, "_Net_Return_raw"]
        mom_raw = raw_values.loc[fund_name, "_MoM_raw"]

        styles = []
        for col in row.index:
            if col == "Fund":
                styles.append(style_fund_cell(fund_name, FUND_COLORS))
            elif col == "Return [€ (%)]":
                bg = "background-color: rgba(46,160,67,0.15);" if tr_raw >= 0 else "background-color: rgba(248,81,73,0.15);"
                styles.append(bg)
            elif col == "Net Return [€ (%)]":
                bg = "background-color: rgba(46,160,67,0.15);" if nr_raw >= 0 else "background-color: rgba(248,81,73,0.15);"
                styles.append(bg)
            elif col == "MoM performance (%)":
                bg = "background-color: rgba(46,160,67,0.15);" if mom_raw >= 0 else "background-color: rgba(248,81,73,0.15);"
                styles.append(bg)
            else:
                styles.append("")
        return styles

    styled_summary = display_summary.style.apply(style_fund_rows, axis=1)
    st.dataframe(styled_summary, width="stretch", hide_index=False)

    # ===== TOTALS ROW =====
    st.markdown("")
    st.markdown("**Totals based on filters:**")
    total_gross = summary["Gross Contributions (€)"].sum()
    total_fees = summary["Fees (€)"].sum()
    total_net = summary["Net Invested (€)"].sum()
    total_return = summary["Total Return (€)"].sum()
    total_net_return = summary["Net Return (€)"].sum()
    total_return_pct = (total_return / total_gross * 100) if total_gross > 0 else 0
    total_net_return_pct = (total_net_return / total_net * 100) if total_net > 0 else 0
    total_fees_pct = (total_fees / total_gross * 100) if total_gross > 0 else 0

    row1c1, row1c2, row1c3 = st.columns(3)
    with row1c1:
        st.metric("Total Return", f"€ {total_return:,.2f}", delta=f"{total_return_pct:+.2f}%", delta_color="normal")
    with row1c2:
        st.metric("Total Net Return", f"€ {total_net_return:,.2f}", delta=f"{total_net_return_pct:+.2f}%", delta_color="normal")
    with row1c3:
        # Daily P/L — calcolo diretto da dati storici e quantità
        daily_pnl_eur = 0.0
        daily_pnl_prev_mv = 0.0
        if len(hist_data) > 0 and "date" in hist_data.columns:
            hist_desc = hist_data.sort_values("date", ascending=False)
            tx_sorted_pnl = transactions.copy()
            tx_sorted_pnl["Date"] = pd.to_datetime(tx_sorted_pnl["Date"], errors="coerce")
            tx_sorted_pnl = tx_sorted_pnl.dropna(subset=["Date"]).sort_values("Date")
            for fund in filter_funds:
                if fund not in hist_desc.columns:
                    continue
                s = pd.to_numeric(hist_desc[fund], errors="coerce")
                if len(s) < 2 or pd.isna(s.iloc[0]) or pd.isna(s.iloc[1]):
                    continue
                fund_qty = tx_sorted_pnl[tx_sorted_pnl["Fund"] == fund]["Quantity"].sum()
                price_change = float(s.iloc[0]) - float(s.iloc[1])
                daily_pnl_eur += fund_qty * price_change
                daily_pnl_prev_mv += fund_qty * float(s.iloc[1])
        daily_pnl_pct = (daily_pnl_eur / daily_pnl_prev_mv * 100) if daily_pnl_prev_mv > 0 else 0.0
        pct_sign = "+" if daily_pnl_pct > 0 else ""
        st.metric("Daily P/L", f"€ {daily_pnl_eur:+,.2f}", delta=f"{pct_sign}{daily_pnl_pct:.2f}%", delta_color="normal")

    row2c1, row2c2, row2c3 = st.columns(3)
    with row2c1:
        st.metric("Total Gross Contributions", f"€ {total_gross:,.2f}")
    with row2c2:
        st.metric("Total Market Value", f"€ {total_market_value:,.2f}")
    with row2c3:
        st.metric("Total Fees", f"€ {total_fees:,.2f}", delta=f"↓ {total_fees_pct:.2f}%", delta_color="off")

    # ===== GRAFICI =====
    st.divider()
    st.header("📊 Charts")

    # ===== DAILY RETURNS STACKED BAR CHART =====
    if len(filter_funds) > 0:
        _render_daily_returns_bar(df, filter_funds, hist_data, transactions)

    # ===== INVESTMENT EVOLUTION + ALLOCATION PIES =====
    if len(df) > 0:
        _render_evolution_and_allocation(df, funds, hist_data)


# =============================================================================
# SOTTO-FUNZIONI GRAFICI (private)
# =============================================================================

def _render_daily_returns_bar(df, filter_funds, hist_data, transactions):
    """Renderizza stacked bar chart con i return giornalieri per fondo."""
    st.subheader("📈 Revenue P&L - Daily Returns by Fund")
    st.caption("Shows the daily return (market value change) for each fund and total portfolio")

    if len(hist_data) == 0 or "date" not in hist_data.columns:
        st.info("No historical data available.")
        return

    first_tx_date = pd.to_datetime(transactions["Date"], errors="coerce").min()

    hist_asc = hist_data[["date"] + filter_funds].copy()
    hist_asc["date"] = pd.to_datetime(hist_asc["date"], errors="coerce")
    hist_asc = hist_asc.dropna(subset=["date"])
    hist_asc = hist_asc[hist_asc["date"] >= first_tx_date].sort_values("date").reset_index(drop=True)

    if len(hist_asc) == 0:
        st.info("No historical data available after your first transaction date.")
        return

    # Calcola quantità a t-1 per ciascun fondo
    tx_sorted = transactions.copy()
    tx_sorted["Date"] = pd.to_datetime(tx_sorted["Date"], errors="coerce")
    tx_sorted = tx_sorted.dropna(subset=["Date"]).sort_values("Date")

    qty_prev_df = pd.DataFrame({"date": hist_asc["date"]})
    for fund in filter_funds:
        fund_tx = tx_sorted[tx_sorted["Fund"] == fund][["Date", "Quantity"]].copy()
        if len(fund_tx) == 0:
            qty_prev_df[fund] = 0.0
            continue
        fund_tx["cum_qty"] = fund_tx["Quantity"].cumsum()
        merged = pd.merge_asof(
            hist_asc[["date"]],
            fund_tx[["Date", "cum_qty"]].sort_values("Date"),
            left_on="date", right_on="Date", direction="backward",
        )
        qty_prev_df[fund] = merged["cum_qty"].fillna(0.0).shift(1).fillna(0.0)

    # Market Value giornaliero e delta
    mv_df = hist_asc[["date"]].copy()
    for fund in filter_funds:
        price = pd.to_numeric(hist_asc[fund], errors="coerce")
        mv_df[f"{fund} MV (€)"] = qty_prev_df[fund] * price
        mv_df[f"{fund} Δ (€)"] = (qty_prev_df[fund] * price) - (qty_prev_df[fund] * price.shift(1))

    # Calcola totale giornaliero
    delta_cols = [f"{f} Δ (€)" for f in filter_funds if f"{f} Δ (€)" in mv_df.columns]
    mv_df["Total Δ (€)"] = mv_df[delta_cols].sum(axis=1)

    # Crea stacked bar chart
    fig = go.Figure()

    for fund in filter_funds:
        col = f"{fund} Δ (€)"
        if col in mv_df.columns:
            color = FUND_COLORS.get(fund, "#999999")
            fig.add_trace(go.Bar(
                x=mv_df["date"], y=mv_df[col],
                name=fund,
                marker=dict(color=color),
                hovertemplate=f"<b>{fund}</b>: €%{{y:,.2f}}<extra></extra>",
            ))

    # Traccia invisibile per mostrare il totale nel tooltip
    fig.add_trace(go.Scatter(
        x=mv_df["date"], y=[0] * len(mv_df),
        mode="lines", line=dict(width=0), showlegend=False,
        hovertemplate="<b>Total</b>: €" + mv_df["Total Δ (€)"].apply(lambda v: f"{v:,.2f}") + "<extra></extra>",
    ))

    fig.update_layout(
        barmode="relative",
        height=600, hovermode="x unified", xaxis_title="", yaxis_title="Daily Return (€)",
        template="plotly_white", showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        dragmode="pan", uirevision="daily_returns_bar",
        newshape=dict(line_color="#888888"), margin=dict(r=20),
    )
    apply_standard_xaxis(fig, RANGE_SELECTOR_BUTTONS_SHORT)
    fig.update_yaxes(
        rangemode="normal", fixedrange=False, showspikes=True, spikemode="across",
        zeroline=True, zerolinecolor="rgba(150,150,150,0.5)", zerolinewidth=2,
    )
    st.plotly_chart(fig, use_container_width=True, config=get_plotly_config("daily_returns_bar"))


def _render_evolution_and_allocation(df, funds, hist_data):
    """Renderizza Investment Evolution e Allocation Pies affiancati."""
    df["date_dt"] = pd.to_datetime(df["Date"], errors="coerce")
    df = df.dropna(subset=["date_dt"])
    if len(df) == 0:
        return

    # Contributi cumulati (step)
    df_sorted = df.sort_values("date_dt")
    df_sorted["Gross Contribution (real)"] = df_sorted["Quantity"] * df_sorted["Price (€)"] + df_sorted["Fees (€)"]
    df_sorted["Gross Contribution (theor)"] = (df_sorted["Gross Contribution (real)"] / 10).round() * 10
    daily_data = df_sorted.groupby("date_dt").agg({"Gross Contribution (theor)": "sum"}).reset_index()
    daily_data["Gross Contribution"] = daily_data["Gross Contribution (theor)"].cumsum()
    daily_data = daily_data.sort_values("date_dt")

    # Stair-step
    stair_dates, stair_values = [], []
    for idx_row, row in daily_data.iterrows():
        if idx_row > 0:
            stair_dates.append(row["date_dt"])
            stair_values.append(daily_data.iloc[idx_row - 1]["Gross Contribution"])
        stair_dates.append(row["date_dt"])
        stair_values.append(row["Gross Contribution"])
    stair_df = pd.DataFrame({"date_dt": stair_dates, "Gross Contribution": stair_values})

    # Market Value nel tempo
    hist_data_local = load_historical_prices(funds)
    market_value_by_date = []
    if len(hist_data_local) > 0 and "date" in hist_data_local.columns:
        for hist_date in sorted(hist_data_local["date"].unique()):
            tx_up = df_sorted[df_sorted["date_dt"] <= hist_date]
            if len(tx_up) == 0:
                continue
            mv = 0.0
            for fund in tx_up["Fund"].unique():
                qty = tx_up[tx_up["Fund"] == fund]["Quantity"].sum()
                if fund in hist_data_local.columns:
                    price_row = hist_data_local[hist_data_local["date"] == hist_date][fund]
                    if len(price_row) > 0 and pd.notna(price_row.iloc[0]):
                        mv += qty * price_row.iloc[0]
            if mv > 0:
                market_value_by_date.append({"date": hist_date, "market_value": mv})
    market_value_df = pd.DataFrame(market_value_by_date) if market_value_by_date else pd.DataFrame()

    # Estendi linea contributi fino all'ultima data storica
    if len(hist_data_local) > 0 and "date" in hist_data_local.columns and len(stair_df) > 0:
        latest_hist = pd.to_datetime(hist_data_local["date"], errors="coerce").max()
        latest_stair = pd.to_datetime(stair_df["date_dt"], errors="coerce").max()
        if pd.notna(latest_hist) and pd.notna(latest_stair) and latest_hist > latest_stair:
            stair_df = pd.concat([
                stair_df,
                pd.DataFrame({"date_dt": [latest_hist], "Gross Contribution": [stair_df["Gross Contribution"].iloc[-1]]}),
            ], ignore_index=True)

    # ----- Layout: Allocation (sinistra) + Evolution (destra) -----
    col_pie, col_evo = st.columns([1, 1])

    with col_pie:
        _render_allocation_pies(df, funds, hist_data_local)

    with col_evo:
        _render_investment_evolution_chart(stair_df, market_value_df, has_alloc_filter=True)


def _render_allocation_pies(df, funds, hist_data):
    """Renderizza i pie chart di allocazione (Gross Contributions + Market Value)."""
    st.subheader("💰 Allocation")
    alloc_by = st.selectbox("Group by:", ["Fund", "Type", "Asset Manager"], key="alloc_selectbox")

    df["invested"] = df["Quantity"] * df["Price (€)"] + df["Fees (€)"]

    # Palette colori per tipo e asset manager
    type_colors = {
        "Bond": "#6B8CAE", "Equity": "#B8860B", "Mixed": "#6BA565",
        "Commodity": "#B8604B", "Alternative": "#8B6B9E", "Other": "#6B7480",
    }
    am_palette = [
        "#6B8CAE", "#B8860B", "#6BA565", "#B8604B", "#8B6B9E",
        "#6B7480", "#A85B8E", "#7A7A7A", "#998B3C", "#5B8FA3",
    ]

    # ----- Gross Contributions -----
    if alloc_by == "Fund":
        alloc_gc = df.groupby("Fund")["invested"].sum().reset_index().sort_values("invested", ascending=False)
        alloc_gc.columns = ["Category", "Value"]
        # Colori meno luminosi per i fund: aggiungiamo trasparenza
        from components.styling import hex_to_rgb
        color_map = {}
        for c in alloc_gc["Category"]:
            base_color = FUND_COLORS.get(c, "#999999")
            r, g, b = hex_to_rgb(base_color)
            color_map[c] = f"rgba({r}, {g}, {b}, 0.7)"
    elif alloc_by == "Type":
        tmp = df.merge(funds[["Fund", "Type"]], on="Fund", how="left")
        alloc_gc = tmp.groupby("Type")["invested"].sum().reset_index().sort_values("invested", ascending=False)
        alloc_gc.columns = ["Category", "Value"]
        color_map = {c: type_colors.get(c, "#999999") for c in alloc_gc["Category"]}
    else:
        tmp = df.merge(funds[["Fund", "Fund Name"]], on="Fund", how="left")
        tmp["Asset Manager"] = tmp["Fund Name"].str.split().str[0]
        alloc_gc = tmp.groupby("Asset Manager")["invested"].sum().reset_index().sort_values("invested", ascending=False)
        alloc_gc.columns = ["Category", "Value"]
        color_map = {c: am_palette[i % len(am_palette)] for i, c in enumerate(alloc_gc["Category"])}

    # ----- Market Value -----
    mv_map = {}
    if len(hist_data) > 0 and "date" in hist_data.columns:
        latest_d = pd.to_datetime(hist_data["date"], errors="coerce").max()
        qty_by_fund = df.groupby("Fund")["Quantity"].sum()
        for fund in qty_by_fund.index:
            if fund in hist_data.columns:
                vals = hist_data[hist_data["date"] == latest_d][fund].values
                if len(vals) > 0 and pd.notna(vals[0]):
                    mv_map[fund] = float(qty_by_fund.loc[fund]) * float(vals[0])

    if alloc_by == "Fund":
        alloc_mv = pd.DataFrame({"Category": list(mv_map.keys()), "Value": list(mv_map.values())}).sort_values("Value", ascending=False)
    elif alloc_by == "Type":
        mv_df_tmp = pd.DataFrame({"Fund": list(mv_map.keys()), "MV": list(mv_map.values())})
        mv_df_tmp = mv_df_tmp.merge(funds[["Fund", "Type"]], on="Fund", how="left")
        alloc_mv = mv_df_tmp.groupby("Type")["MV"].sum().reset_index().rename(columns={"Type": "Category", "MV": "Value"}).sort_values("Value", ascending=False)
        for c in alloc_mv["Category"]:
            color_map.setdefault(c, type_colors.get(c, "#999999"))
    else:
        mv_df_tmp = pd.DataFrame({"Fund": list(mv_map.keys()), "MV": list(mv_map.values())})
        mv_df_tmp = mv_df_tmp.merge(funds[["Fund", "Fund Name"]], on="Fund", how="left")
        mv_df_tmp["Asset Manager"] = mv_df_tmp["Fund Name"].str.split().str[0]
        alloc_mv = mv_df_tmp.groupby("Asset Manager")["MV"].sum().reset_index().rename(columns={"Asset Manager": "Category", "MV": "Value"}).sort_values("Value", ascending=False)
        next_idx = len(color_map)
        for i, c in enumerate(alloc_mv["Category"]):
            color_map.setdefault(c, am_palette[(next_idx + i) % len(am_palette)])

    # Renderizza 2 pie affiancati
    pie_l, pie_r = st.columns(2)
    with pie_l:
        st.caption("Gross Contributions")
        fig_gc = go.Figure(data=[go.Pie(
            labels=alloc_gc["Category"], values=alloc_gc["Value"], hole=0.4,
            marker=dict(colors=[color_map.get(c, "#999999") for c in alloc_gc["Category"]]),
            textinfo="percent", textposition="inside",
            textfont=dict(size=14, color="#ffffff", family="system-ui"),
            hovertemplate="<b>%{label}</b><br>€%{value:,.2f}<br>%{percent}<extra></extra>",
        )])
        fig_gc.update_layout(height=520, showlegend=False, hovermode="closest", font=dict(family="system-ui", size=12))
        st.plotly_chart(fig_gc, use_container_width=True)

    with pie_r:
        st.caption("Market Value")
        fig_mv = go.Figure(data=[go.Pie(
            labels=alloc_mv["Category"], values=alloc_mv["Value"], hole=0.4,
            marker=dict(colors=[color_map.get(c, "#999999") for c in alloc_mv["Category"]]),
            textinfo="percent", textposition="inside",
            textfont=dict(size=14, color="#ffffff", family="system-ui"),
            hovertemplate="<b>%{label}</b><br>€%{value:,.2f}<br>%{percent}<extra></extra>",
        )])
        fig_mv.update_layout(height=520, showlegend=False, hovermode="closest", font=dict(family="system-ui", size=12))
        st.plotly_chart(fig_mv, use_container_width=True)

    # Legenda unificata
    cats_union = list(dict.fromkeys(list(alloc_gc["Category"]) + list(alloc_mv["Category"])))
    legend_style = "display:flex; justify-content:center; flex-wrap:nowrap; gap:16px; align-items:center; overflow-x:auto; padding:6px 0; border-top:1px solid rgba(150,150,150,.2);"
    legend_html = f"<div style='{legend_style}'>" + "".join([
        f"<div><span style='display:inline-block;width:12px;height:12px;border-radius:2px;background:{color_map.get(c, '#999999')};border:1px solid rgba(0,0,0,.35);margin-right:6px;vertical-align:middle;'></span>{c}</div>"
        for c in cats_union
    ]) + "</div>"
    st.markdown(legend_html, unsafe_allow_html=True)


def _render_investment_evolution_chart(stair_df, market_value_df, has_alloc_filter=False):
    """Renderizza il grafico Investment Evolution (contributi step + market value)."""
    st.subheader("📈 Investment Evolution")
    if has_alloc_filter:
        # Spacer per allineare con il selectbox "Group by" nella colonna allocation
        st.markdown("")
    fig = go.Figure()

    # Linea contributi (stair-step)
    fig.add_trace(go.Scatter(
        x=stair_df["date_dt"], y=stair_df["Gross Contribution"],
        mode="lines", name="Gross Contribution",
        line=dict(color="#f093fb", width=2.5),
        hovertemplate="<b>Gross Contribution</b>: €%{y:,.2f}<extra></extra>",
        fill="tozeroy", fillcolor="rgba(102, 126, 234, 0.1)",
    ))

    # Overlay market value
    if len(market_value_df) > 0:
        fig.add_trace(go.Scatter(
            x=market_value_df["date"], y=market_value_df["market_value"],
            mode="lines", name="Market Value",
            line=dict(color="#667eea", width=2.5),
            hovertemplate="<b>Market Value</b>: €%{y:,.2f}<extra></extra>",
        ))

    fig.update_layout(
        height=520, hovermode="x unified", xaxis_title="", yaxis_title="Value (€)",
        template="plotly_white", showlegend=False, dragmode="pan",
        uirevision="overview_evolution", newshape=dict(line_color="#888888"),
    )
    apply_standard_xaxis(fig, RANGE_SELECTOR_BUTTONS_SHORT)
    fig.update_yaxes(autorange=True, rangemode="normal", fixedrange=False, showspikes=True, spikemode="across")

    st.plotly_chart(fig, use_container_width=True, config=get_plotly_config("investment_evolution"))

    # Legenda sotto il grafico
    legend_style = "display:flex; justify-content:center; flex-wrap:nowrap; gap:16px; align-items:center; overflow-x:auto; padding:6px 0; border-top:1px solid rgba(150,150,150,.2);"
    st.markdown(
        f"<div style='{legend_style}'>"
        f"<div><span style='display:inline-block;width:28px;height:0;border-top:3px solid #f093fb;vertical-align:middle;margin-right:6px;'></span>Gross Contribution</div>"
        f"<div><span style='display:inline-block;width:28px;height:0;border-top:3px solid #667eea;vertical-align:middle;margin-right:6px;'></span>Market Value</div>"
        f"</div>",
        unsafe_allow_html=True,
    )
