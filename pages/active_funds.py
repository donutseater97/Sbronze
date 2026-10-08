"""
pages/active_funds.py — Pagina "Funds".

Mostra la lista dei fondi (attivi, chiusi, sostituiti) con le relative
informazioni (stato, ticker, ISIN, nome completo, tipo) in una tabella colorata.

Status (colonna di funds.csv):
    Active  fondo in uso
    Closed  posizione chiusa senza fondo sostitutivo
    Subbed  sostituito da un altro fondo (es. US (old) → US (a)); lo storico
            resta tracciato ma il fondo è spento di default nei filtri una
            volta azzerata la quantità
"""

import streamlit as st
from utils.privacy import render_page_header
import pandas as pd

from config import FUND_COLORS
from components.styling import style_fund_cell
from utils.transactions import STATUS_ACTIVE, STATUS_CLOSED, STATUS_SUBBED

# Stile della cella Status
_STATUS_STYLE = {
    STATUS_ACTIVE: "color: #2fbf71; font-weight: 600;",
    STATUS_CLOSED: "color: #8f9bb3;",
    STATUS_SUBBED: "color: #e0a030; font-style: italic;",
}


def active_funds(funds: pd.DataFrame):
    """Renderizza la pagina Funds.

    Args:
        funds: DataFrame dei fondi con colonne Fund, Status, Ticker, ISIN,
               Fund Name, Type, Colour (URL opzionale).
    """
    render_page_header("📋 Funds")

    if len(funds) == 0:
        st.info("No funds added yet")
        return

    # Seleziona colonne da mostrare (URL incluso se presente in funds.csv)
    base_cols = ["Fund", "Status", "Ticker", "ISIN", "Fund Name", "Type"]
    base_cols = [c for c in base_cols if c in funds.columns]
    has_url = "URL" in funds.columns
    cols = base_cols + (["URL"] if has_url else [])
    display_funds = funds[cols].copy().reset_index(drop=True)

    # Colonna helper per styling
    display_funds["_fund_type"] = funds["Fund"].values

    # Stile: colora la colonna Fund con il colore del rispettivo fondo
    def style_fund_rows(row):
        fund = row["_fund_type"]
        styles = []
        for col in row.index:
            if col == "Fund":
                styles.append(style_fund_cell(fund, FUND_COLORS))
            elif col == "Status":
                styles.append(_STATUS_STYLE.get(row["Status"], ""))
            elif col == "_fund_type":
                styles.append("display: none;")
            else:
                styles.append("")
        return styles

    styled_funds = display_funds.style.apply(style_fund_rows, axis=1)

    column_config = {"_fund_type": None}
    if has_url:
        column_config["URL"] = st.column_config.LinkColumn(
            "URL", display_text="Official page ↗"
        )

    st.dataframe(
        styled_funds,
        width="stretch",
        hide_index=True,
        column_config=column_config,
    )
    st.caption(
        "Status: **Active** = in use · **Closed** = position closed with no "
        "replacement · **Subbed** = replaced by another fund via a switch "
        "(history kept; off by default in the fund filters once its quantity is zero)."
    )