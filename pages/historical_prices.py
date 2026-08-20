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
from utils.privacy import privacy_on, render_page_header
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


def _get_timeframe_start_end(timeframe: str, min_d: date, max_d: date, all_start_d: date) -> tuple[date, date]:
    """Restituisce start/end in base a un timeframe predefinito."""
    max_ts = pd.to_datetime(max_d)
    min_ts = pd.to_datetime(min_d)

    if timeframe == "1M":
        start_ts = max_ts - pd.DateOffset(months=1)
    elif timeframe == "3M":
        start_ts = max_ts - pd.DateOffset(months=3)
    elif timeframe == "6M":
        start_ts = max_ts - pd.DateOffset(months=6)
    elif timeframe == "YTD":
        start_ts = pd.Timestamp(year=max_ts.year, month=1, day=1)
    elif timeframe == "1Y":
        start_ts = max_ts - pd.DateOffset(years=1)
    else:  # All
        start_ts = pd.to_datetime(all_start_d)

    start_ts = max(start_ts, min_ts)
    return start_ts.date(), max_d


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
    render_page_header("📈 Historical Data Charts")

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

    tx_dates = pd.to_datetime(transactions.get("Date"), errors="coerce") if "Date" in transactions.columns else pd.Series(dtype="datetime64[ns]")
    first_tx_date = tx_dates.dropna().min().date() if len(tx_dates.dropna()) > 0 else min_d
    default_start = max(first_tx_date, min_d)

    # ----- Filtro timeframe + date + toggle vista -----
    if "hist_timeframe_applied" not in st.session_state:
        st.session_state.hist_timeframe_applied = None

    col0, col1, col2, col3 = st.columns([2.2, 2, 2, 1.4])
    with col0:
        timeframe = st.segmented_control(
            "Time-frame",
            ["1M", "3M", "6M", "YTD", "1Y", "All"],
            default="All",
            key="hist_timeframe",
        )
        if timeframe is None:
            timeframe = "All"

        if timeframe != st.session_state.hist_timeframe_applied:
            tf_start, tf_end = _get_timeframe_start_end(timeframe, min_d, max_d, default_start)
            st.session_state.hist_start_date = tf_start
            st.session_state.hist_end_date = tf_end
            st.session_state.hist_timeframe_applied = timeframe

    with col1:
        start_d = st.date_input(
            "Start",
            value=st.session_state.get("hist_start_date", default_start),
            min_value=min_d,
            max_value=max_d,
            key="hist_start_date",
        )
    with col2:
        end_d = st.date_input(
            "End",
            value=st.session_state.get("hist_end_date", max_d),
            min_value=min_d,
            max_value=max_d,
            key="hist_end_date",
        )

    if start_d > end_d:
        start_d, end_d = end_d, start_d
        st.session_state.hist_start_date = start_d
        st.session_state.hist_end_date = end_d

    with col3:
        st.markdown("")
        view_mode = st.segmented_control(
            "View", ["Grid", "Combined"],
            default="Grid" if st.session_state.hist_view_mode == "grid" else "Combined",
            key="hist_view_segmented",
        )
        st.session_state.hist_view_mode = "combined" if view_mode == "Combined" else "grid"

    plot_df = hist_df_display[
        (hist_df_display["date"] >= pd.to_datetime(start_d))
        & (hist_df_display["date"] <= pd.to_datetime(end_d))
    ]

    if not selected_funds:
        st.info("Select at least one fund")
        return

    # ----- Average NAV per fondo (FISSO, su TUTTE le transazioni) -----
    # Bug precedente: veniva calcolato solo sulle transazioni dentro il range
    # di date selezionato, quindi la linea si spostava cambiando intervallo.
    # L'average NAV è invece il prezzo medio di carico e NON dipende dalla
    # finestra visualizzata. Usiamo la stessa formula della pagina Overview:
    # (contributi lordi teorici - commissioni) / quantità, su tutto lo storico.
    avg_nav_by_fund = {}
    tx_all = transactions.copy()
    tx_all["Date"] = pd.to_datetime(tx_all.get("Date"), errors="coerce")
    tx_all = tx_all.dropna(subset=["Date"])
    if len(tx_all) > 0:
        tx_all["Gross Contribution (real)"] = (
            tx_all["Quantity"] * tx_all["Price (€)"] + tx_all["Fees (€)"]
        )
        tx_all["Gross Contribution (theor)"] = (
            (tx_all["Gross Contribution (real)"] / 10).round() * 10
        )
        grouped = tx_all.groupby("Fund").agg(
            gross=("Gross Contribution (theor)", "sum"),
            fees=("Fees (€)", "sum"),
            qty=("Quantity", "sum"),
        )
        for fund, row in grouped.iterrows():
            if row["qty"] and row["qty"] != 0:
                avg_nav_by_fund[fund] = (row["gross"] - row["fees"]) / row["qty"]

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

    # Controllo altezza: il combinato parte 3× più alto della versione compatta
    # e l'utente può ridimensionare lo spazio verticale occupato dal grafico.
    height_mult = st.slider(
        "Chart height", min_value=1.0, max_value=5.0, value=1.5, step=0.5,
        help="Vertical size of the combined chart.",
        key="hist_combined_height_mult",
    )

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
                hovertemplate=(f"<b>{fund}</b><extra></extra>" if privacy_on()
                               else f"<b>{fund}</b>: %{{y:+.2f}}%<extra></extra>"),
                showlegend=False,
            ),
            row=1,
            col=1,
        )

        # Annotazione % return (dentro il grafico, a destra dell'ultimo punto)
        last_pct = pct_return.iloc[-1]
        fig.add_annotation(
            x=fund_df["date"].iloc[-1],
            y=last_pct,
            text=f"{last_pct:+.2f}%",
            showarrow=False,
            xanchor="right",
            xshift=-4,
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
                hovertemplate=(f"<b>{fund}</b><extra></extra>" if privacy_on()
                               else f"<b>{fund}</b>: €%{{y:,.2f}}<extra></extra>"),
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
                    hovertemplate=(f"<b>{fund} Avg NAV</b><extra></extra>" if privacy_on()
                                   else f"<b>{fund} Avg NAV</b>: €%{{y:,.2f}}<extra></extra>"),
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
                    + ("" if privacy_on() else
                       f"Fees: €{t_row['Fees (€)']:.2f}<br>"
                       f"Total: €{(t_row['Quantity'] * t_row['Price (€)'] + t_row['Fees (€)']):.2f}")
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
                    hovertemplate=("<b>Transazione</b><extra></extra>" if privacy_on()
                                   else "%{text}<extra></extra>"),
                    text=hover_texts,
                    showlegend=False,
                ),
                row=row,
                col=1,
            )

        # --- Annotazione prezzo (dentro il grafico, a destra dell'ultimo punto) ---
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
            xshift=-4,
            font=dict(size=11, color=color),
            bordercolor=color,
            borderwidth=1.5,
            borderpad=3,
            bgcolor="rgba(30,30,30,0.7)",
            xref=xref,
            yref=yref,
        )

    # ------------------------------------------------------------------
    # DATI PER IL CROSSHAIR JS (linea unica su tutti i subplot)
    # ------------------------------------------------------------------
    # I native spike/hover di Plotly non riescono a disegnare UNA linea verticale
    # che attraversi subplot impilati (ognuno ha il proprio dominio Y). Come fa
    # investing.com, disegniamo il crosshair via JS: al plotly_hover tracciamo
    # una linea a piena altezza (yref="paper") e un'unica etichetta con i valori
    # di tutti i fondi alla data puntata. Qui prepariamo solo i dati.
    import numpy as _np
    hub_dates = plot_df.sort_values("date")["date"]
    date_keys = [pd.Timestamp(d).strftime("%Y-%m-%d") for d in hub_dates]
    # Per ogni data: label HTML con tutti i fondi (NAV + %), colori inclusi.
    per_date_rows = {dk: [] for dk in date_keys}
    fund_series = {}
    for fund in selected_funds:
        s = pd.to_numeric(plot_df.set_index("date")[fund], errors="coerce").reindex(hub_dates.values)
        base = s.dropna().iloc[0] if s.notna().any() else None
        pct = (s / base - 1.0) * 100.0 if base is not None else s * 0
        fund_series[fund] = (s.values, pct.values)
    for i, dk in enumerate(date_keys):
        for fund in selected_funds:
            nav, pct = fund_series[fund]
            color = FUND_COLORS.get(fund, "#999999")
            navv, pctv = nav[i], pct[i]
            if pd.isna(navv):
                continue
            if privacy_on():
                txt = f"{fund}: {pctv:+.2f}%"
            else:
                txt = f"{fund}: €{navv:.2f} ({pctv:+.2f}%)"
            per_date_rows[dk].append(f'<span style="color:{color}">●</span> {txt}')
    # Mappa data -> blocco HTML del tooltip
    crosshair_labels = {
        dk: (f'<b>{dk}</b><br>' + "<br>".join(rows)) for dk, rows in per_date_rows.items()
    }

    # ------------------------------------------------------------------
    # LAYOUT
    # ------------------------------------------------------------------
    # Tema coerente con la pagina (config.toml): sfondo #0d1117, testo #e6edf3.
    _PAGE_BG = "#0d1117"
    _PAGE_TEXT = "#e6edf3"
    _GRID = "rgba(230,237,243,0.08)"
    total_height = int((180 + 105 * n_funds) * height_mult)
    fig.update_layout(
        height=total_height,
        hovermode="x",
        template="plotly_dark",
        paper_bgcolor=_PAGE_BG,
        plot_bgcolor=_PAGE_BG,
        font=dict(family="sans-serif", color=_PAGE_TEXT, size=12),
        showlegend=False,
        dragmode="pan",
        uirevision="hist_combined_stacked",
        newshape=dict(line_color="#888888"),
        margin=dict(r=36, t=30, b=10, l=50),
        spikedistance=-1,
        hoverdistance=100,
    )
    # Griglia e assi in tinta scura coerente con lo sfondo pagina
    fig.update_xaxes(gridcolor=_GRID, zerolinecolor=_GRID, linecolor=_GRID)
    fig.update_yaxes(gridcolor=_GRID, zerolinecolor=_GRID, linecolor=_GRID)

    # Asse Y primo pannello (senza titolo)
    fig.update_yaxes(
        title_text="",
        row=1,
        col=1,
        fixedrange=False,
        showspikes=False,
        automargin=True,
        zeroline=True,
        zerolinecolor="rgba(150,150,150,0.3)",
    )

    # Asse Y per i singoli fondi: range basato SOLO sul NAV del fondo nel range
    # temporale selezionato (min/max), ignorando la linea Avg NAV (che può stare
    # molto fuori scala e comprimerebbe la lettura del prezzo).
    _mask = (plot_df["date"] >= pd.to_datetime(start_d)) & (plot_df["date"] <= pd.to_datetime(end_d))
    _interval = plot_df[_mask] if _mask.any() else plot_df
    for i, fund in enumerate(selected_funds):
        s = pd.to_numeric(_interval[fund], errors="coerce").dropna()
        cfg_y = dict(title_text="", fixedrange=False, showspikes=False, automargin=True)
        if len(s) > 0:
            lo, hi = float(s.min()), float(s.max())
            pad = (hi - lo) * 0.08 if hi > lo else max(abs(hi) * 0.02, 0.5)
            cfg_y["range"] = [lo - pad, hi + pad]
            cfg_y["autorange"] = False
        fig.update_yaxes(row=i + 2, col=1, **cfg_y)

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
    if x_max > x_min:
        x_padding = max((x_max - x_min) * 0.02, pd.Timedelta(days=2))
    else:
        x_padding = pd.Timedelta(days=2)
    x_max_display = x_max + x_padding

    # Il range del rangeslider è vincolato al filtro date della pagina
    # (start_d / end_d), esattamente come nella vista grid.
    bottom_xaxis_key = f"xaxis{n_rows}" if n_rows > 1 else "xaxis"

    # Range su tutti gli assi X (assi già "matched" con shared_xaxes). In
    # hovermode "x unified" la linea verticale attraversa i subplot da sola,
    # quindi non servono spike manuali (che confliggerebbero).
    for r in range(1, n_rows + 1):
        xaxis_key = "xaxis" if r == 1 else f"xaxis{r}"
        cfg = dict(range=[x_min, x_max_display])
        if xaxis_key == "xaxis":
            # Rangeselector (1M/3M/... All) ancorato in ALTO, sopra il pannello
            # % Return, così non si sovrappone all'ultimo grafico in basso.
            cfg.update(
                rangeselector=dict(
                    buttons=RANGE_SELECTOR_BUTTONS,
                    x=0, xanchor="left", y=1.0, yanchor="bottom",
                    bgcolor="rgba(230,237,243,0.06)",
                    bordercolor="rgba(230,237,243,0.2)",
                    borderwidth=1,
                    font=dict(color=_PAGE_TEXT, size=11),
                    activecolor="rgba(88,166,255,0.5)",
                ),
            )
        if xaxis_key == bottom_xaxis_key:
            # Rangeslider (mini-mappa) resta in basso.
            cfg.update(
                rangeslider=dict(visible=True, thickness=0.04, range=[x_min, x_max]),
            )
        fig.update_layout(**{xaxis_key: cfg})

    # Stile titoli subplot (più piccoli, colore tenue).
    # IMPORTANTE: modificare SOLO le annotazioni-titolo dei subplot (xref="paper"),
    # senza toccare le annotazioni prezzo/% custom (xref="x", "x2", ecc.).
    for ann in fig.layout.annotations:
        if ann.xref == "paper" and ann.yref == "paper":
            ann.font = dict(size=13, color="rgba(180,180,180,0.9)")
            ann.x = 0.01
            ann.xanchor = "left"

    # Nessuna traccia mostra il tooltip nativo: il crosshair JS fornisce l'unica
    # etichetta consolidata. Le tracce devono comunque emettere plotly_hover
    # (hoverinfo="none": evento sì, box nativo no). Le date delle transazioni
    # sono già incluse nell'etichetta del crosshair.
    for tr in fig.data:
        tr.hoverinfo = "none"
        tr.hovertemplate = None

    # ------------------------------------------------------------------
    # RENDER con crosshair JS a piena altezza (come investing.com)
    # ------------------------------------------------------------------
    import json
    import uuid as _uuid
    import streamlit.components.v1 as _components
    from plotly.utils import PlotlyJSONEncoder

    fig_json = json.dumps(fig, cls=PlotlyJSONEncoder)
    labels_json = json.dumps(crosshair_labels)
    div_id = "hist_combined_" + _uuid.uuid4().hex[:8]
    cfg = get_plotly_config("historical_combined")
    cfg_json = json.dumps(cfg)

    html = f"""
<style>
  html, body {{
    margin:0; padding:0;
    background:{_PAGE_BG};
    font-family: sans-serif;
    color:{_PAGE_TEXT};
  }}
  #wrap_{div_id} {{ position:relative; background:{_PAGE_BG}; }}
  #wrap_{div_id}:fullscreen {{ background:{_PAGE_BG}; padding:8px; }}
</style>
<div id="wrap_{div_id}">
  <div id="{div_id}" style="width:100%;"></div>
</div>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
<script>
(function() {{
  const fig = {fig_json};
  const labels = {labels_json};
  const gd = document.getElementById("{div_id}");
  const wrap = document.getElementById("wrap_{div_id}");

  // Bottone Full screen NATIVO nella modebar di Plotly (SVG icona espansione).
  const fsButton = {{
    name: "Full screen",
    title: "Toggle full screen",
    icon: {{
      width: 1000, height: 1000,
      path: "M150 150 L400 150 L400 250 L250 250 L250 400 L150 400 Z "
          + "M850 150 L850 400 L750 400 L750 250 L600 250 L600 150 Z "
          + "M150 850 L150 600 L250 600 L250 750 L400 750 L400 850 Z "
          + "M850 850 L600 850 L600 750 L750 750 L750 600 L850 600 Z",
    }},
    click: function() {{
      if (!document.fullscreenElement) {{
        (wrap.requestFullscreen || wrap.webkitRequestFullscreen
          || wrap.msRequestFullscreen).call(wrap);
      }} else {{
        (document.exitFullscreen || document.webkitExitFullscreen
          || document.msExitFullscreen).call(document);
      }}
    }},
  }};
  const cfg = Object.assign(
    {{responsive:true, displaylogo:false}},
    {cfg_json},
    {{modeBarButtonsToAdd: [fsButton].concat(({cfg_json}.modeBarButtonsToAdd)||[])}}
  );

  document.addEventListener("fullscreenchange", function() {{
    setTimeout(function() {{ Plotly.Plots.resize(gd); }}, 100);
  }});

  Plotly.newPlot(gd, fig.data, fig.layout, cfg).then(function() {{
    // Contenitore linea verticale + etichetta (overlay HTML sopra il grafico)
    gd.style.position = "relative";
    const vline = document.createElement("div");
    vline.style.cssText = "position:absolute;top:0;bottom:0;width:1px;"
      + "background:rgba(200,200,200,0.7);pointer-events:none;display:none;z-index:5;";
    gd.appendChild(vline);
    const tip = document.createElement("div");
    tip.style.cssText = "position:absolute;pointer-events:none;display:none;z-index:6;"
      + "background:rgba(20,20,20,0.94);border:1px solid rgba(150,150,150,0.5);"
      + "border-radius:4px;padding:6px 9px;font-size:12px;color:#eee;"
      + "font-family:sans-serif;white-space:nowrap;line-height:1.5;";
    gd.appendChild(tip);

    function fmtDate(x) {{
      // x può essere ms o stringa; normalizza a YYYY-MM-DD
      const d = new Date(x);
      if (!isNaN(d)) {{
        return d.toISOString().slice(0,10);
      }}
      return String(x).slice(0,10);
    }}

    gd.on("plotly_hover", function(ev) {{
      if (!ev.points || !ev.points.length) return;
      const pt = ev.points[0];
      const key = fmtDate(pt.x);
      const html = labels[key];
      if (!html) return;
      // Posizione X in pixel del PUNTO dati (allineamento perfetto con i dati):
      // usa la conversione dell'asse X del primo subplot.
      const xa = pt.xaxis;
      const xpix = xa._offset + xa.d2p(pt.x);
      // Estensione verticale: dall'alto del primo plot al fondo dell'ultimo.
      const fullLayout = gd._fullLayout;
      const yTop = fullLayout.yaxis._offset;
      const yaxes = Object.keys(fullLayout).filter(k => /^yaxis\\d*$/.test(k))
        .map(k => fullLayout[k]);
      let yBottom = 0;
      yaxes.forEach(ya => {{ yBottom = Math.max(yBottom, ya._offset + ya._length); }});
      vline.style.left = xpix + "px";
      vline.style.top = yTop + "px";
      vline.style.height = (yBottom - yTop) + "px";
      vline.style.bottom = "auto";
      vline.style.display = "block";
      tip.innerHTML = html;
      // Tooltip vicino al cursore, dentro i limiti del grafico
      const bb = gd.getBoundingClientRect();
      let tx = xpix + 14;
      const ty = Math.max(8, (ev.event.clientY - bb.top) - 10);
      tip.style.display = "block";
      const tw = tip.offsetWidth;
      if (tx + tw > gd.clientWidth) tx = xpix - tw - 14;
      tip.style.left = tx + "px";
      tip.style.top = ty + "px";
    }});
    gd.on("plotly_unhover", function() {{
      vline.style.display = "none";
      tip.style.display = "none";
    }});
  }});
}})();
</script>
"""
    _components.html(html, height=total_height + 10, scrolling=False)


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
        hovertemplate=(f"<b>{fund}</b><extra></extra>" if privacy_on()
                       else f"<b>{fund}</b>: €%{{y:,.2f}}<extra></extra>"),
        showlegend=False,
    ))

    # Linea media NAV
    if fund in avg_nav_by_fund:
        fig.add_trace(go.Scatter(
            x=[fund_df["date"].min(), fund_df["date"].max()],
            y=[avg_nav_by_fund[fund], avg_nav_by_fund[fund]],
            mode="lines", name=f"{fund} Avg NAV",
            line=dict(color=color, dash="dash", width=1.5),
            hovertemplate=(f"<b>{fund} Avg NAV</b><extra></extra>" if privacy_on()
                           else f"<b>{fund} Avg NAV</b>: €%{{y:,.2f}}<extra></extra>"),
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
                + ("" if privacy_on() else
                   f"Fees: €{t_row['Fees (€)']:.2f}<br>"
                   f"Total: €{(t_row['Quantity'] * t_row['Price (€)'] + t_row['Fees (€)']):.2f}")
            )
        fig.add_trace(go.Scatter(
            x=trans_dates, y=trans_prices, mode="markers", name=f"{fund} Transactions",
            marker=dict(size=10, color=color, symbol="circle", line=dict(width=2, color="white")),
            hovertemplate=("<b>Transazione</b><extra></extra>" if privacy_on()
                           else "%{text}<extra></extra>"), text=hover_texts, showlegend=False,
        ))

    # Range Y basato SOLO sul NAV del fondo nel range visualizzato (min/max),
    # ignorando la linea Avg NAV e i marker (che sposterebbero la scala).
    _s = pd.to_numeric(fund_df[fund], errors="coerce").dropna()
    if len(_s) > 0:
        lo, hi = float(_s.min()), float(_s.max())
        pad = (hi - lo) * 0.08 if hi > lo else max(abs(hi) * 0.02, 0.5)
        y_min, y_max = lo - pad, hi + pad
    else:
        y_min, y_max = None, None

    fig.update_layout(
        height=320, hovermode="x unified", template="plotly_white", showlegend=False,
        margin=dict(t=40, b=30, l=10, r=36), dragmode="pan",
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

    # La colorazione via pandas Styler è costosa a ogni interazione: limitiamo
    # la finestra temporale (default 1M) e usiamo UNA sola passata di stile con
    # COLORE DI SFONDO cella (verde/rosso) invece del colore font.
    total_rows = len(historical_data_df)
    win_opts = ["1M", "3M", "6M", "1Y", "Max"]
    win_days = {"1M": 30, "3M": 91, "6M": 182, "1Y": 365, "Max": None}
    choice = st.radio(
        "Range", win_opts, index=0, horizontal=True,
        help="Time window of rows to display (styled per-cell, so shorter is faster).",
    )
    days = win_days[choice]
    n_rows = total_rows if days is None else min(days, total_rows)
    historical_data_df = historical_data_df.head(n_rows)
    st.caption(f"Showing {n_rows} of {total_rows} rows (most recent first).")

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

    # Colore SFONDO cella (verde salita, rosso discesa) + evidenzia transazioni,
    # in UNA sola passata per colonna (più veloce di due .apply separati).
    _dates_list = display_df["date"].tolist()

    def _style_col(column):
        col_name = column.name
        if col_name == "date":
            return [""] * len(display_df)
        tx_dates = tx_dates_by_fund.get(col_name, set())
        raw = historical_data_df[col_name]
        out = []
        n = len(display_df)
        for i in range(n):
            base = ""
            is_tx = _dates_list[i] in tx_dates
            if i < n - 1:
                cur = raw.iloc[i]
                prev = raw.iloc[i + 1]
                if pd.notna(cur) and pd.notna(prev) and cur != prev:
                    up = cur > prev
                    # Palette tenue (come Transaction History, alpha 0.12) per la
                    # variazione giornaliera; molto più forte (0.35) sui giorni di
                    # transazione, per farli risaltare.
                    alpha = 0.35 if is_tx else 0.12
                    if up:
                        base = f"background-color: rgba(46,160,67,{alpha});"
                    else:
                        base = f"background-color: rgba(248,81,73,{alpha});"
                elif is_tx:
                    # Transazione in un giorno senza variazione di prezzo: evidenzia
                    # comunque con un tono neutro forte.
                    base = "background-color: rgba(230,237,243,0.14);"
            elif is_tx:
                base = "background-color: rgba(230,237,243,0.14);"
            # Bordo per i giorni di transazione (sovrapposto al colore variazione)
            if is_tx:
                base += "box-shadow: inset 0 0 0 2px rgba(230,237,243,0.55);"
            out.append(base)
        return out

    styler = display_df.style.apply(_style_col, subset=selected_funds, axis=0)

    display_df = display_df[["date"] + selected_funds]
    st.dataframe(styler, use_container_width=True)
