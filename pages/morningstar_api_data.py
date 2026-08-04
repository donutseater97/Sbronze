"""
pages/morningstar_api_data.py — Pagina "Morningstar API data".

Ricostruisce un X-Ray di portafoglio (asset allocation, esposizione
valutaria, settori azionari, style box, partecipazioni aggregate) usando
l'endpoint pubblico Morningstar security_details, pesando i dati di
ciascun fondo per il controvalore corrente in euro.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from config import FUND_COLORS
from components.chart_helpers import get_plotly_config
from utils.privacy import fmt_eur
from utils.morningstar_api import (
    fetch_security_details_xml,
    parse_fund_analytics,
    aggregate_portfolio,
    ASSET_CLASS_ORDER,
    STYLEBOX_ROWS, STYLEBOX_COLS,
    BOND_STYLEBOX_ROWS, BOND_STYLEBOX_COLS,
)


# -----------------------------------------------------------------------------
# Caching — un download per fondo, riutilizzato per 6 ore
# -----------------------------------------------------------------------------

@st.cache_data(ttl=6 * 3600, show_spinner=False)
def _load_fund_analytics(security_id: str) -> dict:
    """Scarica e interpreta i dati Morningstar per un singolo fondo (cached)."""
    return parse_fund_analytics(fetch_security_details_xml(security_id, id_type="ISIN"))


# -----------------------------------------------------------------------------
# Helper — valore corrente per fondo (quote possedute × ultimo NAV)
# -----------------------------------------------------------------------------

def _current_values(funds: pd.DataFrame, transactions: pd.DataFrame,
                    hist_data: pd.DataFrame) -> dict[str, float]:
    """Calcola {fondo: controvalore corrente in EUR} da transazioni e NAV."""
    values: dict[str, float] = {}
    if len(transactions) == 0 or len(hist_data) == 0:
        return values
    qty = transactions.groupby("Fund")["Quantity"].sum()
    latest = hist_data.sort_values("date").iloc[-1]
    for fund in funds["Fund"]:
        q = float(qty.get(fund, 0.0))
        nav = latest.get(fund)
        if q > 0 and pd.notna(nav):
            values[fund] = q * float(nav)
    return values


def _stylebox_table(cells: dict[int, float], rows: list[str], cols: list[str]) -> pd.DataFrame:
    """Trasforma le 9 celle {1..9: pct} in una tabella 3×3 etichettata."""
    data = [[cells.get(r * 3 + c + 1, 0.0) for c in range(3)] for r in range(3)]
    return pd.DataFrame(data, index=rows, columns=cols).round(1)


# -----------------------------------------------------------------------------
# Pagina
# -----------------------------------------------------------------------------

def morningstar_api_data(funds: pd.DataFrame, transactions: pd.DataFrame,
                         hist_data: pd.DataFrame, last_date_str: str):
    """Renderizza la pagina Morningstar API data."""
    st.header("🔎 Morningstar API data")
    st.caption(
        "X-Ray di portafoglio ricostruito dall'endpoint pubblico Morningstar "
        "(security_details), con i dati di ciascun fondo pesati per il "
        "controvalore corrente. Per alcuni fondi Morningstar pubblica solo le "
        "prime 10 partecipazioni: il look-through può quindi essere parziale."
    )

    if len(funds) == 0:
        st.info("No funds added yet")
        return

    # --- Pesi correnti per fondo -------------------------------------------
    weights = _current_values(funds, transactions, hist_data)
    if not weights:
        st.warning("Impossibile calcolare il controvalore corrente dei fondi "
                   "(transazioni o prezzi storici mancanti).")
        return

    # --- Download dati Morningstar per fondo (cached) -----------------------
    per_fund: dict[str, dict] = {}
    failed: list[str] = []
    with st.spinner("Scarico i dati Morningstar per i fondi..."):
        for _, row in funds.iterrows():
            fund = row["Fund"]
            security_id = row["ISIN"] if pd.notna(row.get("ISIN")) else row["Ticker"]
            if fund not in weights or pd.isna(security_id):
                continue
            try:
                per_fund[fund] = _load_fund_analytics(security_id)
            except Exception as e:
                failed.append(f"{fund}: {e}")
    if failed:
        st.warning(f"Dati Morningstar non disponibili per: {', '.join(failed)}. "
                   "Aggregazione calcolata sui fondi restanti.")
    if not per_fund:
        st.error("\n".join(failed))
        return

    active_weights = {f: w for f, w in weights.items() if f in per_fund}
    agg = aggregate_portfolio(per_fund, active_weights)

    # --- Overview ------------------------------------------------------------
    total_value = sum(active_weights.values())
    n_holdings = len(agg["holdings"]) if not agg["holdings"].empty else 0
    c1, c2, c3 = st.columns(3)
    c1.metric("Importo Portafoglio", fmt_eur(total_value, "{:,.2f} €"))
    c2.metric("Numero di strumenti", f"{len(per_fund)}")
    c3.metric("Partecipazioni aggregate", f"{n_holdings}")

    st.divider()

    # --- Asset Allocation + Esposizione valutaria ----------------------------
    col_aa, col_ccy = st.columns(2)

    with col_aa:
        st.subheader("Asset Allocation")
        alloc = agg["asset_allocation"]
        labels = [l for l in ASSET_CLASS_ORDER if l in alloc]
        vals = [alloc[l] for l in labels]
        fig = go.Figure(go.Bar(
            x=vals, y=labels, orientation="h",
            marker_color=["#3B6FD4", "#E8772E", "#6AA84F", "#E8C22E", "#BBBBBB"][:len(labels)],
            text=[f"{v:.1f}%" for v in vals], textposition="outside",
        ))
        fig.update_layout(height=320, margin=dict(l=10, r=30, t=10, b=10),
                          xaxis_title="Percentuale %",
                          yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, width="stretch", config=get_plotly_config("asset_allocation"))

    with col_ccy:
        st.subheader("Currency Exposure")
        ccy = {k: v for k, v in sorted(agg["currency"].items(),
                                       key=lambda x: -x[1]) if v > 0.01}
        fig = go.Figure(go.Pie(
            labels=list(ccy.keys()), values=list(ccy.values()),
            hole=0.55, sort=False,
            textinfo="none",
            hovertemplate="%{label}: %{value:.2f}%<extra></extra>",
        ))
        fig.update_layout(height=320, margin=dict(l=10, r=10, t=10, b=10),
                          legend=dict(orientation="v", font=dict(size=11)))
        st.plotly_chart(fig, width="stretch", config=get_plotly_config("currency_exposure"))
        st.caption("Esposizione calcolata sul valore di mercato delle posizioni "
                   "in ciascuna valuta (posizione netta per fondo).")

    st.divider()

    # --- Settori azionari -----------------------------------------------------
    st.subheader("Esposizione Settori Azionari")
    sectors = dict(sorted(agg["sectors"].items(), key=lambda x: -x[1]))
    if sectors:
        fig = go.Figure(go.Bar(
            x=list(sectors.values()), y=list(sectors.keys()), orientation="h",
            marker_color="#3B6FD4",
            text=[f"{v:.2f}%" for v in sectors.values()], textposition="outside",
        ))
        fig.update_layout(height=420, margin=dict(l=10, r=40, t=10, b=10),
                          xaxis_title="Percentuale % (della componente azionaria)",
                          yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig, width="stretch", config=get_plotly_config("sector_exposure"))
    else:
        st.info("Nessun dato settoriale disponibile.")

    st.divider()

    # --- Style Box -------------------------------------------------------------
    st.subheader("Style Box")
    col_eq, col_bd = st.columns(2)
    with col_eq:
        st.markdown("**Equity**")
        if agg["stylebox"]:
            st.dataframe(
                _stylebox_table(agg["stylebox"], STYLEBOX_ROWS, STYLEBOX_COLS)
                .style.background_gradient(cmap="Blues", axis=None)
                .format("{:.1f}"),
                width="stretch",
            )
        else:
            st.info("N/D")
    with col_bd:
        st.markdown("**Bonds**")
        if agg["bond_stylebox"]:
            st.dataframe(
                _stylebox_table(agg["bond_stylebox"], BOND_STYLEBOX_ROWS, BOND_STYLEBOX_COLS)
                .style.background_gradient(cmap="Oranges", axis=None)
                .format("{:.1f}"),
                width="stretch",
            )
        else:
            st.info("N/D")
    st.caption("Equity: Value/Blend/Growth × Large/Mid/Small, pesato sulla componente "
               "azionaria. Bonds: sensibilità ai tassi × qualità creditizia.")

    st.divider()

    # --- Partecipazioni aggregate ------------------------------------------------
    st.subheader("Partecipazioni aggregate (look-through)")
    holdings = agg["holdings"]
    if holdings.empty:
        st.info("Nessuna partecipazione disponibile.")
        return
    top_n = st.slider("Numero di posizioni da mostrare", 10, min(100, len(holdings)), 25, step=5)
    show = holdings.head(top_n).copy()
    show["PortfolioWeight"] = show["PortfolioWeight"].map(lambda v: f"{v:.2f}%")
    show = show.rename(columns={
        "SecurityName": "Titolo", "Country": "Paese", "Currency": "Valuta",
        "PortfolioWeight": "Peso portafoglio", "Funds": "Fondi",
    })[["Titolo", "Paese", "Valuta", "Peso portafoglio", "Fondi"]]
    st.dataframe(show, width="stretch", hide_index=True)
    st.caption(f"Totale partecipazioni aggregate: {len(holdings)} "
               "(unione dei titoli pubblicati da Morningstar per ciascun fondo; "
               "lo stesso titolo detenuto da più fondi è consolidato).")