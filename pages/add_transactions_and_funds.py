"""
pages/add_transactions_and_funds.py — Pagina admin "Add Transactions & Funds".

Pagina protetta da password che consente di:
- Aggiungere nuove transazioni (acquisti)
- Registrare uno switch tra due fondi (es. US (old) → US (a)): due righe
  "Switch Out" / "Switch In" scritte in un unico commit
- Aggiungere nuovi fondi al portafoglio
- Committare automaticamente le modifiche su GitHub via API
"""

import streamlit as st
import pandas as pd
from datetime import date

from config import (
    FUNDS_FILE,
    FUNDS_REPO_PATH,
    TRANSACTIONS_FILE,
    TRANSACTIONS_REPO_PATH,
    check_role,
    GITHUB_TOKEN,
    GITHUB_REPO,
    GITHUB_BRANCH,
    load_funds_and_transactions,
    load_historical_prices,
)
from utils.github_store import append_csv_rows, GitHubWriteError, GitHubConfigError
from utils.transactions import (
    FUND_COLUMNS,
    OP_BUY,
    OP_SWITCH_IN,
    OP_SWITCH_OUT,
    QTY_EPS,
    STATUS_ACTIVE,
    STATUSES,
    TX_COLUMNS,
    current_quantities,
    fund_status_map,
)
_FLASH_KEY = "_admin_flash"
_PENDING_KEY = "_admin_pending_writes"


