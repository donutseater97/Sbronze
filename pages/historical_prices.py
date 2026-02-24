"""
pages/historical_prices.py — Pagina "Historical Data Charts".

Mostra i grafici storici dei prezzi NAV per ciascun fondo con:
- Vista combinata (tutti i fondi su un unico grafico)
- Vista griglia (un grafico per fondo, 3 per riga)
- Marker delle transazioni sui grafici
- Linea media NAV
- Tabella dati storici con colorazione verde/rosso
"""

import os
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import date, datetime

from config import FUND_COLORS, FUNDS_FILE, HISTORICAL_FILE, load_historical_prices
from components.fund_filter import render_fund_filter
from components.styling import hex_to_rgb
from components.chart_helpers import (
    apply_standard_xaxis,
    get_plotly_config,
    add_price_annotation,
    calculate_y_range_with_padding,
    RANGE_SELECTOR_BUTTONS,
)


def historical_prices(
    funds: pd.DataFrame,
    transactions: pd.DataFrame,
    hist_data_global: pd.DataFrame,
    yahoo_tickers: list[str],
):
    """Renderizza la pagina Historical Data Charts.

    Args:
        funds:            DataFrame dei fondi.
        transactions:     DataFrame delle transazioni.
        hist_data_global: DataFrame prezzi storici.
        yahoo_tickers:    Lista ticker Yahoo Finance (non usata direttamente, per debug).
    """
    st.header("📈 Historical Data Charts")

    # ----- Bottone ricarica dati da disco -----
    if "force_refresh" not in st.session_state:
        st.session_state.force_refresh = False

    if st.button("🔄 Reload Cached Data", help="Reload historical_data.csv from disk"):
        st.session_state.force_refresh = True
        st.cache_data.clear()
        st.rerun()

    if st.session_state.force_refresh:
        st.info("🔄 Reloading cached CSV...")
        st.session_state.force_refresh = False

    with st.spinner("Loading historical price data..."):
        hist_df = load_historical_prices(funds)

    # ----- Nessun dato -----
    if len(hist_df) == 0:
        st.error("⚠️ No historical data available.")
        if "last_fetch_error" in st.session_state:
            st.warning(f"**Last fetch status:** {st.session_state.last_fetch_error}")
        st.info(
            "**Possible reasons:**\n"
            "- Yahoo Finance is blocking requests (rate limiting)\n"
            "- Tickers in funds.csv are incorrect or delisted\n"
            "- Network connectivity issues"
        )
        with st.expander("🔍 Show configured tickers"):
            st.code(f"Tickers: {', '.join(yahoo_tickers)}")
        return

    # ----- Dati caricati con successo -----
    st.success(f"✅ Loaded {len(hist_df)} price records for {len(hist_df.columns)-1} funds")

    # Banner "last updated"
    try:
        max_date = pd.to_datetime(hist_df.get("date"), errors="coerce").max()
        file_ts = None
        if os.path.exists(HISTORICAL_FILE):
            ts = os.path.getmtime(HISTORICAL_FILE)
            file_ts = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d %H:%M UTC")
        parts = []
        if pd.notna(max_date):
            parts.append(f"Last data date: {max_date.strftime('%Y-%m-%d')}")
        if file_ts:
            parts.append(f"File updated: {file_ts}")
        if parts:
            st.caption(" • ".join(parts) + " • Source: cached CSV (GitHub Actions)")
    except Exception:
        pass

    # Colonne fund valide
    funds_fresh = pd.read_csv(FUNDS_FILE) if os.path.exists(FUNDS_FILE) else funds
    fund_cols = [c for c in hist_df.columns if c in funds_fresh["Fund"].tolist()]
    hist_df_display = hist_df[["date"] + fund_cols].copy()
    hist_df_display["date"] = pd.to_datetime(hist_df_display["date"])

    # ----- Filtro fondi -----
    if "hist_view_mode" not in st.session_state:
        st.session_state.hist_view_mode = "grid"

    selected_funds = render_fund_filter(fund_cols, FUND_COLORS)

    # ----- Limiti date dal dataset -----
    min_d = hist_df_display["date"].min().date()
    max_d = hist_df_display["date"].max().date()

    default_start = date(2024, 10, 1)
    if min_d > default_start:
        default_start = min_d

    # ----- Filtro date + toggle vista -----
    col1, col2, col3 = st.columns([2, 2, 1.5])
    with col1:
        start_d = st.date_input("Start", value=default_start, min_value=min_d, key="hist_start_date")
    with col2:
        end_d = st.date_input("End", value=max_d, min_value=min_d, key="hist_end_date")
    with col3:
        st.markdown("")
        view_label = "Combined View" if st.session_state.hist_view_mode == "combined" else "Grid View"
        use_combined = st.toggle(view_label, value=(st.session_state.hist_view_mode == "combined"), key="hist_view_toggle")
        st.session_state.hist_view_mode = "combined" if use_combined else "grid"

    plot_df = hist_df_display[
        (hist_df_display["date"] >= pd.to_datetime(start_d))
        & (hist_df_display["date"] <= pd.to_datetime(end_d))
    ]

    if not selected_funds:
        st.info("Select at least one fund")
        return

    # ----- Average NAV per fondo (dal range selezionato) -----
    avg_nav_by_fund = {}
    tx_range = transactions.copy()
    tx_range["Date"] = pd.to_datetime(tx_range.get("Date"), errors="coerce")
    tx_range = tx_range.dropna(subset=["Date"])
    tx_range = tx_range[
        (tx_range["Date"] >= pd.to_datetime(start_d))
        & (tx_range["Date"] <= pd.to_datetime(end_d))
    ]
    if len(tx_range) > 0:
        tx_range["Gross Contribution"] = tx_range["Quantity"] * tx_range["Price (€)"] + tx_range["Fees (€)"]
        grouped = tx_range.groupby("Fund").agg({"Gross Contribution": "sum", "Quantity": "sum"})
        for fund, row in grouped.iterrows():
            if row["Quantity"] and row["Quantity"] != 0:
                avg_nav_by_fund[fund] = row["Gross Contribution"] / row["Quantity"]

    # ===== RENDERING GRAFICO =====
    if st.session_state.hist_view_mode == "combined":
        _render_combined_view(plot_df, selected_funds, avg_nav_by_fund, transactions, start_d, end_d)
    else:
        _render_grid_view(plot_df, selected_funds, avg_nav_by_fund, transactions, start_d, end_d)

    # ===== LEGENDA =====
    _render_unified_legend(selected_funds)

    # ===== TABELLA DATI STORICI =====
    _render_historical_table(hist_df_display, selected_funds, transactions)


