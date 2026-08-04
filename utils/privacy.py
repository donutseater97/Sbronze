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
    """Backward-compatible standalone toggle (delegates to the shared control)."""
    _render_privacy_control(compact=False)

def normalize_spark(values, base=100.0):
    """Convert an absolute money series into an indexed series (base=100).

    Metric-card sparklines (st.metric chart_data) show the raw value on hover,
    which would leak absolute euro amounts. Indexing to a base keeps the exact
    same shape but makes the hover value a small dimensionless number instead
    of your real euro figure. Use for money sparklines; leave NAV/price
    sparklines (public data) untouched.
    """
    vals = [float(v) if v is not None else 0.0 for v in values]
    if not vals:
        return vals
    ref = next((abs(v) for v in vals if abs(v) > 1e-9), 0.0)
    if ref == 0.0:
        return [0.0 for _ in vals]
    return [base * v / ref for v in vals]


def render_page_header(title: str) -> None:
    """Render a page title with the privacy toggle aligned to the top-right.

    The toggle state lives in st.session_state["privacy_mode"] (a non-widget
    key) so it persists across pages. Call at the top of every page instead
    of st.header(...).
    """
    left, right = st.columns([5, 2], vertical_alignment="center")
    with left:
        st.header(title)
    with right:
        _render_privacy_control(compact=True)


def _render_privacy_control(compact: bool = False) -> None:
    """Shared privacy control: free activation, password-gated deactivation."""
    from config import OWNER_PASSWORD  # import locale per evitare cicli

    if not privacy_on():
        label = "🙈 Privacy" if compact else "🙈 Privacy mode — nascondi valori €"
        activated = st.toggle(
            label, value=False, key="_privacy_toggle_activate",
            help=("Hide all portfolio amounts and quantities. Free to enable; "
                  "disabling requires the admin password."),
        )
        if activated:
            st.session_state.privacy_mode = True
            st.rerun()
    else:
        with st.popover("🙈 Privacy on"):
            st.caption("Portfolio values are hidden.")
            pwd = st.text_input("Admin password", type="password", key="_privacy_pwd")
            if st.button("Disable", key="_privacy_pwd_btn"):
                if pwd == OWNER_PASSWORD:
                    st.session_state.privacy_mode = False
                    st.rerun()
                else:
                    st.error("Wrong password")