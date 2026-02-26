"""
components/fund_filter.py — Filtro fondi riutilizzabile con st.pills.

Questo componente genera un widget pills multi-select per filtrare
i fondi.  Viene usato in più pagine (overview, transaction history,
historical prices, evolution) per filtrare i dati mostrati.

Legge e scrive `st.session_state.fund_filter`.
"""

import streamlit as st


# Mapping colori fondo → emoji cerchio colorato
_COLOR_DOT = {
    "#FF0000": "🔴", "#ff0000": "🔴",  # rosso
    "#0066FF": "🔵", "#0066ff": "🔵",  # blu
    "#00FF00": "🟢", "#00ff00": "🟢",  # verde
    "#999999": "⚪",                    # grigio
    "#00CCFF": "🔵", "#00ccff": "🔵",  # cyan → blu
    "#CC00FF": "🟣", "#cc00ff": "🟣",  # viola
}


def _get_dot(color_hex: str) -> str:
    """Restituisce un emoji cerchio colorato per il colore dato."""
    return _COLOR_DOT.get(color_hex, "⚪")


def render_fund_filter(
    fund_list: list[str],
    fund_colors: dict,
    key_suffix: str = "",
) -> list[str]:
    """Mostra pills multi-select per filtrare i fondi con indicatori colorati.

    Args:
        fund_list:   Lista di nomi fondi da mostrare come opzioni.
        fund_colors: Dizionario {fund_name: '#RRGGBB'} per la colorazione.
        key_suffix:  Suffisso opzionale per rendere le key uniche tra pagine.

    Returns:
        Lista dei fondi attualmente selezionati (sottoinsieme di fund_list).
    """
    if not fund_list:
        return []

    # Selezione corrente (default = tutti i fondi)
    current = [f for f in st.session_state.get("fund_filter", fund_list) if f in fund_list]

    # Usa un contatore di reset per forzare un nuovo widget key ad ogni reset
    reset_counter = st.session_state.get(f"_pill_reset_n{key_suffix}", 0)
    pills_key = f"fund_pills{key_suffix}_v{reset_counter}"

    # Opzioni: fondi + ✕
    all_options = list(fund_list) + ["✕"]

    # format_func: aggiungi cerchio colorato al nome del fondo
    def fmt(opt):
        if opt == "✕":
            return "✕ Reset"
        dot = _get_dot(fund_colors.get(opt, ""))
        return f"{dot} {opt}"

    selected = st.pills(
        "Filter by Fund:",
        options=all_options,
        default=current,
        selection_mode="multi",
        format_func=fmt,
        key=pills_key,
    )

    selected = list(selected) if selected else []

    # Gestione ✕: resetta a tutti i fondi
    if "✕" in selected:
        st.session_state.fund_filter = list(fund_list)
        st.session_state[f"_pill_reset_n{key_suffix}"] = reset_counter + 1
        st.rerun()

    st.session_state.fund_filter = [f for f in selected if f in fund_list]

    return [f for f in st.session_state.fund_filter if f in fund_list]
