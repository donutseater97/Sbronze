"""
components/fund_filter.py — Filtro fondi riutilizzabile con st.pills.

Questo componente genera un widget pills multi-select per filtrare
i fondi.  Viene usato in più pagine (overview, transaction history,
historical prices, evolution) per filtrare i dati mostrati.

Legge e scrive `st.session_state.fund_filter`.
"""

import streamlit as st
from components.styling import hex_to_rgb


def render_fund_filter(
    fund_list: list[str],
    fund_colors: dict,
    key_suffix: str = "",
) -> list[str]:
    """Mostra pills multi-select per filtrare i fondi con colori.

    Args:
        fund_list:   Lista di nomi fondi da mostrare come opzioni.
        fund_colors: Dizionario {fund_name: '#RRGGBB'} per la colorazione.
        key_suffix:  Suffisso opzionale per rendere le key uniche tra pagine.

    Returns:
        Lista dei fondi attualmente selezionati (sottoinsieme di fund_list).
    """
    if not fund_list:
        return []

    # CSS per colorare ogni pill con il colore del fondo
    css_parts = ["<style>"]
    for fund in fund_list:
        r, g, b = hex_to_rgb(fund_colors.get(fund, "#999999"))
        # Colora il testo della pill selezionata (aria-checked=true)
        css_parts.append(f"""
        button[data-testid="stBaseButton-pills"][aria-label="{fund}"] {{
            color: rgb({r}, {g}, {b}) !important;
            font-weight: 600 !important;
        }}
        """)
    css_parts.append("</style>")
    st.markdown("".join(css_parts), unsafe_allow_html=True)

    # Selezione corrente (default = tutti i fondi)
    current = [f for f in st.session_state.get("fund_filter", fund_list) if f in fund_list]

    # Layout: pills + reset button
    pill_col, reset_col = st.columns([6, 1])

    with pill_col:
        selected = st.pills(
            "Filter by Fund:",
            options=fund_list,
            default=current,
            selection_mode="multi",
            key=f"fund_pills{key_suffix}",
        )

    with reset_col:
        st.markdown("")  # spacer per allineare
        if st.button("✕", key=f"reset_pills{key_suffix}", help="Select all funds"):
            st.session_state.fund_filter = list(fund_list)
            # Clear the pills widget key to force re-render with all selected
            pills_key = f"fund_pills{key_suffix}"
            if pills_key in st.session_state:
                del st.session_state[pills_key]
            st.rerun()

    st.session_state.fund_filter = list(selected) if selected else []

    return [f for f in st.session_state.fund_filter if f in fund_list]
