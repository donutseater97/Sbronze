"""
components/fund_filter.py — Bottoni filtro fondi riutilizzabili.

Questo componente genera una riga di bottoni colorati, uno per ciascun
fondo, più un bottone di reset.  Viene usato in 4 pagine diverse
(overview, transaction history, historical prices, evolution) per
filtrare i dati mostrati.

Legge e scrive `st.session_state.fund_filter`.
"""

import streamlit as st
from components.styling import hex_to_rgb


def render_fund_filter(
    fund_list: list[str],
    fund_colors: dict,
    key_suffix: str = "",
) -> list[str]:
    """Mostra i bottoni filtro fondi e restituisce la lista dei fondi selezionati.

    Ogni bottone è colorato con il colore del rispettivo fondo quando è
    attivo (type='primary'), grigio quando è inattivo (type='secondary').

    Args:
        fund_list:   Lista di nomi fondi da mostrare come bottoni.
        fund_colors: Dizionario {fund_name: '#RRGGBB'} per la colorazione.
        key_suffix:  Suffisso opzionale per rendere le key uniche tra pagine.

    Returns:
        Lista dei fondi attualmente selezionati (sottoinsieme di fund_list).
    """
    if not fund_list:
        return []

    st.markdown("**Filter by Fund:**")

    # --- CSS dinamico: colora i bottoni attivi con il colore del fondo ---
    css_parts = ["<style>"]
    for fund in fund_list:
        r, g, b = hex_to_rgb(fund_colors.get(fund, "#999999"))
        css_parts.append(f"""
        button[data-testid="baseButton-primary"][aria-label="{fund}"] {{
            background-color: rgba(200, 200, 200, 0.8) !important;
            border: none !important;
            color: rgb({r}, {g}, {b}) !important;
            font-weight: 600 !important;
        }}
        """)
    css_parts.append("</style>")
    st.markdown("".join(css_parts), unsafe_allow_html=True)

    # --- Griglia di bottoni: un bottone per fondo + bottone reset ---
    cols = st.columns(len(fund_list) + 1)

    for idx, fund in enumerate(fund_list):
        with cols[idx]:
            is_active = fund in st.session_state.fund_filter
            if st.button(
                fund,
                key=f"fund_btn_{fund}{key_suffix}",
                type="primary" if is_active else "secondary",
                width="stretch",
            ):
                # Toggle: aggiungi/rimuovi il fondo dal filtro
                if is_active:
                    st.session_state.fund_filter.remove(fund)
                else:
                    st.session_state.fund_filter.append(fund)
                st.rerun()

    # Bottone reset (✕) nell'ultima colonna
    with cols[-1]:
        if st.button(
            "✕",
            key=f"reset_fund_filters{key_suffix}",
            help="Reset filters",
            width="stretch",
        ):
            st.session_state.fund_filter = list(fund_list)
            st.rerun()

    # Restituisci solo i fondi selezionati che sono nella lista corrente
    return [f for f in st.session_state.fund_filter if f in fund_list]
