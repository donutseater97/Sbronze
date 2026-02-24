"""
pages/active_funds.py — Pagina "Active Funds".

Mostra la lista dei fondi attivi con le relative informazioni
(ticker, ISIN, nome completo, tipo) in una tabella colorata.
"""

import streamlit as st
import pandas as pd

from config import FUND_COLORS
from components.styling import style_fund_cell


def active_funds(funds: pd.DataFrame):
    """Renderizza la pagina Active Funds.

    Args:
        funds: DataFrame dei fondi con colonne Fund, Ticker, ISIN, Fund Name, Type, Colour.
    """
    st.header("📋 Active Funds")

    if len(funds) == 0:
        st.info("No funds added yet")
        return

    # Seleziona colonne da mostrare
    display_funds = funds[["Fund", "Ticker", "ISIN", "Fund Name", "Type"]].copy()

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

    st.dataframe(
        styled_funds,
        width="stretch",
        hide_index=True,
        column_config={"_fund_type": None},
    )
