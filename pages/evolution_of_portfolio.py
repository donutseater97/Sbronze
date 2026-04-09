"""
pages/evolution_of_portfolio.py — Pagina "Evolution of Portfolio".

Mostra l'evoluzione dettagliata del portafoglio:
- Tabella P/L Evolution con NAV giornaliero e variazione % per fondo
- Grafico Daily NAV Evolution
- Tabella Market Value Evolution con variazione € giornaliera per fondo
- Grafico Holdings Market Value (area chart impilato)
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from config import FUND_COLORS
from components.styling import hex_to_rgb
from components.chart_helpers import (
    apply_standard_xaxis,
    get_plotly_config,
    RANGE_SELECTOR_BUTTONS_SHORT,
)


def evolution_of_portfolio(
    funds: pd.DataFrame,
    transactions: pd.DataFrame,
    hist_data_global: pd.DataFrame,
):
    """Renderizza la pagina Evolution of Portfolio.

    Args:
        funds:            DataFrame dei fondi.
        transactions:     DataFrame delle transazioni.
        hist_data_global: DataFrame prezzi storici.
    """
    st.header("📊 Evolution of Portfolio")

    # Usa filtro fondi dallo stato sessione
    if "fund_filter" not in st.session_state or len(st.session_state.fund_filter) == 0:
        filter_funds = funds["Fund"].tolist() if len(funds) > 0 else []
    else:
        filter_funds = st.session_state.fund_filter

    if len(transactions) == 0 or len(filter_funds) == 0:
        st.info("No data available. Please add transactions and ensure at least one fund is selected.")
        return

    hist_data = hist_data_global
    if len(hist_data) == 0 or "date" not in hist_data.columns:
        st.info("No historical data available for evolution calculations.")
        return

    # Prepara dati storici in ordine crescente
    hist_asc = hist_data[["date"] + filter_funds].copy()
    hist_asc["date"] = pd.to_datetime(hist_asc["date"], errors="coerce")
    hist_asc = hist_asc.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    # Transazioni ordinate per data
    tx_sorted = transactions.copy()
    tx_sorted["Date"] = pd.to_datetime(tx_sorted["Date"], errors="coerce")
    tx_sorted = tx_sorted.dropna(subset=["Date"]).sort_values("Date")

    # Prima transazione per fondo (per filtrare dati prima dell'acquisto)
    first_tx_date_by_fund = tx_sorted.groupby("Fund")["Date"].min().to_dict()

    # Calcola quantità a t-1 per ciascun fondo (per calcolo P/L)
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

    # ===== 1. REVENUE P&L BY FUND (stacked bar chart) =====
    _render_revenue_pnl_bar(hist_asc, filter_funds, transactions)

    st.divider()

    # ===== 2. GRAFICO FUNDS NAV EVOLUTION =====
    _render_funds_nav_chart(hist_asc, filter_funds, first_tx_date_by_fund)

    st.divider()

    # ===== 3. GRAFICO PORTFOLIO MARKET VALUE EVOLUTION =====
    _render_portfolio_market_value(hist_asc, filter_funds, qty_prev_df, transactions)

    # ===== 4. GRAFICO PORTFOLIO COMPOSITION =====
    _render_portfolio_composition(hist_asc, filter_funds, qty_prev_df, transactions, first_tx_date_by_fund)

    st.divider()

    # ===== 5. TABELLA MARKET VALUE EVOLUTION (in fondo) =====
    _render_market_value_table(hist_asc, filter_funds, qty_prev_df, first_tx_date_by_fund)


# =============================================================================
# SOTTO-FUNZIONI (private)
# =============================================================================

def _render_revenue_pnl_bar(hist_asc, filter_funds, transactions):
    """Stacked bar chart: solo ritorno da movimento NAV (esclusi versamenti)."""
    st.subheader("📈 Absolute and % Change by Fund")
    st.caption("Shows NAV-only change by fund (excludes new contributions), in absolute € or %")

    # Selettore frequenza
    freq_options = {
        "1D": "D", "1W": "W", "1M": "ME",
        "3M": "QE", "6M": "2QE", "1Y": "YE",
    }
    controls_col_l, controls_col_r = st.columns([3, 2])
    with controls_col_l:
        freq_label = st.segmented_control(
            "Frequency", list(freq_options.keys()),
            default="1D", key="revenue_pnl_freq"
        )
    with controls_col_r:
        display_mode = st.segmented_control(
            "Display",
            ["Absolute (€)", "Percentage (%)"],
            default="Absolute (€)",
            key="revenue_pnl_display_mode",
        )
    if freq_label is None:
        freq_label = "1D"
    if display_mode is None:
        display_mode = "Absolute (€)"
    freq = freq_options[freq_label]

    if len(hist_asc) == 0:
        st.info("No historical data available.")
        return

    first_tx_date = pd.to_datetime(transactions["Date"], errors="coerce").min()
    hist_filtered = hist_asc[hist_asc["date"] >= first_tx_date].copy().reset_index(drop=True)
    if len(hist_filtered) == 0:
        st.info("No historical data available after your first transaction date.")
        return

    # Calcola quantità corrente per ciascun fondo (as-of each date)
    tx_sorted = transactions.copy()
    tx_sorted["Date"] = pd.to_datetime(tx_sorted["Date"], errors="coerce")
    tx_sorted = tx_sorted.dropna(subset=["Date"]).sort_values("Date")

    qty_df = pd.DataFrame({"date": hist_filtered["date"]})
    for fund in filter_funds:
        fund_tx = tx_sorted[tx_sorted["Fund"] == fund][["Date", "Quantity"]].copy()
        if len(fund_tx) == 0:
            qty_df[fund] = 0.0
            continue
        fund_tx["cum_qty"] = fund_tx["Quantity"].cumsum()
        merged = pd.merge_asof(
            hist_filtered[["date"]],
            fund_tx[["Date", "cum_qty"]].sort_values("Date"),
            left_on="date", right_on="Date", direction="backward",
        )
        qty_df[fund] = merged["cum_qty"].fillna(0.0)

    # Calcolo giornaliero del ritorno NAV-only:
    # return_day = qty_day * (price_day - price_prev_day)
    # Questo isola il movimento di prezzo, escludendo l'effetto dei versamenti
    nav_return_daily = hist_filtered[["date"]].copy()
    market_value_daily = hist_filtered[["date"]].copy()
    for fund in filter_funds:
        price = pd.to_numeric(hist_filtered[fund], errors="coerce")
        price_change = price - price.shift(1)
        nav_return_daily[fund] = qty_df[fund].values * price_change.values
        market_value_daily[fund] = qty_df[fund].values * price.values

    nav_return_daily = nav_return_daily.iloc[1:].reset_index(drop=True)  # drop first NaN row

    # Resample alla frequenza scelta (somma dei ritorni nel periodo)
    nav_return_daily = nav_return_daily.set_index("date")
    nav_abs_resampled = nav_return_daily.resample(freq).sum(min_count=1).dropna(how="all")

    if len(nav_abs_resampled) == 0:
        st.info("Not enough data for selected frequency.")
        return

    # Base per percentuali: market value di fine periodo precedente
    mv_resampled_last = (
        market_value_daily
        .set_index("date")
        .resample(freq)
        .last()
        .reindex(nav_abs_resampled.index)
    )

    if display_mode == "Percentage (%)":
        prev_mv = mv_resampled_last[filter_funds].shift(1)
        nav_pct_resampled = nav_abs_resampled[filter_funds].div(prev_mv.where(prev_mv != 0)).mul(100)

        total_abs = nav_abs_resampled[filter_funds].sum(axis=1)
        total_prev_mv = mv_resampled_last[filter_funds].sum(axis=1).shift(1)
        nav_pct_resampled["Total"] = total_abs.div(total_prev_mv.where(total_prev_mv != 0)).mul(100)

        chart_df = nav_pct_resampled.reset_index()
        yaxis_title = f"{freq_label} Change (%)"
        hover_fmt = "%{y:,.2f}%"
        total_fmt = lambda v: "-" if pd.isna(v) else f"{v:,.2f}%"
    else:
        nav_abs_resampled["Total"] = nav_abs_resampled[filter_funds].sum(axis=1)
        chart_df = nav_abs_resampled.reset_index()
        yaxis_title = f"{freq_label} Change (€)"
        hover_fmt = "€%{y:,.2f}"
        total_fmt = lambda v: f"€{v:,.2f}"

    # Crea stacked bar chart
    fig = go.Figure()
    for fund in filter_funds:
        color = FUND_COLORS.get(fund, "#999999")
        fig.add_trace(go.Bar(
            x=chart_df["date"], y=chart_df[fund],
            name=fund, marker=dict(color=color),
            hovertemplate=f"<b>{fund}</b>: {hover_fmt}<extra></extra>",
        ))

    # Traccia invisibile per totale nel tooltip
    fig.add_trace(go.Scatter(
        x=chart_df["date"], y=[0] * len(chart_df),
        mode="lines", line=dict(width=0), showlegend=False,
        hovertemplate="<b>Total</b>: " + chart_df["Total"].apply(total_fmt) + "<extra></extra>",
    ))

    fig.update_layout(
        barmode="relative",
        height=600, hovermode="x unified", xaxis_title="", yaxis_title=yaxis_title,
        template="plotly_white", showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        dragmode="pan", uirevision="absolute_pct_change_by_fund",
        newshape=dict(line_color="#888888"), margin=dict(r=20),
    )
    apply_standard_xaxis(fig, RANGE_SELECTOR_BUTTONS_SHORT)
    fig.update_yaxes(
        rangemode="normal", fixedrange=False, showspikes=True, spikemode="across",
        zeroline=True, zerolinecolor="rgba(150,150,150,0.5)", zerolinewidth=2,
    )
    st.plotly_chart(fig, use_container_width=True, config=get_plotly_config("absolute_pct_change_by_fund"))


def _render_funds_nav_chart(hist_asc, filter_funds, first_tx_date_by_fund):
    """Grafico lineare NAV per fondo."""
    st.subheader("📊 Funds NAV Evolution Chart")
    fig = go.Figure()
    pnl_asc = hist_asc.sort_values("date", ascending=True).reset_index(drop=True)

    for fund in filter_funds:
        first_date = first_tx_date_by_fund.get(fund)
        fund_data = pnl_asc[pnl_asc["date"] >= pd.to_datetime(first_date)] if first_date else pnl_asc
        fig.add_trace(go.Scatter(
            x=fund_data["date"], y=fund_data[fund],
            mode="lines", name=fund,
            line=dict(color=FUND_COLORS.get(fund, "#999999"), width=2),
            hovertemplate=f"<b>{fund}</b>: €%{{y:,.2f}}<extra></extra>",
        ))

    fig.update_layout(
        height=500, hovermode="x unified", xaxis_title="Date", yaxis_title="NAV (€)",
        template="plotly_white", showlegend=True,
        legend=dict(orientation="v", yanchor="top", y=0.99, xanchor="left", x=0.01),
        dragmode="pan",
    )
    apply_standard_xaxis(fig, RANGE_SELECTOR_BUTTONS_SHORT)
    st.plotly_chart(fig, use_container_width=True)


def _render_market_value_table(hist_asc, filter_funds, qty_prev_df, first_tx_date_by_fund):
    """Tabella Market Value giornaliero con variazione € per fondo."""
    st.subheader("📈 Portfolio Market Value Evolution - Daily Holdings Value")
    st.caption("Shows the market value of your holdings (quantity held × daily NAV) with € change from previous day")

    mv_df = hist_asc[["date"]].copy()
    for fund in filter_funds:
        price = pd.to_numeric(hist_asc[fund], errors="coerce")
        qty = qty_prev_df[fund]
        mv_df[f"{fund} (€)"] = qty * price
        mv_df[f"{fund} (€) Δ"] = (qty * price) - (qty * price.shift(1))

    # Totale portafoglio
    total_mv = pd.DataFrame([mv_df[f"{f} (€)"] for f in filter_funds]).sum(axis=0)
    mv_df["Daily MV Total (€)"] = total_mv
    mv_df["Daily MV Total Δ (€)"] = total_mv - total_mv.shift(1)

    # Display decrescente
    mv_display = mv_df.sort_values("date", ascending=False).reset_index(drop=True)
    display = mv_display[["date"]].copy()
    display["Date"] = display["date"].dt.strftime("%Y-%m-%d")
    display = display.drop(columns=["date"])

    for fund in filter_funds:
        first_date = first_tx_date_by_fund.get(fund)
        if first_date:
            first_date = pd.to_datetime(first_date)

            def fmt_mv(idx, fn=fund):
                delta = mv_display[f"{fn} (€) Δ"].iloc[idx]
                if pd.isna(delta):
                    return "-"
                sign = "+" if delta > 0 else ""
                return f"{sign}€{delta:.2f}"

            display[fund] = [
                fmt_mv(i) if pd.to_datetime(mv_display["date"].iloc[i]) >= first_date else "-"
                for i in range(len(mv_display))
            ]

    # Totale giornaliero
    def fmt_total(idx):
        delta = mv_display["Daily MV Total Δ (€)"].iloc[idx]
        if pd.isna(delta):
            return "-"
        sign = "+" if delta > 0 else ""
        return f"{sign}€{delta:.2f}"

    display["Daily Total Δ (€)"] = [fmt_total(i) for i in range(len(mv_display))]

    # Stile
    def style_fn(row):
        styles = [""] * len(row)
        idx = row.name
        for col_idx, fund in enumerate(filter_funds, start=1):
            delta = mv_display[f"{fund} (€) Δ"].iloc[idx]
            if pd.isna(delta) or delta == 0:
                pass
            elif delta > 0:
                styles[col_idx] = "background-color: rgba(107, 203, 119, 0.15); color: #2d6a3f;"
            else:
                styles[col_idx] = "background-color: rgba(226, 106, 106, 0.15); color: #8b2e2e;"
        # Colonna totale
        total_idx = len(filter_funds) + 1
        daily_val = mv_display["Daily MV Total Δ (€)"].iloc[idx]
        if pd.notna(daily_val) and daily_val != 0:
            if daily_val > 0:
                styles[total_idx] = "background-color: rgba(107, 203, 119, 0.15); color: #2d6a3f; font-weight: 600;"
            else:
                styles[total_idx] = "background-color: rgba(226, 106, 106, 0.15); color: #8b2e2e; font-weight: 600;"
        return styles

    st.dataframe(display.style.apply(style_fn, axis=1), width="stretch", hide_index=True)


def _render_portfolio_market_value(hist_asc, filter_funds, qty_prev_df, transactions):
    """Grafico Portfolio Market Value Evolution."""
    st.subheader("📉 Portfolio Market Value Evolution")
    st.caption("Shows your portfolio market value over time, starting from your first transaction")

    first_tx_date = pd.to_datetime(transactions["Date"], errors="coerce").min()

    # Calcola quantità corrente (non t-1) per ciascun fondo
    tx_sorted = transactions.copy()
    tx_sorted["Date"] = pd.to_datetime(tx_sorted["Date"], errors="coerce")
    tx_sorted = tx_sorted.dropna(subset=["Date"]).sort_values("Date")

    qty_current_df = pd.DataFrame({"date": hist_asc["date"]})
    for fund in filter_funds:
        fund_tx = tx_sorted[tx_sorted["Fund"] == fund][["Date", "Quantity"]].copy()
        if len(fund_tx) == 0:
            qty_current_df[fund] = 0.0
            continue
        fund_tx["cum_qty"] = fund_tx["Quantity"].cumsum()
        merged = pd.merge_asof(
            hist_asc[["date"]],
            fund_tx[["Date", "cum_qty"]].sort_values("Date"),
            left_on="date", right_on="Date", direction="backward",
        )
        qty_current_df[fund] = merged["cum_qty"].fillna(0.0)

    # Market Value giornaliero
    mv_df = hist_asc[["date"]].copy().reset_index(drop=True)
    for fund in filter_funds:
        price = pd.to_numeric(hist_asc[fund], errors="coerce").reset_index(drop=True)
        qty = qty_current_df[fund].reset_index(drop=True)
        mv_df[f"{fund} MV (€)"] = qty * price

    mv_df["Daily MV (€)"] = mv_df[[f"{f} MV (€)" for f in filter_funds]].sum(axis=1)

    # Filtra da prima transazione
    mv_df = mv_df[mv_df["date"] >= first_tx_date].reset_index(drop=True)

    if len(mv_df) == 0:
        st.info("No historical data available after your first transaction date.")
        return

    # Crea grafico
    fig = go.Figure()
    latest_date = mv_df["date"].max()

    # Linea totale portafoglio
    fig.add_trace(go.Scatter(
        x=mv_df["date"], y=mv_df["Daily MV (€)"],
        mode="lines", name="Portfolio MV",
        line=dict(color="#667eea", width=3),
        fill="tozeroy", fillcolor="rgba(102, 126, 234, 0.1)",
        hovertemplate="<b>Portfolio MV</b>: €%{y:,.2f}<extra></extra>",
    ))

    # Annotazione ultimo valore totale
    last_mv = mv_df["Daily MV (€)"].iloc[-1]
    fig.add_annotation(
        x=latest_date, y=last_mv, text=f"€{last_mv:,.0f}",
        showarrow=False, xanchor="left", xshift=10,
        font=dict(size=14, color="#667eea"),
        bordercolor="#667eea", borderwidth=2, borderpad=4,
        bgcolor="rgba(255,255,255,0)",
    )

    # Linee per singolo fondo
    for fund in filter_funds:
        col = f"{fund} MV (€)"
        if col in mv_df.columns:
            color = FUND_COLORS.get(fund, "#999999")
            fig.add_trace(go.Scatter(
                x=mv_df["date"], y=mv_df[col],
                mode="lines", name=fund,
                line=dict(color=color, width=2, dash="dot"),
                hovertemplate=f"<b>{fund}</b>: €%{{y:,.2f}}<extra></extra>",
            ))
            last_fund_mv = mv_df[col].iloc[-1]
            fig.add_annotation(
                x=latest_date, y=last_fund_mv, text=f"€{last_fund_mv:,.0f}",
                showarrow=False, xanchor="left", xshift=10,
                font=dict(size=13, color=color),
                bordercolor=color, borderwidth=1.5, borderpad=4,
                bgcolor="rgba(255,255,255,0)",
            )

    # Range Y con padding
    all_vals = [mv_df["Daily MV (€)"].min(), mv_df["Daily MV (€)"].max()]
    for fund in filter_funds:
        col = f"{fund} MV (€)"
        if col in mv_df.columns:
            all_vals.extend([mv_df[col].min(), mv_df[col].max()])
    max_mv = max(all_vals) if all_vals else 1000
    min_mv = min(all_vals) if all_vals else 0
    padding = (max_mv - min_mv) * 0.05

    fig.update_layout(
        height=600, hovermode="x unified", xaxis_title="", yaxis_title="Market Value (€)",
        template="plotly_white", showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        dragmode="pan", uirevision="portfolio_mv_evolution",
        newshape=dict(line_color="#888888"), margin=dict(r=100),
        yaxis=dict(range=[min_mv - padding, max_mv + padding]),
    )
    apply_standard_xaxis(fig, RANGE_SELECTOR_BUTTONS_SHORT)
    fig.update_yaxes(
        rangemode="normal", fixedrange=False, showspikes=True, spikemode="across",
        zeroline=True, zerolinecolor="rgba(150,150,150,0.5)", zerolinewidth=2,
    )
    st.plotly_chart(fig, use_container_width=True, config=get_plotly_config("portfolio_mv_evolution"))


def _render_portfolio_composition(hist_asc, filter_funds, qty_prev_df, transactions, first_tx_date_by_fund):
    """Grafico Portfolio Composition (stacked area % per fund)."""
    st.subheader("🧩 Portfolio Composition")
    st.caption("Shows the percentage composition of your portfolio over time")

    # Filtro Gross Contribution vs Market Value
    comp_type = st.segmented_control(
        "View by:",
        ["Market Value", "Gross Contribution"],
        default="Market Value",
        key="composition_filter"
    )
    if comp_type is None:
        comp_type = "Market Value"

    first_tx_date = pd.to_datetime(transactions["Date"], errors="coerce").min()
    hist_filtered = hist_asc[hist_asc["date"] >= first_tx_date].copy().reset_index(drop=True)

    if len(hist_filtered) == 0:
        st.info("No historical data available after your first transaction date.")
        return

    comp_df = hist_filtered[["date"]].copy()

    if comp_type == "Market Value":
        # Calcola quantità corrente (non t-1) per ciascun fondo
        tx_sorted = transactions.copy()
        tx_sorted["Date"] = pd.to_datetime(tx_sorted["Date"], errors="coerce")
        tx_sorted = tx_sorted.dropna(subset=["Date"]).sort_values("Date")

        qty_current_df = pd.DataFrame({"date": hist_filtered["date"]})
        for fund in filter_funds:
            fund_tx = tx_sorted[tx_sorted["Fund"] == fund][["Date", "Quantity"]].copy()
            if len(fund_tx) == 0:
                qty_current_df[fund] = 0.0
                continue
            fund_tx["cum_qty"] = fund_tx["Quantity"].cumsum()
            merged = pd.merge_asof(
                hist_filtered[["date"]],
                fund_tx[["Date", "cum_qty"]].sort_values("Date"),
                left_on="date", right_on="Date", direction="backward",
            )
            qty_current_df[fund] = merged["cum_qty"].fillna(0.0).values

        for fund in filter_funds:
            price = pd.to_numeric(hist_filtered[fund], errors="coerce").reset_index(drop=True)
            qty = qty_current_df[fund].reset_index(drop=True)
            comp_df[fund] = (qty * price).fillna(0.0)
    else:
        # Gross Contribution cumulata per fund
        tx_sorted = transactions.copy()
        tx_sorted["Date"] = pd.to_datetime(tx_sorted["Date"], errors="coerce")
        tx_sorted = tx_sorted.dropna(subset=["Date"]).sort_values("Date")
        tx_sorted["Gross Contribution"] = tx_sorted["Quantity"] * tx_sorted["Price (€)"] + tx_sorted["Fees (€)"]

        for fund in filter_funds:
            fund_tx = tx_sorted[tx_sorted["Fund"] == fund][["Date", "Gross Contribution"]].copy()
            if len(fund_tx) == 0:
                comp_df[fund] = 0.0
                continue
            fund_tx["cum_contrib"] = fund_tx["Gross Contribution"].cumsum()
            merged = pd.merge_asof(
                comp_df[["date"]],
                fund_tx[["Date", "cum_contrib"]].sort_values("Date"),
                left_on="date", right_on="Date", direction="backward",
            )
            comp_df[fund] = merged["cum_contrib"].fillna(0.0).values

    # Crea stacked area chart con valori assoluti e groupnorm="percent"
    fig = go.Figure()

    for fund in filter_funds:
        color = FUND_COLORS.get(fund, "#999999")
        r, g, b = hex_to_rgb(color)
        fig.add_trace(go.Scatter(
            x=comp_df["date"], y=comp_df[fund],
            mode="lines", name=fund,
            line=dict(color=color, width=0.5),
            hovertemplate=f"<b>{fund}</b>: %{{y:.2f}}%<extra></extra>",
            stackgroup="one",
            groupnorm="percent",
            fillcolor=f"rgba({r}, {g}, {b}, 0.7)",
        ))

    fig.update_layout(
        height=500, hovermode="x unified", xaxis_title="Date", yaxis_title="Composition (%)",
        template="plotly_white", showlegend=True,
        legend=dict(orientation="v", yanchor="top", y=0.99, xanchor="left", x=0.01),
        dragmode="pan", uirevision="portfolio_composition",
        yaxis=dict(range=[0, 100], ticksuffix="%"),
    )
    apply_standard_xaxis(fig, RANGE_SELECTOR_BUTTONS_SHORT)
    st.plotly_chart(fig, use_container_width=True, config=get_plotly_config("portfolio_composition"))
