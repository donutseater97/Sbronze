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

# Stringhe usate al posto dei valori oscurati
MASK = "€ ••••"
MASK_PLAIN = "••••"


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
    """Renderizza il controllo privacy nella home.

    Attivazione libera (nessuna password). La disattivazione richiede la
    password admin (la stessa della pagina "Add Transactions & Funds"),
    inserita direttamente qui senza cambiare pagina.

    Lo stato vive in st.session_state["privacy_mode"] — una chiave NON
    legata a un widget, così persiste navigando tra le pagine (le chiavi
    dei widget vengono eliminate da Streamlit quando il widget non è
    presente nella pagina corrente).
    """
    from config import OWNER_PASSWORD  # import locale per evitare cicli

    if not privacy_on():
        activated = st.toggle(
            "🙈 Privacy mode — nascondi valori €",
            value=False,
            key="_privacy_toggle_activate",
            help=(
                "Oscura tutti gli importi e le quantità del portafoglio. "
                "Attivabile liberamente; per disattivarla serve la password admin."
            ),
        )
        if activated:
            st.session_state.privacy_mode = True
            st.rerun()
    else:
        col_status, col_unlock = st.columns([3, 2])
        with col_status:
            st.markdown("🙈 **Privacy mode attiva** — valori del portafoglio nascosti")
        with col_unlock:
            with st.popover("🔓 Disattiva"):
                pwd = st.text_input(
                    "Password admin", type="password", key="_privacy_pwd"
                )
                if st.button("Conferma", key="_privacy_pwd_btn"):
                    if pwd == OWNER_PASSWORD:
                        st.session_state.privacy_mode = False
                        st.rerun()
                    else:
                        st.error("Password errata")