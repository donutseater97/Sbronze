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
    """Index a money sparkline to base=100 ONLY when privacy mode is active.

    Metric-card sparklines (st.metric chart_data) show the raw value on hover.
    When privacy is on we index the series to a base so the hover reveals a
    dimensionless number instead of real euros; when privacy is off we return
    the original values unchanged, so the hover shows the correct amounts.
    """
    if not privacy_on():
        return values
    vals = [float(v) if v is not None else 0.0 for v in values]
    if not vals:
        return vals
    ref = next((abs(v) for v in vals if abs(v) > 1e-9), 0.0)
    if ref == 0.0:
        return [0.0 for _ in vals]
    return [base * v / ref for v in vals]


def render_page_header(title: str) -> None:
    """Render a page title with sign-in + privacy controls on the top-right.

    The privacy and role state live in st.session_state (non-widget keys) so
    they persist across pages. Call at the top of every page instead of
    st.header(...).
    """
    left, mid, right = st.columns([5, 1.3, 1.3], vertical_alignment="center")
    with left:
        st.header(title)
    with mid:
        _render_role_control()
    with right:
        _render_privacy_control(compact=True)


def _render_role_control() -> None:
    """Sign-in popover: authenticate as admin or viewer (state is cross-page)."""
    from config import check_role

    role = st.session_state.get("role")
    label = {"admin": "👤 Admin", "viewer": "👤 Viewer"}.get(role, "👤 Sign in")
    with st.popover(label):
        if role:
            st.caption(f"Signed in as **{role}**.")
            if st.button("Sign out", key="_role_signout"):
                st.session_state.role = None
                st.session_state.authenticated = False
                st.rerun()
        else:
            st.caption("Admins can edit data and disable privacy mode; viewers "
                       "can browse everything else.")
            pwd = st.text_input("Password", type="password", key="_role_pwd")
            if st.button("Sign in", key="_role_signin"):
                r = check_role(pwd)
                if r:
                    st.session_state.role = r
                    st.session_state.authenticated = (r == "admin")
                    st.rerun()
                else:
                    st.error("Incorrect password")


def _render_privacy_control(compact: bool = False) -> None:
    """Privacy control.

    Any signed-in user (admin or viewer) can toggle privacy on/off freely.
    Anonymous users can enable it, but disabling requires signing in first.
    """
    signed_in = st.session_state.get("role") in ("admin", "viewer")

    if not privacy_on():
        label = "🙈 Privacy" if compact else "🙈 Privacy mode — nascondi valori €"
        activated = st.toggle(
            label, value=False, key="_privacy_toggle_activate",
            help="Hide all portfolio amounts and quantities.",
        )
        if activated:
            st.session_state.privacy_mode = True
            st.rerun()
    else:
        if signed_in:
            # Utenti autenticati: disattivazione diretta, nessuna password.
            with st.popover("🙈 Privacy on"):
                st.caption("Portfolio values are hidden.")
                if st.button("Reveal values", key="_privacy_reveal_btn"):
                    st.session_state.privacy_mode = False
                    st.rerun()
        else:
            # Anonimi: devono prima autenticarsi (via il popover Sign in).
            with st.popover("🙈 Privacy on"):
                st.caption("Portfolio values are hidden. Sign in (top-left of "
                           "this header) to reveal them.")