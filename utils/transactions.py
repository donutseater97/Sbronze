"""
utils/transactions.py — Tipi di operazione (Buy / Switch) e regole contabili condivise.

Nessuna dipendenza da Streamlit: è usato sia dalle pagine sia da
scripts/compute_analytics.py (GitHub Action).

MODELLO
-------
transaction_history.csv ha due colonne oltre a quelle storiche:

    Operation    "Buy" (default) | "Switch Out" | "Switch In"
    Linked Fund  per gli switch: il fondo controparte (vuoto per i Buy)

Uno switch (es. US (old) → US (a)) sono DUE righe:
    Switch Out  Fund=US (old)  Quantity < 0 (azzera/riduce la posizione)  Linked=US (a)
    Switch In   Fund=US (a)    Quantity > 0 (al NAV di US (a))            Linked=US (old)

Le quantità sono firmate, quindi ovunque si fa Σ quantità × NAV (market value,
P/L giornaliero, evoluzione) il risultato è già corretto senza casi speciali.
Le regole qui sotto servono solo dove entrano i "contributi":

  • Contributo lordo per riga (rispetto al FONDO):
        Buy        → (Q×P + fee) arrotondato ai 10 € (versamento "teorico")
        Switch In  → Q×P + fee (controvalore trasferito, esatto)
        Switch Out → 0 (è un'uscita: vedi "withdrawal")
  • Withdrawal (controvalore uscito) per riga:
        Switch Out → |Q|×P − fee ; altrimenti 0
  • Rendimento del fondo = Market Value + Withdrawal − Contributi
    → per un fondo "Subbed" a quantità 0 è il rendimento REALIZZATO.

  • Per una SELEZIONE di fondi (filtri), il capitale "esterno" esclude gli
    switch interni (entrambi i lati selezionati): così i totali non contano
    due volte lo stesso denaro.
  • "Lineage": i totali di portafoglio includono anche i fondi che sono
    confluiti (via switch) in un fondo selezionato, così il rendimento
    realizzato di US (old) resta nei totali anche se il suo filtro è spento.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

# -----------------------------------------------------------------------------
# Costanti
# -----------------------------------------------------------------------------

OP_BUY = "Buy"
OP_SWITCH_OUT = "Switch Out"
OP_SWITCH_IN = "Switch In"
OPERATIONS = [OP_BUY, OP_SWITCH_OUT, OP_SWITCH_IN]

STATUS_ACTIVE = "Active"
STATUS_CLOSED = "Closed"
STATUS_SUBBED = "Subbed"
STATUSES = [STATUS_ACTIVE, STATUS_CLOSED, STATUS_SUBBED]

TX_COLUMNS = ["Date", "Fund", "Price (€)", "Quantity", "Fees (€)", "Operation", "Linked Fund"]
FUND_COLUMNS = ["Fund", "Status", "Ticker", "ISIN", "Fund Name", "Type", "Colour", "URL"]

QTY_EPS = 1e-6   # sotto questa soglia una quantità è considerata zero


# -----------------------------------------------------------------------------
# Normalizzazione
# -----------------------------------------------------------------------------

def normalize_transactions(tx: pd.DataFrame) -> pd.DataFrame:
    """Garantisce le colonne Operation / Linked Fund (retro-compatibile)."""
    df = tx.copy()
    if "Operation" not in df.columns:
        df["Operation"] = OP_BUY
    op = df["Operation"].astype("object").where(df["Operation"].notna(), "")
    df["Operation"] = op.astype(str).str.strip().replace("", OP_BUY)
    if "Linked Fund" not in df.columns:
        df["Linked Fund"] = ""
    lf = df["Linked Fund"].astype("object").where(df["Linked Fund"].notna(), "")
    df["Linked Fund"] = lf.astype(str).str.strip()
    for c in ("Price (€)", "Quantity", "Fees (€)"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    if "Fees (€)" in df.columns:
        df["Fees (€)"] = df["Fees (€)"].fillna(0.0)
    return df


def normalize_funds(funds: pd.DataFrame) -> pd.DataFrame:
    """Garantisce la colonna Status (default Active)."""
    df = funds.copy()
    if "Status" not in df.columns:
        df.insert(1 if "Fund" in df.columns else 0, "Status", STATUS_ACTIVE)
    st_ = df["Status"].astype("object").where(df["Status"].notna(), "")
    df["Status"] = st_.astype(str).str.strip().replace("", STATUS_ACTIVE)
    return df


# -----------------------------------------------------------------------------
# Maschere e misure per riga
# -----------------------------------------------------------------------------

def is_buy(tx: pd.DataFrame) -> pd.Series:
    return tx["Operation"] == OP_BUY


def is_switch(tx: pd.DataFrame) -> pd.Series:
    return tx["Operation"].isin([OP_SWITCH_OUT, OP_SWITCH_IN])


def theor_contribution(tx: pd.DataFrame) -> pd.Series:
    """Versamento "teorico" (arrotondato ai 10 €) per i Buy; NaN per gli switch."""
    real = tx["Quantity"] * tx["Price (€)"] + tx["Fees (€)"]
    return ((real / 10).round() * 10).where(is_buy(tx))


def add_flow_columns(tx: pd.DataFrame) -> pd.DataFrame:
    """Aggiunge le misure per riga usate da tutte le pagine.

    _gc        contributo lordo nel fondo (Buy arrotondato, Switch In esatto)
    _net       contributo netto nel fondo (Q×P, senza fee)
    _wd        controvalore uscito (Switch Out: |Q|×P − fee)
    _wd_net    controvalore uscito al netto delle fee (|Q|×P)
    _inflow    True per Buy / Switch In (righe che "caricano" quote)
    """
    df = tx.copy()
    buy = is_buy(df)
    sin = df["Operation"] == OP_SWITCH_IN
    sout = df["Operation"] == OP_SWITCH_OUT
    qp = df["Quantity"] * df["Price (€)"]
    df["_gc"] = np.where(buy, theor_contribution(df), np.where(sin, qp + df["Fees (€)"], 0.0))
    df["_net"] = np.where(buy | sin, qp, 0.0)
    df["_wd"] = np.where(sout, -qp - df["Fees (€)"], 0.0)
    df["_wd_net"] = np.where(sout, -qp, 0.0)
    df["_inflow"] = buy | sin
    return df


def operation_label(op: str, linked: str) -> str:
    """Etichetta leggibile: "Buy", "Switch Out → US (a)", "Switch In ← US (old)"."""
    if op == OP_SWITCH_OUT:
        return f"⇄ Switch Out → {linked}" if linked else "⇄ Switch Out"
    if op == OP_SWITCH_IN:
        return f"⇄ Switch In ← {linked}" if linked else "⇄ Switch In"
    return op or OP_BUY


# -----------------------------------------------------------------------------
# Quantità, stato, selezione di default
# -----------------------------------------------------------------------------

def current_quantities(tx: pd.DataFrame) -> pd.Series:
    if len(tx) == 0:
        return pd.Series(dtype=float)
    q = tx.groupby("Fund")["Quantity"].sum()
    return q.where(q.abs() > QTY_EPS, 0.0)


def fund_status_map(funds: pd.DataFrame) -> dict:
    if "Status" not in funds.columns:
        return {f: STATUS_ACTIVE for f in funds["Fund"]}
    return dict(zip(funds["Fund"], funds["Status"]))


def default_fund_selection(funds: pd.DataFrame, tx: pd.DataFrame) -> list[str]:
    """Fondi selezionati di default nei filtri: Active, oppure ancora detenuti.

    Così un fondo già marcato Subbed ma non ancora trasferito resta nei totali
    finché ha quote; dopo lo switch (quantità 0) esce dalla selezione di default.
    """
    status = fund_status_map(funds)
    qty = current_quantities(tx) if len(tx) else pd.Series(dtype=float)
    return [f for f in funds["Fund"].tolist()
            if status.get(f, STATUS_ACTIVE) == STATUS_ACTIVE or float(qty.get(f, 0.0)) > QTY_EPS]


def expand_lineage(selection, tx: pd.DataFrame) -> list[str]:
    """Aggiunge (transitivamente) i fondi confluiti via switch in quelli selezionati."""
    sel = list(dict.fromkeys(selection))
    if len(tx) == 0 or "Operation" not in tx.columns:
        return sel
    sw = tx[is_switch(tx) & (tx["Linked Fund"] != "")]
    # coppie (sorgente → destinazione)
    pairs = set()
    for _, r in sw.iterrows():
        if r["Operation"] == OP_SWITCH_OUT:
            pairs.add((r["Fund"], r["Linked Fund"]))
        else:
            pairs.add((r["Linked Fund"], r["Fund"]))
    changed = True
    while changed:
        changed = False
        for src, dst in pairs:
            if dst in sel and src not in sel:
                sel.append(src)
                changed = True
    return sel


# -----------------------------------------------------------------------------
# Flussi "esterni" a una selezione di fondi
# -----------------------------------------------------------------------------

def external_flows(tx: pd.DataFrame, selection) -> pd.DataFrame:
    """Righe dei fondi selezionati con i flussi esterni alla selezione.

    Colonne aggiunte:
      cap_gross / cap_net : capitale entrato nella selezione (Buy + Switch In
                            da fondi NON selezionati)
      wd_gross / wd_net   : controvalore uscito dalla selezione (Switch Out
                            verso fondi NON selezionati)
    Gli switch con entrambi i lati selezionati sono interni: flussi a zero.
    """
    S = set(selection)
    df = add_flow_columns(tx[tx["Fund"].isin(S)])
    internal = is_switch(df) & df["Linked Fund"].isin(S)
    df["cap_gross"] = np.where(internal, 0.0, df["_gc"])
    df["cap_net"] = np.where(internal, 0.0, df["_net"])
    df["wd_gross"] = np.where(internal, 0.0, df["_wd"])
    df["wd_net"] = np.where(internal, 0.0, df["_wd_net"])
    return df


# -----------------------------------------------------------------------------
# Saldo contributi (costo di carico della posizione in essere)
# -----------------------------------------------------------------------------

def book_flows(tx: pd.DataFrame) -> pd.DataFrame:
    """Variazione per riga del "saldo contributi" del fondo.

    Entrate (Buy / Switch In) aumentano il saldo del contributo lordo/netto;
    uno Switch Out lo riduce in proporzione alle quote cedute (costo medio).
    A posizione azzerata il saldo torna a 0: utile per composizioni e torte
    "per contributi", dove un fondo Subbed non deve comparire con valori
    negativi o fantasma.

    Ritorna il DataFrame (ordinato per data) con colonne _book_gross, _book_net.
    """
    df = add_flow_columns(tx)
    df["_ord"] = np.where(df["_inflow"], 0, 1)   # stessa data: prima le entrate
    df = df.sort_values(["Date", "_ord"], kind="stable")
    bg = np.zeros(len(df))
    bn = np.zeros(len(df))
    state = {}   # fund -> [qty, gross, net]
    for i, (fund, q, gc, net, inflow) in enumerate(
            zip(df["Fund"], df["Quantity"], df["_gc"], df["_net"], df["_inflow"])):
        s = state.setdefault(fund, [0.0, 0.0, 0.0])
        if inflow:
            s[0] += q
            s[1] += gc
            s[2] += net
            bg[i], bn[i] = gc, net
        else:
            held = s[0]
            frac = min(1.0, abs(q) / held) if held > QTY_EPS else 1.0
            dg, dn = -s[1] * frac, -s[2] * frac
            s[0] += q
            s[1] += dg
            s[2] += dn
            bg[i], bn[i] = dg, dn
    df["_book_gross"] = bg
    df["_book_net"] = bn
    return df.drop(columns=["_ord"])


def average_nav_by_fund(tx: pd.DataFrame) -> dict:
    """Prezzo medio di carico: (contributi in entrata − fee) / quote entrate."""
    if len(tx) == 0:
        return {}
    df = add_flow_columns(tx)
    inn = df[df["_inflow"]]
    g = inn.groupby("Fund").agg(gc=("_gc", "sum"), fees=("Fees (€)", "sum"),
                                qty=("Quantity", "sum"))
    return {f: (r["gc"] - r["fees"]) / r["qty"] for f, r in g.iterrows() if r["qty"] > QTY_EPS}


def exit_price_by_fund(tx: pd.DataFrame) -> dict:
    """NAV medio di uscita (Switch Out) per i fondi ormai a quantità zero."""
    if len(tx) == 0:
        return {}
    qty = current_quantities(tx)
    out = tx[tx["Operation"] == OP_SWITCH_OUT]
    res = {}
    for f, g in out.groupby("Fund"):
        if abs(float(qty.get(f, 0.0))) <= QTY_EPS and g["Quantity"].sum() != 0:
            res[f] = float((g["Quantity"] * g["Price (€)"]).sum() / g["Quantity"].sum())
    return res