def add_transactions_and_funds(
    funds: pd.DataFrame,
    transactions: pd.DataFrame,
    hist_data: pd.DataFrame | None = None,
):
    """Renderizza la pagina Add Transactions & Funds.

    ⚠️ Modifica in-place i DataFrame globali `funds` e `transactions`
    e li salva su disco + GitHub.

    Args:
        funds:        DataFrame dei fondi (verrà modificato se si aggiunge un fondo).
        transactions: DataFrame delle transazioni (verrà modificato se si aggiunge una transazione).

    Returns:
        Tupla (funds_aggiornato, transactions_aggiornato).
    """

    # ===== AUTENTICAZIONE (solo ADMIN) =====
    # Questa pagina modifica i dati: richiede il ruolo admin. I viewer possono
    # navigare tutto il resto ma non editare qui.
    st.subheader("🔐 Authentication")
    if st.session_state.get("role") != "admin":
        if st.session_state.get("role") == "viewer":
            st.warning("You are signed in as **viewer**. Editing transactions and "
                       "funds requires an **admin** password.")
        pwd = st.text_input("Enter admin password to edit data:", type="password")
        if pwd:
            role = check_role(pwd)
            if role == "admin":
                st.session_state.authenticated = True
                st.session_state.role = "admin"
                st.rerun()
            elif role == "viewer":
                st.error("Viewer password accepted elsewhere, but this page "
                         "requires the admin password.")
            else:
                st.error("Incorrect password")
        else:
            st.info("Enter the admin password to add transactions and funds")
        return funds, transactions

    IS_OWNER = st.session_state.get("role") == "admin"
    _render_status()

    # ===== AGGIUNGI TRANSAZIONE =====
    st.header("💰 Add Transaction")
    if len(funds) == 0:
        st.info("Add a fund first")
    elif IS_OWNER:
        with st.form("add_Transaction"):
            fund_choice = st.selectbox("Fund", funds["Fund"].tolist())
            contrib_date = st.date_input("Date", date.today())
            price = st.number_input("Price (€)", min_value=0.0)
            quantity = st.number_input("Quantity", min_value=0.0, step=0.001, format="%f")
            fees = st.number_input("Fees (€)", min_value=0.0)
            submitted_c = st.form_submit_button("Add Transaction")

            if submitted_c:
                if quantity <= 0 or price <= 0:
                    st.error("Quantity and Price must be greater than 0")
                else:
                    new_row = pd.DataFrame([{
                        "Date": pd.Timestamp(contrib_date).strftime("%Y-%m-%d %H:%M:%S"),
                        "Fund": fund_choice,
                        "Price (€)": price,
                        "Quantity": quantity,
                        "Fees (€)": fees,
                        "Operation": OP_BUY,
                        "Linked Fund": "",
                    }])
                    _commit_rows(
                        TRANSACTIONS_REPO_PATH, TRANSACTIONS_FILE, new_row, TX_COLUMNS,
                        f"Add transaction for {fund_choice} on "
                        f"{contrib_date.strftime('%Y-%m-%d')} via Streamlit",
                        label=f"{fund_choice} {contrib_date:%Y-%m-%d} · {quantity:g} @ €{price:.2f}",
                    )

    st.divider()

    # ===== SWITCH TRA FONDI =====
    st.header("⇄ Switch Between Funds")
    if IS_OWNER and len(funds) >= 2:
        _render_switch_section(funds, transactions, hist_data)

    st.divider()

    # ===== AGGIUNGI FONDO =====
    st.header("➕ Add Fund")
    if IS_OWNER:
        with st.form("add_fund"):
            fund_cat = st.text_input("Fund", placeholder="e.g., US, EU, EM, Tech")

            col1, col2 = st.columns(2)
            with col1:
                isin = st.text_input("ISIN", placeholder="e.g., LU0281484963")
                name = st.text_input("Fund Name", placeholder="e.g., JPMorgan Funds - US Select Equity Plus Fund D (acc) - EUR")
                fund_type = st.selectbox("Type", ["Equity", "Bond"])
                status = st.selectbox("Status", STATUSES, index=STATUSES.index(STATUS_ACTIVE))
            with col2:
                ticker = st.text_input("Ticker", placeholder="e.g., 0P0001CRXW")
                colour = st.color_picker("Colour", value="#C00000")
                fund_url = st.text_input("Official page URL (optional)",
                                         placeholder="https://...")
            submitted = st.form_submit_button("Add Fund")
            if submitted:
                # Validazione
                if not fund_cat.strip() or not isin.strip() or not ticker.strip() or not name.strip():
                    st.error("All fields are required")
                elif fund_cat in funds["Fund"].values:
                    st.error(f"Fund '{fund_cat}' already exists")
                elif isin in funds["ISIN"].values:
                    st.error(f"ISIN '{isin}' already exists")
                elif ticker in funds["Ticker"].values:
                    st.error(f"Ticker '{ticker}' already exists")
                else:
                    new_fund = pd.DataFrame([{
                        "Fund": fund_cat, "Status": status, "Ticker": ticker, "ISIN": isin,
                        "Fund Name": name, "Type": fund_type, "Colour": colour,
                        "URL": fund_url or "",
                    }])
                    _commit_rows(
                        FUNDS_REPO_PATH, FUNDS_FILE, new_fund, FUND_COLUMNS,
                        f"Add fund '{fund_cat}' via Streamlit",
                        label=f"fund {fund_cat}",
                        success_note="GitHub Actions will fetch its prices shortly.",
                    )

    return funds, transactions


def _nav_on(hist_data, fund, day):
    """NAV del fondo alla data (ultimo valore <= data) da historical_data, o None."""
    if hist_data is None or len(hist_data) == 0 or fund not in hist_data.columns:
        return None
    h = hist_data[["date", fund]].dropna()
    h = h[pd.to_datetime(h["date"]) <= pd.Timestamp(day)]
    if h.empty:
        return None
    return float(h.sort_values("date").iloc[-1][fund])