# =============================================================================
# SOTTO-FUNZIONI (private)
# =============================================================================

def _render_combined_view(plot_df, selected_funds, avg_nav_by_fund, transactions, start_d, end_d):
    """Vista combinata: pannello % return normalizzato in alto + grafici NAV individuali sotto.

    Layout a subplots con x-axis condiviso (zoom/pan temporale sincronizzato).
    Ogni grafico ha il proprio y-axis (pan verticale indipendente).

    Il primo pannello (più grande) mostra il rendimento percentuale di tutti i fondi
    normalizzato a 0% dalla prima data visibile. I pannelli sottostanti mostrano
    il NAV di ciascun fondo con linea media NAV e marker transazioni.
    """
    n_funds = len(selected_funds)
    n_rows = 1 + n_funds  # riga 1 = % return, righe 2..N+1 = singoli fondi

    # Altezze relative: primo pannello leggermente più grande dei singoli
    row_heights = [1.3] + [1.0] * n_funds

    # Titoli dei subplot (primo = % Return, poi nome fondo)
    subplot_titles = ["% Return (Normalized)"] + selected_funds

    fig = make_subplots(
        rows=n_rows,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.015,
        row_heights=row_heights,
        subplot_titles=subplot_titles,
    )

    # ------------------------------------------------------------------
    # RIGA 1 — Rendimento % normalizzato (base = 0% alla data iniziale)
    # ------------------------------------------------------------------
    for fund in selected_funds:
        fund_df = plot_df[["date", fund]].dropna().sort_values("date")
        if len(fund_df) == 0:
            continue

        start_val = fund_df[fund].iloc[0]
        if start_val != 0:
            pct_return = (fund_df[fund] / start_val - 1) * 100
        else:
            pct_return = fund_df[fund] * 0

        color = FUND_COLORS.get(fund, "#999999")

        fig.add_trace(
            go.Scatter(
                x=fund_df["date"],
                y=pct_return,
                mode="lines",
                name=fund,
                line=dict(color=color, width=2),
                hovertemplate=f"<b>{fund}</b><br>%{{x|%Y-%m-%d}}<br>%{{y:+.2f}}%<extra></extra>",
                showlegend=False,
            ),
            row=1,
            col=1,
        )

        # Annotazione laterale con ultimo % return (dentro il grafico, a destra)
        last_pct = pct_return.iloc[-1]
        fig.add_annotation(
            x=fund_df["date"].iloc[-1],
            y=last_pct,
            text=f"{last_pct:+.2f}%",
            showarrow=False,
            xanchor="right",
            xshift=-6,
            font=dict(size=11, color=color),
            bordercolor=color,
            borderwidth=1.5,
            borderpad=3,
            bgcolor="rgba(30,30,30,0.7)",
            xref="x",
            yref="y",
        )

    # Linea orizzontale 0% di riferimento
    fig.add_hline(
        y=0,
        line=dict(color="rgba(150,150,150,0.4)", width=1, dash="dot"),
        row=1,
        col=1,
    )

    # ------------------------------------------------------------------
    # RIGHE 2..N+1 — Grafici NAV individuali (prezzo + avg NAV + transazioni)
    # ------------------------------------------------------------------
    # Prepara transazioni nel range di date selezionato
    trans_df = transactions.copy()
    trans_df["Date"] = pd.to_datetime(trans_df["Date"], errors="coerce")
    trans_df = trans_df.dropna(subset=["Date"])
    trans_df = trans_df[
        (trans_df["Date"] >= pd.to_datetime(start_d))
        & (trans_df["Date"] <= pd.to_datetime(end_d))
    ]

    for i, fund in enumerate(selected_funds):
        row = i + 2  # riga 1 = % return → i fondi partono da riga 2
        fund_df = plot_df[["date", fund]].dropna().sort_values("date")
        if len(fund_df) == 0:
            continue

        color = FUND_COLORS.get(fund, "#999999")

        # --- Linea prezzo NAV ---
        fig.add_trace(
            go.Scatter(
                x=fund_df["date"],
                y=fund_df[fund],
                mode="lines",
                name=fund,
                line=dict(color=color, width=2),
                hovertemplate=f"<b>{fund}</b><br>%{{x|%Y-%m-%d}}<br>€%{{y:,.2f}}<extra></extra>",
                showlegend=False,
            ),
            row=row,
            col=1,
        )

        # --- Linea media NAV (tratteggiata) ---
        if fund in avg_nav_by_fund:
            fig.add_trace(
                go.Scatter(
                    x=[fund_df["date"].min(), fund_df["date"].max()],
                    y=[avg_nav_by_fund[fund], avg_nav_by_fund[fund]],
                    mode="lines",
                    name=f"{fund} Avg NAV",
                    line=dict(color=color, dash="dash", width=1.5),
                    hovertemplate=f"<b>{fund} Avg NAV</b><br>€%{{y:,.2f}}<extra></extra>",
                    showlegend=False,
                ),
                row=row,
                col=1,
            )

        # --- Marker transazioni ---
        fund_trans = trans_df[trans_df["Fund"] == fund]
        if len(fund_trans) > 0:
            trans_prices, trans_dates, hover_texts = [], [], []
            for _, t_row in fund_trans.iterrows():
                t_date = t_row["Date"]
                closest_idx = (fund_df["date"] - t_date).abs().idxmin()
                trans_prices.append(fund_df.loc[closest_idx, fund])
                trans_dates.append(t_date)
                hover_texts.append(
                    f"<b>Transaction</b><br>"
                    f"Date: {t_date.strftime('%Y-%m-%d')}<br>"
                    f"Qty: {t_row['Quantity']:.3f}<br>"
                    f"Price: €{t_row['Price (€)']:.2f}<br>"
                    f"Fees: €{t_row['Fees (€)']:.2f}<br>"
                    f"Total: €{(t_row['Quantity'] * t_row['Price (€)'] + t_row['Fees (€)']):.2f}"
                )
            fig.add_trace(
                go.Scatter(
                    x=trans_dates,
                    y=trans_prices,
                    mode="markers",
                    name=f"{fund} Transactions",
                    marker=dict(
                        size=9,
                        color=color,
                        symbol="circle",
                        line=dict(width=2, color="white"),
                    ),
                    hovertemplate="%{text}<extra></extra>",
                    text=hover_texts,
                    showlegend=False,
                ),
                row=row,
                col=1,
            )

        # --- Annotazione prezzo (dentro il grafico, a destra) ---
        latest_price = fund_df[fund].iloc[-1]
        # Riferimenti assi per subplot: riga 1 → x/y, riga 2 → x2/y2, ...
        xref = "x" if row == 1 else f"x{row}"
        yref = "y" if row == 1 else f"y{row}"
        fig.add_annotation(
            x=fund_df["date"].iloc[-1],
            y=latest_price,
            text=f"€{latest_price:,.2f}",
            showarrow=False,
            xanchor="right",
            xshift=-6,
            font=dict(size=11, color=color),
            bordercolor=color,
            borderwidth=1.5,
            borderpad=3,
            bgcolor="rgba(30,30,30,0.7)",
            xref=xref,
            yref=yref,
        )

    # ------------------------------------------------------------------
    # LAYOUT
    # ------------------------------------------------------------------
    # Altezza compatta: tutti i pannelli devono stare in una sola pagina
    total_height = 180 + 105 * n_funds
    fig.update_layout(
        height=total_height,
        hovermode="x unified",
        template="plotly_white",
        showlegend=False,
        dragmode="pan",
        uirevision="hist_combined_stacked",
        newshape=dict(line_color="#888888"),
        margin=dict(r=20, t=30, b=10, l=50),
    )

    # Asse Y primo pannello (senza titolo)
    fig.update_yaxes(
        title_text="",
        row=1,
        col=1,
        fixedrange=False,
        showspikes=True,
        spikemode="across",
        automargin=True,
        zeroline=True,
        zerolinecolor="rgba(150,150,150,0.3)",
    )

    # Asse Y per i singoli fondi (senza titolo)
    for i in range(n_funds):
        fig.update_yaxes(
            title_text="",
            row=i + 2,
            col=1,
            fixedrange=False,
            showspikes=True,
            spikemode="across",
            automargin=True,
        )

    # --- Linee separatrici orizzontali tra i sotto-grafici ---
    # Calcola le posizioni Y (in coordinate paper) dei bordi inferiori di ogni subplot
    total_weight = sum(row_heights)
    cum = 0
    for r_idx in range(n_rows - 1):  # non serve dopo l'ultimo
        cum += row_heights[r_idx]
        # Posizione Y in paper coordinates (1 = top, 0 = bottom)
        y_paper = 1.0 - cum / total_weight
        fig.add_shape(
            type="line",
            xref="paper", yref="paper",
            x0=0, x1=1,
            y0=y_paper, y1=y_paper,
            line=dict(color="rgba(150,150,150,0.4)", width=1),
        )

    # Range esplicito dell'asse X per tutti i subplot (previene il bug 1970
    # causato da autorange che interpreta male annotazioni cross-subplot)
    x_min = plot_df["date"].min()
    x_max = plot_df["date"].max()

    # Rangeslider e rangeselector sull'ultimo asse X (in basso).
    # Il range del rangeslider è vincolato al filtro date della pagina
    # (start_d / end_d), esattamente come nella vista grid.
    bottom_xaxis_key = f"xaxis{n_rows}" if n_rows > 1 else "xaxis"
    fig.update_layout(**{
        bottom_xaxis_key: dict(
            range=[x_min, x_max],
            rangeslider=dict(visible=True, thickness=0.04, range=[x_min, x_max]),
            rangeselector=dict(buttons=RANGE_SELECTOR_BUTTONS),
            showspikes=True,
            spikemode="across",
            spikesnap="cursor",
            spikethickness=1,
            spikecolor="#888888",
        )
    })

    # Range esplicito anche sugli altri assi X (condivisi ma serve per autorange)
    for r in range(1, n_rows):
        xaxis_key = "xaxis" if r == 1 else f"xaxis{r}"
        fig.update_layout(**{xaxis_key: dict(range=[x_min, x_max])})

    # Stile titoli subplot (più piccoli, colore tenue)
    for ann in fig.layout.annotations:
        ann.font = dict(size=13, color="rgba(180,180,180,0.9)")
        ann.x = 0.01
        ann.xanchor = "left"

    st.plotly_chart(fig, use_container_width=True, config=get_plotly_config("historical_combined"))


