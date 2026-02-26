"""
components/fund_filter.py — Filtro fondi riutilizzabile con st.pills.

Questo componente genera un widget pills multi-select per filtrare
i fondi.  Viene usato in più pagine (overview, transaction history,
historical prices, evolution) per filtrare i dati mostrati.

Legge e scrive `st.session_state.fund_filter`.
"""

import streamlit as st


def render_fund_filter(
    fund_list: list[str],
    fund_colors: dict,
    key_suffix: str = "",
) -> list[str]:
    """Mostra pills multi-select per filtrare i fondi.

    Args:
        fund_list:   Lista di nomi fondi da mostrare come opzioni.
        fund_colors: Dizionario {fund_name: '#RRGGBB'} (riservato per usi futuri).
        key_suffix:  Suffisso opzionale per rendere le key uniche tra pagine.

    Returns:
        Lista dei fondi attualmente selezionati (sottoinsieme di fund_list).
    """
    if not fund_list:
        return []

    # Opzioni: tutti i fondi + "✕" per reset
    options = list(fund_list) + ["✕"]

    # Selezione corrente (default = tutti i fondi)
    current = [f for f in st.session_state.get("fund_filter", fund_list) if f in fund_list]

    selected = st.pills(
        "Filter by Fund:",
        options=options,
        default=current,
        selection_mode="multi",
        key=f"fund_pills{key_suffix}",
    )

    # Gestione "✕": se selezionato, resetta a tutti i fondi
    if "✕" in selected:
        st.session_state.fund_filter = list(fund_list)
        st.rerun()
    else:
        st.session_state.fund_filter = list(selected)

    return [f for f in st.session_state.fund_filter if f in fund_list]
