"""
pages/evolution_of_portfolio.py — Pagina "Evolution of Portfolio".

Mostra l'evoluzione dettagliata del portafoglio:
- Tabella P/L Evolution con NAV giornaliero e variazione % per fondo
- Grafico Daily NAV Evolution
- Tabella Market Value Evolution con variazione € giornaliera per fondo
- Grafico Holdings Market Value (area chart impilato)
"""

import streamlit as st
from utils.privacy import privacy_on, mask_text, render_page_header
import pandas as pd
import plotly.graph_objects as go

from config import FUND_COLORS
from components.fund_filter import render_fund_filter
from utils.formatting import f_eur, f_date, style_cols
from components.styling import (
    hex_to_rgb,
    daily_change_style,
    fund_header_css,
    DAILY_WINDOW_OPTIONS,
    DAILY_WINDOW_DAYS,
)
from components.chart_helpers import (
    apply_standard_xaxis,
    get_plotly_config,
    RANGE_SELECTOR_BUTTONS_SHORT,
)


# Layout comune per i grafici a mezza larghezza: stessa altezza per allineare
# le righe della griglia, legenda orizzontale sotto il range slider (in alto
# si sovrapporrebbe ai bottoni del range selector su colonne strette).
HALF_CHART_HEIGHT = 520
HALF_LEGEND = dict(orientation="h", yanchor="top", y=-0.32, xanchor="left", x=0,
                   font=dict(size=11))
HALF_MARGIN = dict(l=10, r=10, t=40, b=10)


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
    render_page_header("📊 Evolution of Portfolio")

    if len(transactions) == 0:
        st.info("No data available. Please add transactions.")
        return

    hist_data = hist_data_global
    if len(hist_data) == 0 or "date" not in hist_data.columns:
        st.info("No historical data available for evolution calculations.")
        return

    # Filtro fondi esplicito anche in questa sezione
    available_funds = [f for f in funds.get("Fund", pd.Series(dtype=str)).tolist() if f in hist_data.columns]
    if not available_funds:
        available_funds = [c for c in hist_data.columns if c != "date"]

    filter_funds = render_fund_filter(available_funds, FUND_COLORS, key_suffix="_evolution")
    filter_funds = [f for f in filter_funds if f in hist_data.columns]

    if len(filter_funds) == 0:
        st.info("Select at least one fund to view Evolution charts.")
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

    # ===== 2-4. GRAFICI SECONDARI: griglia a 2 colonne =====
    # Solo "Absolute and % Change by Fund" resta a tutta larghezza; gli altri
    # grafici occupano metà riga ciascuno.
    row1_l, row1_r = st.columns(2, gap="medium")
    with row1_l:
        _render_funds_nav_chart(hist_asc, filter_funds, first_tx_date_by_fund)
    with row1_r:
        _render_portfolio_market_value(hist_asc, filter_funds, qty_prev_df, transactions)

    row2_l, _row2_r = st.columns(2, gap="medium")
    with row2_l:
        _render_portfolio_composition(hist_asc, filter_funds, qty_prev_df, transactions, first_tx_date_by_fund)

    st.divider()

    # ===== 5. TABELLA MARKET VALUE EVOLUTION (in fondo, tutta larghezza) =====
    _render_market_value_table(hist_asc, filter_funds, qty_prev_df, tx_sorted)


# =============================================================================
# SOTTO-FUNZIONI (private)
# =============================================================================