def _render_grid_view(plot_df, selected_funds, avg_nav_by_fund, transactions, start_d, end_d):
    """Vista griglia: un grafico per fondo, max 3 per riga."""
    cols_per_row = 2 if len(selected_funds) > 6 else min(3, len(selected_funds))

    # Transazioni nel range selezionato (per marker)
    trans_df = transactions.copy()
    trans_df["Date"] = pd.to_datetime(trans_df["Date"], errors="coerce")
    trans_df = trans_df.dropna(subset=["Date"])
    trans_df = trans_df[
        (trans_df["Date"] >= pd.to_datetime(start_d))
        & (trans_df["Date"] <= pd.to_datetime(end_d))
    ]

    for row_start in range(0, len(selected_funds), cols_per_row):
        row_funds = selected_funds[row_start:row_start + cols_per_row]
        cols = st.columns(len(row_funds))
        for col_slot, fund in zip(cols, row_funds):
            with col_slot:
                _render_single_fund_chart(plot_df, fund, avg_nav_by_fund, trans_df)


def _render_single_fund_chart(plot_df, fund, avg_nav_by_fund, trans_df):
    """Renderizza il grafico di un singolo fondo (vista griglia)."""
    fund_df = plot_df[["date", fund]].dropna().sort_values("date")
    if len(fund_df) == 0:
        st.info(f"No data for {fund}")
        return

    latest_price = fund_df[fund].iloc[-1]
    color = FUND_COLORS.get(fund, "#999999")
    fig = go.Figure()

    # Linea prezzo
    fig.add_trace(go.Scatter(
        x=fund_df["date"], y=fund_df[fund],
        mode="lines", name=fund,
        line=dict(color=color, width=2),
        hovertemplate=f"<b>{fund}</b><br>%{{x|%Y-%m-%d}}<br>€%{{y:,.2f}}<extra></extra>",
        showlegend=False,
    ))

    # Linea media NAV
    if fund in avg_nav_by_fund:
        fig.add_trace(go.Scatter(
            x=[fund_df["date"].min(), fund_df["date"].max()],
            y=[avg_nav_by_fund[fund], avg_nav_by_fund[fund]],
            mode="lines", name=f"{fund} Avg NAV",
            line=dict(color=color, dash="dash", width=1.5),
            hovertemplate=f"<b>{fund} Avg NAV</b><br>€%{{y:,.2f}}<extra></extra>",
            showlegend=False,
        ))

    # Marker transazioni
    fund_trans = trans_df[trans_df["Fund"] == fund]
    if len(fund_trans) > 0:
        trans_prices, trans_dates, hover_texts = [], [], []
        for _, t_row in fund_trans.iterrows():
            t_date = t_row["Date"]
            closest_idx = (fund_df["date"] - t_date).abs().idxmin()
            trans_prices.append(fund_df.loc[closest_idx, fund])
            trans_dates.append(t_date)
            hover_texts.append(
                f"<b>Transaction</b><br>"
                f"Date: {t_date.strftime('%Y-%m-%d')}<br>"
                f"Quantity: {t_row['Quantity']:.3f}<br>"
                f"Price: €{t_row['Price (€)']:.2f}<br>"
                f"Fees: €{t_row['Fees (€)']:.2f}<br>"
                f"Total: €{(t_row['Quantity'] * t_row['Price (€)'] + t_row['Fees (€)']):.2f}"
            )
        fig.add_trace(go.Scatter(
            x=trans_dates, y=trans_prices, mode="markers", name=f"{fund} Transactions",
            marker=dict(size=10, color=color, symbol="circle", line=dict(width=2, color="white")),
            hovertemplate="%{text}<extra></extra>", text=hover_texts, showlegend=False,
        ))

    y_min, y_max = calculate_y_range_with_padding(fig.data)

    fig.update_layout(
        height=320, hovermode="x unified", template="plotly_white", showlegend=False,
        margin=dict(t=40, b=30, l=10, r=100), dragmode="pan",
        uirevision="hist_grid_sync", newshape=dict(line_color="#888888"),
    )
    apply_standard_xaxis(fig, RANGE_SELECTOR_BUTTONS)

    yaxis_cfg = dict(title_text="NAV (€)", rangemode="normal", fixedrange=False, showspikes=True, spikemode="across", automargin=True)
    if y_min is not None and y_max is not None:
        yaxis_cfg["range"] = [y_min, y_max]
        yaxis_cfg["autorange"] = False
        add_price_annotation(fig, fund_df["date"].iloc[-1], latest_price, f"€{latest_price:,.2f}", color)
    else:
        yaxis_cfg["autorange"] = True
    fig.update_yaxes(**yaxis_cfg)

    st.plotly_chart(fig, use_container_width=True, config=get_plotly_config(f"historical_{fund}"))