def _render_switch_section(funds, transactions, hist_data):
    """Form per registrare uno switch: azzera (o riduce) il fondo di uscita e
    carica le nuove quote sul fondo di destinazione, in un unico commit.

    Righe scritte in transaction_history.csv:
        Switch Out  Fund=<da>  Quantity=-q_out  Fees=0     Linked Fund=<a>
        Switch In   Fund=<a>   Quantity=+q_in   Fees=fee   Linked Fund=<da>
    La fee dello switch va sulla gamba in entrata: controvalore in entrata
    (q_in × NAV + fee) ≈ controvalore in uscita (q_out × NAV).
    """
    st.caption(
        "Moves a position from one fund to another (e.g. **US (old) → US (a)**). "
        "Records two linked rows: a *Switch Out* that removes the units from the "
        "source fund and a *Switch In* with the units received in the target "
        "fund at its own NAV. Switches are not counted as new contributions."
    )
    fund_names = funds["Fund"].tolist()
    status = fund_status_map(funds)
    qty = current_quantities(transactions) if len(transactions) else pd.Series(dtype=float)
    held = [f for f in fund_names if float(qty.get(f, 0.0)) > QTY_EPS]
    if not held:
        st.info("No fund currently held: nothing to switch.")
        return

    # Default: fondo detenuto ma non Active (es. Subbed) → primo Active non detenuto
    src_default = next((f for f in held if status.get(f) != STATUS_ACTIVE), held[0])
    c1, c2 = st.columns(2)
    with c1:
        src = st.selectbox("From fund (Switch Out)", held, index=held.index(src_default),
                           key="sw_src")
    targets = [f for f in fund_names if f != src]
    tgt_default = next((f for f in targets if status.get(f) == STATUS_ACTIVE
                        and float(qty.get(f, 0.0)) <= QTY_EPS), targets[0])
    with c2:
        tgt = st.selectbox("To fund (Switch In)", targets, index=targets.index(tgt_default),
                           key="sw_tgt")

    held_qty = round(float(qty.get(src, 0.0)), 6)
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"**Out — {src}**")
        out_date = st.date_input("Out date", date.today(), key="sw_out_date")
        nav_hint = _nav_on(hist_data, src, out_date)
        out_price = st.number_input("Out NAV (€)", min_value=0.0, format="%.4f", key="sw_out_price",
                                    help=f"NAV in historical data on that date: €{nav_hint:.2f}"
                                    if nav_hint else None)
        full = st.checkbox(f"Transfer the entire position ({held_qty:g} units)", value=True,
                           key="sw_full")
        if full:
            out_qty = held_qty
        else:
            out_qty = st.number_input("Units out", min_value=0.0, max_value=held_qty,
                                      step=0.001, format="%f", key="sw_out_qty")
    with c2:
        st.markdown(f"**In — {tgt}**")
        in_date = st.date_input("In date", date.today(), key="sw_in_date")
        nav_hint_in = _nav_on(hist_data, tgt, in_date)
        in_price = st.number_input("In NAV (€)", min_value=0.0, format="%.4f", key="sw_in_price",
                                   help=f"NAV in historical data on that date: €{nav_hint_in:.2f}"
                                   if nav_hint_in else None)
        in_qty = st.number_input("Units in (as on the bank statement)", min_value=0.0,
                                 step=0.001, format="%f", key="sw_in_qty")
        in_fees = st.number_input("Switch fees (€)", min_value=0.0, key="sw_fees")

    out_value = out_qty * out_price
    in_value = in_qty * in_price + in_fees
    if out_price > 0 and in_price > 0:
        implied = (out_value - in_fees) / in_price
        st.caption(f"Value out: €{out_value:,.2f} · value in (units × NAV + fees): "
                   f"€{in_value:,.2f} · units implied at this NAV: {implied:,.3f}")
        if in_qty > 0 and out_value > 0 and abs(in_value - out_value) / out_value > 0.01:
            st.warning("Value in and value out differ by more than 1%: check NAVs, "
                       "units and fees before saving.")
    if status.get(src) == STATUS_ACTIVE:
        st.info(f"After the switch, consider setting **{src}** to *Subbed* in "
                "`data/funds.csv` so it is off by default in the filters.")

    if st.button("Record switch", type="primary", key="sw_submit"):
        if out_price <= 0 or in_price <= 0 or out_qty <= 0 or in_qty <= 0:
            st.error("NAVs and units (out and in) must be greater than 0")
        elif out_qty > held_qty + QTY_EPS:
            st.error(f"Units out exceed the {held_qty:g} units held in {src}")
        elif in_date < out_date:
            st.error("The In date cannot be earlier than the Out date")
        else:
            rows = pd.DataFrame([
                {"Date": pd.Timestamp(out_date).strftime("%Y-%m-%d %H:%M:%S"),
                 "Fund": src, "Price (€)": out_price, "Quantity": -out_qty,
                 "Fees (€)": 0.0, "Operation": OP_SWITCH_OUT, "Linked Fund": tgt},
                {"Date": pd.Timestamp(in_date).strftime("%Y-%m-%d %H:%M:%S"),
                 "Fund": tgt, "Price (€)": in_price, "Quantity": in_qty,
                 "Fees (€)": in_fees, "Operation": OP_SWITCH_IN, "Linked Fund": src},
            ])
            _commit_rows(
                TRANSACTIONS_REPO_PATH, TRANSACTIONS_FILE, rows, TX_COLUMNS,
                f"Switch {src} -> {tgt} on {out_date:%Y-%m-%d} via Streamlit",
                label=f"switch {src} → {tgt} · {out_qty:g} out @ €{out_price:.2f}, "
                      f"{in_qty:g} in @ €{in_price:.2f}",
            )


