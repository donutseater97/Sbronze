"""
utils/privacy.py — Modalità privacy: oscura i valori in euro del portafoglio.

Quando la modalità è attiva (toggle nella home, sbloccabile solo dopo
autenticazione in "Add Transactions & Funds"), tutti gli importi personali
in euro vengono sostituiti da "€ ••••" mantenendo visibili le percentuali.

I NAV dei fondi (prezzi di mercato pubblici) NON vengono oscurati:
non rivelano nulla del patrimonio personale.

Lo stato vive in st.session_state["privacy_mode"] ed è quindi valido
per l'intera sessione su tutte le pagine.
"""

import streamlit as st

# Stringa usata al posto degli importi oscurati
MASK = "€ ••••"


def privacy_on() -> bool:
    """True se la modalità privacy è attiva nella sessione corrente."""
    return bool(st.session_state.get("privacy_mode", False))


def fmt_eur(value, pattern: str = "€ {:,.2f}") -> str:
    """Formatta un importo in euro, oscurandolo se la privacy è attiva.

    Args:
        value:   Valore numerico.
        pattern: Format string (es. "€ {:,.2f}", "€{:+,.2f}").

    Returns:
        Stringa formattata oppure MASK.
    """
    if privacy_on():
        return MASK
    return pattern.format(value)


def mask_text(text: str) -> str:
    """Restituisce MASK se la privacy è attiva, altrimenti il testo originale.

    Utile per stringhe già formattate (es. metriche, annotazioni grafici).
    """
    return MASK if privacy_on() else text


def render_privacy_toggle() -> None:
    """Renderizza il toggle privacy (abilitato solo dopo autenticazione).

    Da chiamare nella pagina home. Lo stato è condiviso tra tutte le pagine
    tramite st.session_state["privacy_mode"].
    """
    authenticated = st.session_state.get("authenticated", False)
    st.toggle(
        "🙈 Privacy mode — nascondi valori €",
        key="privacy_mode",
        disabled=not authenticated,
        help=(
            "Oscura tutti gli importi in euro del portafoglio (contributi, "
            "controvalore, P/L) mostrando solo le percentuali. I NAV dei "
            "fondi restano visibili perché sono prezzi pubblici. "
            "Sbloccabile inserendo la password nella pagina "
            "\"Add Transactions & Funds\"."
        ),
    )