def _render_revenue_pnl_bar(hist_asc, filter_funds, transactions):
    """Stacked bar chart: solo ritorno da movimento NAV (esclusi versamenti)."""
    st.subheader("📈 Absolute and % Change by Fund")
    st.caption("Shows NAV-only change (excludes new contributions) as absolute €, per-fund %, or total portfolio %")

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
        _display_options = (
            ["Funds (%)", "Portfolio (%)"] if privacy_on()
            else ["Absolute (€)", "Funds (%)", "Portfolio (%)"]
        )
        _display_default = "Funds (%)" if privacy_on() else "Absolute (€)"
        display_mode = st.segmented_control(
            "Display",
            _display_options,
            default=_display_default,
            key="revenue_pnl_display_mode",
        )
    if freq_label is None:
        freq_label = "1D"
    if display_mode is None or (privacy_on() and display_mode == "Absolute (€)"):
        display_mode = _display_default
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

    total_abs = nav_abs_resampled[filter_funds].sum(axis=1)
    total_prev_mv = mv_resampled_last[filter_funds].sum(axis=1).shift(1)

    if display_mode == "Funds (%)":
        prev_mv = mv_resampled_last[filter_funds].shift(1)
        nav_pct_resampled = nav_abs_resampled[filter_funds].div(prev_mv.where(prev_mv != 0)).mul(100)
        nav_pct_resampled["Total"] = total_abs.div(total_prev_mv.where(total_prev_mv != 0)).mul(100)

        chart_df = nav_pct_resampled.reset_index()
        yaxis_title = f"{freq_label} Change (%)"
        hover_fmt = "%{y:,.2f}%"
        total_fmt = lambda v: "-" if pd.isna(v) else f"{v:,.2f}%"
        portfolio_only_mode = False
    elif display_mode == "Portfolio (%)":
        portfolio_pct = total_abs.div(total_prev_mv.where(total_prev_mv != 0)).mul(100)
        chart_df = pd.DataFrame({
            "date": portfolio_pct.index,
            "Portfolio": portfolio_pct.values,
        }).reset_index(drop=True)
        yaxis_title = f"{freq_label} Portfolio Change (%)"
        portfolio_only_mode = True
    else:
        nav_abs_resampled["Total"] = nav_abs_resampled[filter_funds].sum(axis=1)
        chart_df = nav_abs_resampled.reset_index()
        yaxis_title = f"{freq_label} Change (€)"
        hover_fmt = "€%{y:,.2f}"
        total_fmt = lambda v: f"€{v:,.2f}"
        portfolio_only_mode = False

    # Crea stacked bar chart
    fig = go.Figure()
    if portfolio_only_mode:
        portfolio_colors = [
            "#2fbf71" if pd.notna(v) and v > 0 else "#e15252" if pd.notna(v) and v < 0 else "#8f9bb3"
            for v in chart_df["Portfolio"]
        ]
        fig.add_trace(go.Bar(
            x=chart_df["date"],
            y=chart_df["Portfolio"],
            name="Portfolio",
            marker=dict(color=portfolio_colors),
            hovertemplate=("<b>Portfolio</b><extra></extra>" if privacy_on()
                           else "<b>Portfolio</b>: %{y:,.2f}%<extra></extra>"),
        ))
    else:
        for fund in filter_funds:
            color = FUND_COLORS.get(fund, "#999999")
            fig.add_trace(go.Bar(
                x=chart_df["date"], y=chart_df[fund],
                name=fund, marker=dict(color=color),
                hovertemplate=(f"<b>{fund}</b><extra></extra>" if privacy_on()
                               else f"<b>{fund}</b>: {hover_fmt}<extra></extra>"),
            ))

        # Traccia invisibile per totale nel tooltip
        fig.add_trace(go.Scatter(
            x=chart_df["date"], y=[0] * len(chart_df),
            mode="lines", line=dict(width=0), showlegend=False,
            hovertemplate=("<b>Total</b><extra></extra>" if privacy_on()
                           else "<b>Total</b>: " + chart_df["Total"].apply(total_fmt) + "<extra></extra>"),
        ))

    fig.update_layout(
        barmode="group" if portfolio_only_mode else "relative",
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
    if portfolio_only_mode:
        fig.update_yaxes(tickformat=".1f")
    if privacy_on():
        fig.update_yaxes(showticklabels=False)
    st.plotly_chart(fig, use_container_width=True, config=get_plotly_config("absolute_pct_change_by_fund"))


def _render_funds_nav_chart(hist_asc, filter_funds, first_tx_date_by_fund):
    """Grafico lineare NAV per fondo."""
    st.subheader("📊 Funds NAV Evolution Chart")
    st.caption("Daily NAV of each fund, starting from your first purchase of that fund")
    fig = go.Figure()
    pnl_asc = hist_asc.sort_values("date", ascending=True).reset_index(drop=True)

    for fund in filter_funds:
        first_date = first_tx_date_by_fund.get(fund)
        fund_data = pnl_asc[pnl_asc["date"] >= pd.to_datetime(first_date)] if first_date else pnl_asc
        fig.add_trace(go.Scatter(
            x=fund_data["date"], y=fund_data[fund],
            mode="lines", name=fund,
            line=dict(color=FUND_COLORS.get(fund, "#999999"), width=2),
            hovertemplate=(f"<b>{fund}</b><extra></extra>" if privacy_on()
                           else f"<b>{fund}</b>: €%{{y:,.2f}}<extra></extra>"),
        ))

    fig.update_layout(
        height=HALF_CHART_HEIGHT, hovermode="x unified", xaxis_title="", yaxis_title="NAV (€)",
        template="plotly_white", showlegend=True, legend=HALF_LEGEND,
        dragmode="pan", margin=HALF_MARGIN,
    )
    apply_standard_xaxis(fig, RANGE_SELECTOR_BUTTONS_SHORT)
    if privacy_on():
        fig.update_yaxes(showticklabels=False)
    st.plotly_chart(fig, use_container_width=True)


def compute_daily_holdings_delta(hist_asc, filter_funds, qty_prev_df):
    """Variazione giornaliera € del controvalore, SOLO effetto prezzo (NAV).

    Per ogni fondo:  Δ_t = qty_{t-1} × (NAV_t − NAV_{t-1})
    dove qty_{t-1} è la quantità detenuta a fine giornata precedente: le quote
    comprate il giorno t (al NAV del giorno t) non maturano variazione in t.
    NAV_{t-1} è l'ultimo NAV valido precedente (robusto a buchi nei dati).

    Il totale è la SOMMA dei Δ per fondo, quindi esclude i nuovi versamenti.
    (Il vecchio totale era MV_t − MV_{t-1} e includeva gli acquisti: da qui
    i giorni con tutti i fondi in rosso e totale in verde.)

    Returns:
        DataFrame con colonna "date", una colonna per fondo e "Total".
    """
    out = hist_asc[["date"]].copy().reset_index(drop=True)
    for fund in filter_funds:
        price = pd.to_numeric(hist_asc[fund], errors="coerce").reset_index(drop=True)
        prev_price = price.ffill().shift(1)
        qty = qty_prev_df[fund].reset_index(drop=True)
        delta = qty * (price - prev_price)
        # Nessuna quota detenuta => nessuna variazione (anche se il NAV manca)
        delta = delta.where(qty != 0, 0.0)
        out[fund] = delta
    out["Total"] = out[filter_funds].sum(axis=1, min_count=1)
    return out


def _render_market_value_table(hist_asc, filter_funds, qty_prev_df, tx_sorted):
    """Tabella Δ € giornaliera per fondo + totale, stile tabella Historical Data."""
    st.subheader("📈 Portfolio Market Value Evolution - Daily Holdings Value")
    if privacy_on():
        st.info("🙈 Tabella nascosta in privacy mode (contiene solo valori in €).")
        return
    st.caption(
        "Daily € change of your holdings from NAV movement only "
        "(quantity held at the previous close × NAV change). New contributions "
        "are excluded, so the Total is the sum of the fund columns."
    )

    delta_df = compute_daily_holdings_delta(hist_asc, filter_funds, qty_prev_df)

    # Parti dal primo giorno in cui c'è qualcosa in portafoglio
    held = (qty_prev_df[filter_funds].reset_index(drop=True) != 0).any(axis=1)
    if not held.any():
        st.info("No holdings for the selected funds yet.")
        return
    delta_df = delta_df[held.values].copy()

    delta_df = delta_df.sort_values("date", ascending=False).reset_index(drop=True)
    total_rows = len(delta_df)
    choice = st.radio(
        "Range", DAILY_WINDOW_OPTIONS, index=0, horizontal=True,
        key="mv_table_range",
        help="Time window of rows to display (styled per-cell, so shorter is faster).",
    )
    days = DAILY_WINDOW_DAYS[choice]
    n_rows = total_rows if days is None else min(days, total_rows)
    delta_df = delta_df.head(n_rows).reset_index(drop=True)
    st.caption(f"Showing {n_rows} of {total_rows} rows (most recent first).")

    st.markdown(fund_header_css(filter_funds, FUND_COLORS), unsafe_allow_html=True)

    # Date transazioni per fondo (evidenziate come in Historical Data)
    date_str = delta_df["date"].dt.strftime("%Y-%m-%d")
    tx_dates_by_fund = {
        f: set(tx_sorted.loc[tx_sorted["Fund"] == f, "Date"].dt.strftime("%Y-%m-%d"))
        for f in filter_funds
    }
    tx_any = set().union(*tx_dates_by_fund.values()) if tx_dates_by_fund else set()

    # Valori numerici + testo da Styler.format => ordinamento per valore reale
    total_col = "Daily Total Δ (€)"
    display = pd.DataFrame({"Date": delta_df["date"].dt.normalize()})
    for fund in filter_funds:
        display[fund] = delta_df[fund].values
    display[total_col] = delta_df["Total"].values

    def _direction(v):
        if pd.isna(v) or abs(v) < 0.005:
            return 0
        return 1 if v > 0 else -1

    dates_list = date_str.tolist()

    def _style_col(column):
        name = column.name
        if name == total_col:
            raw, txs = delta_df["Total"], tx_any
        else:
            raw, txs = delta_df[name], tx_dates_by_fund.get(name, set())
        out = []
        for i in range(len(display)):
            css = daily_change_style(_direction(raw.iloc[i]), dates_list[i] in txs)
            if name == total_col:
                css += "font-weight: 600;"
            out.append(css)
        return out

    styler = display.style.apply(_style_col, subset=filter_funds + [total_col], axis=0)
    styler = styler.format(f_eur(signed=True), subset=filter_funds + [total_col], na_rep="")
    styler = style_cols(styler, {"Date": f_date("%Y-%m-%d")})
    st.dataframe(styler, width="stretch", hide_index=True)


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
        hovertemplate=("<b>Portfolio MV</b><extra></extra>" if privacy_on()
                       else "<b>Portfolio MV</b>: €%{y:,.2f}<extra></extra>"),
    ))

    # Annotazione ultimo valore totale
    last_mv = mv_df["Daily MV (€)"].iloc[-1]
    fig.add_annotation(
        x=latest_date, y=last_mv, text=mask_text(f"€{last_mv:,.0f}"),
        showarrow=False, xanchor="left", xshift=10,
        font=dict(size=14, color="#667eea"),
        bordercolor="#667eea", borderwidth=2, borderpad=4,
        bgcolor="rgba(255,255,255,0)",
    )

    # Linee per singolo fondo (le etichette finali si disegnano dopo, quando
    # il range Y è noto, per poterle distanziare senza sovrapposizioni)
    fund_labels = []
    for fund in filter_funds:
        col = f"{fund} MV (€)"
        if col in mv_df.columns:
            color = FUND_COLORS.get(fund, "#999999")
            fig.add_trace(go.Scatter(
                x=mv_df["date"], y=mv_df[col],
                mode="lines", name=fund,
                line=dict(color=color, width=2, dash="dot"),
                hovertemplate=(f"<b>{fund}</b><extra></extra>" if privacy_on()
                               else f"<b>{fund}</b>: €%{{y:,.2f}}<extra></extra>"),
            ))
            fund_labels.append((fund, color, float(mv_df[col].iloc[-1])))

    # Range Y con padding
    all_vals = [mv_df["Daily MV (€)"].min(), mv_df["Daily MV (€)"].max()]
    for fund in filter_funds:
        col = f"{fund} MV (€)"
        if col in mv_df.columns:
            all_vals.extend([mv_df[col].min(), mv_df[col].max()])
    max_mv = max(all_vals) if all_vals else 1000
    min_mv = min(all_vals) if all_vals else 0
    padding = (max_mv - min_mv) * 0.05
    _add_spread_end_labels(fig, latest_date, fund_labels, last_mv,
                           y_range=(min_mv - padding, max_mv + padding))

    fig.update_layout(
        height=HALF_CHART_HEIGHT, hovermode="x unified", xaxis_title="", yaxis_title="Market Value (€)",
        template="plotly_white", showlegend=True, legend=HALF_LEGEND,
        dragmode="pan", uirevision="portfolio_mv_evolution",
        newshape=dict(line_color="#888888"), margin={**HALF_MARGIN, "r": 95},
        yaxis=dict(range=[min_mv - padding, max_mv + padding]),
    )
    apply_standard_xaxis(fig, RANGE_SELECTOR_BUTTONS_SHORT)
    fig.update_yaxes(
        rangemode="normal", fixedrange=False, showspikes=True, spikemode="across",
        zeroline=True, zerolinecolor="rgba(150,150,150,0.5)", zerolinewidth=2,
    )
    if privacy_on():
        fig.update_yaxes(showticklabels=False, title_text="Market Value (€, nascosto)")
    st.plotly_chart(fig, use_container_width=True, config=get_plotly_config("portfolio_mv_evolution"))