def _commit_rows(repo_path, local_path, rows, columns, message, label,
                 success_note=""):
    """Appende righe al CSV su GitHub; aggiorna file locale e cache SOLO a commit verificato.

    GitHub è la fonte di verità: il CSV si ricostruisce dal file remoto
    corrente (non dal DataFrame in cache), così un inserimento non può mai
    sovrascrivere quelli precedenti. Se il push fallisce, le righe restano in
    una coda "pending" visibile con un bottone di retry: nulla va perso in
    silenzio e nulla viene mostrato come salvato se non lo è.
    """
    if not (GITHUB_TOKEN and GITHUB_REPO):
        st.error("❌ GITHUB_TOKEN / GITHUB_REPO not configured in Streamlit secrets: "
                 "nothing was saved.")
        return False
    try:
        with st.spinner("Committing to GitHub…"):
            res = append_csv_rows(GITHUB_REPO, repo_path, GITHUB_BRANCH, GITHUB_TOKEN,
                                  rows, columns, message)
    except (GitHubWriteError, ValueError) as e:
        pending = st.session_state.setdefault(_PENDING_KEY, [])
        pending.append({"repo_path": repo_path, "local_path": local_path,
                        "rows": rows.to_dict("records"), "columns": columns,
                        "message": message, "label": label, "error": str(e),
                        "config": isinstance(e, GitHubConfigError)})
        st.rerun()
        return False

    # Commit verificato: allinea copia locale e invalida le cache
    with open(local_path, "w", encoding="utf-8", newline="") as fh:
        fh.write(res.content)
    load_funds_and_transactions.clear()
    load_historical_prices.clear()
    link = f" ([commit]({res.commit_url}))" if res.commit_url else ""
    st.session_state[_FLASH_KEY] = (
        f"✅ Saved to GitHub: {label}{link}. {success_note}".strip())
    st.rerun()
    return True


def _render_status():
    """Messaggio dell'ultimo commit riuscito + coda delle scritture fallite."""
    flash = st.session_state.pop(_FLASH_KEY, None)
    if flash:
        st.success(flash)

    pending = st.session_state.get(_PENDING_KEY) or []
    if not pending:
        return
    st.error(f"❌ {len(pending)} change(s) are NOT on GitHub yet. They were not "
             "saved anywhere else: retry, or re-enter them later.")
    for i, item in enumerate(list(pending)):
        c1, c2, c3 = st.columns([5, 1, 1], vertical_alignment="center")
        c1.markdown(f"**{item['label']}**  \n<small>{item['error']}</small>",
                    unsafe_allow_html=True)
        if c2.button("Retry", key=f"retry_pending_{i}", disabled=item["config"],
                     help="Token / permission errors must be fixed in secrets first."
                     if item["config"] else None):
            st.session_state[_PENDING_KEY].pop(i)
            _commit_rows(item["repo_path"], item["local_path"],
                         pd.DataFrame(item["rows"]), item["columns"],
                         item["message"], item["label"])
        if c3.button("Discard", key=f"discard_pending_{i}"):
            st.session_state[_PENDING_KEY].pop(i)
            st.rerun()