"""
pages/active_funds.py — Pagina "Active Funds".

Mostra la lista dei fondi attivi con le relative informazioni
(ticker, ISIN, nome completo, tipo) in una tabella colorata.
"""

import streamlit as st
from utils.privacy import render_page_header
import pandas as pd

from config import FUND_COLORS
from components.styling import style_fund_cell


def active_funds(funds: pd.DataFrame):
    """Renderizza la pagina Active Funds.

    Args:
        funds: DataFrame dei fondi con colonne Fund, Ticker, ISIN, Fund Name, Type, Colour.
    """
    render_page_header("📋 Active Funds")

    if len(funds) == 0:
        st.info("No funds added yet")
        return

    # Seleziona colonne da mostrare (URL incluso se presente in funds.csv)
    base_cols = ["Fund", "Ticker", "ISIN", "Fund Name", "Type"]
    has_url = "URL" in funds.columns
    cols = base_cols + (["URL"] if has_url else [])
    display_funds = funds[cols].copy()

    # Colonna helper per styling
    display_funds["_fund_type"] = funds["Fund"].values

    # Stile: colora la colonna Fund con il colore del rispettivo fondo
    def style_fund_rows(row):
        fund = row["_fund_type"]
        styles = []
        for col in row.index:
            if col == "Fund":
                styles.append(style_fund_cell(fund, FUND_COLORS))
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