def _render_unified_legend(selected_funds):
    """Legenda unificata sotto i grafici."""
    html = "<div style='display:flex; flex-wrap:nowrap; gap:18px; align-items:center; overflow-x:auto; padding:8px 0; border-top:1px solid rgba(150,150,150,.2);'>"
    html += "<div><span style='display:inline-block;width:22px;height:0;border-top:3px solid #888;vertical-align:middle;margin-right:6px;'></span>NAV</div>"
    html += "<div><span style='display:inline-block;width:22px;height:0;border-top:3px dashed #888;vertical-align:middle;margin-right:6px;'></span>Avg NAV</div>"
    html += "<div><span style='display:inline-block;width:10px;height:10px;border-radius:50%;background:#888;margin-right:6px;border:2px solid #fff;vertical-align:middle;'></span>Transaction</div>"
    for f in selected_funds:
        color = FUND_COLORS.get(f, "#999999")
        html += f"<div><span style='display:inline-block;width:12px;height:12px;border-radius:2px;background:{color};border:1px solid rgba(0,0,0,.3);margin-right:6px;vertical-align:middle;'></span>{f}</div>"
    html += "</div>"
    st.markdown(html, unsafe_allow_html=True)


def _render_historical_table(hist_df_display, selected_funds, transactions):
    """Tabella dati storici con colorazione verde/rosso per variazione."""
    st.divider()
    st.subheader("📊 Historical Data")

    historical_data_df = hist_df_display[["date"] + selected_funds].copy() if selected_funds else pd.DataFrame()
    historical_data_df["date"] = pd.to_datetime(historical_data_df["date"])
    historical_data_df = historical_data_df.sort_values("date", ascending=False).reset_index(drop=True)

    if len(historical_data_df) == 0:
        st.info("No historical data to display")
        return

    historical_data_df["date"] = historical_data_df["date"].dt.strftime("%Y-%m-%d")

    # CSS per header colorati
    header_css = "<style>\ntable th { font-weight: 600 !important; }\n"
    header_css += "table th:first-child { background-color: rgba(100, 100, 100, 0.3) !important; }\n"
    for idx, fund in enumerate(selected_funds, start=1):
        r, g, b = hex_to_rgb(FUND_COLORS.get(fund, "#999999"))
        header_css += f"table th:nth-child({idx+1}) {{ background-color: rgba({r}, {g}, {b}, 0.3) !important; }}\n"
    header_css += "</style>\n"
    st.markdown(header_css, unsafe_allow_html=True)

    display_df = historical_data_df.copy()

    # Mappa date transazioni per evidenziazione
    tx_dates_by_fund = {}
    if len(transactions) > 0:
        tx_tmp = transactions.copy()
        tx_tmp["Date"] = pd.to_datetime(tx_tmp["Date"], errors="coerce")
        tx_tmp = tx_tmp.dropna(subset=["Date"])
        for f in selected_funds:
            tx_dates_by_fund[f] = set(tx_tmp[tx_tmp["Fund"] == f]["Date"].dt.strftime("%Y-%m-%d").tolist())

    # Formatta prezzi
    for col in selected_funds:
        display_df[col] = display_df[col].apply(lambda x: f"€{x:.2f}" if pd.notna(x) else "")

    # Stile verde/rosso per variazione giornaliera
    def _colorize(column):
        col_name = column.name
        if col_name == "date":
            return [""] * len(display_df)
        styles = []
        for i in range(len(display_df)):
            if i == len(display_df) - 1:
                styles.append("")
                continue
            cur = historical_data_df[col_name].iloc[i]
            prev = historical_data_df[col_name].iloc[i + 1]
            if pd.isna(cur) or pd.isna(prev) or cur == prev:
                styles.append("")
            elif cur > prev:
                styles.append("color: #6BCB77; font-weight: 600;")
            else:
                styles.append("color: #E26A6A; font-weight: 600;")
        return styles

    # Evidenzia giorni di transazione
    def _highlight_transactions(column):
        col_name = column.name
        if col_name == "date":
            return [""] * len(display_df)
        tx_dates = tx_dates_by_fund.get(col_name, set())
        return [
            "background-color: rgba(180, 180, 180, 0.15);" if d in tx_dates else ""
            for d in display_df["date"].tolist()
        ]

    styler = (
        display_df.style
        .apply(_colorize, subset=selected_funds, axis=0)
        .apply(_highlight_transactions, subset=selected_funds, axis=0)
    )

    display_df = display_df[["date"] + selected_funds]
    st.dataframe(styler, use_container_width=True)