def _add_spread_end_labels(fig, x, labels, total_value, y_range,
                           min_gap_px=20, plot_px=None):
    """Etichette "ultimo valore" per fondo, distanziate verticalmente.

    Con la griglia a mezza altezza i valori finali dei fondi sono vicini e i
    riquadri si sovrapponevano. Le etichette vengono ordinate per valore e
    spinte a una distanza minima (in pixel, convertita in unità dati); una
    linea sottile collega ogni etichetta al punto reale.
    """
    if not labels:
        return
    lo, hi = y_range
    span = (hi - lo) or 1.0
    if plot_px is None:
        # altezza utile ≈ figura − margini − range slider/legenda
        plot_px = HALF_CHART_HEIGHT * 0.58
    gap = min_gap_px * span / plot_px
    # L'etichetta del totale è un ostacolo fisso: nessuna etichetta fondo
    # deve finirle addosso.
    items = sorted(labels, key=lambda t: t[2])
    placed = []
    prev = None
    for fund, color, val in items:
        y = val if prev is None else max(val, prev + gap)
        if abs(y - total_value) < gap:
            y = total_value - gap if y < total_value else total_value + gap
        placed.append((fund, color, val, y))
        prev = y
    # Se si esce dal range in alto, trasla tutto verso il basso
    overflow = placed[-1][3] - (hi - gap / 2) if placed else 0
    if overflow > 0:
        placed = [(f, c, v, y - overflow) for f, c, v, y in placed]
    for fund, color, val, y in placed:
        ay_px = -(y - val) * plot_px / span   # offset testo in pixel (su = negativo)
        fig.add_annotation(
            x=x, y=val, text=mask_text(f"€{val:,.0f}"),
            showarrow=True, arrowhead=0, arrowwidth=1, arrowcolor=color,
            ax=24, ay=ay_px, axref="pixel", ayref="pixel",
            xanchor="left", font=dict(size=12, color=color),
            bordercolor=color, borderwidth=1.5, borderpad=3,
            bgcolor="rgba(13,17,23,0.85)",
        )


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
            hovertemplate=(f"<b>{fund}</b><extra></extra>" if privacy_on()
                           else f"<b>{fund}</b>: %{{y:.2f}}%<extra></extra>"),
            stackgroup="one",
            groupnorm="percent",
            fillcolor=f"rgba({r}, {g}, {b}, 0.7)",
        ))

    fig.update_layout(
        height=HALF_CHART_HEIGHT, hovermode="x unified", xaxis_title="", yaxis_title="Composition (%)",
        template="plotly_white", showlegend=True, legend=HALF_LEGEND, margin=HALF_MARGIN,
        dragmode="pan", uirevision="portfolio_composition",
        yaxis=dict(range=[0, 100], ticksuffix="%"),
    )
    apply_standard_xaxis(fig, RANGE_SELECTOR_BUTTONS_SHORT)
    if privacy_on():
        fig.update_yaxes(showticklabels=False)
    st.plotly_chart(fig, use_container_width=True, config=get_plotly_config("portfolio_composition"))